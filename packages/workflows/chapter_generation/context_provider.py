from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from packages.storage.postgres.models.chapter import Chapter
from packages.storage.postgres.models.character import Character
from packages.storage.postgres.models.character_chapter_asset import CharacterChapterAsset
from packages.storage.postgres.models.foreshadowing import Foreshadowing
from packages.storage.postgres.models.timeline_event import TimelineEvent
from packages.storage.postgres.models.world_entry import WorldEntry


@dataclass(frozen=True)
class StoryConstraintContext:
    chapters: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    world_entries: list[dict[str, Any]]
    timeline_events: list[dict[str, Any]]
    foreshadowings: list[dict[str, Any]]


class SQLAlchemyStoryContextProvider:
    """从业务表读取写作硬约束上下文。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def load(
        self,
        *,
        project_id,
        chapter_no: int | None = None,
        chapter_window_before: int = 2,
        chapter_window_after: int = 1,
    ) -> StoryConstraintContext:
        return StoryConstraintContext(
            chapters=self._list_chapters(
                project_id=project_id,
                limit=20,
                chapter_no=chapter_no,
                chapter_window_before=chapter_window_before,
                chapter_window_after=chapter_window_after,
            ),
            characters=self._list_characters(
                project_id=project_id,
                limit=30,
                chapter_no=chapter_no,
            ),
            world_entries=self._list_world_entries(project_id=project_id, limit=30),
            timeline_events=self._list_timeline_events(project_id=project_id, limit=30),
            foreshadowings=self._list_foreshadowings(project_id=project_id, limit=30),
        )

    def _list_chapters(
        self,
        *,
        project_id,
        limit: int,
        chapter_no: int | None = None,
        chapter_window_before: int = 2,
        chapter_window_after: int = 1,
    ) -> list[dict[str, Any]]:
        stmt = select(Chapter).where(Chapter.project_id == project_id)
        if chapter_no is not None:
            before = max(0, int(chapter_window_before))
            after = max(0, int(chapter_window_after))
            lower = max(1, int(chapter_no) - before)
            upper = int(chapter_no) + after
            stmt = stmt.where(and_(Chapter.chapter_no >= lower, Chapter.chapter_no <= upper))
        stmt = stmt.order_by(Chapter.chapter_no.asc()).limit(limit)
        rows = list(self.db.execute(stmt).scalars().all())
        return [
            {
                "id": str(row.id),
                "chapter_no": int(row.chapter_no),
                "title": row.title,
                "summary": row.summary,
                "content_preview": (row.content or "")[:200],
                "status": str(row.status.value if hasattr(row.status, "value") else row.status),
            }
            for row in rows
        ]

    def _list_characters(
        self,
        *,
        project_id,
        limit: int,
        chapter_no: int | None = None,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Character)
            .where(Character.project_id == project_id, Character.is_canonical.is_(True))
            .order_by(Character.updated_at.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        snap_by_char: dict[str, CharacterChapterAsset] = {}
        if chapter_no is not None:
            snap_stmt = (
                select(CharacterChapterAsset)
                .join(Character, Character.id == CharacterChapterAsset.character_id)
                .where(
                    Character.project_id == project_id,
                    CharacterChapterAsset.chapter_no == int(chapter_no),
                )
            )
            for snap in self.db.execute(snap_stmt).scalars().all():
                snap_by_char[str(snap.character_id)] = snap

        out: list[dict[str, Any]] = []
        for row in rows:
            inv = dict(getattr(row, "inventory_json", None) or {})
            wealth = dict(getattr(row, "wealth_json", None) or {})
            snap = snap_by_char.get(str(row.id))
            chapter_inventory = dict(snap.inventory_json or {}) if snap else {}
            chapter_wealth = dict(snap.wealth_json or {}) if snap else {}
            item = {
                "id": str(row.id),
                "name": row.name,
                "role_type": row.role_type,
                "faction": row.faction,
                "profile_json": row.profile_json or {},
                "speech_style_json": row.speech_style_json or {},
                "arc_status_json": row.arc_status_json or {},
                "inventory_json": inv,
                "wealth_json": wealth,
                "chapter_no_for_assets": int(chapter_no) if chapter_no is not None else None,
                "chapter_inventory_snapshot": chapter_inventory,
                "chapter_wealth_snapshot": chapter_wealth,
            }
            item["effective_inventory_json"] = chapter_inventory if chapter_inventory else inv
            item["effective_wealth_json"] = chapter_wealth if chapter_wealth else wealth
            out.append(item)
        return out

    def _list_world_entries(self, *, project_id, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(WorldEntry)
            .where(WorldEntry.project_id == project_id, WorldEntry.is_canonical.is_(True))
            .order_by(WorldEntry.updated_at.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        return [
            {
                "id": str(row.id),
                "entry_type": row.entry_type,
                "title": row.title,
                "content": row.content,
                "metadata_json": row.metadata_json or {},
            }
            for row in rows
        ]

    def _list_timeline_events(self, *, project_id, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(TimelineEvent)
            .where(TimelineEvent.project_id == project_id)
            .order_by(TimelineEvent.created_at.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        return [
            {
                "id": str(row.id),
                "chapter_no": row.chapter_no,
                "event_title": row.event_title,
                "event_desc": row.event_desc,
                "location": row.location,
                "involved_characters": row.involved_characters or [],
                "causal_links": row.causal_links or [],
            }
            for row in rows
        ]

    def _list_foreshadowings(self, *, project_id, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(Foreshadowing)
            .where(Foreshadowing.project_id == project_id)
            .order_by(Foreshadowing.updated_at.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        return [
            {
                "id": str(row.id),
                "setup_chapter_no": row.setup_chapter_no,
                "setup_text": row.setup_text,
                "expected_payoff": row.expected_payoff,
                "payoff_chapter_no": row.payoff_chapter_no,
                "payoff_text": row.payoff_text,
                "status": str(row.status.value if hasattr(row.status, "value") else row.status),
            }
            for row in rows
        ]
