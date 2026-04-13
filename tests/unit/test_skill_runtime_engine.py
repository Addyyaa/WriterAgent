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


if __name__ == "__main__":
    unittest.main(verbosity=2)
