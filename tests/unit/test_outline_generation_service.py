"""outline_generation：输入/输出合同与 structure_json 补齐。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.llm.text_generation.mock_provider import MockTextGenerationProvider
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.workflows.outline_generation.service import (
    OutlineGenerationRequest,
    OutlineGenerationWorkflowService,
    _coerce_structure_json,
)


class TestCoerceStructureJson(unittest.TestCase):
    def test_coerce_fills_missing_keys(self) -> None:
        raw = {"acts": [{"name": "A", "chapter_targets": ["x"], "risk_points": []}]}
        out, coerced = _coerce_structure_json(raw, "目标")
        self.assertTrue(coerced)
        self.assertEqual(out["chapter_goal"], "目标")
        self.assertEqual(out["core_conflict"], "")
        self.assertEqual(out["end_hook"], "")
        self.assertEqual(out["must_preserve_facts"], [])
        self.assertEqual(out["open_questions"], [])
        self.assertEqual(out["assumptions_used"], [])
        self.assertEqual(len(out["acts"]), 1)

    def test_coerce_non_dict_returns_fallback(self) -> None:
        out, coerced = _coerce_structure_json(None, "g")
        self.assertTrue(coerced)
        self.assertIn("acts", out)
        self.assertEqual(out["chapter_goal"], "g")


class TestOutlineGenerationRun(unittest.TestCase):
    def test_run_uses_outline_intake_and_mock_shape(self) -> None:
        project = SimpleNamespace(
            id="p-1",
            title="T",
            genre="G",
            premise="前提",
            metadata_json={},
        )
        outline_row = SimpleNamespace(
            id="ol-1",
            version_no=1,
            title="大纲",
            content="梗概",
            structure_json={"chapter_goal": "x"},
        )
        project_repo = MagicMock(spec=ProjectRepository)
        project_repo.get.return_value = project
        outline_repo = MagicMock(spec=OutlineRepository)
        outline_repo.create_version.return_value = outline_row

        svc = OutlineGenerationWorkflowService(
            project_repo=project_repo,
            outline_repo=outline_repo,
            text_provider=MockTextGenerationProvider(),
        )
        intake = {
            "project_brief": {
                "id": "p-1",
                "title": "T",
                "genre": "G",
                "premise": "短",
                "metadata_json": {},
            },
            "target_chapter_position": {
                "chapter_no": 1,
                "target_words": None,
                "arc_stage": None,
                "next_hook_type": None,
            },
            "prior_chapter_summary": None,
            "confirmed_facts": [],
            "current_states": [],
            "supporting_evidence": [],
            "conflicts": [],
            "information_gaps": [],
            "key_facts": [],
        }
        result = svc.run(
            OutlineGenerationRequest(
                project_id="p-1",
                writing_goal="写开篇",
                style_hint=None,
                outline_intake=intake,
            )
        )
        self.assertTrue(result.outline_id)
        project_repo.get.assert_called_once()
        outline_repo.create_version.assert_called_once()
        call_kw = outline_repo.create_version.call_args.kwargs
        self.assertIn("chapter_goal", call_kw["structure_json"])


if __name__ == "__main__":
    unittest.main()
