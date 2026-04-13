"""
运行长期记忆遗忘任务（可用于 cron / scheduler）。

示例：
    python scripts/run_memory_forgetting_job.py --dry-run
    python scripts/run_memory_forgetting_job.py --project-id <uuid> --apply
    python scripts/run_memory_forgetting_job.py --apply --allow-hard-delete

可选环境变量：
    DATABASE_URL   覆盖默认数据库连接串
    SQL_ECHO=1     打印 SQL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.memory.long_term.lifecycle.forgetting import MemoryForgettingService
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run memory forgetting job")
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="只处理指定项目 UUID；不传则处理全部项目",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="单项目扫描上限；不传使用配置默认值",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出决策，不落库（默认行为）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行落库变更（与 --dry-run 二选一，--apply 优先）",
    )
    parser.add_argument(
        "--allow-hard-delete",
        action="store_true",
        help="允许进入硬删除阶段（默认关闭）",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    echo = os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes")
    engine = create_engine(db_url, echo=echo)
    SessionLocal = sessionmaker(bind=engine)

    dry_run = not args.apply if args.apply or args.dry_run else True

    db = SessionLocal()
    try:
        project_repo = ProjectRepository(db)
        memory_repo = MemoryChunkRepository(db)
        fact_repo = MemoryFactRepository(db)
        service = MemoryForgettingService(
            memory_repo=memory_repo,
            memory_fact_repo=fact_repo,
        )

        if args.project_id:
            project_ids = [UUID(args.project_id)]
        else:
            project_ids = [item.id for item in project_repo.list_all()]

        reports: list[dict] = []
        for project_id in project_ids:
            result = service.run_once(
                project_id=project_id,
                limit=args.limit,
                dry_run=dry_run,
                allow_hard_delete=bool(args.allow_hard_delete),
            )
            reports.append(
                {
                    "project_id": str(project_id),
                    "scanned": result.scanned,
                    "kept": result.kept,
                    "cooled": result.cooled,
                    "suppressed": result.suppressed,
                    "archived": result.archived,
                    "deleted": result.deleted,
                    "dry_run": result.dry_run,
                }
            )

        print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()

