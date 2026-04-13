"""执行备份文件完整性校验（演练脚本）。"""

from __future__ import annotations

import argparse

from packages.storage.postgres.repositories.backup_run_repository import BackupRunRepository
from packages.storage.postgres.session import create_session_factory
from packages.system.backup_service import BackupService


def main() -> int:
    parser = argparse.ArgumentParser(description="WriterAgent 备份校验演练")
    parser.add_argument("--file", required=True, help="备份文件路径")
    args = parser.parse_args()

    session_factory = create_session_factory()
    db = session_factory()
    run = BackupRunRepository(db).create_run(backup_type="restore_verify", status="running", file_path=args.file)
    try:
        result = BackupService(repo=BackupRunRepository(db)).verify_backup_file(file_path=args.file)
        BackupRunRepository(db).mark_success(
            run.id,
            file_path=result["file_path"],
            size_bytes=result["size_bytes"],
            checksum=result["checksum"],
            metadata_json={"verify_only": True},
        )
        print({"ok": True, "run_id": str(run.id), **result})
        return 0
    except Exception as exc:
        BackupRunRepository(db).mark_failed(run.id, error_message=str(exc))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
