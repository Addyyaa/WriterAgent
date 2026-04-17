"""可执行工具名归一与检索 source boost。"""

from __future__ import annotations

from packages.workflows.orchestration.planner_executable_tools import (
    EXECUTABLE_TOOL_TO_SOURCE_BOOSTS,
    PLANNER_EXECUTABLE_TOOL_NAMES,
    normalize_preferred_tool,
    normalize_preferred_tools_list,
    source_boosts_for_executable_tools,
)
from packages.workflows.orchestration.planner_knowledge import merge_planner_preferred_tools
from packages.workflows.orchestration.retrieval_loop import RetrievalLoopService


def test_normalize_aliases_to_catalog_names() -> None:
    assert normalize_preferred_tool("character_inventory") == "get_character_inventory"
    assert normalize_preferred_tool("memory_search") == "search_project_memory_vectors"
    assert normalize_preferred_tool("project_memory") == "search_project_memory_vectors"
    assert normalize_preferred_tool("list_chapters") == "list_project_chapters"


def test_unknown_tool_returns_none() -> None:
    assert normalize_preferred_tool("nope_tool") is None


def test_list_dedupes() -> None:
    assert normalize_preferred_tools_list(
        ["character_inventory", "get_character_inventory", "memory_search"]
    ) == ["get_character_inventory", "search_project_memory_vectors"]


def test_merge_planner_preferred_tools_normalizes() -> None:
    merged = merge_planner_preferred_tools(
        planner_bootstrap_output={
            "global_preferred_tools": ["character_inventory"],
            "steps": [{"preferred_tools": ["memory_search"]}],
        },
        step_input={"plan_preferred_tools": ["project_memory"]},
    )
    assert merged == ["get_character_inventory", "search_project_memory_vectors"]


def test_executable_tool_names_match_catalog_count() -> None:
    assert len(PLANNER_EXECUTABLE_TOOL_NAMES) == 4
    assert set(EXECUTABLE_TOOL_TO_SOURCE_BOOSTS.keys()) == set(PLANNER_EXECUTABLE_TOOL_NAMES)


def test_select_round_sources_accepts_executable_names() -> None:
    src = RetrievalLoopService._DEFAULT_SOURCE_TYPES
    picked = RetrievalLoopService._select_round_sources(
        open_slots=["inventory"],
        source_types=src,
        preferred_tools=["get_character_inventory", "search_project_memory_vectors"],
    )
    assert "character_inventory" in picked
    assert "memory_fact" in picked
