"""Planner `required_slots`：与 RetrievalLoopService._SLOT_SOURCE_MAP 键对齐的闭集与别名归一。"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 与 packages/workflows/orchestration/retrieval_loop.py::_SLOT_SOURCE_MAP 键一致
CANONICAL_PLANNER_SLOTS: frozenset[str] = frozenset(
    {
        "project_goal",
        "outline",
        "chapter_neighborhood",
        "character",
        "world_rule",
        "timeline",
        "foreshadowing",
        "style_preference",
        "conflict_evidence",
        "inventory",
        "current_inventory",
        "character_inventory",
        "power_rules",
        "power_rule",
        "known_power_rules",
        "scene",
        "location",
        "relationship",
        "witnesses",
        "previous_chapter",
        "story_state",
        "scene_state",
    }
)

# 自然语言 / 旧 prompt 别名 → 规范槽位（源类型名如 memory_fact 不作为槽位）
PLANNER_SLOT_ALIASES: dict[str, str] = {
    "recent_trigger_events": "timeline",
    "recent_power_activations": "timeline",
    "scene_constraints": "scene_state",
    "wealth": "current_inventory",
    "current_wealth": "current_inventory",
    "chapter_1_content": "chapter_neighborhood",
    "chapter_2_content": "chapter_neighborhood",
    "chapter_position": "chapter_neighborhood",
    "story_timeline": "timeline",
    "scene_design": "scene_state",
    "conflict_points": "conflict_evidence",
    "used_items": "current_inventory",
}

_SLOT_NORMALIZE_RE = re.compile(r"[\s\-]+")
# planner 自由命名：chapter_1_content、chapter_2_content 等
_CHAPTER_N_CONTENT_RE = re.compile(r"^chapter_\d+_content$")


def _whitespace_norm(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        return ""
    return _SLOT_NORMALIZE_RE.sub("_", s)


def normalize_planner_slot(raw: Any) -> str:
    """别名 → 规范槽位；不在闭集则丢弃并打日志。"""
    base = _whitespace_norm(str(raw))
    if not base:
        return ""
    if base in PLANNER_SLOT_ALIASES:
        base = PLANNER_SLOT_ALIASES[base]
    elif _CHAPTER_N_CONTENT_RE.match(base):
        base = "chapter_neighborhood"
    # memory_fact 等为 source type，禁止当槽位
    if base in ("memory_fact", "user_preference", "project", "chapter", "world_entry"):
        logger.debug("planner slot dropped reserved source-like name=%r", raw)
        return ""
    if base not in CANONICAL_PLANNER_SLOTS:
        logger.debug("planner slot dropped unknown name=%r", raw)
        return ""
    return base


def normalize_planner_slots_list(items: list[str] | None) -> list[str]:
    """保序去重。"""
    out: list[str] = []
    for x in items or []:
        slot = normalize_planner_slot(x)
        if slot and slot not in out:
            out.append(slot)
    return out
