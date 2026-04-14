from __future__ import annotations

import unittest
from unittest import mock

from packages.skills import SkillRuntimeContext, SkillRuntimeEngine
from packages.skills.registry import SkillSpec


class _BrokenExecutor:
    def before_generate(self, *, spec, system_prompt, input_payload, context):
        raise RuntimeError("boom-before")

    def after_generate(self, *, spec, output_payload, context):
        raise RuntimeError("boom-after")


class TestSkillRuntimeEngine(unittest.TestCase):
    def test_before_generate_applies_prompt_instruction(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="creative_writing",
            name="creative_writing",
            version="v1",
            description="",
            tags=["writing"],
        )
        result = engine.run_before_generate(
            skills=[skill],
            system_prompt="你是写作助手",
            input_payload={"goal": "写一段"},
            context=SkillRuntimeContext(
                trace_id="t1",
                role_id="writer_agent",
                workflow_type="chapter_generation",
                step_key="writer_draft",
                mode="draft",
            ),
        )
        self.assertIn("[Skill:creative_writing]", result.system_prompt)
        self.assertGreaterEqual(result.effective_delta, 1)

    def test_after_generate_fills_notes_for_failed_constraint(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="constraint_integration",
            name="constraint_integration",
            version="v1",
            description="",
            tags=["writing"],
        )
        result = engine.run_after_generate(
            skills=[skill],
            output_payload={"status": "failed", "notes": ""},
            context=SkillRuntimeContext(
                trace_id="t2",
                role_id="writer_agent",
                workflow_type="revision",
                step_key="writer_revision",
                mode="revision",
            ),
        )
        self.assertTrue(result.output_payload.get("notes"))

    def test_fail_open_collects_warning(self) -> None:
        engine = SkillRuntimeEngine(executor=_BrokenExecutor(), fail_open=True, strict_fail_close=False)
        skill = SkillSpec(
            id="creative_writing",
            name="creative_writing",
            version="v1",
            description="",
            tags=["writing"],
        )
        before = engine.run_before_generate(
            skills=[skill],
            system_prompt="x",
            input_payload={},
            context=SkillRuntimeContext(
                trace_id="t3",
                role_id="writer_agent",
                workflow_type="chapter_generation",
                step_key="writer_draft",
            ),
        )
        self.assertTrue(before.warnings)

    def test_shadow_mode_collects_local_findings(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="constraint_enforcement",
            name="constraint_enforcement",
            version="v1",
            description="",
            tags=["writing"],
            mode="local_code",
            execution_mode_default="shadow",
            adapters=["constraint"],
        )
        result = engine.run_before_generate(
            skills=[skill],
            system_prompt="你是写作助手",
            input_payload={"story_constraints": {}},
            context=SkillRuntimeContext(
                trace_id="t4",
                role_id="writer_agent",
                workflow_type="chapter_generation",
                step_key="writer_draft",
                mode="draft",
            ),
        )
        self.assertEqual(len(result.runs), 1)
        run = result.runs[0]
        self.assertEqual(run.execution_mode, "shadow")
        self.assertEqual(run.mode_used, "local_code")
        self.assertGreaterEqual(len(run.findings), 1)

    def test_env_flag_can_disable_skill(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="creative_writing",
            name="creative_writing",
            version="v1",
            description="",
            tags=["writing"],
        )
        with mock.patch.dict("os.environ", {"SKILL_CREATIVE_WRITING_ENABLED": "0"}, clear=False):
            result = engine.run_before_generate(
                skills=[skill],
                system_prompt="你是写作助手",
                input_payload={"goal": "写一段"},
                context=SkillRuntimeContext(
                    trace_id="t5",
                    role_id="writer_agent",
                    workflow_type="chapter_generation",
                    step_key="writer_draft",
                    mode="draft",
                ),
            )
        self.assertEqual(result.runs[0].status, "skipped")

    def test_gap_analysis_before_injects_skill_quality_gate(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="gap_analysis",
            name="gap_analysis",
            version="v1",
            description="",
            tags=["agent"],
            mode="hybrid",
            execution_mode_default="active",
            adapters=["qa_spec"],
        )
        result = engine.run_before_generate(
            skills=[skill],
            system_prompt="sys",
            input_payload={"state": {}},
            context=SkillRuntimeContext(
                trace_id="t-gap",
                role_id="plot_agent",
                workflow_type="plot_alignment",
                step_key="plot_alignment",
            ),
        )
        self.assertIsInstance(result.input_payload.get("skill_quality_gate"), dict)
        for run in result.runs:
            if run.skill_id == "gap_analysis":
                self.assertNotEqual(run.no_effect_reason, "未发现 qa_spec/skill_quality_gate")

    def test_gap_analysis_after_does_not_require_qa_spec_in_model_output(self) -> None:
        engine = SkillRuntimeEngine()
        skill = SkillSpec(
            id="gap_analysis",
            name="gap_analysis",
            version="v1",
            description="",
            tags=["agent"],
            mode="hybrid",
            execution_mode_default="active",
            adapters=["qa_spec"],
        )
        result = engine.run_after_generate(
            skills=[skill],
            output_payload={"agent_output": {"writing_context_summary": {}}},
            context=SkillRuntimeContext(
                trace_id="t-gap2",
                role_id="plot_agent",
                workflow_type="plot_alignment",
                step_key="plot_alignment",
            ),
        )
        for run in result.runs:
            if run.skill_id == "gap_analysis":
                self.assertNotEqual(run.no_effect_reason, "未发现 qa_spec/skill_quality_gate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
