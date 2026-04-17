from __future__ import annotations

import unittest
from types import SimpleNamespace

from packages.workflows.orchestration.retrieval_loop import (
    RetrievalLoopRequest,
    RetrievalLoopService,
)
from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig


class _FakeLongTermSearch:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls = 0

    def search_with_scores(self, **kwargs):
        del kwargs
        self.calls += 1
        return list(self.rows)


class _FakeProjectMemoryService:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.long_term_search = _FakeLongTermSearch(rows=rows)


class _FakeStoryContextProvider:
    def __init__(
        self,
        *,
        chapters: list[dict] | None = None,
        characters: list[dict] | None = None,
        world_entries: list[dict] | None = None,
        timeline_events: list[dict] | None = None,
        foreshadowings: list[dict] | None = None,
    ) -> None:
        self.payload = SimpleNamespace(
            chapters=list(chapters or []),
            characters=list(characters or []),
            world_entries=list(world_entries or []),
            timeline_events=list(timeline_events or []),
            foreshadowings=list(foreshadowings or []),
        )

    def load(self, *, project_id, chapter_no=None, chapter_window_before=2, chapter_window_after=1):
        del project_id, chapter_no, chapter_window_before, chapter_window_after
        return self.payload


class _FakeProjectRepo:
    def get(self, project_id):
        return SimpleNamespace(
            id=project_id,
            title="测试项目",
            genre="奇幻",
            premise="测试前提",
            owner_user_id="u1",
        )


class _FakeOutlineRepo:
    def get_active(self, *, project_id):
        del project_id
        return None

    def get_latest(self, *, project_id):
        del project_id
        return SimpleNamespace(id="o1", content="大纲内容", structure_json={"acts": []}, version_no=1)


class _FakeUserRepo:
    def get(self, user_id):
        return SimpleNamespace(id=user_id, preferences={"tone": "克制"}, username="tester")


