from __future__ import annotations

import unittest

from packages.llm.text_generation.base import TextGenerationResult
from packages.workflows.orchestration.agent_output_envelope import (
    build_agent_step_meta_raw,
    step_agent_view,
)


class TestAgentOutputEnvelope(unittest.TestCase):
    def test_step_agent_view_prefers_view(self) -> None:
        step = {"view": {"a": 1}, "agent_output": {"a": 2}}
        self.assertEqual(step_agent_view(step), {"a": 1})

    def test_step_agent_view_falls_back_to_agent_output(self) -> None:
        step = {"agent_output": {"b": 2}}
        self.assertEqual(step_agent_view(step), {"b": 2})

    def test_build_meta_raw_extracts_usage(self) -> None:
        result = TextGenerationResult(
            text='{"x":1}',
            json_data={"x": 1},
            model="m",
            provider="p",
            is_mock=False,
            raw_response_json={
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                "choices": [{"finish_reason": "stop"}],
            },
        )
        meta, raw = build_agent_step_meta_raw(
            result=result,
            schema_ref="ref",
            schema_version="v1",
            prompt_hash="abc",
            strategy_version="sv",
            skills_executed_count=0,
        )
        self.assertEqual(meta.get("usage", {}).get("total_tokens"), 3)
        self.assertEqual(meta.get("finish_reason"), "stop")
        self.assertIn("text", raw)
        self.assertIn("response_summary", raw)


if __name__ == "__main__":
    unittest.main()
