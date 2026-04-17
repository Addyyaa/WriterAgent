from __future__ import annotations

import json
import uuid
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


def _is_foreshadow_open(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s in {"open", "pending", "unresolved", "active"}


class SQLAlchemyStoryContextProvider:
    """从业务表读取写作硬约束上下文（候选池）。

    返回的是在条数上限内的结构化候选集（章节窗口、角色与世界等），
    **不保证**与当前 LLM 步骤 token 预算匹配。一致性审查等步骤不得将 ``load()``
    结果整包直接作为 LLM 输入，须经
    ``packages.workflows.consistency_review.context_builder`` 中的切片与聚焦逻辑
    再进入 ``PromptPayloadAssembler``。

    ``load()`` 为宽池候选；``load_focused()`` 在 relevance_blob（写作目标、规划槽位、核验事实、
    多轮仍未覆盖的 open_slots 等，由编排层拼接）中按名称/标题命中优先筛选章节/角色/世界/时间线，
    减少无关行进入后续摘要/切片。
    """

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

    def load_focused(
        self,
        *,
        project_id,
        chapter_no: int | None = None,
        chapter_window_before: int = 2,
        chapter_window_after: int = 1,
        relevance_blob: str = "",
    ) -> StoryConstraintContext:
        """聚焦加载：优先纳入 relevance_blob 中出现的角色名与世界条目标题，时间线/伏笔按章号裁剪。"""
        blob = str(relevance_blob or "").strip()[:12000]
        chapters = self._list_chapters(
            project_id=project_id,
            limit=20,
            chapter_no=chapter_no,
            chapter_window_before=chapter_window_before,
            chapter_window_after=chapter_window_after,
        )
        chs = self._list_characters(project_id=project_id, limit=48, chapter_no=chapter_no)
        named = [
            c
            for c in chs
            if str(c.get("name") or "").strip() and str(c.get("name")) in blob
        ]
        if len(named) < 3:
            characters = chs[:18]
        else:
            characters = named[:24]

        worlds = self._list_world_entries(project_id=project_id, limit=40)
        world_hits = [
            w
            for w in worlds
            if str(w.get("title") or "").strip() and str(w.get("title")) in blob
        ]
        if len(world_hits) < 2:
            world_entries = worlds[:10]
        else:
            world_entries = world_hits[:12]

        timeline_all = self._list_timeline_events(project_id=project_id, limit=40)
        timeline_hits: list[dict[str, Any]] = []
        for ev in timeline_all:
            if not isinstance(ev, dict):
                continue
            raw_no = ev.get("chapter_no")
            try:
                ev_ch = int(raw_no) if raw_no is not None else None
            except (TypeError, ValueError):
                ev_ch = None
            if chapter_no is not None and ev_ch is not None and ev_ch > int(chapter_no):
                continue
            et = str(ev.get("event_title") or "")
            ed = str(ev.get("event_desc") or "")
            if blob and (
                (et and et in blob) or (len(ed) >= 4 and ed[:120] in blob)
            ):
                timeline_hits.append(ev)
        if len(timeline_hits) < 2:
            timeline_events: list[dict[str, Any]] = []
            for ev in timeline_all:
                if not isinstance(ev, dict):
                    continue
                raw_no = ev.get("chapter_no")
                try:
                    ev_ch = int(raw_no) if raw_no is not None else None
                except (TypeError, ValueError):
                    ev_ch = None
                if chapter_no is not None and ev_ch is not None and ev_ch > int(chapter_no):
                    continue
                timeline_events.append(ev)
                if len(timeline_events) >= 14:
                    break
        else:
            timeline_events = timeline_hits[:14]

        fore_all = self._list_foreshadowings(project_id=project_id, limit=32)
        foreshadowings: list[dict[str, Any]] = []
        for item in fore_all:
            if not isinstance(item, dict):
                continue
            if not _is_foreshadow_open(item.get("status")):
                continue
            setup_ch = item.get("setup_chapter_no")
            try:
                setup_int = int(setup_ch) if setup_ch is not None else None
            except (TypeError, ValueError):
                setup_int = None
            if chapter_no is not None and setup_int is not None and setup_int > int(chapter_no):
                continue
            foreshadowings.append(item)
            if len(foreshadowings) >= 8:
                break

        return StoryConstraintContext(
            chapters=chapters,
            characters=characters,
            world_entries=world_entries,
            timeline_events=timeline_events,
            foreshadowings=foreshadowings,
        )

    def load_candidate_pool(
        self,
        *,
        project_id,
        chapter_no: int | None = None,
        chapter_window_before: int = 2,
        chapter_window_after: int = 1,
    ) -> StoryConstraintContext:
        """显式宽池入口，语义同 `load()`。"""
        return self.load(
            project_id=project_id,
            chapter_no=chapter_no,
            chapter_window_before=chapter_window_before,
            chapter_window_after=chapter_window_after,
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
                "age": getattr(row, "age", None),
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

    def fetch_evidence_entity(
        self,
        *,
        project_id,
        scope: str,
        entity_id: str,
        max_json_chars: int = 2800,
    ) -> dict[str, Any]:
        """按需拉取单条实体（供一致性审查多轮 tool calling）；不在候选池切片内时使用。"""
        try:
            eid = uuid.UUID(str(entity_id).strip())
        except ValueError:
            return {"found": False, "scope": scope, "reason": "invalid_entity_id"}

        key = str(scope or "").strip().lower()
        payload: dict[str, Any] | None = None

        if key == "character":
            row = self.db.execute(
                select(Character).where(
                    and_(Character.id == eid, Character.project_id == project_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"found": False, "scope": key, "entity_id": str(entity_id)}
            inv = dict(getattr(row, "inventory_json", None) or {})
            wealth = dict(getattr(row, "wealth_json", None) or {})
            payload = {
                "id": str(row.id),
                "name": row.name,
                "role_type": row.role_type,
                "faction": row.faction,
                "age": getattr(row, "age", None),
                "profile_json": row.profile_json or {},
                "speech_style_json": row.speech_style_json or {},
                "arc_status_json": row.arc_status_json or {},
                "inventory_json": inv,
                "wealth_json": wealth,
            }
        elif key in {"world_entry", "world"}:
            row = self.db.execute(
                select(WorldEntry).where(
                    and_(WorldEntry.id == eid, WorldEntry.project_id == project_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"found": False, "scope": key, "entity_id": str(entity_id)}
            payload = {
                "id": str(row.id),
                "entry_type": row.entry_type,
                "title": row.title,
                "content": row.content,
                "metadata_json": row.metadata_json or {},
            }
        elif key in {"timeline_event", "timeline"}:
            row = self.db.execute(
                select(TimelineEvent).where(
                    and_(TimelineEvent.id == eid, TimelineEvent.project_id == project_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"found": False, "scope": key, "entity_id": str(entity_id)}
            payload = {
                "id": str(row.id),
                "chapter_no": row.chapter_no,
                "event_title": row.event_title,
                "event_desc": row.event_desc,
                "location": row.location,
                "involved_characters": row.involved_characters or [],
            }
        elif key in {"foreshadowing", "foreshadow"}:
            row = self.db.execute(
                select(Foreshadowing).where(
                    and_(Foreshadowing.id == eid, Foreshadowing.project_id == project_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"found": False, "scope": key, "entity_id": str(entity_id)}
            payload = {
                "id": str(row.id),
                "setup_chapter_no": row.setup_chapter_no,
                "setup_text": row.setup_text,
                "expected_payoff": row.expected_payoff,
                "payoff_chapter_no": row.payoff_chapter_no,
                "payoff_text": row.payoff_text,
                "status": str(row.status.value if hasattr(row.status, "value") else row.status),
            }
        else:
            return {"found": False, "scope": scope, "reason": "unknown_scope"}

        out = {"found": True, "scope": key, "entity": payload}
        raw = json.dumps(out, ensure_ascii=False)
        if len(raw) > max_json_chars:
            return {
                "found": True,
                "scope": key,
                "truncated": True,
                "preview": raw[: max(1, max_json_chars - 3)] + "...",
            }
        return out
