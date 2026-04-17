"""world_agent world_alignment：收口 bundle、证据分层、章意图与 lore 截断。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from packages.workflows.orchestration.prompt_payload_assembler import PromptPayloadAssembler
from packages.workflows.orchestration.service import WritingOrchestratorService
from packages.workflows.orchestration.step_input_specs import STEP_INPUT_SPECS


class TestWorldAgentPromptPayload(unittest.TestCase):
    def _svc(self) -> WritingOrchestratorService:
        svc = WritingOrchestratorService.__new__(WritingOrchestratorService)
        svc.project_repo = MagicMock()
        svc.story_state_snapshot_repo = None
        svc.agent_registry = MagicMock()
        svc.agent_registry.local_data_tools_catalog.return_value = []
        svc.retrieval_loop = MagicMock()
        provider = MagicMock()

        class _Ctx:
            def __init__(self) -> None:
                self.world_entries = [
                    {
                        "id": "we1",
                        "entry_type": "location",
                        "title": "古城",
                        "content": "城内禁止飞行。" * 5,
                    },
                    {
                        "id": "we2",
                        "entry_type": "faction",
                        "title": "魔法部",
                        "content": "登记魔力使用。",
                    },
                ]
                self.chapters = []
                self.characters = []
                self.timeline_events = []
                self.foreshadowings = []

        provider.load_focused.return_value = _Ctx()
        svc.retrieval_loop.story_context_provider = provider
        svc.chapter_tool = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo = MagicMock()
        svc.chapter_tool.workflow_service.chapter_repo.get_next_chapter_no.return_value = 3
        svc.prompt_payload_assembler = PromptPayloadAssembler()
        return svc

    def test_world_alignment_spec_registered(self) -> None:
        spec = STEP_INPUT_SPECS.get("world_agent:world_alignment")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.include_project)
        self.assertFalse(spec.include_outline)
        dep_keys = [d.step_key for d in spec.dependencies]
        self.assertIn("plot_alignment", dep_keys)
        self.assertEqual(spec.retrieval.gap_treatment, "soft_sidebar")

    def test_build_role_prompt_world_alignment_end_to_end(self) -> None:
        proj = SimpleNamespace(title="T", genre="g", premise="世" * 2000, metadata_json={})
        row = SimpleNamespace(
            id="run-w1",
            project_id="proj-1",
            trace_id="tr-1",
            initiated_by="u1",
            input_json={"writing_goal": "g", "chapter_no": 3},
        )
        step = SimpleNamespace(
            step_key="world_alignment",
            step_type="agent",
            role_id="world_agent",
            agent_name="world_agent",
            input_json={"workflow_type": "world_alignment"},
        )
        raw_state = {
            "outline_generation": {
                "view": {
                    "title": "大纲",
                    "structure_json": {"chapters": [{"chapter_no": 3, "title": "风暴前夜"}]},
                }
            },
            "plot_alignment": {
                "view": {
                    "chapter_goal": "突入古城",
                    "core_conflict": "魔力对耗",
                    "narcotic_arc": [{"plot_beat": "潜入"}],
                    "climax_twist": "反转",
                }
            },
            "retrieval_context": {
                "view": {
                    "writing_context_summary": {
                        "key_facts": ["规则A", "待核实：神器"],
                        "current_states": ["场景：古城"],
                        "information_gaps": ["gap1"],
                    },
                }
            },
        }
        svc = self._svc()
        svc.project_repo.get.return_value = proj
        payload = WritingOrchestratorService._build_role_prompt_payload(
            svc, row=row, step=step, raw_state=raw_state, role_id="world_agent"
        )
        for k in ("project", "outline", "retrieval", "retrieval_decision", "retrieval_summary", "world_context"):
            self.assertNotIn(k, payload)
        self.assertIn("world_lore_brief", payload)
        self.assertIn("chapter_intent", payload)
        self.assertEqual((payload.get("chapter_intent") or {}).get("chapter_no"), 3)

    def test_world_gatekeeper_payload_content(self) -> None:
        """完整 payload：六键 + 无 project/outline/retrieval 重复通道。"""
        proj = SimpleNamespace(
            title="T",
            genre="g",
            premise="世" * 2500,
            metadata_json={"tone": "冷"},
        )
        row = SimpleNamespace(
            id="run-w2",
            project_id="proj-1",
            trace_id="tr-1",
            initiated_by="u1",
            input_json={"writing_goal": "写第三章", "chapter_no": 3},
        )
        step = SimpleNamespace(
            step_key="world_alignment",
            step_type="agent",
            role_id="world_agent",
            agent_name="world_agent",
            input_json={"workflow_type": "world_alignment"},
        )
        raw_state = {
            "outline_generation": {
                "view": {
                    "title": "大纲",
                    "structure_json": {"chapters": [{"chapter_no": 3, "title": "风暴前夜"}]},
                }
            },
            "plot_alignment": {
                "view": {
                    "chapter_goal": "突入古城",
                    "core_conflict": "魔力对耗",
                    "narcotic_arc": [{"plot_beat": "潜入"}],
                    "climax_twist": "反转",
                }
            },
        }
        svc = self._svc()
        svc.project_repo.get.return_value = proj
        core = svc.prompt_payload_assembler.build(
            role_id="world_agent",
            step_key="world_alignment",
            workflow_type="world_alignment",
            project_context={
                "id": "proj-1",
                "title": proj.title,
                "genre": proj.genre,
                "premise": proj.premise,
                "metadata_json": proj.metadata_json,
            },
            raw_state=raw_state,
            retrieval_bundle={
                "summary": {
                    "key_facts": ["规则：魔力守恒", "待核实：古代神器"],
                    "current_states": ["场景：古城", "待确认：反派"],
                    "confirmed_facts": ["已确认：月食"],
                    "supporting_evidence": ["档案：登记"],
                    "conflicts": [{"description": "互斥"}],
                    "information_gaps": ["gap1"],
                },
                "items": [{"text": "世界规则：禁飞", "source": "memory"}],
            },
            outline_state={"title": "大纲", "structure_json": {}},
        )
        retrieval_view = dict(core.get("retrieval") or {})
        key_facts = [str(x).strip() for x in list(retrieval_view.get("key_facts") or []) if str(x).strip()]
        current_states = [
            str(x).strip()
            for x in list(retrieval_view.get("current_states") or [])
            if str(x).strip()
        ]
        payload = WritingOrchestratorService._build_world_gatekeeper_payload(
            svc,
            row=row,
            step=step,
            core=core,
            project_context={
                "id": "proj-1",
                "title": proj.title,
                "genre": proj.genre,
                "premise": proj.premise,
                "metadata_json": proj.metadata_json,
            },
            outline_state={"title": "大纲", "structure_json": {"chapters": [{"chapter_no": 3, "title": "风暴前夜"}]}},
            outline_structure={"chapters": [{"chapter_no": 3, "title": "风暴前夜"}]},
            raw_state=raw_state,
            retrieval_bundle={
                "summary": retrieval_view,
                "items": [{"text": "世界规则：禁飞", "source": "memory"}],
            },
            retrieval_view=retrieval_view,
            key_facts=key_facts,
            current_states=current_states,
            effective_chapter_no=3,
        )
        for k in (
            "project",
            "outline",
            "retrieval",
            "retrieval_decision",
            "retrieval_summary",
            "world_context",
        ):
            self.assertNotIn(k, payload)
        self.assertIn("world_lore_brief", payload)
        self.assertIn("chapter_world_slice", payload)
        self.assertIn("chapter_intent", payload)
        ci = payload["chapter_intent"]
        self.assertEqual(ci.get("chapter_no"), 3)
        self.assertEqual(ci.get("chapter_title"), "风暴前夜")
        self.assertEqual(ci.get("chapter_goal"), "突入古城")
        brief = payload["world_lore_brief"] or {}
        self.assertLessEqual(len(str(brief.get("premise_excerpt") or "")), 1200)
        gaps = payload.get("unresolved_gaps") or []
        self.assertTrue(any("待核实" in str(x) or "待确认" in str(x) for x in gaps))
        conf = payload.get("confirmed_world_facts") or []
        self.assertTrue(any("魔力守恒" in str(x) for x in conf))
        applicable = payload.get("chapter_applicable_states") or []
        self.assertTrue(any("古城" in str(x) for x in applicable))
        wslice = payload.get("chapter_world_slice") or {}
        self.assertTrue(len(wslice.get("world_entries") or []) >= 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
