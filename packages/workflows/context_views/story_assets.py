"""第二层：story_assets 摘要视图（Summary-first），与权威库 load() 解耦。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _clip(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(1, limit - 3)] + "..."


@dataclass(frozen=True)
class StoryAssetSummaryBudget:
    """控制摘要粒度；默认偏保守以控制 prompt 体积。"""

    max_characters: int = 24
    max_world_entries: int = 20
    max_timeline_events: int = 16
    max_foreshadowings: int = 12
    profile_field_chars: int = 96
    world_content_chars: int = 220
    timeline_desc_chars: int = 160
    foreshadow_setup_chars: int = 140
    inventory_key_cap: int = 8
    wealth_key_cap: int = 6
    chapter_summary_chars: int = 400


def build_story_assets_from_context(
    context: Any,
    *,
    chapter_no: int | None,
    budget: StoryAssetSummaryBudget | None = None,
    summary_first: bool = True,
) -> dict[str, Any]:
    """
    由权威候选池构造进入 writer payload 的 story_assets。

    - summary_first=True：角色/世界/时间线/伏笔为短视图，完整档案留在 DB + 工具层。
    - summary_first=False：沿用 context_provider 列表形态（仍受各表 limit 约束）。
    """
    b = budget or StoryAssetSummaryBudget()
    if not summary_first:
        return {
            "chapters": list(context.chapters),
            "characters": list(context.characters),
            "world_entries": list(context.world_entries),
            "timeline_events": list(context.timeline_events),
            "foreshadowings": list(context.foreshadowings),
            "asset_view_mode": "full",
        }

    chapters_out: list[dict[str, Any]] = []
    for ch in list(context.chapters)[:40]:
        if not isinstance(ch, dict):
            continue
        chapters_out.append(
            {
                "id": ch.get("id"),
                "chapter_no": ch.get("chapter_no"),
                "title": ch.get("title"),
                "summary": _clip(str(ch.get("summary") or ""), b.chapter_summary_chars),
                "content_preview": _clip(str(ch.get("content_preview") or ""), 200),
            }
        )

    characters_out: list[dict[str, Any]] = []
    for c in list(context.characters)[: b.max_characters]:
        if not isinstance(c, dict):
            continue
        prof = dict(c.get("profile_json") or {})
        pieces: list[str] = []
        for key in ("personality", "appearance", "abilities", "backstory"):
            val = prof.get(key)
            if val is not None and str(val).strip():
                pieces.append(f"{key}:{_clip(str(val), b.profile_field_chars)}")
        inv = dict(c.get("effective_inventory_json") or c.get("inventory_json") or {})
        wealth = dict(c.get("effective_wealth_json") or c.get("wealth_json") or {})
        characters_out.append(
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "role_type": c.get("role_type"),
                "faction": c.get("faction"),
                "chapter_no_for_assets": c.get("chapter_no_for_assets"),
                "profile_snippet": " | ".join(pieces[:4]) if pieces else None,
                "inventory_keys": [str(k) for k in list(inv.keys())[: b.inventory_key_cap]],
                "wealth_keys": [str(k) for k in list(wealth.keys())[: b.wealth_key_cap]],
            }
        )

    world_out: list[dict[str, Any]] = []
    for w in list(context.world_entries)[: b.max_world_entries]:
        if not isinstance(w, dict):
            continue
        meta = dict(w.get("metadata_json") or {})
        world_out.append(
            {
                "id": w.get("id"),
                "entry_type": w.get("entry_type"),
                "title": w.get("title"),
                "content_snippet": _clip(str(w.get("content") or ""), b.world_content_chars),
                "rule_hints": [
                    str(x).strip()
                    for x in list(meta.get("forbidden_terms") or meta.get("ban_terms") or [])[:4]
                    if str(x).strip()
                ],
            }
        )

    timeline_out: list[dict[str, Any]] = []
    for ev in list(context.timeline_events)[: b.max_timeline_events]:
        if not isinstance(ev, dict):
            continue
        chn = ev.get("chapter_no")
        try:
            chn_i = int(chn) if chn is not None else None
        except (TypeError, ValueError):
            chn_i = None
        if chapter_no is not None and chn_i is not None and chn_i > int(chapter_no):
            continue
        timeline_out.append(
            {
                "id": ev.get("id"),
                "chapter_no": ev.get("chapter_no"),
                "event_title": ev.get("event_title"),
                "anchor_line": _clip(str(ev.get("event_desc") or ""), b.timeline_desc_chars),
                "location": ev.get("location"),
            }
        )

    foreshadow_out: list[dict[str, Any]] = []
    for fs in list(context.foreshadowings)[: b.max_foreshadowings]:
        if not isinstance(fs, dict):
            continue
        foreshadow_out.append(
            {
                "id": fs.get("id"),
                "status": fs.get("status"),
                "setup_chapter_no": fs.get("setup_chapter_no"),
                "payoff_chapter_no": fs.get("payoff_chapter_no"),
                "setup_snippet": _clip(str(fs.get("setup_text") or ""), b.foreshadow_setup_chars),
            }
        )

    return {
        "chapters": chapters_out,
        "characters": characters_out,
        "world_entries": world_out,
        "timeline_events": timeline_out,
        "foreshadowings": foreshadow_out,
        "asset_view_mode": "summary_first",
        "chapter_no": chapter_no,
    }
