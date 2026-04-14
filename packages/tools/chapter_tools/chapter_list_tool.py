from __future__ import annotations

from typing import Any

from packages.storage.postgres.repositories.chapter_repository import ChapterRepository


class ChapterListTool:
    """列出项目章节：仅章节名称（title）与概述（summary），不含正文。"""

    def __init__(self, db) -> None:
        self._db = db

    def run(self, *, project_id) -> dict[str, Any]:
        repo = ChapterRepository(self._db)
        rows = repo.list_by_project(project_id)
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": str(getattr(row, "id", "")),
                    "chapter_no": int(getattr(row, "chapter_no", 0) or 0),
                    "title": str(getattr(row, "title", "") or ""),
                    "summary": str(getattr(row, "summary", "") or ""),
                }
            )
        return {"count": len(items), "items": items}
