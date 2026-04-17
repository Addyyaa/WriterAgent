"""槽位闭集与别名归一。"""

from __future__ import annotations

from packages.workflows.orchestration.planner_knowledge import extract_planner_retrieval_slots, merge_planner_retrieval_slots
from packages.workflows.orchestration.planner_slot_vocabulary import (
    CANONICAL_PLANNER_SLOTS,
    normalize_planner_slot,
    normalize_planner_slots_list,
)
from packages.workflows.orchestration.retrieval_loop import RetrievalLoopService


def test_alias_maps_to_timeline_and_scene_state() -> None:
    assert normalize_planner_slot("recent_trigger_events") == "timeline"
    assert normalize_planner_slot("scene_constraints") == "scene_state"


def test_memory_fact_not_a_slot() -> None:
    assert normalize_planner_slot("memory_fact") == ""


def test_unknown_slot_dropped() -> None:
    assert normalize_planner_slot("totally_unknown_slot_xyz") == ""


def test_merge_inference_drops_unknown_hints() -> None:
    merged = RetrievalLoopService._merge_inference_slots(
        workflow_type="revision",
        writing_goal="修订",
        planner_hints=["not_a_real_slot_zzz"],
        explicit_extra=None,
        merge_workflow_defaults_when_planner_nonempty=True,
        skip_workflow_base=True,
    )
    assert merged == ["conflict_evidence"]


def test_extract_bootstrap_slots_normalized() -> None:
    slots = extract_planner_retrieval_slots(
        {
            "global_required_slots": ["recent_trigger_events"],
            "steps": [{"required_slots": ["memory_fact", "character"]}],
        }
    )
    assert "timeline" in slots
    assert "character" in slots
    assert "memory_fact" not in slots


def test_merge_planner_retrieval_slots_order() -> None:
    m = merge_planner_retrieval_slots(
        planner_bootstrap_output={"global_required_slots": ["scene_constraints"]},
        step_input={"plan_required_slots": ["world_rule"]},
    )
    assert m[0] == "scene_state"
    assert "world_rule" in m


def test_canonical_covers_slot_map_keys() -> None:
    assert CANONICAL_PLANNER_SLOTS == frozenset(RetrievalLoopService._SLOT_SOURCE_MAP.keys())


def test_chapter_n_content_alias() -> None:
    assert normalize_planner_slot("chapter_3_content") == "chapter_neighborhood"


def test_story_timeline_and_conflict_points() -> None:
    assert normalize_planner_slot("story_timeline") == "timeline"
    assert normalize_planner_slot("conflict_points") == "conflict_evidence"
    assert normalize_planner_slot("used_items") == "current_inventory"
