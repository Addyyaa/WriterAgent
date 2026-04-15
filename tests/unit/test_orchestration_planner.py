from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from packages.workflows.orchestration.planner import (
    MockDynamicPlanner,
    OpenAICompatibleDynamicPlanner,
)
from packages.workflows.orchestration.runtime_config import PlannerRuntimeConfig
from packages.workflows.orchestration.types import WorkflowRunRequest


class _DummyResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class TestOrchestrationPlanner(unittest.TestCase):
    def setUp(self) -> None:
        self.request = WorkflowRunRequest(
            project_id="project-1",
            workflow_type="writing_full",
            writing_goal="测试规划器",
        )
        self.context = {
            "project": {"title": "测试工程"},
            "input": {"writing_goal": "测试规划器"},
        }

    def test_mock_planner_is_deterministic(self) -> None:
        planner = MockDynamicPlanner()
        plan_a = planner.plan(self.request, context_json=self.context)
        plan_b = planner.plan(self.request, context_json=self.context)
        self.assertEqual(plan_a, plan_b)
        self.assertGreaterEqual(len(plan_a.nodes), 8)
        self.assertEqual(plan_a.nodes[0].step_key, "planner_bootstrap")
        self.assertTrue(any(node.step_key == "retrieval_context" for node in plan_a.nodes))
        self.assertTrue(any(node.step_key == "writer_draft" for node in plan_a.nodes))
        self.assertTrue(any(node.step_key == "writer_revision" for node in plan_a.nodes))

    def test_mock_planner_single_workflow(self) -> None:
        planner = MockDynamicPlanner()
        plan = planner.plan(
            WorkflowRunRequest(
                project_id="project-1",
                workflow_type="outline_generation",
                writing_goal="先出大纲",
            ),
            context_json=self.context,
        )
        self.assertEqual(len(plan.nodes), 1)
        self.assertEqual(plan.nodes[0].step_key, "outline_generation")
        self.assertEqual(plan.nodes[0].workflow_type, "outline_generation")

    def test_openai_planner_use_mock_short_circuit(self) -> None:
        planner = OpenAICompatibleDynamicPlanner(
            PlannerRuntimeConfig(use_mock=True),
            fallback=MockDynamicPlanner(),
        )
        plan = planner.plan(self.request, context_json=self.context)
        self.assertEqual(plan.plan_version, "mock-v1")
        self.assertGreaterEqual(len(plan.nodes), 1)

    def test_openai_planner_http_error_fallback(self) -> None:
        planner = OpenAICompatibleDynamicPlanner(
            PlannerRuntimeConfig(
                use_mock=False,
                fallback_to_mock_on_error=True,
                model="planner-x",
                base_url="https://example.com/v1",
                api_key="test-key",
                temperature=0.1,
            ),
            fallback=MockDynamicPlanner(),
        )
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            side_effect=RuntimeError("boom"),
        ):
            plan = planner.plan(self.request, context_json=self.context)
        self.assertEqual(plan.plan_version, "mock-v1")
        self.assertGreaterEqual(len(plan.nodes), 1)

    def test_openai_planner_http_error_raise_when_fallback_disabled(self) -> None:
        planner = OpenAICompatibleDynamicPlanner(
            PlannerRuntimeConfig(
                use_mock=False,
                fallback_to_mock_on_error=False,
                model="planner-x",
                base_url="https://example.com/v1",
                api_key="test-key",
                temperature=0.1,
            ),
            fallback=MockDynamicPlanner(),
        )
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                planner.plan(self.request, context_json=self.context)

    def test_openai_planner_parse_success(self) -> None:
        planner = OpenAICompatibleDynamicPlanner(
            PlannerRuntimeConfig(
                use_mock=False,
                model="planner-x",
                base_url="https://example.com/v1",
                api_key="test-key",
                temperature=0.1,
            ),
            fallback=MockDynamicPlanner(),
        )
        body = {
            "model": "planner-x",
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"nodes":[{"step_key":"outline_generation","step_type":"workflow",'
                            '"workflow_type":"outline_generation","agent_name":"plot_agent","depends_on":[],"input_json":{}}],'
                            '"retry_policy":{"max_retries":2},"fallback_policy":{"mode":"safe"}}'
                        )
                    }
                }
            ],
        }
        with patch(
            "packages.llm.text_generation.openai_compatible.httpx.post",
            return_value=_DummyResponse(status_code=200, body=body),
        ):
            plan = planner.plan(self.request, context_json=self.context)
        self.assertEqual(plan.plan_version, "llm-v1")
        self.assertEqual(len(plan.nodes), 1)
        self.assertEqual(plan.nodes[0].step_key, "outline_generation")

    def test_openai_planner_system_prompt_prefers_agent_profile_file(self) -> None:
        with TemporaryDirectory() as tmp:
            agent_root = Path(tmp) / "agents" / "planner_agent"
            agent_root.mkdir(parents=True, exist_ok=True)
            (agent_root / "prompt.md").write_text("你是测试 Planner 提示词", encoding="utf-8")

            with patch.dict(os.environ, {"WRITER_AGENT_CONFIG_ROOT": str(Path(tmp) / "agents")}):
                planner = OpenAICompatibleDynamicPlanner(
                    PlannerRuntimeConfig(use_mock=False),
                    fallback=MockDynamicPlanner(),
                )

            self.assertIn("你是测试 Planner 提示词", planner.system_prompt)
            self.assertIn("你必须仅输出一个 JSON 对象", planner.system_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
