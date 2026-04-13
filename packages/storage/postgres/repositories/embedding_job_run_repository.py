from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.embedding_job_run import EmbeddingJobRun


class EmbeddingJobRunRepository(BaseRepository):
    """Embedding 作业运行记录仓储。"""

    def create_run(
        self,
        *,
        project_id,
        status: str,
        requested: int,
        processed: int,
        failed: int,
        skipped: int,
        retried: int,
        recovered_processing: int,
        duration_seconds: float,
        started_at: datetime,
        ended_at: datetime,
        error_message: str | None = None,
        metadata_json: dict | None = None,
    ) -> EmbeddingJobRun:
        row = EmbeddingJobRun(
            project_id=project_id,
            status=status,
            requested=requested,
            processed=processed,
            failed=failed,
            skipped=skipped,
            retried=retried,
            recovered_processing=recovered_processing,
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
            error_message=error_message,
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_recent(self, *, limit: int = 20) -> list[EmbeddingJobRun]:
        if limit <= 0:
            return []
        stmt = select(EmbeddingJobRun).order_by(EmbeddingJobRun.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

