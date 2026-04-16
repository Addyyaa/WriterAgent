"""编排层将 planner 知识字段传入 RetrievalLoopRequest 的接线单测。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.core.context_bundle_decision import mirror_context_bundle_lists_from_summary
from packages.workflows.orchestration.retrieval_loop import (
    RetrievalLoopRequest,
    RetrievalLoopService,
    RetrievalLoopSummary,
)
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig
from packages.workflows.orchestration.service import WritingOrchestratorService


class TestOrchestratorRetrievalRequestWiring(unittest.TestCase):
    def test_run_retrieval_loop_forwards_merged_planner_fields(self) -> None:
        """planner_bootstrap view + step plan_* 合并后写入 request。"""
        captured: dict[str, object] = {}

        def capture_run(req: RetrievalLoopRequest) -> RetrievalLoopSummary:
            captured["planner_slot_hints"] = list(req.planner_slot_hints or [])
            captured["planner_verify_facts"] = list(req.planner_verify_facts or [])
            captured["planner_preferred_tools"] = list(req.planner_preferred_tools or [])
            captured["relevance_blob"] = req.relevance_blob
            captured["focus_character_id"] = req.focus_character_id
            stub_bundle = {
                "summary": {
                    "key_facts": [],
                    "current_states": [],
                    "confirmed_facts": [],
                    "supporting_evidence": [],
                    "conflicts": [],
                    "information_gaps": [],
                },
                "items": [],
                "meta": {},
            }
            mirror_context_bundle_lists_from_summary(stub_bundle)
            return RetrievalLoopSummary(
                retrieval_trace_id="mock",
                context_bundle=stub_bundle,
            )

        loop = MagicMock()
        loop.run = capture_run

        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.retrieval_loop = loop

        row = SimpleNamespace(
            id=1,
            project_id="p1",
            trace_id="tr1",
            initiated_by="u1",
            input_json={"metadata_json": {}, "focus_character_id": "char-protagonist"},
        )
        step = SimpleNamespace(
            id=2,
            step_key="writer_draft",
            input_json={
                "plan_required_slots": ["inventory"],
                "plan_must_verify_facts": ["主角是否已暴露能力"],
                "plan_preferred_tools": ["memory_search"],
            },
        )
        raw_state = {
            "planner_bootstrap": {
                "view": {
                    "global_required_slots": ["power_rules"],
                    "global_preferred_tools": ["character_inventory"],
                    "steps": [
                        {
                            "required_slots": ["timeline"],
                            "must_verify_facts": ["失火日是否一致"],
                            "preferred_tools": ["project_memory"],
                        }
                    ],
                }
            }
        }
        WritingOrchestratorService._run_retrieval_loop(
            svc,
            row=row,
            step=step,
            workflow_type="chapter_generation",
            writing_goal="写第3章高潮",
            chapter_no=3,
            raw_state=raw_state,
        )
        hints = captured["planner_slot_hints"]
        self.assertIn("power_rules", hints)
        self.assertIn("timeline", hints)
        self.assertIn("inventory", hints)
        facts = captured["planner_verify_facts"]
        self.assertIn("失火日是否一致", facts)
        self.assertIn("主角是否已暴露能力", facts)
        blob = str(captured["relevance_blob"] or "")
        self.assertIn("写第3章高潮", blob)
        self.assertIn("inventory", blob)
        self.assertEqual(captured["focus_character_id"], "char-protagonist")
        pt = captured["planner_preferred_tools"]
        self.assertIn("character_inventory", pt)
        self.assertIn("memory_search", pt)

    def test_retrieval_round_decision_includes_slot_query_fragments(self) -> None:
        """开放槽位时首轮 decision 带 per-slot query 片段，便于回放。"""
        from tests.unit.test_retrieval_loop_service import (
            _FakeOutlineRepo,
            _FakeProjectMemoryService,
            _FakeProjectRepo,
            _FakeStoryContextProvider,
            _FakeUserRepo,
        )

        cfg = OrchestratorRuntimeConfig(
            retrieval_max_rounds=3,
            retrieval_round_top_k=4,
            retrieval_max_unique_evidence=32,
            retrieval_stop_min_coverage=0.99,
            retrieval_stop_min_gain=0.05,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
            retrieval_merge_workflow_when_planner_slots=False,
        )
        service = RetrievalLoopService(
            runtime_config=cfg,
            project_memory_service=_FakeProjectMemoryService(rows=[]),
            story_context_provider=_FakeStoryContextProvider(
                chapters=[{"id": "c1", "chapter_no": 1, "summary": "摘要"}],
                characters=[{"id": "ch1", "name": "主角", "profile_json": {}}],
                world_entries=[],
                timeline_events=[],
                foreshadowings=[],
            ),
            project_repo=_FakeProjectRepo(),
            outline_repo=_FakeOutlineRepo(),
            user_repo=_FakeUserRepo(),
        )
        result = service.run(
            RetrievalLoopRequest(
                workflow_run_id=1,
                workflow_step_id=2,
                project_id="p1",
                trace_id="t1",
                step_key="writer_draft",
                workflow_type="chapter_generation",
                writing_goal="补全设定",
                chapter_no=1,
                user_id="u1",
                planner_slot_hints=["power_rules", "inventory"],
                must_have_slots=["power_rules", "inventory"],
            )
        )
        self.assertTrue(result.rounds, "至少应有一轮检索")
        frags = result.rounds[0].decision.slot_query_fragments or {}
        self.assertIsInstance(frags, dict)
        self.assertTrue(
            any(str(v).strip() for v in frags.values()),
            f"应有非空 slot 片段，got {frags!r}",
        )


if __name__ == "__main__":
    unittest.main()
