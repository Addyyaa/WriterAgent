"""辅助 LLM 路径（规划器、上下文压缩、本地工具总结）的 schema 与校验一致性。"""

from __future__ import annotations

import unittest

from packages.llm.text_generation.openai_compatible import OpenAICompatibleTextProvider
from packages.schemas.context_compression_output import CONTEXT_COMPRESSION_OUTPUT_SCHEMA
from packages.schemas.dynamic_planner_output import (
    DYNAMIC_PLANNER_INPUT_SCHEMA,
    DYNAMIC_PLANNER_OUTPUT_SCHEMA,
    dynamic_planner_output_schema,
)
from packages.schemas.local_tools_summary_output import (
    LOCAL_PROJECTS_SUMMARY_INPUT_SCHEMA,
    LOCAL_PROJECTS_SUMMARY_OUTPUT_SCHEMA,
)


class AuxiliaryLlmSchemasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OpenAICompatibleTextProvider(
            api_key="k",
            model="m",
            base_url="https://api.openai.com/v1",
            compat_mode="full",
        )

    def test_context_compression_output(self) -> None:
        err = self.provider._validate_response_schema(
            payload={"compressed": "短摘要"},
            schema=CONTEXT_COMPRESSION_OUTPUT_SCHEMA,
        )
        self.assertEqual(err, [])

    def test_dynamic_planner_input_output(self) -> None:
        inp = {
            "workflow_type": "writing_full",
            "writing_goal": "g",
            "context": {"k": 1},
        }
        self.assertEqual(
            self.provider._validate_response_schema(payload=inp, schema=DYNAMIC_PLANNER_INPUT_SCHEMA),
            [],
        )
        out = {
            "nodes": [
                {
                    "step_key": "s",
                    "step_type": "workflow",
                    "workflow_type": "chapter_generation",
                    "agent_name": "writer_agent",
                    "depends_on": [],
                    "input_json": {},
                }
            ],
            "retry_policy": {"max_retries": 1},
            "fallback_policy": {},
        }
        self.assertEqual(
            self.provider._validate_response_schema(payload=out, schema=DYNAMIC_PLANNER_OUTPUT_SCHEMA),
            [],
        )

    def test_dynamic_planner_strict_requires_knowledge_keys(self) -> None:
        strict = dynamic_planner_output_schema(strict_node_knowledge=True)
        minimal = {
            "nodes": [
                {
                    "step_key": "s",
                    "step_type": "workflow",
                    "workflow_type": "chapter_generation",
                    "agent_name": "writer_agent",
                    "depends_on": [],
                    "input_json": {},
                }
            ],
            "retry_policy": {},
            "fallback_policy": {},
        }
        self.assertNotEqual(
            self.provider._validate_response_schema(payload=minimal, schema=strict),
            [],
        )
        full_node = {
            "step_key": "s",
            "step_type": "workflow",
            "workflow_type": "chapter_generation",
            "agent_name": "writer_agent",
            "depends_on": [],
            "input_json": {},
            "required_slots": [],
            "preferred_tools": [],
            "must_verify_facts": [],
            "allowed_assumptions": [],
            "fallback_when_missing": None,
        }
        ok = {
            "nodes": [full_node],
            "retry_policy": {},
            "fallback_policy": {},
        }
        self.assertEqual(self.provider._validate_response_schema(payload=ok, schema=strict), [])

    def test_local_projects_summary(self) -> None:
        inp = {
            "tool_result": {"items": []},
            "instruction": "总结",
        }
        self.assertEqual(
            self.provider._validate_response_schema(payload=inp, schema=LOCAL_PROJECTS_SUMMARY_INPUT_SCHEMA),
            [],
        )
        out = {"overview": "o", "project_titles": ["a"], "notes": "n"}
        self.assertEqual(
            self.provider._validate_response_schema(payload=out, schema=LOCAL_PROJECTS_SUMMARY_OUTPUT_SCHEMA),
            [],
        )


if __name__ == "__main__":
    unittest.main()
