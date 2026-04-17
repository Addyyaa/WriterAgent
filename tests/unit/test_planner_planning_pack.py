"""规划前 planning_pack 与 premise 软截断。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from packages.workflows.orchestration.planner_planning_pack import (
    PREMISE_SOFT_CAP_WHEN_PACK,
    build_planning_pack,
    soft_cap_premise_for_planner,
)


def test_soft_cap_premise_when_pack_has_signal() -> None:
    pack = {
        "chapter_index": [{"chapter_no": 1, "title": "A", "summary": "x"}],
        "story_state": None,
        "open_foreshadowing": [],
        "timeline_signals": [],
    }
    long = "字" * 5000
    out = soft_cap_premise_for_planner(long, planning_pack=pack)
    assert len(out) <= PREMISE_SOFT_CAP_WHEN_PACK + 2


def test_soft_cap_skipped_when_pack_empty_signal() -> None:
    pack = {"chapter_index": [], "story_state": None, "open_foreshadowing": [], "timeline_signals": []}
    long = "短 premise"
    assert soft_cap_premise_for_planner(long, planning_pack=pack) == long


def test_build_planning_pack_chapter_index_and_fallback_state() -> None:
    db = MagicMock()
    ch = MagicMock()
    ch.chapter_no = 2
    ch.title = "第二章"
    ch.summary = "承接上一案"

    with patch(
        "packages.workflows.orchestration.planner_planning_pack.ChapterRepository"
    ) as CR, patch(
        "packages.workflows.orchestration.planner_planning_pack.StoryStateSnapshotRepository"
    ) as SR, patch(
        "packages.workflows.orchestration.planner_planning_pack.ForeshadowingRepository"
    ) as FR, patch(
        "packages.workflows.orchestration.planner_planning_pack.TimelineEventRepository"
    ) as TR, patch(
        "packages.workflows.orchestration.planner_planning_pack.CharacterRepository"
    ) as CharR, patch(
        "packages.workflows.orchestration.planner_planning_pack.CharacterInventoryTool"
    ):
        CR.return_value.list_by_project.return_value = [ch]
        SR.return_value.get_latest_before.return_value = None
        FR.return_value.list_by_project.return_value = []
        TR.return_value.list_by_project.return_value = []
        CharR.return_value.list_by_project.return_value = []

        pack = build_planning_pack(
            db,
            project_id="proj-1",
            input_json={"writing_goal": "写第3章", "chapter_no": 3},
            workflow_type="chapter_generation",
        )
        assert len(pack["chapter_index"]) == 1
        assert pack["chapter_index"][0]["chapter_no"] == 2
        assert pack["story_state"] is not None
        assert pack["story_state"]["source"] == "chapter_list_fallback"
