from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence, TypeVar

from packages.core.utils import summarize_text_extractive
from packages.llm.embeddings.base import EmbeddingProvider
from packages.memory.long_term.observability import MemoryObservability
from packages.memory.long_term.runtime_config import MemoryRuntimeConfig
from packages.memory.long_term.temporal import SOURCE_TIMESTAMP_KEY
from packages.retrieval.chunking.base import TextChunker
from packages.storage.postgres.models.memory_chunk import MemoryChunk
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import (
    MemoryChunkRepository,
)


class MemoryIngestionError(RuntimeError):
    """记忆摄入流程异常基类。"""


class InvalidIngestionInputError(MemoryIngestionError):
    """输入参数不合法。"""


class EmbeddingGenerationError(MemoryIngestionError):
    """向量生成失败或结果不一致。"""


@dataclass(frozen=True)
class PendingEmbeddingProcessStats:
    """批处理 pending 分块时的统计结果。"""

    requested: int
    processed: int
    failed: int
    skipped: int
    retried: int = 0
    recovered_processing: int = 0


class MemoryIngestionService:
    """
    记忆文本摄入服务。

    默认启用双层去重策略：
    1. exact dedup（归一化 hash）
    2. semantic dedup（embedding 距离阈值）

    存储分层：
    - memory_facts: 去重后的规范事实
    - memory_mentions: 原始提及
    - memory_chunks: 仅保留 canonical facts 供检索
    """

    def __init__(
        self,
        chunker: TextChunker,
        embedding_provider: EmbeddingProvider,
        memory_repo: MemoryChunkRepository,
        memory_fact_repo: MemoryFactRepository | None = None,
        embedding_batch_size: int | None = None,
        replace_existing_by_default: bool | None = None,
        enable_semantic_dedup: bool = True,
        semantic_dedup_threshold: float | None = None,
        summary_target_tokens: int | None = None,
        runtime_config: MemoryRuntimeConfig | None = None,
        observability: MemoryObservability | None = None,
    ) -> None:
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.memory_repo = memory_repo
        self.enable_semantic_dedup = enable_semantic_dedup

        self.runtime_config = runtime_config or MemoryRuntimeConfig.from_env()
        self.observability = observability or MemoryObservability(
            logger_name=self.runtime_config.observability.logger_name,
            enable_logging=self.runtime_config.observability.enable_logging,
        )

        effective_threshold = (
            self.runtime_config.ingestion.semantic_dedup_threshold
            if semantic_dedup_threshold is None
            else semantic_dedup_threshold
        )
        if effective_threshold < 0:
            raise ValueError("semantic_dedup_threshold 不能小于 0")
        self.semantic_dedup_threshold = effective_threshold

        effective_summary_tokens = (
            self.runtime_config.ingestion.summary_target_tokens
            if summary_target_tokens is None
            else summary_target_tokens
        )
        if effective_summary_tokens <= 0:
            raise ValueError("summary_target_tokens 必须大于 0")
        self.summary_target_tokens = int(effective_summary_tokens)

        self.memory_fact_repo = (
            memory_fact_repo
            if memory_fact_repo is not None
            else (
                MemoryFactRepository(memory_repo.db)
                if enable_semantic_dedup
                else None
            )
        )

        effective_batch_size = (
            self.runtime_config.ingestion.embedding_batch_size
            if embedding_batch_size is None
            else embedding_batch_size
        )
        if effective_batch_size <= 0:
            raise ValueError("embedding_batch_size 必须大于 0")
        self.embedding_batch_size = effective_batch_size

        self.replace_existing_by_default = (
            self.runtime_config.ingestion.replace_existing_by_default
            if replace_existing_by_default is None
            else replace_existing_by_default
        )

    def ingest_text(
        self,
        project_id,
        text: str,
        source_type: str,
        source_id=None,
        chunk_type: str = "paragraph",
        metadata_json: dict | None = None,
        source_timestamp: str | datetime | None = None,
        replace_existing: bool | None = None,
    ) -> list[MemoryChunk]:
        """
        同步摄入：分块 -> embedding -> 存储。

        时间语义：
        - 可通过 `source_timestamp` 传入“内容发生时间”并写入 metadata_json。
        - 不在 ingestion 层做时间抽取（例如从自然语言里解析日期）。

        启用双层去重时，replace_existing 不再主导写入策略，
        因为写入由“事实归并 + 提及聚合”控制。
        # 规则：
        # enable_semantic_dedup=True 时：
        #   replace_existing 仅影响原始 mention / pending 行，不直接决定 canonical fact 写入
        # enable_semantic_dedup=False 时：
        #   replace_existing 才直接影响 source chunks 替换逻辑
        """
        clean_text = self._normalize_text(text)
        if not clean_text:
            return []
        clean_source_type = self._normalize_source_type(source_type)
        metadata_json = metadata_json or {}

        chunks = self._chunk_text(clean_text)
        if not chunks:
            return []

        embeddings = self._embed_in_batches(chunks)

        rows: list[dict] = []
        for idx, (chunk_text, embedding) in enumerate(
            zip(chunks, embeddings, strict=True)
        ):
            summary_text = self._build_chunk_summary(chunk_text)
            rows.append(
                {
                    "source_type": clean_source_type,
                    "source_id": source_id,
                    "chunk_type": chunk_type,
                    "text": chunk_text,
                    "summary_text": summary_text,
                    "metadata_json": self._build_ingest_metadata(
                        metadata_json=metadata_json,
                        chunk_index=idx,
                        chunk_total=len(chunks),
                        source_timestamp=source_timestamp,
                        summary_text=summary_text,
                        summary_method="extractive_v1",
                    ),
                    "embedding": embedding,
                    "embedding_status": "done",
                }
            )

        if self.enable_semantic_dedup and self.memory_fact_repo is not None:
            created = self._persist_rows_with_dedup(project_id=project_id, rows=rows)
            self.observability.incr("ingestion.sync.calls")
            self.observability.incr("ingestion.sync.rows", len(created))
            self.observability.emit(
                "memory.ingestion.sync",
                project_id=str(project_id),
                source_type=clean_source_type,
                chunks=len(chunks),
                created=len(created),
                dedup=True,
            )
            return created

        should_replace = (
            self.replace_existing_by_default
            if replace_existing is None
            else replace_existing
        )

        if should_replace and source_id is not None:
            created = self.memory_repo.replace_source_chunks(
                project_id=project_id,
                source_type=clean_source_type,
                source_id=source_id,
                chunks=rows,
            )
        else:
            created = self.memory_repo.create_chunks(project_id=project_id, chunks=rows)

        self.observability.incr("ingestion.sync.calls")
        self.observability.incr("ingestion.sync.rows", len(created))
        self.observability.emit(
            "memory.ingestion.sync",
            project_id=str(project_id),
            source_type=clean_source_type,
            chunks=len(chunks),
            created=len(created),
            dedup=False,
            replace_existing=bool(should_replace),
        )
        return created

    def ingest_text_as_pending(
        self,
        project_id,
        text: str,
        source_type: str,
        source_id=None,
        chunk_type: str = "paragraph",
        metadata_json: dict | None = None,
        source_timestamp: str | datetime | None = None,
        replace_existing: bool | None = None,
    ) -> list[MemoryChunk]:
        """
        仅完成入库分块，不立即生成 embedding。

        时间语义：
        - 可通过 `source_timestamp` 透传“内容发生时间”。
        - 若上游未提供则保持 null（不强制要求）。

        异步流程中，双层去重会在 process_pending_embeddings 中执行。
        """
        clean_text = self._normalize_text(text)
        if not clean_text:
            return []
        clean_source_type = self._normalize_source_type(source_type)
        metadata_json = metadata_json or {}

        chunks = self._chunk_text(clean_text)
        if not chunks:
            return []

        rows: list[dict] = []
        for idx, chunk_text in enumerate(chunks):
            summary_text = self._build_chunk_summary(chunk_text)
            rows.append(
                {
                    "source_type": clean_source_type,
                    "source_id": source_id,
                    "chunk_type": chunk_type,
                    "text": chunk_text,
                    "summary_text": summary_text,
                    "metadata_json": self._build_ingest_metadata(
                        metadata_json=metadata_json,
                        chunk_index=idx,
                        chunk_total=len(chunks),
                        source_timestamp=source_timestamp,
                        summary_text=summary_text,
                        summary_method="extractive_v1",
                    ),
                    "embedding": None,
                    "embedding_status": "pending",
                }
            )

        should_replace = (
            self.replace_existing_by_default
            if replace_existing is None
            else replace_existing
        )

        if should_replace and source_id is not None:
            created = self.memory_repo.replace_source_chunks(
                project_id=project_id,
                source_type=clean_source_type,
                source_id=source_id,
                chunks=rows,
            )
        else:
            created = self.memory_repo.create_chunks(project_id=project_id, chunks=rows)

        self.observability.incr("ingestion.pending.calls")
        self.observability.incr("ingestion.pending.rows", len(created))
        self.observability.emit(
            "memory.ingestion.pending",
            project_id=str(project_id),
            source_type=clean_source_type,
            chunks=len(chunks),
            created=len(created),
            replace_existing=bool(should_replace),
        )
        return created

    def retry_failed_embeddings(
        self,
        *,
        project_id=None,
        limit: int = 200,
    ) -> int:
        moved = self.memory_repo.reset_failed_to_pending(project_id=project_id, limit=limit)
        if moved > 0:
            self.observability.incr("ingestion.retry_failed.rows", moved)
            self.observability.emit(
                "memory.ingestion.retry_failed",
                project_id=str(project_id) if project_id else None,
                moved=moved,
                limit=limit,
            )
        return moved

    def process_pending_embeddings(
        self,
        *,
        project_id=None,
        limit: int = 200,
        batch_size: int | None = None,
        continue_on_error: bool = True,
        retry_failed_first: bool = False,
        retry_failed_limit: int | None = None,
        recover_stuck_processing: bool = True,
        processing_stale_after_seconds: int = 900,
    ) -> PendingEmbeddingProcessStats:
        """
        处理 pending 分块并更新状态。

        启用双层去重时：
        - 新事实：pending 行升级为 canonical fact 行
        - 重复事实：pending 行折叠删除，仅保留 mention
        """
        if limit <= 0:
            return PendingEmbeddingProcessStats(
                requested=0,
                processed=0,
                failed=0,
                skipped=0,
            )

        recovered_processing = 0
        retried = 0

        if recover_stuck_processing:
            recovered_processing = self.memory_repo.reset_processing_to_pending(
                project_id=project_id,
                stale_after_seconds=processing_stale_after_seconds,
                limit=limit,
            )

        if retry_failed_first:
            retried = self.retry_failed_embeddings(
                project_id=project_id,
                limit=retry_failed_limit or limit,
            )

        pending_rows = self.memory_repo.list_pending_embeddings(
            project_id=project_id,
            limit=limit,
        )
        if not pending_rows:
            stats = PendingEmbeddingProcessStats(
                requested=0,
                processed=0,
                failed=0,
                skipped=0,
                retried=retried,
                recovered_processing=recovered_processing,
            )
            self._emit_pending_process_event(project_id=project_id, stats=stats)
            return stats

        requested = len(pending_rows)
        processed = 0
        failed = 0
        skipped = 0
        effective_batch_size = batch_size or self.embedding_batch_size
        if effective_batch_size <= 0:
            raise ValueError("batch_size 必须大于 0")

        for batch in self._batched(pending_rows, effective_batch_size):
            valid_rows: list[MemoryChunk] = []
            texts: list[str] = []

            for row in batch:
                chunk_text = self._normalize_text(row.chunk_text or "")
                if not chunk_text:
                    skipped += 1
                    self._mark_failed_safely(row.id)
                    continue

                self.memory_repo.mark_embedding_processing(row.id)
                valid_rows.append(row)
                texts.append(chunk_text)

            if not valid_rows:
                continue

            try:
                embeddings = self.embedding_provider.embed_texts(texts)
                if len(embeddings) != len(valid_rows):
                    raise EmbeddingGenerationError(
                        "embedding 返回数量与分块数量不一致："
                        f"{len(embeddings)} != {len(valid_rows)}"
                    )

                for row, embedding in zip(valid_rows, embeddings, strict=True):
                    # 单条记录原子事务：fact/mention 与 chunk 状态保持一致提交，
                    # 避免出现“事实已写入但 chunk 未完成状态迁移”的半成功问题。
                    try:
                        if self.enable_semantic_dedup and self.memory_fact_repo is not None:
                            result = self.memory_fact_repo.upsert_fact_with_mention(
                                project_id=row.project_id,
                                source_type=row.source_type or "unknown",
                                source_id=row.source_id,
                                chunk_type=row.chunk_type,
                                raw_text=row.chunk_text or "",
                                embedding=embedding,
                                metadata_json=row.metadata_json or {},
                                semantic_threshold=self.semantic_dedup_threshold,
                                auto_commit=False,
                            )
                            if result.created_new_fact:
                                canonical_metadata = self._build_canonical_metadata(
                                    original_metadata=row.metadata_json or {},
                                    original_source_type=row.source_type or "unknown",
                                    original_source_id=row.source_id,
                                    semantic_distance=result.semantic_distance,
                                    fact_id=result.fact.id,
                                    summary_text=result.fact.summary_text,
                                )
                                self.memory_repo.update_chunk(
                                    row.id,
                                    source_type="memory_fact",
                                    source_id=result.fact.id,
                                    chunk_type="canonical_fact",
                                    text=result.fact.canonical_text,
                                    summary_text=result.fact.summary_text,
                                    metadata_json=canonical_metadata,
                                    embedding=embedding,
                                    embedding_status="done",
                                    auto_commit=False,
                                )
                            else:
                                self.memory_repo.delete(row.id, auto_commit=False)
                        else:
                            self.memory_repo.mark_embedding_done(
                                row.id,
                                embedding,
                                auto_commit=False,
                            )
                        self.memory_repo.db.commit()
                        processed += 1
                    except Exception:
                        self.memory_repo.db.rollback()
                        self._mark_failed_safely(row.id)
                        failed += 1
                        if not continue_on_error:
                            raise
            except Exception as exc:
                for row in valid_rows:
                    self._mark_failed_safely(row.id)
                    failed += 1
                if not continue_on_error:
                    raise EmbeddingGenerationError(
                        "process_pending_embeddings 处理失败，已标记当前批次为 failed"
                    ) from exc

        stats = PendingEmbeddingProcessStats(
            requested=requested,
            processed=processed,
            failed=failed,
            skipped=skipped,
            retried=retried,
            recovered_processing=recovered_processing,
        )
        self._emit_pending_process_event(project_id=project_id, stats=stats)
        return stats

    def get_metrics_snapshot(self) -> dict[str, int]:
        return self.observability.snapshot()

    def _emit_pending_process_event(self, *, project_id, stats: PendingEmbeddingProcessStats) -> None:
        self.observability.incr("ingestion.pending_process.calls")
        self.observability.incr("ingestion.pending_process.requested", stats.requested)
        self.observability.incr("ingestion.pending_process.processed", stats.processed)
        self.observability.incr("ingestion.pending_process.failed", stats.failed)
        self.observability.incr("ingestion.pending_process.skipped", stats.skipped)
        self.observability.incr("ingestion.pending_process.retried", stats.retried)
        self.observability.incr(
            "ingestion.pending_process.recovered_processing",
            stats.recovered_processing,
        )
        self.observability.emit(
            "memory.ingestion.process_pending",
            project_id=str(project_id) if project_id else None,
            requested=stats.requested,
            processed=stats.processed,
            failed=stats.failed,
            skipped=stats.skipped,
            retried=stats.retried,
            recovered_processing=stats.recovered_processing,
        )

    def _mark_failed_safely(self, chunk_id) -> None:
        try:
            self.memory_repo.mark_embedding_failed(chunk_id)
        except Exception:
            self.memory_repo.update_chunk(
                chunk_id,
                embedding_status="failed",
            )

    def _chunk_text(self, text: str) -> list[str]:
        try:
            raw_chunks = self.chunker.chunk(text)
        except Exception as exc:
            raise MemoryIngestionError("文本分块失败") from exc

        chunks = [item.strip() for item in raw_chunks if item and item.strip()]
        return chunks

    def _embed_in_batches(self, chunks: Sequence[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for batch in self._batched(chunks, self.embedding_batch_size):
            try:
                batch_embeddings = self.embedding_provider.embed_texts(list(batch))
            except Exception as exc:
                raise EmbeddingGenerationError("向量生成失败") from exc

            if len(batch_embeddings) != len(batch):
                raise EmbeddingGenerationError(
                    "embedding 返回数量与分块数量不一致："
                    f"{len(batch_embeddings)} != {len(batch)}"
                )
            embeddings.extend(batch_embeddings)
        return embeddings

    def _persist_rows_with_dedup(
        self,
        *,
        project_id,
        rows: list[dict],
    ) -> list[MemoryChunk]:
        if not rows:
            return []
        if self.memory_fact_repo is None:
            return self.memory_repo.create_chunks(project_id=project_id, chunks=rows)

        canonical_rows: list[dict] = []
        for row in rows:
            result = self.memory_fact_repo.upsert_fact_with_mention(
                project_id=project_id,
                source_type=row["source_type"],
                source_id=row.get("source_id"),
                chunk_type=row.get("chunk_type"),
                raw_text=row["text"],
                embedding=row["embedding"],
                metadata_json=row.get("metadata_json") or {},
                semantic_threshold=self.semantic_dedup_threshold,
            )

            # 仅新事实进入检索主表，确保检索层天然去重。
            if result.created_new_fact:
                canonical_rows.append(
                    {
                        "source_type": "memory_fact",
                        "source_id": result.fact.id,
                        "chunk_type": "canonical_fact",
                        "text": result.fact.canonical_text,
                        "summary_text": result.fact.summary_text,
                        "metadata_json": self._build_canonical_metadata(
                            original_metadata=row.get("metadata_json") or {},
                            original_source_type=row["source_type"],
                            original_source_id=row.get("source_id"),
                            semantic_distance=result.semantic_distance,
                            fact_id=result.fact.id,
                            summary_text=result.fact.summary_text,
                        ),
                        "embedding": row["embedding"],
                        "embedding_status": "done",
                    }
                )
            else:
                self._revive_or_touch_fact_chunk(
                    project_id=project_id,
                    fact_id=result.fact.id,
                    fallback_embedding=row["embedding"],
                )

        if not canonical_rows:
            return []
        return self.memory_repo.create_chunks(project_id=project_id, chunks=canonical_rows)

    def _revive_or_touch_fact_chunk(
        self,
        *,
        project_id,
        fact_id,
        fallback_embedding: list[float],
    ) -> None:
        """
        当旧 fact 再次被提及时，确保其 canonical chunk 可检索。
        """
        rows = self.memory_repo.list_by_source(
            project_id=project_id,
            source_type="memory_fact",
            source_id=fact_id,
            limit=1,
        )
        if not rows:
            fact = self.memory_fact_repo.get(fact_id) if self.memory_fact_repo else None
            if fact is None:
                return
            self.memory_repo.create_chunks(
                project_id=project_id,
                chunks=[
                    {
                        "source_type": "memory_fact",
                        "source_id": fact.id,
                        "chunk_type": "canonical_fact",
                        "text": fact.canonical_text,
                        "summary_text": fact.summary_text,
                        "metadata_json": {
                            "dedup_strategy": "exact_then_semantic",
                            "canonical_fact_id": str(fact.id),
                            "summary_text": fact.summary_text,
                        },
                        "embedding": self._normalize_embedding_payload(
                            fact.embedding,
                            fallback=fallback_embedding,
                        ),
                        "embedding_status": "done",
                    }
                ],
            )
            return

        chunk = rows[0]
        metadata = dict(chunk.metadata_json or {})
        for key in ("forgetting_stage", "forgetting_reason", "forgetting_score", "forgotten_at"):
            metadata.pop(key, None)

        if str(chunk.embedding_status) != "done" or metadata != (chunk.metadata_json or {}):
            self.memory_repo.update_chunk(
                chunk.id,
                metadata_json=metadata,
                embedding_status="done",
                auto_commit=True,
            )

    @staticmethod
    def _normalize_embedding_payload(value: Any, *, fallback: Sequence[float]) -> list[float]:
        """
        兼容历史数据里 embedding 可能是 pgvector 字符串（如 "[0.1,0.2]"）的情况。
        """
        candidate = value if value is not None else fallback
        if isinstance(candidate, str):
            text = candidate.strip()
            if text.startswith("[") and text.endswith("]"):
                body = text[1:-1].strip()
                if not body:
                    return [float(x) for x in list(fallback)]
                try:
                    return [float(part.strip()) for part in body.split(",") if part.strip()]
                except ValueError:
                    return [float(x) for x in list(fallback)]
            return [float(x) for x in list(fallback)]
        if isinstance(candidate, Sequence):
            try:
                return [float(x) for x in list(candidate)]
            except (TypeError, ValueError):
                return [float(x) for x in list(fallback)]
        return [float(x) for x in list(fallback)]

    @staticmethod
    def _build_canonical_metadata(
        *,
        original_metadata: dict,
        original_source_type: str,
        original_source_id,
        semantic_distance: float | None,
        fact_id,
        summary_text: str | None,
    ) -> dict:
        metadata = dict(original_metadata)
        metadata.update(
            {
                "dedup_strategy": "exact_then_semantic",
                "canonical_fact_id": str(fact_id),
                "origin_source_type": original_source_type,
                "origin_source_id": str(original_source_id) if original_source_id else None,
                "semantic_distance": semantic_distance,
                "summary_text": summary_text,
            }
        )
        return metadata

    @staticmethod
    def _build_ingest_metadata(
        *,
        metadata_json: dict,
        chunk_index: int,
        chunk_total: int,
        source_timestamp: str | datetime | None,
        summary_text: str | None,
        summary_method: str | None,
    ) -> dict:
        """
        构建入库 metadata。

        说明：
        - `source_timestamp` 仅透传上游提供值，不在 ingestion 层做文本时间抽取。
        - 具体规范化（ISO8601/UTC）由 repository 层统一处理，避免多处重复逻辑。
        """
        metadata = dict(metadata_json)
        if source_timestamp is not None:
            metadata[SOURCE_TIMESTAMP_KEY] = source_timestamp
        if summary_text:
            metadata["summary_text"] = summary_text
        if summary_method:
            metadata["summary_method"] = summary_method
        metadata.update(
            {
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
                "ingested_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        return metadata

    def _build_chunk_summary(self, text: str) -> str:
        return summarize_text_extractive(
            text,
            target_tokens=self.summary_target_tokens,
            min_sentences=1,
            max_sentences=3,
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        if not isinstance(value, str):
            raise InvalidIngestionInputError("text 必须是字符串")
        return value.strip()

    @staticmethod
    def _normalize_source_type(value: str) -> str:
        if not isinstance(value, str):
            raise InvalidIngestionInputError("source_type 必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise InvalidIngestionInputError("source_type 不能为空")
        return normalized

    T = TypeVar("T")

    @staticmethod
    def _batched(seq: Sequence[T], size: int) -> Iterable[Sequence[T]]:
        for i in range(0, len(seq), size):
            yield seq[i : i + size]
