from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.storage.postgres.repositories.memory_rebuild_checkpoint_repository import (
    MemoryRebuildCheckpointRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository


@dataclass(frozen=True)
class RebuildStats:
    rebuilt: int
    stale_marked: int
    stale_requeued: int
    processed: int
    failed: int


class MemoryRebuildService:
    """长期记忆重建服务。"""

    def __init__(
        self,
        ingestion_service: MemoryIngestionService,
        memory_repo: MemoryChunkRepository,
        checkpoint_repo: MemoryRebuildCheckpointRepository | None = None,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.memory_repo = memory_repo
        self.checkpoint_repo = checkpoint_repo or MemoryRebuildCheckpointRepository(memory_repo.db)

    def rebuild_source(
        self,
        *,
        project_id,
        source_type: str,
        source_id,
        text: str,
        chunk_type: str = "paragraph",
        metadata_json: dict | None = None,
        source_timestamp: str | datetime | None = None,
    ) -> int:
        rows = self.ingestion_service.ingest_text(
            project_id=project_id,
            text=text,
            source_type=source_type,
            source_id=source_id,
            chunk_type=chunk_type,
            metadata_json=metadata_json,
            source_timestamp=source_timestamp,
            replace_existing=True,
        )
        return len(rows)

    def mark_source_stale(
        self,
        *,
        project_id,
        source_type: str,
        source_id,
        limit: int = 500,
    ) -> int:
        rows = self.memory_repo.list_by_source(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            embedding_status="done",
            limit=limit,
        )
        marked = 0
        for row in rows:
            self.memory_repo.mark_embedding_stale(row.id)
            marked += 1
        return marked

    def recompute_stale(
        self,
        *,
        project_id=None,
        requeue_limit: int = 200,
        process_limit: int = 200,
        batch_size: int | None = None,
        continue_on_error: bool = True,
    ) -> RebuildStats:
        stale_requeued = self.memory_repo.reset_stale_to_pending(
            project_id=project_id,
            limit=requeue_limit,
        )
        process_stats = self.ingestion_service.process_pending_embeddings(
            project_id=project_id,
            limit=process_limit,
            batch_size=batch_size,
            continue_on_error=continue_on_error,
        )
        return RebuildStats(
            rebuilt=0,
            stale_marked=0,
            stale_requeued=stale_requeued,
            processed=process_stats.processed,
            failed=process_stats.failed,
        )

    def rebuild_with_checkpoint(
        self,
        *,
        project_id,
        sources: list[dict],
        job_key: str = "default",
        checkpoint: int | None = None,
        metadata_json: dict | None = None,
    ) -> tuple[int, int]:
        """断点续跑：优先使用持久化 checkpoint，返回 (next_checkpoint, rebuilt_count)。"""
        state = self.checkpoint_repo.get_checkpoint(job_key=job_key, project_id=project_id)
        start_index = int(state.next_index) if state is not None else 0
        if checkpoint is not None:
            start_index = max(0, int(checkpoint))

        base_metadata = dict(metadata_json or {})
        base_metadata.update({"source_total": len(sources)})
        self.checkpoint_repo.save_checkpoint(
            job_key=job_key,
            project_id=project_id,
            next_index=start_index,
            status="running",
            metadata_json=base_metadata,
        )

        rebuilt = 0
        idx = start_index
        try:
            for idx in range(start_index, len(sources)):
                item = sources[idx]
                rebuilt += self.rebuild_source(
                    project_id=project_id,
                    source_type=str(item.get("source_type") or "unknown"),
                    source_id=item.get("source_id"),
                    text=str(item.get("text") or ""),
                    chunk_type=str(item.get("chunk_type") or "paragraph"),
                    metadata_json=item.get("metadata_json") or {},
                    source_timestamp=item.get("source_timestamp"),
                )
                self.checkpoint_repo.save_checkpoint(
                    job_key=job_key,
                    project_id=project_id,
                    next_index=idx + 1,
                    status="running",
                    metadata_json={
                        **base_metadata,
                        "last_source_type": str(item.get("source_type") or "unknown"),
                        "last_source_id": str(item.get("source_id"))
                        if item.get("source_id") is not None
                        else None,
                    },
                )
        except Exception as exc:
            self.checkpoint_repo.save_checkpoint(
                job_key=job_key,
                project_id=project_id,
                next_index=idx,
                status="failed",
                metadata_json={
                    **base_metadata,
                    "error": str(exc),
                },
            )
            raise

        next_index = len(sources)
        self.checkpoint_repo.save_checkpoint(
            job_key=job_key,
            project_id=project_id,
            next_index=next_index,
            status="done",
            metadata_json={
                **base_metadata,
                "rebuilt": rebuilt,
            },
        )
        return next_index, rebuilt


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
