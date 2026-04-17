"""动态规划前最小状态包：章节索引、故事状态、伏笔/时间线摘要、按需库存。"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.character_repository import CharacterRepository
from packages.storage.postgres.repositories.foreshadowing_repository import ForeshadowingRepository
from packages.storage.postgres.repositories.story_state_snapshot_repository import StoryStateSnapshotRepository
from packages.storage.postgres.repositories.timeline_event_repository import TimelineEventRepository
from packages.tools.character_tools.inventory_tool import CharacterInventoryTool

CHAPTER_INDEX_LIMIT = 40
CHAPTER_SUMMARY_MAX = 400
FORESHADOW_LIMIT = 8
TIMELINE_LIMIT = 8
STORY_STATE_JSON_MAX = 3500
PREMISE_SOFT_CAP_WHEN_PACK = 2000

_INVENTORY_GOAL_HINT = re.compile(
    r"道具|背包|物品|库存|财富|钱币|消耗品|行囊|inventory|携带",
    re.IGNORECASE,
)


def _trunc(s: str, n: int) -> str:
    text = str(s or "").strip()
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)] + "…"


def _parse_chapter_no(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def build_planning_pack(
    db: Session,
    *,
    project_id: Any,
    input_json: dict[str, Any] | None,
    workflow_type: str | None,
) -> dict[str, Any]:
    """聚合只读摘要，供 planner LLM 承接当前故事进度（不替代下游完整检索）。"""
    inp = dict(input_json or {})
    ch_no_int = _parse_chapter_no(inp.get("chapter_no"))
    goal = str(inp.get("writing_goal") or "")
    wf = str(workflow_type or "").strip().lower()

    chapter_repo = ChapterRepository(db)
    chapters = chapter_repo.list_by_project(project_id)
    chapter_index: list[dict[str, Any]] = []
    for ch in chapters[:CHAPTER_INDEX_LIMIT]:
        chapter_index.append(
            {
                "chapter_no": int(getattr(ch, "chapter_no", 0) or 0),
                "title": _trunc(getattr(ch, "title", None) or "", 200),
                "summary": _trunc(getattr(ch, "summary", None) or "", CHAPTER_SUMMARY_MAX),
            }
        )

    story_state_block: dict[str, Any] | None = None
    snap_repo = StoryStateSnapshotRepository(db)
    if ch_no_int is not None:
        snap = snap_repo.get_latest_before(project_id=project_id, before_chapter_no=int(ch_no_int))
        if snap is not None:
            sj = dict(snap.state_json or {})
            text = json.dumps(sj, ensure_ascii=False)
            story_state_block = {
                "after_chapter_no": int(snap.chapter_no),
                "source": snap.source,
                "state_summary": _trunc(text, STORY_STATE_JSON_MAX),
            }
    if story_state_block is None and chapter_index:
        last = chapter_index[-1]
        story_state_block = {
            "after_chapter_no": last.get("chapter_no"),
            "source": "chapter_list_fallback",
            "state_summary": _trunc(str(last.get("summary") or ""), STORY_STATE_JSON_MAX),
        }

    fore_repo = ForeshadowingRepository(db)
    open_f: list[dict[str, Any]] = []
    for row in fore_repo.list_by_project(project_id=project_id, limit=FORESHADOW_LIMIT, status="open"):
        open_f.append(
            {
                "setup_chapter_no": row.setup_chapter_no,
                "setup_text": _trunc(row.setup_text or "", 320),
                "expected_payoff": _trunc(row.expected_payoff or "", 320),
                "status": row.status,
            }
        )

    timeline_repo = TimelineEventRepository(db)
    tl_signals: list[dict[str, Any]] = []
    for ev in timeline_repo.list_by_project(project_id=project_id, limit=TIMELINE_LIMIT):
        tl_signals.append(
            {
                "chapter_no": ev.chapter_no,
                "title": _trunc(ev.event_title or "", 160),
                "desc": _trunc(ev.event_desc or "", 320),
            }
        )

    focus_inventory: dict[str, Any] | None = None
    want_inv = bool(_INVENTORY_GOAL_HINT.search(goal)) or (wf == "chapter_generation" and ch_no_int is not None)
    if want_inv and ch_no_int is not None:
        focus_cid = str(inp.get("focus_character_id") or "").strip() or None
        if not focus_cid:
            chars = CharacterRepository(db).list_by_project(project_id=project_id, limit=24)
            if chars:
                focus_cid = str(chars[0].id)
        if focus_cid:
            tool = CharacterInventoryTool(db)
            inv = tool.run(project_id=project_id, character_id=focus_cid, chapter_no=int(ch_no_int))
            if inv.get("found"):
                focus_inventory = {
                    "character_id": focus_cid,
                    "chapter_no": ch_no_int,
                    "source": inv.get("source"),
                    "inventory_json": inv.get("inventory_json"),
                    "wealth_json": inv.get("wealth_json"),
                }

    return {
        "chapter_index": chapter_index,
        "target_chapter_no": ch_no_int,
        "story_state": story_state_block,
        "open_foreshadowing": open_f,
        "timeline_signals": tl_signals,
        "focus_inventory": focus_inventory,
    }


def soft_cap_premise_for_planner(premise: str | None, *, planning_pack: dict[str, Any]) -> str:
    """当 planning_pack 有实质内容时压缩 premise，引导模型更多依赖当前进度摘要。"""
    p = str(premise or "").strip()
    if not p or not planning_pack:
        return p
    has_signal = bool(
        planning_pack.get("chapter_index")
        or planning_pack.get("story_state")
        or planning_pack.get("open_foreshadowing")
        or planning_pack.get("timeline_signals")
    )
    if not has_signal:
        return p
    return _trunc(p, PREMISE_SOFT_CAP_WHEN_PACK)
