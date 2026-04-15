from __future__ import annotations

import unittest
from types import SimpleNamespace

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest, TextGenerationResult
from packages.workflows.chapter_generation.service import ChapterGenerationWorkflowService
from packages.workflows.writer_output import (
    WRITER_OUTPUT_CONTRACT_DRAFT,
    WRITER_OUTPUT_SCHEMA_REF_DRAFT,
)
from packages.workflows.chapter_generation.types import ChapterGenerationRequest


class _FakeDB:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _FakeProjectRepo:
    def __init__(self) -> None:
        self.project = SimpleNamespace(
            id="p1",
            title="项目",
            genre="科幻",
            premise="前提",
            metadata_json={},
        )

    def get(self, project_id):
        return self.project if project_id == "p1" else None


class _FakeChapterRepo:
    def __init__(self) -> None:
        self.db = _FakeDB()
        self.saved = None
        self.restore_called = False
        self.delete_version_called = False
        self.deleted_chapter_called = False
        self.existing = SimpleNamespace(
            id="c1",
            title="old",
            content="old-content",
            summary="old-summary",
            draft_version=3,
            chapter_no=1,
        )

    def get_by_project_chapter_no(self, project_id, chapter_no):
        if chapter_no == 1:
            return self.existing
        return None

    def save_generated_draft(self, **kwargs):
        chapter = SimpleNamespace(
            id="c1",
            chapter_no=kwargs.get("chapter_no") or 1,
            title=kwargs["title"],
            content=kwargs["content"],
            summary=kwargs["summary"],
            draft_version=4,
        )
        version = SimpleNamespace(id=9)
        self.saved = kwargs
        return chapter, version, False

    def delete_version(self, version_id, *, auto_commit=True):
        self.delete_version_called = True
        return True

    def delete(self, chapter_id):
        self.deleted_chapter_called = True
        return True

    def restore_generated_draft(self, **kwargs):
        self.restore_called = True
        return self.existing


class _FakeAgentRunRepo:
    def __init__(self) -> None:
        self.last = None

    def create_run(self, **kwargs):
        self.last = SimpleNamespace(id="run-1", status="pending", error_code=None)
        return self.last

    def start(self, run_id):
        self.last.status = "running"
        return self.last

    def succeed(self, run_id, **kwargs):
        self.last.status = "success"
        self.last.output_json = kwargs.get("output_json")
        return self.last

    def fail(self, run_id, **kwargs):
        self.last.status = "failed"
        self.last.error_code = kwargs.get("error_code")
        return self.last


class _FakeToolCallRepo:
    def __init__(self) -> None:
        self.calls = []
        self._seq = 0

    def create_call(self, **kwargs):
        self._seq += 1
        row = SimpleNamespace(id=f"call-{self._seq}", status="pending")
        self.calls.append(row)
        return row

    def start(self, call_id):
        return None

    def succeed(self, call_id, **kwargs):
        return None

    def fail(self, call_id, **kwargs):
        return None


class _FakeSkillRunRepo:
    def __init__(self) -> None:
        self.last = None

    def create_run(self, **kwargs):
        self.last = SimpleNamespace(id="skill-1", status="pending")
        return self.last

    def start(self, run_id):
        self.last.status = "running"
        return self.last

    def succeed(self, run_id, **kwargs):
        self.last.status = "success"
        self.last.output_snapshot_json = kwargs.get("output_snapshot_json")
        return self.last

    def fail(self, run_id, **kwargs):
        self.last.status = "failed"
        self.last.output_snapshot_json = kwargs.get("output_snapshot_json")
        return self.last


class _FakeStoryContextProvider:
    def load(self, *, project_id, chapter_no=None, chapter_window_before=2, chapter_window_after=1):
        del project_id, chapter_no, chapter_window_before, chapter_window_after
        return SimpleNamespace(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )


class _FakeProjectMemoryService:
    def build_context(self, **kwargs):
        return SimpleNamespace(items=[])


class _FakeIngestionService:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def ingest_text(self, **kwargs):
        if self.should_fail:
            raise RuntimeError("ingest failed")
        return [SimpleNamespace(id="chunk1")]


def _long_chapter_json(*, units: int = 1100) -> dict:
    """非空白字符数约 units，满足 target_words=1200 的 ±10% 区间 [1080,1320]。"""
    body = "测" * max(300, int(units))
    return {"title": "标题", "content": body, "summary": "摘要一二三四五六七八九十"}

