"""修订步：按 consistency issue.category 映射检索槽位与优先工具（issue-scoped，不继承整包 workflow 默认）。"""

from __future__ import annotations

from typing import Any

# 单条 issue 类别 -> 槽位（与 RetrievalLoopService._SLOT_SOURCE_MAP 键一致）
_ISSUE_CATEGORY_TO_SLOTS: dict[str, tuple[str, ...]] = {
    "character": ("character", "relationship", "conflict_evidence"),
    "worldview": ("world_rule", "conflict_evidence"),
    "world_rule": ("world_rule", "conflict_evidence"),
    "world": ("world_rule", "conflict_evidence"),
    "timeline": ("timeline", "chapter_neighborhood", "story_state", "scene_state", "conflict_evidence"),
    "continuity": ("timeline", "chapter_neighborhood", "story_state", "scene_state", "conflict_evidence"),
    "inventory": (
        "current_inventory",
        "character_inventory",
        "chapter_neighborhood",
        "conflict_evidence",
    ),
    "props": (
        "current_inventory",
        "character_inventory",
        "chapter_neighborhood",
        "conflict_evidence",
    ),
    "item_consistency": (
        "current_inventory",
        "character_inventory",
        "chapter_neighborhood",
        "conflict_evidence",
    ),
    "scene": ("scene_state", "story_state", "chapter_neighborhood", "conflict_evidence"),
    "location": ("scene_state", "story_state", "chapter_neighborhood", "conflict_evidence"),
    "style": ("style_preference", "conflict_evidence"),
    "foreshadowing": ("foreshadowing", "conflict_evidence", "timeline"),
}

_DEFAULT_SLOTS: tuple[str, ...] = ("conflict_evidence",)

# 与槽位配套的优先工具（结构化优先，避免修订步宽池）
_SLOT_HINT_TO_PREFERRED_TOOLS: dict[str, tuple[str, ...]] = {
    "character": ("get_character_inventory", "search_project_memory_vectors"),
    "relationship": ("search_project_memory_vectors",),
    "world_rule": ("search_project_memory_vectors",),
    "timeline": ("search_project_memory_vectors",),
    "foreshadowing": ("search_project_memory_vectors",),
    "chapter_neighborhood": (
        "get_chapter_content",
        "list_project_chapters",
        "search_project_memory_vectors",
    ),
    "story_state": ("search_project_memory_vectors",),
    "scene_state": ("search_project_memory_vectors",),
    "current_inventory": ("get_character_inventory",),
    "character_inventory": ("get_character_inventory",),
    "style_preference": ("search_project_memory_vectors",),
    "conflict_evidence": ("search_project_memory_vectors",),
}


def _normalize_issue_category(raw: Any) -> str:
    s = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "world_view": "worldview",
        "worldview": "worldview",
        "logic": "continuity",
        "plot": "continuity",
    }
    return aliases.get(s, s)


def slots_for_issue_category(category: Any) -> tuple[str, ...]:
    """单条 issue 的槽位列表。"""
    key = _normalize_issue_category(category)
    return _ISSUE_CATEGORY_TO_SLOTS.get(key, _DEFAULT_SLOTS)


def revision_slots_for_issues(issues: list[dict[str, Any]] | None) -> list[str]:
    """多条 issue：逐条映射后 union + 去重，保持首次出现顺序。"""
    out: list[str] = []
    for item in list(issues or []):
        if not isinstance(item, dict):
            continue
        cat = item.get("category")
        for slot in slots_for_issue_category(cat):
            if slot not in out:
                out.append(slot)
    if not out:
        out = list(_DEFAULT_SLOTS)
    return out


def preferred_tools_for_slots(slots: list[str]) -> list[str]:
    """由槽位推导 planner_preferred_tools，去重。"""
    tools: list[str] = []
    for slot in slots:
        for t in _SLOT_HINT_TO_PREFERRED_TOOLS.get(str(slot).strip().lower(), ()):
            if t not in tools:
                tools.append(t)
    return tools
