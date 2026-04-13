from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from packages.storage.postgres.repositories.backup_run_repository import BackupRunRepository


class BackupService:
    def __init__(self, *, repo: BackupRunRepository) -> None:
        self.repo = repo

    def run_full_backup(self, *, output_dir: str, database_url: str | None = None) -> dict:
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_path = output_root / f"writeragent_backup_{ts}.sql"
        run = self.repo.create_run(backup_type="full", file_path=str(file_path))

        db_url = database_url or os.environ.get("DATABASE_URL", "")
        if not db_url:
            self.repo.mark_failed(run.id, error_message="DATABASE_URL 未配置")
            raise RuntimeError("DATABASE_URL 未配置")

        cmd = ["pg_dump", db_url, "-f", str(file_path)]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            self.repo.mark_failed(run.id, error_message=(proc.stderr or proc.stdout or "pg_dump 失败")[:4000])
            raise RuntimeError(proc.stderr or proc.stdout or "pg_dump 失败")

        size = file_path.stat().st_size if file_path.exists() else 0
        checksum = self._sha256_file(file_path)
        self.repo.mark_success(
            run.id,
            size_bytes=size,
            checksum=checksum,
            file_path=str(file_path),
            metadata_json={"command": "pg_dump"},
        )
        return {
            "run_id": str(run.id),
            "file_path": str(file_path),
            "size_bytes": int(size),
            "checksum": checksum,
        }

    def verify_backup_file(self, *, file_path: str) -> dict:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(str(path))
        return {
            "file_path": str(path),
            "size_bytes": int(path.stat().st_size),
            "checksum": self._sha256_file(path),
        }

    @staticmethod
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
