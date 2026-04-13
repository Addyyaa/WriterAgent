from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from packages.memory.long_term.temporal import source_timestamp_to_epoch
from packages.retrieval.errors import RetrievalInputError
from packages.retrieval.hybrid.base import FusionStrategy
from packages.retrieval.hybrid.rrf_fusion import RRFFusionStrategy
from packages.retrieval.rerank.base import Reranker
from packages.retrieval.types import FilterExpr, RetrievalOptions, ScoredDoc


VectorRetriever = Callable[[str, FilterExpr, RetrievalOptions], list[ScoredDoc]]
KeywordRetriever = Callable[[str, FilterExpr, RetrievalOptions], list[ScoredDoc]]
QueryRewriterFn = Callable[[str], list[str]]


@dataclass(frozen=True)
class RetrievalPipelineTrace:
    """单次检索流水线的可观测结果。"""

    query_variants: int
    vector_candidates: int
    keyword_candidates: int
    merged_candidates: int
    returned: int


class RetrievalPipeline:
    """通用检索流水线。

    流程：query rewrite -> multi-retriever -> fusion -> rerank -> post-filter。
    """

    def __init__(
        self,
        *,
        vector_retriever: VectorRetriever,
        keyword_retriever: KeywordRetriever | None = None,
        query_rewriter: QueryRewriterFn | None = None,
        fusion_strategy: FusionStrategy | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.vector_retriever = vector_retriever
        self.keyword_retriever = keyword_retriever
        self.query_rewriter = query_rewriter
        self.fusion_strategy = fusion_strategy or RRFFusionStrategy()
        self.reranker = reranker

    def run(
        self,
        *,
        query: str,
        filters: FilterExpr | None = None,
        options: RetrievalOptions | None = None,
    ) -> list[ScoredDoc]:
        docs, _ = self.run_with_trace(query=query, filters=filters, options=options)
        return docs

    def run_with_trace(
        self,
        *,
        query: str,
        filters: FilterExpr | None = None,
        options: RetrievalOptions | None = None,
    ) -> tuple[list[ScoredDoc], RetrievalPipelineTrace]:
        if not isinstance(query, str) or not query.strip():
            raise RetrievalInputError("query 不能为空字符串")

        filters = filters or FilterExpr()
        options = options or RetrievalOptions()
        if options.top_k <= 0:
            return [], RetrievalPipelineTrace(0, 0, 0, 0, 0)

        variants = self._build_variants(query=query, enable_query_rewrite=options.enable_query_rewrite)
        if not variants:
            return [], RetrievalPipelineTrace(0, 0, 0, 0, 0)

        merged_by_id: dict[str, ScoredDoc] = {}
        vector_candidates = 0
        keyword_candidates = 0

        candidate_k = max(options.top_k, options.top_k * max(1, options.candidate_multiplier))
        candidate_options = RetrievalOptions(
            top_k=candidate_k,
            max_distance=options.max_distance,
            sort_by=options.sort_by,
            enable_query_rewrite=options.enable_query_rewrite,
            enable_hybrid=options.enable_hybrid,
            enable_rerank=options.enable_rerank,
            candidate_multiplier=options.candidate_multiplier,
        )

        for variant in variants:
            vector_docs = self.vector_retriever(variant, filters, candidate_options)
            vector_candidates += len(vector_docs)

            keyword_docs: list[ScoredDoc] = []
            if options.enable_hybrid and self.keyword_retriever is not None:
                keyword_docs = self.keyword_retriever(variant, filters, candidate_options)
                keyword_candidates += len(keyword_docs)

            if keyword_docs:
                combined = self.fusion_strategy.fuse([vector_docs, keyword_docs], top_k=candidate_k)
            elif options.enable_hybrid:
                combined = self.fusion_strategy.fuse([vector_docs], top_k=candidate_k)
            else:
                combined = vector_docs

            for doc in combined:
                self._merge_doc(merged_by_id, doc)

        merged = list(merged_by_id.values())
        merged = self._sort_results(merged, sort_by=options.sort_by)

        if options.enable_rerank and self.reranker is not None:
            merged = self.reranker.rerank(
                query=query,
                candidates=merged,
                top_k=options.top_k,
                sort_by=options.sort_by,
            )

        merged = self._post_filter(merged, options=options)
        final_docs = merged[: options.top_k]

        return final_docs, RetrievalPipelineTrace(
            query_variants=len(variants),
            vector_candidates=vector_candidates,
            keyword_candidates=keyword_candidates,
            merged_candidates=len(merged_by_id),
            returned=len(final_docs),
        )

    def _build_variants(self, *, query: str, enable_query_rewrite: bool) -> list[str]:
        base = query.strip()
        if not base:
            return []

        if not enable_query_rewrite or self.query_rewriter is None:
            return [base]

        variants = self.query_rewriter(base)
        if not variants:
            return [base]

        deduped: list[str] = []
        seen: set[str] = set()
        for item in variants:
            text = item.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)

        return deduped or [base]

    @staticmethod
    def _merge_doc(merged_by_id: dict[str, ScoredDoc], doc: ScoredDoc) -> None:
        key = str(doc.id)
        existing = merged_by_id.get(key)
        if existing is None:
            merged_by_id[key] = ScoredDoc(**doc.__dict__)
            return

        existing_hybrid = float(existing.hybrid_score or 0.0)
        current_hybrid = float(doc.hybrid_score or 0.0)
        if current_hybrid > existing_hybrid:
            merged_by_id[key] = ScoredDoc(**doc.__dict__)
            return

        if current_hybrid == existing_hybrid:
            existing_distance = existing.distance if existing.distance is not None else 1.0
            current_distance = doc.distance if doc.distance is not None else 1.0
            if current_distance < existing_distance:
                merged_by_id[key] = ScoredDoc(**doc.__dict__)

    @staticmethod
    def _sort_results(rows: list[ScoredDoc], *, sort_by: str) -> list[ScoredDoc]:
        def ts_epoch(item: ScoredDoc) -> float | None:
            return source_timestamp_to_epoch(item.source_timestamp)

        if sort_by == "source_timestamp_desc":
            return sorted(
                rows,
                key=lambda x: (
                    ts_epoch(x) is None,
                    -(ts_epoch(x) or 0.0),
                    -(x.hybrid_score or 0.0),
                    x.distance if x.distance is not None else 1.0,
                ),
            )

        if sort_by == "source_timestamp_asc":
            return sorted(
                rows,
                key=lambda x: (
                    ts_epoch(x) is None,
                    ts_epoch(x) or 0.0,
                    -(x.hybrid_score or 0.0),
                    x.distance if x.distance is not None else 1.0,
                ),
            )

        if sort_by == "distance_then_source_timestamp_desc":
            return sorted(
                rows,
                key=lambda x: (
                    -(x.hybrid_score or 0.0),
                    x.distance if x.distance is not None else 1.0,
                    ts_epoch(x) is None,
                    -(ts_epoch(x) or 0.0),
                ),
            )

        return sorted(
            rows,
            key=lambda x: (
                -(x.hybrid_score or 0.0),
                x.distance if x.distance is not None else 1.0,
            ),
        )

    @staticmethod
    def _post_filter(rows: list[ScoredDoc], *, options: RetrievalOptions) -> list[ScoredDoc]:
        if options.max_distance is None:
            return rows
        out: list[ScoredDoc] = []
        for row in rows:
            if row.distance is None:
                out.append(row)
                continue
            if row.distance <= float(options.max_distance):
                out.append(row)
        return out
