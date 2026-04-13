from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.memory_rebuild_checkpoint import (
    MemoryRebuildCheckpoint,
)


class MemoryRebuildCheckpointRepository(BaseRepository):
    """重建断点仓储。"""

    def get_checkpoint(self, *, job_key: str, project_id) -> MemoryRebuildCheckpoint | None:
        stmt = select(MemoryRebuildCheckpoint).where(
            MemoryRebuildCheckpoint.job_key == job_key,
            MemoryRebuildCheckpoint.project_id == project_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def save_checkpoint(
        self,
        *,
        job_key: str,
        project_id,
        next_index: int,
        status: str,
        metadata_json: dict | None = None,
    ) -> MemoryRebuildCheckpoint:
        row = self.get_checkpoint(job_key=job_key, project_id=project_id)
        if row is None:
            row = MemoryRebuildCheckpoint(
                job_key=job_key,
                project_id=project_id,
                next_index=max(0, int(next_index)),
                status=status,
                metadata_json=metadata_json or {},
            )
            self.db.add(row)
        else:
            row.next_index = max(0, int(next_index))
            row.status = status
            row.metadata_json = metadata_json or {}
        self.db.commit()
        self.db.refresh(row)
        return row

