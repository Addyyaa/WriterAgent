from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from uuid import uuid4

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest, TextGenerationResult
from packages.workflows.revision.service import RevisionRequest, RevisionWorkflowService


class _CaptureProvider(TextGenerationProvider):
    def __init__(self) -> None:
        self.last: TextGenerationRequest | None = None

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.last = request
        payload = {
            "mode": "revision",
            "status": "success",
            "segments": [{"beat_id": 1, "type": "description", "content": "修订后正文段落。"}],
            "word_count": 10,
            "notes": "",
            "chapter": {
                "title": "T",
                "content": "修订后正文段落。",
                "summary": "摘要",
            },
        }
        return TextGenerationResult(
            text=json.dumps(payload, ensure_ascii=False),
            json_data=payload,
            model="mock",
            provider="mock",
            is_mock=True,
            raw_response_json={},
        )


class _FakeChapterRepo:
    def __init__(self, chapter: SimpleNamespace) -> None:
        self._chapter = chapter

    def get(self, chapter_id):
        return self._chapter if str(chapter_id) == str(self._chapter.id) else None

    def save_generated_draft(self, **kwargs):
        ch = SimpleNamespace(id=self._chapter.id, chapter_no=kwargs.get("chapter_no", 1))
        ver = SimpleNamespace(id=42)
        return ch, ver, False


class _FakeReportRepo:
    def get_latest_by_chapter(self, *, chapter_id):
        return SimpleNamespace(
            status="failed",
            summary="摘要问题",
            issues_json=[
                {
                    "category": "logic",
                    "severity": "warning",
                    "evidence_context": "ctx",
                    "evidence_draft": "draft",
                    "reasoning": "因为",
                    "revision_suggestion": "改成一致",
                }
            ],
            recommendations_json=[{"action": "dup", "detail": "不应进 LLM"}],
        )


class _FakeIngestion:
    def ingest_text(self, **kwargs) -> None:
        return None


class TestRevisionWorkflowService(unittest.TestCase):
    def test_payload_uses_assembler_no_output_schema_or_recommendations(self) -> None:
        cid = uuid4()
        body = "ORIGINAL_CHAPTER_BODY_XYZ_保持全文进入修订"
        chapter = SimpleNamespace(
            id=cid,
            title="章",
            content=body,
            summary="旧摘",
            chapter_no=1,
        )
        cap = _CaptureProvider()
        svc = RevisionWorkflowService(
            chapter_repo=_FakeChapterRepo(chapter),
            report_repo=_FakeReportRepo(),
            ingestion_service=_FakeIngestion(),  # type: ignore[arg-type]
            text_provider=cap,
            agent_registry=None,
            schema_registry=None,
        )
        bundle = {
            "summary": {"key_facts": ["事实A"], "current_states": []},
            "items": [{"source": "memory", "text": "证据条", "score": None}],
            "meta": {},
        }
        svc.run(
            RevisionRequest(
                project_id="p1",
                chapter_id=cid,
                trace_id="t1",
                force=True,
                retrieval_bundle=bundle,
                project_context={
                    "id": "p1",
                    "title": "P",
                    "genre": "科幻",
                    "premise": "前提",
                    "metadata_json": {},
                },
            )
        )
        self.assertIsNotNone(cap.last)
        assert cap.last is not None
        payload = dict(cap.last.input_payload or {})
        raw = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("output_schema", payload)
        self.assertNotIn('"output_schema":', raw)
        self.assertNotIn("recommendations", raw)
        self.assertNotIn("retrieval_context", raw)
        self.assertIn("revision_chapter", payload.get("state") or {})
        self.assertIn(body, raw)
        self.assertIn("retrieval", payload)
        self.assertIn("output_format", payload)
        issues = (payload.get("state") or {}).get("consistency_review", {}).get("issues")
        self.assertIsInstance(issues, list)
        self.assertEqual(len(issues), 1)

    def test_revision_context_builder_fields(self) -> None:
        from packages.workflows.revision.context_builder import (
            build_revision_context_slice,
            build_revision_evidence_pack,
            build_revision_focus,
        )

        issues = [{"category": "a", "severity": "high", "reasoning": "r", "revision_suggestion": "s"}]
        f = build_revision_focus(chapter_no=2, issues=issues)
        self.assertEqual(f.get("chapter_no"), 2)
        self.assertEqual(f.get("issue_count"), 1)
        s = build_revision_context_slice(issues=issues)
        self.assertEqual(len(s.get("issue_signals") or []), 1)
        p = build_revision_evidence_pack(issues=issues)
        self.assertEqual(len(p.get("from_issues") or []), 1)


if __name__ == "__main__":
    unittest.main()
