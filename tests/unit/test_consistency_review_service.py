from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest, TextGenerationResult
from packages.workflows.chapter_generation.context_provider import StoryConstraintContext
from packages.workflows.consistency_review.service import (
    ConsistencyReviewRequest,
    ConsistencyReviewWorkflowService,
)


class _OkProvider(TextGenerationProvider):
    def __init__(self, payload: dict):
        self.payload = payload
        self.last_input: dict | None = None

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.last_input = dict(request.input_payload or {})
        return TextGenerationResult(
            text="ok",
            json_data=dict(self.payload),
            model="mock",
            provider="mock",
            is_mock=True,
            raw_response_json={},
        )


class _FailProvider(TextGenerationProvider):
    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        raise RuntimeError("llm temporary down")


@dataclass
class _FakeChapter:
    id: object
    chapter_no: int
    title: str
    summary: str
    content: str


class _FakeChapterRepo:
    def __init__(self, chapter: _FakeChapter):
        self.chapter = chapter

    def get(self, chapter_id):
        if str(chapter_id) != str(self.chapter.id):
            return None
        return self.chapter


class _FakeReportRepo:
    def __init__(self) -> None:
        self.last_payload: dict | None = None

    def create_report(self, **kwargs):
        self.last_payload = dict(kwargs)
        return SimpleNamespace(
            id=uuid4(),
            status=kwargs.get("status"),
            score=kwargs.get("score"),
            summary=kwargs.get("summary"),
            issues_json=list(kwargs.get("issues_json") or []),
            recommendations_json=list(kwargs.get("recommendations_json") or []),
        )


class _FakeStoryContextProvider:
    def __init__(self, context: StoryConstraintContext) -> None:
        self.context = context

    def load(self, *, project_id, chapter_no=None, chapter_window_before=2, chapter_window_after=1):
        del project_id, chapter_no, chapter_window_before, chapter_window_after
        return self.context


class TestConsistencyReviewWorkflowService(unittest.TestCase):
    def test_hybrid_merge_prefers_failed_status(self) -> None:
        chapter = _FakeChapter(
            id=uuid4(),
            chapter_no=2,
            title="第2章",
            summary="",
            content="主角提前得知终局对决在高塔发生。",
        )
        context = StoryConstraintContext(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[
                {
                    "chapter_no": 8,
                    "event_title": "终局对决在高塔发生",
                    "event_desc": "最终决战地点揭晓",
                }
            ],
            foreshadowings=[],
        )
        report_repo = _FakeReportRepo()
        service = ConsistencyReviewWorkflowService(
            chapter_repo=_FakeChapterRepo(chapter),
            report_repo=report_repo,
            story_context_provider=_FakeStoryContextProvider(context),
            text_provider=_OkProvider(
                {
                    "overall_status": "warning",
                    "audit_summary": "存在轻微措辞问题。",
                    "issues": [
                        {
                            "category": "character",
                            "severity": "warning",
                            "evidence_context": "角色谨慎",
                            "evidence_draft": "角色过于冲动",
                            "reasoning": "语气偏离",
                            "revision_suggestion": "将冲动改为克制。",
                        }
                    ],
                }
            ),
        )

        result = service.run(
            ConsistencyReviewRequest(
                project_id=uuid4(),
                chapter_id=chapter.id,
                trace_id="trace-x",
            )
        )
        assert isinstance(service.text_provider, _OkProvider)
        lp = service.text_provider.last_input
        self.assertIsNotNone(lp)
        assert lp is not None
        self.assertIn("state", lp)
        self.assertIn("review_contract", lp["state"])
        self.assertIn("audit_dimensions", lp["state"]["review_contract"])
        self.assertIn("allowed_severities", lp["state"]["review_contract"])
        self.assertIn("review_focus", lp["state"])
        self.assertNotIn("audit_dimensions", lp["state"]["review_focus"])
        self.assertIn("review_context", lp["state"])
        self.assertIn("review_evidence_pack", lp["state"])
        self.assertIn("characters_detail", lp["state"]["review_evidence_pack"])
        self.assertIn("chapter_draft_audit", lp["state"])
        self.assertIn("content", lp["state"]["chapter_draft_audit"])
        self.assertNotIn("output_schema", json.dumps(lp, ensure_ascii=False))
        self.assertTrue(result.llm_used)
        self.assertEqual(result.status, "failed")
        self.assertGreaterEqual(result.rule_issues_count, 1)
        self.assertGreaterEqual(result.llm_issues_count, 1)
        self.assertGreaterEqual(len(result.recommendations), 1)
        self.assertIsNotNone(report_repo.last_payload)
        assert report_repo.last_payload is not None
        self.assertEqual(str(report_repo.last_payload["status"]), "failed")

    def test_llm_failure_fallback_rule_only(self) -> None:
        chapter = _FakeChapter(
            id=uuid4(),
            chapter_no=1,
            title="第1章",
            summary="",
            content="北港夜雨，主角进入档案馆开始调查。",
        )
        context = StoryConstraintContext(
            chapters=[],
            characters=[],
            world_entries=[],
            timeline_events=[],
            foreshadowings=[],
        )
        service = ConsistencyReviewWorkflowService(
            chapter_repo=_FakeChapterRepo(chapter),
            report_repo=_FakeReportRepo(),
            story_context_provider=_FakeStoryContextProvider(context),
            text_provider=_FailProvider(),
        )

        result = service.run(
            ConsistencyReviewRequest(
                project_id=uuid4(),
                chapter_id=chapter.id,
                trace_id="trace-y",
            )
        )
        self.assertFalse(result.llm_used)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.rule_issues_count, 0)
        self.assertEqual(result.llm_issues_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
