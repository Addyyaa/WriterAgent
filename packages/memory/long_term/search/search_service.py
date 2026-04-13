from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Callable

from packages.core.config import env_bool
from packages.core.tracing import new_request_id, request_context
from packages.core.utils import dedupe_keep_order, stable_bucket_ratio
from packages.evaluation.service import OnlineEvaluationService
from packages.evaluation.retrieval import build_retrieval_impression_payload
from packages.llm.embeddings.base import EmbeddingProvider
from packages.memory.long_term.observability import MemoryObservability
from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.memory.long_term.temporal import (
    SOURCE_TIMESTAMP_KEY,
    normalize_source_timestamp,
)
from packages.retrieval.errors import (
    RetrievalDataError,
    RetrievalTimeoutError,
    RetrieverUnavailableError,
)
from packages.retrieval.hybrid.rrf_fusion import RRFFusionConfig, RRFFusionStrategy
from packages.retrieval.hybrid.weighted_fusion import WeightedFusionStrategy
from packages.retrieval.keyword.bm25_retriever import BM25Retriever
from packages.retrieval.keyword.tfidf_retriever import TFIDFRetriever
from packages.retrieval.evaluators.online_eval_service import OnlineEvalService
from packages.retrieval.pipeline import RetrievalPipeline
from packages.retrieval.query_rewrite.llm_rewriter import LLMQueryRewriter
from packages.retrieval.query_rewrite.rule_rewriter import RuleQueryRewriter
from packages.retrieval.rerank.base import Reranker
from packages.retrieval.rerank.cross_encoder import (
    ExternalCrossEncoderConfig,
    ExternalCrossEncoderReranker,
)
from packages.retrieval.rerank.rule_based import RuleBasedRerankConfig, RuleBasedReranker
from packages.retrieval.types import FilterExpr, RetrievalOptions, ScoredDoc
from packages.retrieval.vector.factory import create_vector_store
from packages.retrieval.vector.filters import VectorFilterExpr, to_dict
from packages.memory.long_term.search.hybrid_search import HybridSearchEngine
from packages.memory.long_term.search.reranker import RuleBasedReranker as LegacyRuleBasedReranker
from packages.storage.postgres.repositories.memory_repository import (
    MemoryChunkRepository,
)
from packages.storage.postgres.repositories.retrieval_eval_repository import (
    RetrievalEvalRepository,
)
from packages.storage.postgres.repositories.evaluation_repository import (
    EvaluationRepository,
)


class _LegacyRerankerAdapter(Reranker):
    """兼容旧版 dict 风格 reranker。"""

    def __init__(self, legacy_reranker) -> None:
        self.legacy_reranker = legacy_reranker

    def rerank(
        self,
        *,
        query: str,
        candidates: list[ScoredDoc],
        top_k: int,
        sort_by: str,
    ) -> list[ScoredDoc]:
        del query
        rows = [item.to_dict() for item in candidates]
        reranked = self.legacy_reranker.rerank(rows, sort_by=sort_by, top_k=top_k)
        return [ScoredDoc.from_mapping(row) for row in reranked]


