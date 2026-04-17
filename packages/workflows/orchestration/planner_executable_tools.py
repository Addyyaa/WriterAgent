"""Planner `preferred_tools`：与 local_data_tools 目录一致的可执行工具名及检索侧 source 映射。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 与 apps/agents/_shared/local_data_tools_catalog.json 名称一致
PLANNER_EXECUTABLE_TOOL_NAMES: tuple[str, ...] = (
    "get_character_inventory",
    "list_project_chapters",
    "search_project_memory_vectors",
    "get_chapter_content",
)

# 历史/语义别名 → 规范名（仅白名单输出）
_TOOL_ALIAS_TO_CANONICAL: dict[str, str] = {
    "character_inventory": "get_character_inventory",
    "inventory_tool": "get_character_inventory",
    "characterinventorytool": "get_character_inventory",
    "memory": "search_project_memory_vectors",
    "project_memory": "search_project_memory_vectors",
    "vector_memory": "search_project_memory_vectors",
    "long_term_search": "search_project_memory_vectors",
    "memory_search": "search_project_memory_vectors",
    "chapter_list": "list_project_chapters",
    "list_chapters": "list_project_chapters",
    "chapter_content": "get_chapter_content",
    "read_chapter": "get_chapter_content",
    "story_state": "search_project_memory_vectors",
    "story_state_snapshot": "search_project_memory_vectors",
    "snapshot": "search_project_memory_vectors",
}

# 可执行工具名 → 检索循环内 source_types 优先 boost（须 ⊆ 请求的 allowed pool）
EXECUTABLE_TOOL_TO_SOURCE_BOOSTS: dict[str, tuple[str, ...]] = {
    "get_character_inventory": ("character_inventory",),
    "search_project_memory_vectors": ("memory_fact",),
    "get_chapter_content": ("chapter",),
    "list_project_chapters": ("chapter", "outline"),
}


def normalize_preferred_tool(raw: Any) -> str | None:
    """将单条工具名转为目录白名单中的规范名；无法识别则返回 None。"""
    t = str(raw or "").strip().lower().replace("-", "_")
    if not t:
        return None
    canon = _TOOL_ALIAS_TO_CANONICAL.get(t, t)
    if canon in PLANNER_EXECUTABLE_TOOL_NAMES:
        return canon
    logger.debug("planner preferred_tools dropped unknown tool name=%r", raw)
    return None


def normalize_preferred_tools_list(items: list[str] | None) -> list[str]:
    """去重保序，仅保留白名单工具。"""
    out: list[str] = []
    for x in items or []:
        n = normalize_preferred_tool(x)
        if n and n not in out:
            out.append(n)
    return out


def source_boosts_for_executable_tools(
    preferred_tools: list[str] | None,
    *,
    allowed: set[str],
) -> list[str]:
    """将（已规范或仍为别名的）工具列表展开为允许的 source_types，保序去重。"""
    boosted: list[str] = []
    for raw in list(preferred_tools or []):
        canon = normalize_preferred_tool(raw)
        if not canon:
            continue
        for st in EXECUTABLE_TOOL_TO_SOURCE_BOOSTS.get(canon, ()):
            if st in allowed and st not in boosted:
                boosted.append(st)
    return boosted
