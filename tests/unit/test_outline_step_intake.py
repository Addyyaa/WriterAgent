"""编排 _run_outline_step：writing_goal 不去重灌入 context_text；outline_intake 结构化。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.workflows.orchestration.retrieval_loop import RetrievalLoopSummary
from packages.workflows.orchestration.service import WritingOrchestratorService


class TestOutlineStepIntake(unittest.TestCase):
    def test_build_outline_generation_intake_no_flat_duplication(self) -> None:
        project = SimpleNamespace(
            id="proj-1",
            title="P",
            genre="g",
            premise="prem",
            metadata_json={"arc_stage": "二幕"},
        )
        row = SimpleNamespace(
            project_id="proj-1",
            input_json={"writing_goal": "仅目标", "chapter_no": 2},
        )
        bundle = {
            "summary": {
                "key_facts": ["f1"],
                "current_states": ["s1"],
                "confirmed_facts": ["c1"],
                "supporting_evidence": ["e1"],
                "conflicts": [],
                "information_gaps": ["g1"],
            },
            "items": [{"source": "memory_fact", "text": "snippet"}],
        }
        from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary

        mirror_context_bundle_lists_from_summary(bundle)
        retrieval = RetrievalLoopSummary(
            retrieval_trace_id="t",
            context_text="扁平长文不应再塞进 goal",
            context_bundle=bundle,
        )

        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        ch_repo = MagicMock()
        ch_repo.get_next_chapter_no.return_value = 2
        ch_repo.get_by_project_chapter_no.return_value = SimpleNamespace(
            chapter_no=1,
            title="上一章",
            summary="承接",
            content="",
        )
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = ch_repo

        intake = WritingOrchestratorService._build_outline_generation_intake(
            svc, row=row, project=project, retrieval=retrieval
        )

        self.assertIn("project_brief", intake)
        self.assertEqual(intake["confirmed_facts"], ["c1"])
        self.assertEqual(intake["key_facts"], ["f1"])
        self.assertIsNotNone(intake["prior_chapter_summary"])
        self.assertNotIn("扁平长文", str(intake))


if __name__ == "__main__":
    unittest.main()
