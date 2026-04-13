from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.backup_run import BackupRun


class BackupRunRepository(BaseRepository):
    def create_run(
        self,
        *,
        backup_type: str,
        status: str = "running",
        metadata_json: dict | None = None,
        file_path: str | None = None,
        auto_commit: bool = True,
    ) -> BackupRun:
        row = BackupRun(
            backup_type=backup_type,
            status=status,
            metadata_json=metadata_json or {},
            file_path=file_path,
            started_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, run_id) -> BackupRun | None:
        return self.db.get(BackupRun, run_id)

    def mark_success(
        self,
        run_id,
        *,
        size_bytes: int | None = None,
        checksum: str | None = None,
        file_path: str | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> BackupRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "success"
        row.finished_at = datetime.now(tz=timezone.utc)
        row.error_message = None
        if size_bytes is not None:
            row.size_bytes = int(size_bytes)
        if checksum is not None:
            row.checksum = checksum
        if file_path is not None:
            row.file_path = file_path
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_failed(
        self,
        run_id,
        *,
        error_message: str,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> BackupRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "failed"
        row.finished_at = datetime.now(tz=timezone.utc)
        row.error_message = error_message
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def latest(self) -> BackupRun | None:
        stmt = select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1)
        return self.db.execute(stmt).scalar_one_or_none()

    def latest_success(self) -> BackupRun | None:
        stmt = (
            select(BackupRun)
            .where(BackupRun.status == "success")
            .order_by(BackupRun.started_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_runs(self, *, limit: int = 100) -> list[BackupRun]:
        stmt = select(BackupRun).order_by(BackupRun.started_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())
