from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.project_transfer_job import ProjectTransferJob


class ProjectTransferJobRepository(BaseRepository):
    def create_job(
        self,
        *,
        job_type: str,
        project_id=None,
        created_by=None,
        source_path: str | None = None,
        target_path: str | None = None,
        include_chapters: bool = True,
        include_versions: bool = True,
        include_long_term_memory: bool = False,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> ProjectTransferJob:
        row = ProjectTransferJob(
            job_type=job_type,
            project_id=project_id,
            created_by=created_by,
            source_path=source_path,
            target_path=target_path,
            include_chapters=bool(include_chapters),
            include_versions=bool(include_versions),
            include_long_term_memory=bool(include_long_term_memory),
            metadata_json=metadata_json or {},
            manifest_json={},
            status="queued",
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, job_id) -> ProjectTransferJob | None:
        return self.db.get(ProjectTransferJob, job_id)

    def list_by_project(self, *, project_id, limit: int = 100) -> list[ProjectTransferJob]:
        stmt = (
            select(ProjectTransferJob)
            .where(ProjectTransferJob.project_id == project_id)
            .order_by(ProjectTransferJob.created_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())

    def mark_running(self, job_id, *, auto_commit: bool = True) -> ProjectTransferJob | None:
        row = self.get(job_id)
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.now(tz=timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_success(
        self,
        job_id,
        *,
        target_path: str | None = None,
        size_bytes: int | None = None,
        checksum: str | None = None,
        manifest_json: dict | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> ProjectTransferJob | None:
        row = self.get(job_id)
        if row is None:
            return None
        row.status = "success"
        row.finished_at = datetime.now(tz=timezone.utc)
        row.error_message = None
        if target_path is not None:
            row.target_path = target_path
        if size_bytes is not None:
            row.size_bytes = int(size_bytes)
        if checksum is not None:
            row.checksum = checksum
        if manifest_json is not None:
            row.manifest_json = dict(manifest_json)
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_failed(self, job_id, *, error_message: str, auto_commit: bool = True) -> ProjectTransferJob | None:
        row = self.get(job_id)
        if row is None:
            return None
        row.status = "failed"
        row.finished_at = datetime.now(tz=timezone.utc)
        row.error_message = error_message
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row
