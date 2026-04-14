from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import sessionmaker

from packages.storage.postgres.repositories.project_repository import ProjectRepository
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


@dataclass(frozen=True)
class LocalProjectListTool:
    """通过本地数据库仓储直接查询项目列表，不依赖 HTTP token。"""

    db_url: str = ""

    def run(self, *, limit: int = 20) -> dict[str, Any]:
        size = max(1, min(int(limit), 200))
        effective_db_url = str(self.db_url or os.environ.get("DATABASE_URL") or _DEFAULT_DATABASE_URL).strip()
        engine = create_engine_with_driver_fallback(effective_db_url, echo=False)
        session_local = sessionmaker(bind=engine)
        db = session_local()
        try:
            repo = ProjectRepository(db)
            rows = repo.list_all()[:size]
            return {
                "count": len(rows),
                "items": [
                    {
                        "id": str(getattr(row, "id", "")),
                        "title": str(getattr(row, "title", "") or ""),
                        "genre": str(getattr(row, "genre", "") or ""),
                        "premise": str(getattr(row, "premise", "") or ""),
                        "created_at": (
                            getattr(row, "created_at", None).isoformat()
                            if getattr(row, "created_at", None) is not None
                            else ""
                        ),
                    }
                    for row in rows
                ],
            }
        finally:
            db.close()
