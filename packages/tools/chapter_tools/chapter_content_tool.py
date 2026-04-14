from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.storage.postgres.repositories.chapter_repository import ChapterRepository


class ChapterContentTool:
    """读取章节正文；支持 chapter_id（UUID）或项目内章节标题（chapter_title）。"""

    def __init__(self, db) -> None:
        self._db = db

    def run(
        self,
        *,
        project_id,
        chapter_id: str | None = None,
        chapter_title: str | None = None,
    ) -> dict[str, Any]:
        repo = ChapterRepository(self._db)
        row = None
        cid = str(chapter_id or "").strip()
        if cid:
            try:
                row = repo.get(UUID(cid))
            except (ValueError, TypeError):
                row = None
            if row is not None and str(row.project_id) != str(project_id):
                return {"found": False, "error": "chapter_id 不属于该项目"}
        if row is None:
            title = str(chapter_title or "").strip()
            if not title:
                return {"found": False, "error": "需提供 chapter_id 或 chapter_title"}
            row = repo.find_by_project_title(project_id, title)
        if row is None:
            return {"found": False, "error": "未找到匹配章节"}
        return {
            "found": True,
            "chapter": {
                "id": str(row.id),
                "project_id": str(row.project_id),
                "chapter_no": int(row.chapter_no or 0),
                "title": str(row.title or ""),
                "summary": str(row.summary or ""),
                "content": str(row.content or ""),
                "status": str(row.status or ""),
                "draft_version": int(row.draft_version or 1),
            },
        }