class MemorySearchService:
    _ADAPTIVE_FALLBACK_FLOOR = 0.45
    _ALLOWED_SORT_BY = {
        "relevance",
        "relevance_then_recent",
        "recent",
        "timeline_asc",
    }

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        memory_repo: MemoryChunkRepository,
        query_rewriter: Callable[[str], list[str]] | None = None,
        hybrid_search_engine=None,
        reranker=None,
        runtime_config: MemoryRuntimeConfig | None = None,
        observability: MemoryObservability | None = None,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.memory_repo = memory_repo
        self.external_query_rewriter = query_rewriter
        self.rule_query_rewriter = RuleQueryRewriter()
        self.llm_query_rewriter = (
            LLMQueryRewriter(query_rewriter) if query_rewriter is not None else None
        )

        self.runtime_config = runtime_config or MemoryRuntimeConfig.from_env()
        self.observability = observability or MemoryObservability(
            logger_name=self.runtime_config.observability.logger_name,
            enable_logging=self.runtime_config.observability.enable_logging,
        )
        self.query_rewrite_backend = (
            self.runtime_config.retrieval.query_rewrite_backend.strip().lower()
        )
        self.keyword_backend = self.runtime_config.retrieval.keyword_backend.strip().lower()
        self.fusion_backend = self.runtime_config.retrieval.fusion_backend.strip().lower()
        self.hybrid_backend = self.runtime_config.retrieval.hybrid_backend.strip().lower()
        self._keyword_candidate_limit = int(
            os.environ.get("WRITER_RETRIEVAL_KEYWORD_CANDIDATE_LIMIT", "1200")
        )
        db_session = getattr(memory_repo, "db", None)
        self.eval_repo = RetrievalEvalRepository(db_session) if db_session is not None else None
        self.online_eval = OnlineEvalService(self.eval_repo) if self.eval_repo is not None else None
        self.unified_eval = None
        if db_session is not None and env_bool("WRITER_EVAL_ONLINE_ENABLED", True):
            self.unified_eval = OnlineEvaluationService(
                repo=EvaluationRepository(db_session),
                schema_registry=None,
                schema_strict=False,
                schema_degrade_mode=True,
            )

        self.rule_reranker = RuleBasedReranker(
            RuleBasedRerankConfig(
                vector_weight=self.runtime_config.retrieval.rerank.vector_weight,
                keyword_weight=self.runtime_config.retrieval.rerank.keyword_weight,
                recency_weight=self.runtime_config.retrieval.rerank.recency_weight,
                canonical_fact_boost=self.runtime_config.retrieval.rerank.canonical_fact_boost,
            )
        )
        self.cross_encoder_reranker = self._build_cross_encoder_reranker()

        if reranker is None:
            self.custom_reranker: Reranker | None = None
        elif isinstance(reranker, Reranker):
            self.custom_reranker = reranker
        elif hasattr(reranker, "rerank"):
            # 兼容 legacy reranker（dict 输入输出）
            self.custom_reranker = _LegacyRerankerAdapter(reranker)
        else:
            self.custom_reranker = None
        self.legacy_reranker = LegacyRuleBasedReranker()

        self.vector_store = create_vector_store(
            memory_repo=self.memory_repo,
            runtime_config=self.runtime_config.retrieval,
        )
        if hybrid_search_engine is None:
            self.legacy_hybrid_engine = HybridSearchEngine(self.memory_repo)
        else:
            self.legacy_hybrid_engine = hybrid_search_engine

        fusion_strategy = RRFFusionStrategy(
            RRFFusionConfig(
                rrf_k=self.runtime_config.retrieval.hybrid.rrf_k,
                weights=(
                    self.runtime_config.retrieval.hybrid.vector_weight,
                    self.runtime_config.retrieval.hybrid.keyword_weight,
                ),
            )
        )
        if self.fusion_backend == "weighted":
            fusion_strategy = WeightedFusionStrategy()
        self.pipeline = RetrievalPipeline(
            vector_retriever=self._vector_retrieve,
            keyword_retriever=self._keyword_retrieve,
            query_rewriter=self._build_query_variants,
            fusion_strategy=fusion_strategy,
            reranker=self.rule_reranker,
        )

    def _build_cross_encoder_reranker(self) -> ExternalCrossEncoderReranker | None:
        cfg = self.runtime_config.retrieval.rerank.cross_encoder
        if not cfg.base_url or not cfg.api_key or not cfg.model:
            return None
        return ExternalCrossEncoderReranker(
            ExternalCrossEncoderConfig(
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                model=cfg.model,
                timeout_seconds=cfg.timeout_seconds,
            )
        )

    def search_texts(
        self,
        project_id,
        query: str,
        request_id: str | None = None,
        user_id: str | None = None,
        top_k: int | None = None,
        source_type: str | None = None,
        chunk_type: str | None = None,
        max_distance: float | None = None,
        fallback_max_distance: float | None = None,
        enable_query_rewrite: bool | None = None,
        sort_by: str = "relevance",
        source_timestamp_gte: str | datetime | None = None,
        source_timestamp_lte: str | datetime | None = None,
        recent_within_days: int | None = None,
        enable_hybrid: bool | None = None,
        enable_rerank: bool | None = None,
    ) -> list[str]:
        results = self.search_with_scores(
            project_id=project_id,
            query=query,
            request_id=request_id,
            user_id=user_id,
            top_k=top_k,
            source_type=source_type,
            chunk_type=chunk_type,
            max_distance=max_distance,
            fallback_max_distance=fallback_max_distance,
            enable_query_rewrite=enable_query_rewrite,
            sort_by=sort_by,
            source_timestamp_gte=source_timestamp_gte,
            source_timestamp_lte=source_timestamp_lte,
            recent_within_days=recent_within_days,
            enable_hybrid=enable_hybrid,
            enable_rerank=enable_rerank,
        )

        return [item["text"] for item in results]

    def search_with_scores(
        self,
        project_id,
        query: str,
        request_id: str | None = None,
        user_id: str | None = None,
        top_k: int | None = None,
        source_type: str | None = None,
        chunk_type: str | None = None,
        max_distance: float | None = None,
        fallback_max_distance: float | None = None,
        enable_query_rewrite: bool | None = None,
        sort_by: str = "relevance",
        source_timestamp_gte: str | datetime | None = None,
        source_timestamp_lte: str | datetime | None = None,
        recent_within_days: int | None = None,
        enable_hybrid: bool | None = None,
        enable_rerank: bool | None = None,
    ) -> list[dict]:
        """
        语义检索 + 时间语义过滤/排序。

        sort_by:
        - relevance: 相关性优先（默认）
        - relevance_then_recent: 相关性优先，冲突时优先较新的 source_timestamp
        - recent: 优先返回最新发生的语义事实
        - timeline_asc: 按语义时间升序（用于剧情演化上下文拼接）
        """
        retrieval_cfg = self.runtime_config.retrieval
        effective_top_k = retrieval_cfg.top_k if top_k is None else top_k
        if effective_top_k <= 0:
            return []
        self._validate_sort_by(sort_by)

        effective_request_id = request_id or self._build_request_id()
        variant = self._assign_variant(project_id=project_id, user_id=user_id, query=query)
        current_rerank_backend = self._resolve_rerank_backend(variant=variant)

        effective_max_distance = (
            max_distance if max_distance is not None else retrieval_cfg.max_distance
        )
        effective_fallback_max_distance = (
            fallback_max_distance
            if fallback_max_distance is not None
            else retrieval_cfg.fallback_max_distance
        )
        effective_enable_query_rewrite = (
            retrieval_cfg.enable_query_rewrite
            if enable_query_rewrite is None
            else bool(enable_query_rewrite)
        )
        effective_enable_hybrid = (
            retrieval_cfg.enable_hybrid
            if enable_hybrid is None
            else bool(enable_hybrid)
        )
        effective_enable_rerank = (
            retrieval_cfg.enable_rerank
            if enable_rerank is None
            else bool(enable_rerank)
        )

        effective_source_timestamp_gte = (
            normalize_source_timestamp(source_timestamp_gte)
            if source_timestamp_gte is not None
            else None
        )
        effective_source_timestamp_lte = (
            normalize_source_timestamp(source_timestamp_lte)
            if source_timestamp_lte is not None
            else None
        )

        if recent_within_days is not None:
            if recent_within_days <= 0:
                return []
            recent_floor = (
                datetime.now(tz=timezone.utc) - timedelta(days=recent_within_days)
            ).isoformat().replace("+00:00", "Z")
            if effective_source_timestamp_gte is None:
                effective_source_timestamp_gte = recent_floor
            else:
                effective_source_timestamp_gte = max(
                    recent_floor,
                    effective_source_timestamp_gte,
                )

        repo_sort = self._to_repo_sort(sort_by)
        filters = FilterExpr(
            project_id=project_id,
            source_type=source_type,
            chunk_type=chunk_type,
            source_timestamp_gte=effective_source_timestamp_gte,
            source_timestamp_lte=effective_source_timestamp_lte,
        )

        self.observability.incr("search.requests")

        strict_rows, strict_trace, current_rerank_backend = self._run_pipeline(
            query=query,
            filters=filters,
            top_k=effective_top_k,
            sort_by=repo_sort,
            max_distance=effective_max_distance,
            enable_query_rewrite=effective_enable_query_rewrite,
            enable_hybrid=effective_enable_hybrid,
            enable_rerank=effective_enable_rerank,
            rerank_backend=current_rerank_backend,
        )
        if strict_rows:
            strict_rows = self._attach_request_meta(
                strict_rows,
                request_id=effective_request_id,
                variant=variant,
                rerank_backend=current_rerank_backend,
            )
            self._emit_search_event(
                project_id=project_id,
                query=query,
                top_k=effective_top_k,
                sort_by=sort_by,
                max_distance=effective_max_distance,
                fallback_max_distance=effective_fallback_max_distance,
                attempt="strict",
                trace=strict_trace,
                returned=len(strict_rows),
                request_id=effective_request_id,
                variant=variant,
                rerank_backend=current_rerank_backend,
            )
            self._safe_record_impression(
                project_id=project_id,
                request_id=effective_request_id,
                user_id=user_id,
                query=query,
                variant=variant,
                rerank_backend=current_rerank_backend,
                rows=strict_rows,
                context_json={
                    "attempt": "strict",
                    "sort_by": sort_by,
                    "max_distance": effective_max_distance,
                    "fallback_max_distance": effective_fallback_max_distance,
                },
            )
            self.observability.incr("search.hits")
            return strict_rows[:effective_top_k]

        # 自适应阈值回退：当严格阈值无命中时，放宽一次阈值。
        if (
            effective_max_distance is not None
            and effective_fallback_max_distance is not None
            and effective_fallback_max_distance > effective_max_distance
        ):
            relaxed_rows, relaxed_trace, current_rerank_backend = self._run_pipeline(
                query=query,
                filters=filters,
                top_k=effective_top_k,
                sort_by=repo_sort,
                max_distance=effective_fallback_max_distance,
                enable_query_rewrite=effective_enable_query_rewrite,
                enable_hybrid=effective_enable_hybrid,
                enable_rerank=effective_enable_rerank,
                rerank_backend=current_rerank_backend,
            )
            if relaxed_rows:
                relaxed_rows = self._attach_request_meta(
                    relaxed_rows,
                    request_id=effective_request_id,
                    variant=variant,
                    rerank_backend=current_rerank_backend,
                )
                self.observability.incr("search.fallback.relaxed_hits")
                self._emit_search_event(
                    project_id=project_id,
                    query=query,
                    top_k=effective_top_k,
                    sort_by=sort_by,
                    max_distance=effective_max_distance,
                    fallback_max_distance=effective_fallback_max_distance,
                    attempt="relaxed",
                    trace=relaxed_trace,
                    returned=len(relaxed_rows),
                    request_id=effective_request_id,
                    variant=variant,
                    rerank_backend=current_rerank_backend,
                )
                self._safe_record_impression(
                    project_id=project_id,
                    request_id=effective_request_id,
                    user_id=user_id,
                    query=query,
                    variant=variant,
                    rerank_backend=current_rerank_backend,
                    rows=relaxed_rows,
                    context_json={
                        "attempt": "relaxed",
                        "sort_by": sort_by,
                        "max_distance": effective_max_distance,
                        "fallback_max_distance": effective_fallback_max_distance,
                    },
                )
                return relaxed_rows[:effective_top_k]

            # 通用自适应回退：显式 fallback 仍无结果时，放宽到保守下限。
            adaptive_floor = max(
                float(effective_fallback_max_distance),
                float(retrieval_cfg.adaptive_fallback_floor or self._ADAPTIVE_FALLBACK_FLOOR),
            )
            if adaptive_floor > float(effective_fallback_max_distance):
                adaptive_rows, adaptive_trace, current_rerank_backend = self._run_pipeline(
                    query=query,
                    filters=filters,
                    top_k=effective_top_k,
                    sort_by=repo_sort,
                    max_distance=adaptive_floor,
                    enable_query_rewrite=effective_enable_query_rewrite,
                    enable_hybrid=effective_enable_hybrid,
                    enable_rerank=effective_enable_rerank,
                    rerank_backend=current_rerank_backend,
                )
                if adaptive_rows:
                    adaptive_rows = self._attach_request_meta(
                        adaptive_rows,
                        request_id=effective_request_id,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                    )
                    self.observability.incr("search.fallback.adaptive_hits")
                    self._emit_search_event(
                        project_id=project_id,
                        query=query,
                        top_k=effective_top_k,
                        sort_by=sort_by,
                        max_distance=effective_max_distance,
                        fallback_max_distance=effective_fallback_max_distance,
                        attempt="adaptive",
                        trace=adaptive_trace,
                        returned=len(adaptive_rows),
                        request_id=effective_request_id,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                    )
                    self._safe_record_impression(
                        project_id=project_id,
                        request_id=effective_request_id,
                        user_id=user_id,
                        query=query,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                        rows=adaptive_rows,
                        context_json={
                            "attempt": "adaptive",
                            "sort_by": sort_by,
                            "max_distance": effective_max_distance,
                            "fallback_max_distance": effective_fallback_max_distance,
                        },
                    )
                    return adaptive_rows[:effective_top_k]

            # 关键词兜底：语义阈值链路全部无结果时，执行一次不受向量阈值约束的混合召回。
            if effective_enable_hybrid:
                lexical_rows, lexical_trace, current_rerank_backend = self._run_pipeline(
                    query=query,
                    filters=filters,
                    top_k=effective_top_k,
                    sort_by=repo_sort,
                    max_distance=None,
                    enable_query_rewrite=effective_enable_query_rewrite,
                    enable_hybrid=True,
                    enable_rerank=effective_enable_rerank,
                    rerank_backend=current_rerank_backend,
                )
                if lexical_rows:
                    lexical_rows = self._attach_request_meta(
                        lexical_rows,
                        request_id=effective_request_id,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                    )
                    self.observability.incr("search.fallback.lexical_hits")
                    self._emit_search_event(
                        project_id=project_id,
                        query=query,
                        top_k=effective_top_k,
                        sort_by=sort_by,
                        max_distance=effective_max_distance,
                        fallback_max_distance=effective_fallback_max_distance,
                        attempt="lexical",
                        trace=lexical_trace,
                        returned=len(lexical_rows),
                        request_id=effective_request_id,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                    )
                    self._safe_record_impression(
                        project_id=project_id,
                        request_id=effective_request_id,
                        user_id=user_id,
                        query=query,
                        variant=variant,
                        rerank_backend=current_rerank_backend,
                        rows=lexical_rows,
                        context_json={
                            "attempt": "lexical",
                            "sort_by": sort_by,
                            "max_distance": effective_max_distance,
                            "fallback_max_distance": effective_fallback_max_distance,
                        },
                    )
                    return lexical_rows[:effective_top_k]

        self.observability.incr("search.no_hits")
        self._emit_search_event(
            project_id=project_id,
            query=query,
            top_k=effective_top_k,
            sort_by=sort_by,
            max_distance=effective_max_distance,
            fallback_max_distance=effective_fallback_max_distance,
            attempt="none",
            trace=strict_trace,
            returned=0,
            request_id=effective_request_id,
            variant=variant,
            rerank_backend=current_rerank_backend,
        )
        self._safe_record_impression(
            project_id=project_id,
            request_id=effective_request_id,
            user_id=user_id,
            query=query,
            variant=variant,
            rerank_backend=current_rerank_backend,
            rows=[],
            context_json={
                "attempt": "none",
                "sort_by": sort_by,
                "max_distance": effective_max_distance,
                "fallback_max_distance": effective_fallback_max_distance,
            },
        )
        return []

    def record_feedback(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        clicked_doc_id: str | None,
        clicked: bool = True,
    ) -> bool:
        if self.online_eval is None:
            self.observability.incr("search.feedback.disabled")
            return False
        try:
            ok = self.online_eval.record_feedback(
                project_id=project_id,
                request_id=request_id,
                user_id=user_id,
                clicked_doc_id=clicked_doc_id,
                clicked=clicked,
            )
        except Exception as exc:
            self.observability.emit(
                "memory.search.feedback_error",
                project_id=str(project_id),
                request_id=request_id,
                user_id=user_id,
                clicked=clicked,
                error=str(exc),
            )
            return False

        if self.unified_eval is not None:
            try:
                self.unified_eval.record_retrieval_feedback(
                    project_id=project_id,
                    request_id=request_id,
                    clicked=bool(clicked),
                    payload_json={
                        "user_id": user_id,
                        "clicked_doc_id": clicked_doc_id,
                        "source": "memory_search.record_feedback",
                    },
                )
            except Exception as exc:
                self.observability.emit(
                    "memory.search.eval_write_error",
                    project_id=str(project_id),
                    request_id=request_id,
                    error=str(exc),
                )

        if ok:
            metric = "search.feedback.clicked" if clicked else "search.feedback.not_clicked"
            self.observability.incr(metric)
        else:
            self.observability.incr("search.feedback.miss")
        return ok

    def get_metrics_snapshot(self) -> dict[str, int]:
        return self.observability.snapshot()

    def _run_pipeline(
        self,
        *,
        query: str,
        filters: FilterExpr,
        top_k: int,
        sort_by: str,
        max_distance: float | None,
        enable_query_rewrite: bool,
        enable_hybrid: bool,
        enable_rerank: bool,
        rerank_backend: str,
    ) -> tuple[list[dict], object, str]:
        if self.hybrid_backend in {"legacy", "legacy_hybrid"}:
            query_embedding = self.embedding_provider.embed_query(query)
            legacy_sort = self._to_repo_sort(sort_by)
            rows = self.legacy_hybrid_engine.search(
                project_id=filters.project_id,
                query_text=query,
                query_embedding=query_embedding,
                top_k=top_k,
                source_type=filters.source_type,
                chunk_type=filters.chunk_type,
                max_distance=max_distance,
                source_timestamp_gte=filters.source_timestamp_gte,
                source_timestamp_lte=filters.source_timestamp_lte,
                sort_by=legacy_sort,
            )
            if enable_rerank:
                rows = self.legacy_reranker.rerank(
                    rows,
                    sort_by=legacy_sort,
                    top_k=top_k,
                    query=query,
                )
            trace = type(
                "LegacyTrace",
                (),
                {
                    "query_variants": 1,
                    "vector_candidates": len(rows),
                    "keyword_candidates": len(rows),
                    "merged_candidates": len(rows),
                },
            )()
            return rows[:top_k], trace, "legacy"

        options = RetrievalOptions(
            top_k=top_k,
            max_distance=max_distance,
            sort_by=sort_by,
            enable_query_rewrite=enable_query_rewrite,
            enable_hybrid=enable_hybrid,
            enable_rerank=enable_rerank,
            candidate_multiplier=self.runtime_config.retrieval.hybrid.candidate_multiplier,
        )

        selected_reranker, applied_backend = self._select_reranker(
            enable_rerank=enable_rerank,
            rerank_backend=rerank_backend,
        )

        previous_reranker = self.pipeline.reranker
        self.pipeline.reranker = selected_reranker
        try:
            docs, trace = self.pipeline.run_with_trace(
                query=query,
                filters=filters,
                options=options,
            )
            rows = [self._doc_to_row(doc) for doc in docs]
            return rows, trace, applied_backend
        except (RetrieverUnavailableError, RetrievalTimeoutError, RetrievalDataError) as exc:
            if enable_rerank and applied_backend == "cross_encoder":
                self.observability.incr("search.rerank.cross_encoder_fallback")
                self.observability.emit(
                    "memory.search.cross_encoder_fallback",
                    query=query,
                    reason=str(exc),
                )
                self.pipeline.reranker = self.rule_reranker
                docs, trace = self.pipeline.run_with_trace(
                    query=query,
                    filters=filters,
                    options=options,
                )
                rows = [self._doc_to_row(doc) for doc in docs]
                return rows, trace, "rule"
            raise
        finally:
            self.pipeline.reranker = previous_reranker

    def _vector_retrieve(
        self,
        query: str,
        filters: FilterExpr,
        options: RetrievalOptions,
    ) -> list[ScoredDoc]:
        query_embedding = self.embedding_provider.embed_query(query)
        filter_dict = to_dict(
            VectorFilterExpr(
                project_id=str(filters.project_id),
                source_type=filters.source_type,
                chunk_type=filters.chunk_type,
                source_timestamp_gte=filters.source_timestamp_gte,
                source_timestamp_lte=filters.source_timestamp_lte,
            )
        )
        filter_dict["max_distance"] = options.max_distance
        filter_dict["sort_by"] = options.sort_by
        rows = self.vector_store.search(
            query_vector=query_embedding,
            top_k=options.top_k,
            filters=filter_dict,
        )
        return [ScoredDoc.from_mapping(row) for row in rows]

    def _keyword_retrieve(
        self,
        query: str,
        filters: FilterExpr,
        options: RetrievalOptions,
    ) -> list[ScoredDoc]:
        # 关键词分支始终参与 hybrid 召回：
        # - 向量分支继续受 max_distance 约束
        # - keyword 结果 distance 为 None，不受向量阈值过滤
        # 这样可避免“语义相近但任务不相关”时只靠向量导致的低精度问题。

        backend = self.keyword_backend
        if backend in {"sql_bm25", "sql", "fts"}:
            rows = self.memory_repo.keyword_search(
                project_id=filters.project_id,
                query_text=query,
                top_k=options.top_k,
                source_type=filters.source_type,
                chunk_type=filters.chunk_type,
                source_timestamp_gte=filters.source_timestamp_gte,
                source_timestamp_lte=filters.source_timestamp_lte,
                sort_by=self._to_keyword_sort(options.sort_by),
            )
            return [ScoredDoc.from_mapping(row) for row in rows]

        # 备选关键词后端：BM25 / TF-IDF（内存轻量版）
        candidates = self.memory_repo.list_by_project(
            filters.project_id,
            limit=max(options.top_k, self._keyword_candidate_limit),
            source_type=filters.source_type,
            chunk_type=filters.chunk_type,
            source_timestamp_gte=filters.source_timestamp_gte,
            source_timestamp_lte=filters.source_timestamp_lte,
            sort_by="created_at_desc",
            embedding_status="done",
        )
        texts = [str(item.chunk_text or "") for item in candidates]
        if not texts:
            return []

        if backend in {"tfidf", "tf-idf"}:
            retriever = TFIDFRetriever()
        else:
            retriever = BM25Retriever()
        retriever.index(texts)
        hits = retriever.search(query, top_k=options.top_k)

        rows: list[ScoredDoc] = []
        for idx, score in hits:
            if idx < 0 or idx >= len(candidates):
                continue
            row = candidates[idx]
            rows.append(
                ScoredDoc.from_mapping(
                    {
                        "id": str(row.id),
                        "project_id": str(row.project_id),
                        "source_type": row.source_type,
                        "source_id": str(row.source_id) if row.source_id is not None else None,
                        "chunk_type": row.chunk_type,
                        "text": row.chunk_text,
                        "summary_text": row.summary_text,
                        "metadata_json": row.metadata_json or {},
                        "keyword_score": float(score),
                        "distance": None,
                        "hybrid_score": float(score),
                        "source_timestamp": (row.metadata_json or {}).get(SOURCE_TIMESTAMP_KEY),
                    }
                )
            )
        return rows

    def _build_query_variants(self, query: str) -> list[str]:
        backend = self.query_rewrite_backend
        if backend == "llm" and self.llm_query_rewriter is not None:
            variants = self.llm_query_rewriter.rewrite(query)
        else:
            variants = self.rule_query_rewriter.rewrite(query)
        if not variants:
            variants = [query.strip()]

        if self.external_query_rewriter is not None and backend != "llm":
            try:
                external_variants = self.external_query_rewriter(query) or []
            except Exception:
                external_variants = []

            for item in external_variants:
                text = str(item).strip()
                if text:
                    variants.append(text)

        return dedupe_keep_order(variants)

    def _emit_search_event(
        self,
        *,
        project_id,
        query: str,
        top_k: int,
        sort_by: str,
        max_distance: float | None,
        fallback_max_distance: float | None,
        attempt: str,
        trace,
        returned: int,
        request_id: str,
        variant: str,
        rerank_backend: str,
    ) -> None:
        with request_context(request_id=request_id, trace_id=request_id):
            self.observability.emit(
                "memory.search",
                project_id=str(project_id),
                request_id=request_id,
                variant=variant,
                rerank_backend=rerank_backend,
                query=query,
                top_k=top_k,
                sort_by=sort_by,
                max_distance=max_distance,
                fallback_max_distance=fallback_max_distance,
                attempt=attempt,
                returned=returned,
                query_variants=getattr(trace, "query_variants", None),
                vector_candidates=getattr(trace, "vector_candidates", None),
                keyword_candidates=getattr(trace, "keyword_candidates", None),
                merged_candidates=getattr(trace, "merged_candidates", None),
            )

    def _safe_record_impression(
        self,
        *,
        project_id,
        request_id: str,
        user_id: str | None,
        query: str,
        variant: str,
        rerank_backend: str,
        rows: list[dict],
        context_json: dict,
    ) -> None:
        if self.online_eval is None:
            return
        try:
            self.online_eval.record_impression(
                project_id=project_id,
                request_id=request_id,
                user_id=user_id,
                query=query,
                variant=variant,
                rerank_backend=rerank_backend,
                impressed_doc_ids=[str(item.get("id")) for item in rows if item.get("id") is not None],
                context_json=context_json,
            )
        except Exception as exc:
            self.observability.emit(
                "memory.search.eval_write_error",
                project_id=str(project_id),
                request_id=request_id,
                error=str(exc),
            )
        if self.unified_eval is not None:
            try:
                self.unified_eval.record_retrieval_impression(
                    project_id=project_id,
                    request_id=request_id,
                    metric_value=float(len(rows)),
                    payload_json=build_retrieval_impression_payload(
                        variant=variant,
                        rerank_backend=rerank_backend,
                        rows_count=len(rows),
                        context_json=dict(context_json or {}),
                    ),
                )
            except Exception as exc:
                self.observability.emit(
                    "memory.search.eval_write_error",
                    project_id=str(project_id),
                    request_id=request_id,
                    error=str(exc),
                )

    @staticmethod
    def _attach_request_meta(
        rows: list[dict],
        *,
        request_id: str,
        variant: str,
        rerank_backend: str,
    ) -> list[dict]:
        out: list[dict] = []
        for row in rows:
            item = dict(row)
            item["request_id"] = request_id
            item["variant"] = variant
            item["rerank_backend"] = rerank_backend
            out.append(item)
        return out

    def _select_reranker(
        self,
        *,
        enable_rerank: bool,
        rerank_backend: str,
    ) -> tuple[Reranker | None, str]:
        if not enable_rerank:
            return None, "disabled"

        backend = (rerank_backend or "rule").strip().lower()
        if backend == "cross_encoder":
            if self.cross_encoder_reranker is not None:
                return self.cross_encoder_reranker, "cross_encoder"
            self.observability.incr("search.rerank.cross_encoder_unavailable")
            self.observability.emit(
                "memory.search.cross_encoder_unavailable",
                reason="missing_service_config",
            )
            return self.rule_reranker, "rule"

        if backend == "rule":
            if self.custom_reranker is not None:
                return self.custom_reranker, "custom"
            return self.rule_reranker, "rule"

        self.observability.incr("search.rerank.backend_invalid")
        self.observability.emit(
            "memory.search.invalid_rerank_backend",
            rerank_backend=backend,
        )
        return self.rule_reranker, "rule"

    def _assign_variant(self, *, project_id, user_id: str | None, query: str) -> str:
        if self.online_eval is not None:
            try:
                assignment = self.online_eval.assign_variant(
                    project_id=project_id,
                    user_id=user_id,
                    query=query,
                    b_ratio=float(self.runtime_config.retrieval.rerank.ab_test.b_ratio),
                )
                return assignment.variant
            except Exception:
                pass

        ab_cfg = self.runtime_config.retrieval.rerank.ab_test
        if not ab_cfg.enabled:
            backend = self.runtime_config.retrieval.rerank.backend.strip().lower()
            return "B" if backend == "cross_encoder" else "A"

        identity = user_id or "anonymous"
        key = f"{project_id}:{identity}:{query}"
        bucket = stable_bucket_ratio(key)
        return "B" if bucket < float(ab_cfg.b_ratio) else "A"

    def _resolve_rerank_backend(self, *, variant: str) -> str:
        if self.runtime_config.retrieval.rerank.ab_test.enabled:
            return "cross_encoder" if variant == "B" else "rule"

        backend = self.runtime_config.retrieval.rerank.backend.strip().lower()
        if backend in {"rule", "cross_encoder"}:
            return backend
        return "rule"

    @staticmethod
    def _build_request_id() -> str:
        return new_request_id()

    @staticmethod
    def _doc_to_row(doc: ScoredDoc) -> dict:
        row = doc.to_dict()
        row[SOURCE_TIMESTAMP_KEY] = doc.source_timestamp
        return row

    def _validate_sort_by(self, sort_by: str) -> None:
        if sort_by not in self._ALLOWED_SORT_BY:
            allowed = ", ".join(sorted(self._ALLOWED_SORT_BY))
            raise ValueError(f"sort_by 非法: {sort_by}，允许值: {allowed}")

    @staticmethod
    def _to_repo_sort(sort_by: str) -> str:
        mapping = {
            "relevance": "distance",
            "relevance_then_recent": "distance_then_source_timestamp_desc",
            "recent": "source_timestamp_desc",
            "timeline_asc": "source_timestamp_asc",
        }
        return mapping[sort_by]

    @staticmethod
    def _to_keyword_sort(vector_sort: str) -> str:
        if vector_sort == "source_timestamp_desc":
            return "source_timestamp_desc"
        if vector_sort == "source_timestamp_asc":
            return "source_timestamp_asc"
        return "keyword_score_desc"