class _FakeTextProvider(TextGenerationProvider):
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        if self.should_fail:
            raise RuntimeError("llm failed")
        payload = _long_chapter_json()
        return TextGenerationResult(
            text="{}",
            json_data=payload,
            model="mock",
            provider="mock",
            is_mock=True,
            raw_response_json={},
        )


class TestChapterGenerationWorkflowUnit(unittest.TestCase):
    def _build_service(self, *, llm_fail: bool = False, ingest_fail: bool = False):
        chapter_repo = _FakeChapterRepo()
        run_repo = _FakeAgentRunRepo()
        skill_repo = _FakeSkillRunRepo()
        service = ChapterGenerationWorkflowService(
            project_repo=_FakeProjectRepo(),
            chapter_repo=chapter_repo,
            agent_run_repo=run_repo,
            tool_call_repo=_FakeToolCallRepo(),
            skill_run_repo=skill_repo,
            story_context_provider=_FakeStoryContextProvider(),
            project_memory_service=_FakeProjectMemoryService(),
            ingestion_service=_FakeIngestionService(should_fail=ingest_fail),  # type: ignore[arg-type]
            text_provider=_FakeTextProvider(should_fail=llm_fail),
        )
        return service, chapter_repo, run_repo, skill_repo

    def test_live_progress_callback_invoked(self) -> None:
        service, _, _, _ = self._build_service()
        events: list[dict] = []
        service.run(
            ChapterGenerationRequest(
                project_id="p1",
                writing_goal="推进冲突",
                chapter_no=1,
                live_progress_callback=lambda p: events.append(dict(p)),
            )
        )
        self.assertTrue(any(e.get("kind") == "writer_draft_llm" for e in events))
        self.assertTrue(any(e.get("kind") == "idle" for e in events))

    def test_writer_prompt_payload_uses_assembler_shape(self) -> None:
        """章节 writer user JSON 与 PromptPayloadAssembler 结构一致（state / retrieval 分区）。"""
        service, _, _, _ = self._build_service()
        project = SimpleNamespace(
            id="p1",
            title="项目",
            genre="科幻",
            premise="前提",
            metadata_json={},
        )
        mem_item = SimpleNamespace(source="mem", text="记忆片段", priority=1)
        memory_context = SimpleNamespace(items=[mem_item])
        story_context = SimpleNamespace(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        payload = service._build_chapter_writer_prompt_payload(
            project=project,
            writing_goal="目标",
            target_words=1200,
            style_hint=None,
            memory_context=memory_context,
            story_context=story_context,
            working_notes=["护栏一行"],
            retrieval_context="编排补充检索",
            chapter_no=1,
            word_count_min=1080,
            word_count_max=1320,
            using_writer_schema=False,
        )
        self.assertEqual(payload.get("step_key"), "chapter_draft")
        self.assertEqual(payload.get("role_id"), "writer_agent")
        self.assertIn("state", payload)
        self.assertIn("chapter_memory", payload["state"])
        self.assertIn("story_assets", payload["state"])
        self.assertIn("retrieval", payload)
        self.assertEqual(payload.get("goal"), "目标")
        self.assertIn("writing_contract", payload)

    def test_writer_draft_payload_with_orchestrator_state(self) -> None:
        """编排 writer_draft：存在四路 alignment 时使用 writer_draft 规格并带 outline。"""
        service, _, _, _ = self._build_service()
        project = SimpleNamespace(
            id="p1",
            title="项目",
            genre="科幻",
            premise="前提",
            metadata_json={},
        )
        memory_context = SimpleNamespace(items=[])
        story_context = SimpleNamespace(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        orch = {
            "outline_generation": {"title": "大纲", "content": "纲要", "structure_json": {}},
            "plot_alignment": {
                "chapter_goal": "g",
                "core_conflict": "c",
                "narcotic_arc": [
                    {
                        "phase": "p1",
                        "plot_beat": "beat",
                        "conflict_level": 5,
                        "pacing_note": "n",
                        "outcome": "o",
                    }
                ],
                "climax_twist": {"description": "d", "impact": "i"},
            },
            "character_alignment": {
                "motivation_analysis": {
                    "explicit": "e",
                    "implicit": "i",
                    "emotion_shift": "s",
                },
                "tone_audit": {"is_consistent": True},
                "constraints": {"must_do": [], "must_not": []},
            },
            "world_alignment": {
                "world_logic_summary": "w",
                "hard_constraints": [],
                "reusable_assets": {
                    "locations": [],
                    "factions": [],
                    "items_concepts": [],
                },
                "potential_conflicts": [],
            },
            "style_alignment": {
                "style_mission": "m",
                "micro_constraints": {
                    "sentence_structure": "s",
                    "vocabulary_level": "v",
                    "forbidden_words": [],
                },
                "rhythm_strategy": {"pacing": "p", "instruction": "i"},
                "anti_drift_checks": [],
                "tonal_keywords": [],
            },
        }
        payload = service._build_chapter_writer_prompt_payload(
            project=project,
            writing_goal="目标",
            target_words=1200,
            style_hint=None,
            memory_context=memory_context,
            story_context=story_context,
            working_notes=None,
            retrieval_context="检索循环补充",
            chapter_no=1,
            word_count_min=1080,
            word_count_max=1320,
            using_writer_schema=False,
            orchestrator_raw_state=orch,
        )
        self.assertEqual(payload.get("step_key"), "writer_draft")
        self.assertIn("outline", payload)
        self.assertIn("plot_alignment", payload["state"])
        self.assertIn("story_assets", payload["state"])

    def test_writer_output_format_follows_runtime_schema_hint(self) -> None:
        """草稿链路 runtime 传入的 schema_ref/contract 应原样进入 user payload，与硬校验一致。"""
        service, _, _, _ = self._build_service()
        project = SimpleNamespace(
            id="p1",
            title="项目",
            genre="科幻",
            premise="前提",
            metadata_json={},
        )
        memory_context = SimpleNamespace(items=[])
        story_context = SimpleNamespace(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        payload = service._build_chapter_writer_prompt_payload(
            project=project,
            writing_goal="目标",
            target_words=1200,
            style_hint=None,
            memory_context=memory_context,
            story_context=story_context,
            working_notes=None,
            retrieval_context=None,
            chapter_no=1,
            word_count_min=1080,
            word_count_max=1320,
            using_writer_schema=True,
            output_format_schema_ref=WRITER_OUTPUT_SCHEMA_REF_DRAFT,
            output_format_contract=WRITER_OUTPUT_CONTRACT_DRAFT,
        )
        fmt = payload.get("output_format") or {}
        self.assertEqual(fmt.get("schema_ref"), WRITER_OUTPUT_SCHEMA_REF_DRAFT)
        self.assertEqual(fmt.get("contract"), WRITER_OUTPUT_CONTRACT_DRAFT)

    def test_success_path(self) -> None:
        service, _, run_repo, skill_repo = self._build_service()
        result = service.run(
            ChapterGenerationRequest(
                project_id="p1",
                writing_goal="推进冲突",
                chapter_no=1,
            )
        )
        self.assertEqual(result.chapter["title"], "标题")
        self.assertEqual(result.memory_ingestion["created_chunks"], 1)
        self.assertIsInstance(result.writer_structured, dict)
        self.assertEqual((result.writer_structured or {}).get("chapter", {}).get("title"), "标题")
        self.assertEqual(run_repo.last.status, "success")
        self.assertEqual(skill_repo.last.status, "success")

    def test_llm_failure_marks_run_failed(self) -> None:
        service, _, run_repo, skill_repo = self._build_service(llm_fail=True)
        with self.assertRaises(RuntimeError):
            service.run(
                ChapterGenerationRequest(
                    project_id="p1",
                    writing_goal="失败场景",
                    chapter_no=1,
                )
            )
        self.assertEqual(run_repo.last.status, "failed")
        self.assertEqual(run_repo.last.error_code, "RuntimeError")
        self.assertEqual(skill_repo.last.status, "failed")

    def test_ingestion_failure_triggers_compensation(self) -> None:
        service, chapter_repo, run_repo, skill_repo = self._build_service(ingest_fail=True)
        with self.assertRaises(RuntimeError):
            service.run(
                ChapterGenerationRequest(
                    project_id="p1",
                    writing_goal="回滚场景",
                    chapter_no=1,
                )
            )
        self.assertTrue(chapter_repo.delete_version_called)
        self.assertTrue(chapter_repo.restore_called)
        self.assertEqual(run_repo.last.status, "failed")
        self.assertEqual(skill_repo.last.status, "success")


if __name__ == "__main__":
    unittest.main(verbosity=2)
