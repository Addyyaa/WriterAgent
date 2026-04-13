"""执行数据库全量备份并写入 backup_runs。"""

from __future__ import annotations

import argparse
from pathlib import Path

from packages.storage.postgres.repositories.backup_run_repository import BackupRunRepository
from packages.storage.postgres.session import create_session_factory
from packages.system.backup_service import BackupService


def main() -> int:
    parser = argparse.ArgumentParser(description="WriterAgent DB 全量备份")
    parser.add_argument("--output-dir", default="data/backups", help="备份输出目录")
    args = parser.parse_args()

    output_dir = str(Path(args.output_dir).expanduser())
    session_factory = create_session_factory()
    db = session_factory()
    try:
        service = BackupService(repo=BackupRunRepository(db))
        result = service.run_full_backup(output_dir=output_dir)
        print(result)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
