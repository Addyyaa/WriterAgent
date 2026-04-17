"""plot_agent：单一 retrieval 包、plot_context 章节兜底、无 retrieval_summary 重复。"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.workflows.orchestration.prompt_payload_assembler import PromptPayloadAssembler
from packages.workflows.orchestration import service as orchestration_service
from packages.workflows.orchestration.service import WritingOrchestratorService


class TestPlotAgentPromptPayload(unittest.TestCase):
    def test_plot_agent_payload_omits_retrieval_summary_and_enriches_plot_context(self) -> None:
        proj = SimpleNamespace(
            title="P",
            genre="g",
            premise="prem",
            metadata_json={"current_arc_stage": "上升", "next_hook_type": "悬念"},
        )
        row = SimpleNamespace(
            id="run-1",
            project_id="proj-uuid",
            trace_id="tr-1",
            initiated_by="u1",
            input_json={
                "writing_goal": "目标",
                "target_words": 2000,
            },
        )
        step = SimpleNamespace(
            id="st-1",
            step_key="plot_alignment",
            step_type="agent",
            input_json={"workflow_type": "plot_alignment"},
        )
        raw_state = {
            "outline_generation": {
                "view": {
                    "title": "大纲",
                    "structure_json": {"current_arc_stage": "自大纲"},
                    "content": "正文不应进入 plot state",
                }
            }
        }

        ch_repo = MagicMock()
        ch_repo.get_next_chapter_no.return_value = 3
        prev_ch = SimpleNamespace(chapter_no=2, title="上一章", summary="承接摘要", content="")
        ch_repo.get_by_project_chapter_no.return_value = prev_ch

        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.project_repo.get.return_value = proj
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.prompt_payload_assembler = PromptPayloadAssembler()
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = ch_repo

        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc,
            row=row,
            step=step,
            raw_state=raw_state,
            role_id="plot_agent",
        )

        self.assertNotIn("retrieval_summary", payload)
        self.assertIn("retrieval", payload)
        st = payload.get("state") or {}
        self.assertNotIn("retrieval_context", st)
        self.assertIn("outline_generation", st)

        pc = payload.get("plot_context") or {}
        self.assertEqual(pc.get("chapter_no"), 3)
        self.assertEqual(pc.get("target_words"), 2000)
        self.assertEqual(pc.get("arc_stage"), "自大纲")
        self.assertEqual(pc.get("next_hook_type"), "悬念")
        prev_ref = pc.get("previous_chapter_ref") or {}
        self.assertEqual(prev_ref.get("chapter_no"), 2)
        self.assertEqual(prev_ref.get("title"), "上一章")
        self.assertIn("承接", str(prev_ref.get("summary") or ""))

        ch_repo.get_next_chapter_no.assert_called_once_with(row.project_id)
        ch_repo.get_by_project_chapter_no.assert_called_once_with(row.project_id, 2)

    def test_plot_context_arc_stage_falls_back_to_metadata_aliases(self) -> None:
        """大纲无阶段字段时，metadata 中 arc_stage 等别名应进入 plot_context.arc_stage。"""
        proj = SimpleNamespace(
            title="P",
            genre="g",
            premise="prem",
            metadata_json={"arc_stage": "第二幕"},
        )
        row = SimpleNamespace(
            id="run-a",
            project_id="proj-a",
            trace_id="t",
            initiated_by="u1",
            input_json={"writing_goal": "g", "chapter_no": 1},
        )
        step = SimpleNamespace(
            id="s",
            step_key="plot_alignment",
            step_type="agent",
            input_json={"workflow_type": "plot_alignment"},
        )
        raw_state = {
            "outline_generation": {
                "view": {
                    "title": "O",
                    "structure_json": {"acts": []},
                }
            }
        }
        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.project_repo.get.return_value = proj
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.prompt_payload_assembler = PromptPayloadAssembler()
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = MagicMock()

        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc,
            row=row,
            step=step,
            raw_state=raw_state,
            role_id="plot_agent",
        )
        self.assertEqual((payload.get("plot_context") or {}).get("arc_stage"), "第二幕")

    def test_plot_context_next_hook_metadata_alias(self) -> None:
        proj = SimpleNamespace(
            title="P",
            genre="g",
            premise="p",
            metadata_json={"chapter_hook_type": "悬念留白"},
        )
        row = SimpleNamespace(
            id="run-b",
            project_id="proj-b",
            trace_id="t",
            initiated_by="u1",
            input_json={"writing_goal": "g", "chapter_no": 1},
        )
        step = SimpleNamespace(
            id="s",
            step_key="plot_alignment",
            step_type="agent",
            input_json={"workflow_type": "plot_alignment"},
        )
        raw_state = {
            "outline_generation": {"view": {"title": "O", "structure_json": {}}},
        }
        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.project_repo.get.return_value = proj
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.prompt_payload_assembler = PromptPayloadAssembler()
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = MagicMock()

        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc,
            row=row,
            step=step,
            raw_state=raw_state,
            role_id="plot_agent",
        )
        self.assertEqual((payload.get("plot_context") or {}).get("next_hook_type"), "悬念留白")

    def test_plot_agent_retrieval_logged_single_bundle(self) -> None:
        """存在 retrieval 视图时记录 plot_agent_retrieval_single_bundle。"""
        proj = SimpleNamespace(title="P", genre="g", premise="p", metadata_json={})
        row = SimpleNamespace(
            id="run-2",
            project_id="proj-2",
            trace_id="t",
            initiated_by="u1",
            input_json={"writing_goal": "g", "chapter_no": 1},
        )
        step = SimpleNamespace(
            id="s",
            step_key="plot_alignment",
            step_type="agent",
            input_json={"workflow_type": "plot_alignment"},
        )
        raw_state = {
            "outline_generation": {"view": {"title": "O", "structure_json": {}}},
            "retrieval_context": {
                "view": {
                    "writing_context_summary": {"key_facts": ["f1"], "current_states": []},
                    "information_gaps": ["待核实：已有前缀"],
                }
            },
        }

        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.project_repo.get.return_value = proj
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.prompt_payload_assembler = PromptPayloadAssembler()
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = MagicMock()

        with patch.object(orchestration_service.logger, "info") as log_info:
            WritingOrchestratorService._build_role_prompt_payload(
                svc,
                row=row,
                step=step,
                raw_state=raw_state,
                role_id="plot_agent",
            )

        found = False
        for call in log_info.call_args_list:
            arg0 = call[0][0] if call[0] else ""
            if "plot_agent_retrieval_single_bundle" not in str(arg0):
                continue
            try:
                if json.loads(str(arg0)).get("event") == "plot_agent_retrieval_single_bundle":
                    found = True
                    break
            except json.JSONDecodeError:
                continue
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
