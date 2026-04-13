"""从备份文件恢复数据库（需要 psql 可执行）。"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from packages.storage.postgres.repositories.backup_run_repository import BackupRunRepository
from packages.storage.postgres.session import create_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description="WriterAgent DB 恢复")
    parser.add_argument("--file", required=True, help="备份 SQL 文件路径")
    args = parser.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL 未配置")

    session_factory = create_session_factory()
    db = session_factory()
    run = BackupRunRepository(db).create_run(
        backup_type="restore_verify",
        status="running",
        file_path=str(file_path),
    )
    try:
        cmd = ["psql", db_url, "-f", str(file_path)]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            BackupRunRepository(db).mark_failed(
                run.id,
                error_message=(proc.stderr or proc.stdout or "restore failed")[:4000],
            )
            raise RuntimeError(proc.stderr or proc.stdout or "restore failed")
        BackupRunRepository(db).mark_success(
            run.id,
            file_path=str(file_path),
            metadata_json={"command": "psql"},
        )
        print({"ok": True, "run_id": str(run.id)})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