class TestRetrievalLoopService(unittest.TestCase):
    def test_stop_on_enough_context(self) -> None:
        cfg = OrchestratorRuntimeConfig(
            retrieval_max_rounds=20,
            retrieval_round_top_k=8,
            retrieval_max_unique_evidence=64,
            retrieval_stop_min_coverage=0.85,
            retrieval_stop_min_gain=0.05,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
        )
        service = RetrievalLoopService(
            runtime_config=cfg,
            project_memory_service=_FakeProjectMemoryService(rows=[]),
            story_context_provider=_FakeStoryContextProvider(
                chapters=[{"id": "c1", "chapter_no": 1, "summary": "上一章摘要"}],
                characters=[{"id": "ch1", "name": "主角", "profile_json": {"goal": "调查"}}],
                world_entries=[{"id": "w1", "title": "北港", "content": "雾港城市"}],
                timeline_events=[{"id": "t1", "event_title": "失火", "event_desc": "档案馆起火"}],
                foreshadowings=[{"id": "f1", "setup_text": "钟声异常", "expected_payoff": "真凶线索"}],
            ),
            project_repo=_FakeProjectRepo(),
            outline_repo=_FakeOutlineRepo(),
            user_repo=_FakeUserRepo(),
            retrieval_trace_repo=None,
        )
        summary = service.run(
            RetrievalLoopRequest(
                workflow_run_id="r1",
                workflow_step_id=1,
                project_id="p1",
                trace_id="trace-1",
                step_key="writer_draft",
                workflow_type="chapter_generation",
                writing_goal="生成第一章",
                chapter_no=1,
                user_id="u1",
            )
        )
        self.assertEqual(summary.stop_reason, "enough_context")
        self.assertGreaterEqual(len(summary.rounds), 1)
        self.assertGreaterEqual(summary.coverage.coverage_score, 0.85)

    def test_stop_on_max_rounds_when_unresolved(self) -> None:
        cfg = OrchestratorRuntimeConfig(
            retrieval_max_rounds=3,
            retrieval_round_top_k=8,
            retrieval_max_unique_evidence=64,
            retrieval_stop_min_coverage=0.9,
            retrieval_stop_min_gain=0.2,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
        )
        service = RetrievalLoopService(
            runtime_config=cfg,
            project_memory_service=_FakeProjectMemoryService(
                rows=[
                    {
                        "id": "m1",
                        "source_type": "memory_fact",
                        "source_id": "mf1",
                        "text": "泛化事实",
                        "metadata_json": {},
                    }
                ]
            ),
            story_context_provider=_FakeStoryContextProvider(),
            project_repo=_FakeProjectRepo(),
            outline_repo=_FakeOutlineRepo(),
            user_repo=None,
            retrieval_trace_repo=None,
        )
        summary = service.run(
            RetrievalLoopRequest(
                workflow_run_id="r2",
                workflow_step_id=2,
                project_id="p1",
                trace_id="trace-2",
                step_key="consistency_review",
                workflow_type="consistency_review",
                writing_goal="检查冲突",
                must_have_slots=["character"],
            )
        )
        self.assertEqual(summary.stop_reason, "max_rounds")
        self.assertEqual(len(summary.rounds), 3)
        self.assertLess(summary.coverage.coverage_score, 0.9)

    def test_stop_on_stale_after_coverage(self) -> None:
        cfg = OrchestratorRuntimeConfig(
            retrieval_max_rounds=6,
            retrieval_round_top_k=8,
            retrieval_max_unique_evidence=64,
            retrieval_stop_min_coverage=0.5,
            retrieval_stop_min_gain=0.05,
            retrieval_stop_stale_rounds=2,
            workflow_run_timeout_seconds=480,
            context_chapter_window_before=2,
            context_chapter_window_after=1,
            api_v1_enabled=False,
        )
        service = RetrievalLoopService(
            runtime_config=cfg,
            project_memory_service=_FakeProjectMemoryService(rows=[]),
            story_context_provider=_FakeStoryContextProvider(
                chapters=[{"id": "c1", "chapter_no": 1, "summary": "邻章摘要"}],
                characters=[{"id": "ch1", "name": "主角", "profile_json": {"goal": "调查"}}],
                world_entries=[{"id": "w1", "title": "硬规则", "content": "不可飞行"}],
                timeline_events=[{"id": "t1", "event_title": "事件甲", "event_desc": "顺序锚点"}],
                # 故意不提供伏笔条目，保留 open_slots，在覆盖率已达标时走 stale 分支
                foreshadowings=[],
            ),
            project_repo=_FakeProjectRepo(),
            outline_repo=_FakeOutlineRepo(),
            user_repo=None,
            retrieval_trace_repo=None,
        )
        summary = service.run(
            RetrievalLoopRequest(
                workflow_run_id="r3",
                workflow_step_id=3,
                project_id="p1",
                trace_id="trace-3",
                step_key="writer_draft",
                workflow_type="chapter_generation",
                writing_goal="按报告修订章节",
                must_have_slots=["project_goal", "character"],
            )
        )
        self.assertEqual(summary.stop_reason, "stale_after_coverage")
        self.assertGreaterEqual(summary.coverage.coverage_score, 0.5)
        self.assertIn("foreshadowing", summary.coverage.open_slots)
        self.assertGreaterEqual(len(summary.rounds), 3)

    def test_merge_planner_hints_explicit_then_workflow_base(self) -> None:
        merged = RetrievalLoopService._merge_inference_slots(
            workflow_type="chapter_generation",
            writing_goal="写一章",
            planner_hints=["inventory", "power_rules"],
            explicit_extra=["character"],
            merge_workflow_defaults_when_planner_nonempty=True,
        )
        self.assertEqual(
            merged[:3],
            ["inventory", "power_rules", "character"],
        )
        self.assertIn("outline", merged)
        self.assertIn("foreshadowing", merged)

    def test_merge_planner_nonempty_skips_workflow_when_disabled(self) -> None:
        merged = RetrievalLoopService._merge_inference_slots(
            workflow_type="chapter_generation",
            writing_goal="写一章",
            planner_hints=["character"],
            explicit_extra=["power_rules"],
            merge_workflow_defaults_when_planner_nonempty=False,
        )
        self.assertEqual(merged, ["character", "power_rules"])
        self.assertNotIn("outline", merged)

    def test_merge_skip_workflow_base_issue_scoped(self) -> None:
        merged = RetrievalLoopService._merge_inference_slots(
            workflow_type="revision",
            writing_goal="修订",
            planner_hints=["character", "world_rule"],
            explicit_extra=None,
            merge_workflow_defaults_when_planner_nonempty=True,
            skip_workflow_base=True,
        )
        self.assertEqual(merged, ["character", "world_rule"])
        self.assertNotIn("chapter_neighborhood", merged)

    def test_merge_without_planner_or_explicit_matches_workflow_base_only(self) -> None:
        base = RetrievalLoopService._workflow_base_slots(
            workflow_type="chapter_generation",
            writing_goal="写一章",
        )
        merged = RetrievalLoopService._merge_inference_slots(
            workflow_type="chapter_generation",
            writing_goal="写一章",
            planner_hints=None,
            explicit_extra=None,
            merge_workflow_defaults_when_planner_nonempty=False,
        )
        self.assertEqual(merged, base)

    def test_unknown_slot_maps_to_broad_sources(self) -> None:
        sources = RetrievalLoopService._sources_for_slot("custom_planner_slot_xyz")
        self.assertTrue(sources)
        self.assertIn("memory_fact", sources)

    def test_build_relevance_blob_includes_open_slots(self) -> None:
        blob = RetrievalLoopService.build_relevance_blob(
            writing_goal="续写",
            planner_slots=["inventory"],
            verify_facts=["是否暴露"],
            open_slots=["power_rules", "timeline"],
        )
        self.assertIsNotNone(blob)
        assert blob is not None
        self.assertIn("still_open_slots", blob)
        self.assertIn("power_rules", blob)

    def test_select_round_sources_prefers_planner_tools(self) -> None:
        src = RetrievalLoopService._DEFAULT_SOURCE_TYPES
        picked = RetrievalLoopService._select_round_sources(
            open_slots=["inventory"],
            source_types=src,
            preferred_tools=["get_character_inventory"],
        )
        self.assertGreaterEqual(len(picked), 1)
        self.assertEqual(picked[0], "character_inventory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
