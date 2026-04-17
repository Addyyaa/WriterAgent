"""character_agent：双模式载荷、证据分层、背景收窄与有效 mode 解析。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.workflows.orchestration.service import WritingOrchestratorService


class TestCharacterAgentPromptPayload(unittest.TestCase):
    def _base_svc(self) -> WritingOrchestratorService:
        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.agent_registry.root = MagicMock()
        svc.agent_registry.compose_prompt_with_shared_tools.side_effect = lambda x: x
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo.get_next_chapter_no.return_value = 3
        svc.chapter_tool.workflow_service.chapter_repo.get_by_project_chapter_no.return_value = None
        svc._character_repo = MagicMock()
        svc._character_repo.list_by_project.return_value = []
        asm = MagicMock()
        asm.build.return_value = {
            "retrieval": {
                "key_facts": ["性格：谨慎", "待核实：是否见过反派"],
                "current_states": ["当前：独处"],
                "confirmed_facts": ["已确认：身份为学生"],
                "conflicts": [{"description": "设定冲突A"}],
                "information_gaps": ["缺口1"],
                "soft_gaps": {"information_gaps": ["软缺口"]},
            },
            "state": {},
            "project": {"id": "p1"},
        }
        svc.prompt_payload_assembler = asm
        return svc

    def test_guardrails_omits_chapter_text_and_splits_evidence(self) -> None:
        proj = SimpleNamespace(
            title="T",
            genre="g",
            premise="x" * 2000,
            metadata_json={},
        )
        row = SimpleNamespace(
            id="run-1",
            project_id="proj-1",
            trace_id="tr-1",
            initiated_by="u1",
            input_json={"writing_goal": "目标", "chapter_no": 3, "target_words": 2000},
        )
        step = SimpleNamespace(
            id="st-1",
            step_key="character_alignment",
            step_type="agent",
            role_id="character_agent",
            agent_name="character_agent",
            input_json={"workflow_type": "character_alignment", "character_mode": "guardrails"},
        )
        raw_state = {
            "outline_generation": {
                "view": {
                    "title": "大纲",
                    "structure_json": {"character_arcs": []},
                }
            },
            "plot_alignment": {
                "view": {
                    "chapter_goal": "cg",
                    "core_conflict": "cc",
                    "narcotic_arc": [{"phase": "p1"}],
                    "climax_twist": "tw",
                }
            },
        }
        svc = self._base_svc()
        svc.project_repo.get.return_value = proj
        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc,
            row=row,
            step=step,
            raw_state=raw_state,
            role_id="character_agent",
        )
        cc = payload.get("Current_Chapter") or {}
        self.assertNotIn("chapter_text", cc)
        self.assertNotIn("dialogue_snippets", cc)
        self.assertEqual(payload.get("character_mode"), "guardrails")
        self.assertIn("role_profile", payload)
        rp = payload.get("role_profile") or {}
        self.assertIn("focus_character", rp)
        ev = cc.get("confirmed_character_evidence") or []
        gaps = cc.get("unresolved_gaps") or []
        self.assertIn("已确认：身份为学生", ev)
        self.assertIn("性格：谨慎", ev)
        self.assertTrue(any("待核实" in str(x) for x in gaps))
        self.assertTrue(any("缺口" in str(x) for x in gaps))
        bg = payload.get("recent_character_background") or {}
        self.assertLessEqual(len(str(bg.get("premise_excerpt") or "")), 1002)

    def test_audit_includes_chapter_text_when_provided(self) -> None:
        proj = SimpleNamespace(title="T", genre="g", premise="短", metadata_json={})
        row = SimpleNamespace(
            id="run-2",
            project_id="proj-1",
            trace_id="tr-2",
            initiated_by="u1",
            input_json={"writing_goal": "目标", "chapter_no": 3},
        )
        step = SimpleNamespace(
            id="st-2",
            step_key="character_alignment",
            step_type="agent",
            role_id="character_agent",
            agent_name="character_agent",
            input_json={
                "workflow_type": "character_alignment",
                "character_mode": "audit",
                "audit_chapter_text": "正文段落……",
                "audit_dialogue_snippets": ["A：你好"],
            },
        )
        raw_state = {
            "outline_generation": {"view": {"title": "大纲", "structure_json": {}}},
            "plot_alignment": {"view": {"chapter_goal": "g"}},
        }
        svc = self._base_svc()
        svc.project_repo.get.return_value = proj
        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc,
            row=row,
            step=step,
            raw_state=raw_state,
            role_id="character_agent",
        )
        cc = payload.get("Current_Chapter") or {}
        self.assertEqual(payload.get("character_mode"), "audit")
        self.assertIn("正文", str(cc.get("chapter_text") or ""))
        self.assertEqual(cc.get("dialogue_snippets"), ["A：你好"])

    def test_effective_mode_degrades_audit_without_text(self) -> None:
        row = SimpleNamespace(id="run-3", project_id="p", input_json={})
        step = SimpleNamespace(
            step_key="character_alignment",
            role_id="character_agent",
            agent_name="character_agent",
            input_json={"character_mode": "audit"},
        )
        svc = self._base_svc()
        svc._character_audit_chapter_inputs = MagicMock(return_value=("", []))
        m = WritingOrchestratorService._effective_character_mode_for_step(svc, row, step)
        self.assertEqual(m, "guardrails")

    def test_strategy_mode_resolve_matches_effective_character(self) -> None:
        row = SimpleNamespace(id="run-4", project_id="p", input_json={})
        step = SimpleNamespace(
            step_key="character_alignment",
            role_id="character_agent",
            agent_name="character_agent",
            input_json={"character_mode": "audit", "audit_chapter_text": "有字"},
        )
        svc = self._base_svc()
        mode = WritingOrchestratorService._agent_strategy_mode_for_resolve(svc, row, step, "character_agent")
        self.assertEqual(mode, "audit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
