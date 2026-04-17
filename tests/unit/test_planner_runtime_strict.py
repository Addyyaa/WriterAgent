"""Planner 强知识合同：按 workflow 默认与 env。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.workflows.orchestration.runtime_config import PlannerRuntimeConfig


class TestPlannerRuntimeStrict(unittest.TestCase):
    def test_effective_strict_global_flag(self) -> None:
        cfg = PlannerRuntimeConfig(
            strict_node_knowledge_schema=True,
            strict_node_knowledge_workflows=frozenset(),
        )
        self.assertTrue(cfg.effective_strict_node_knowledge("outline_generation"))

    def test_effective_strict_by_workflow(self) -> None:
        cfg = PlannerRuntimeConfig(
            strict_node_knowledge_schema=False,
            strict_node_knowledge_workflows=frozenset({"writing_full", "revision"}),
        )
        self.assertTrue(cfg.effective_strict_node_knowledge("revision"))
        self.assertFalse(cfg.effective_strict_node_knowledge("outline_generation"))

    @mock.patch.dict(
        os.environ,
        {"WRITER_PLANNER_STRICT_NODE_KNOWLEDGE_WORKFLOWS": "none"},
        clear=False,
    )
    def test_from_env_empty_workflow_list(self) -> None:
        cfg = PlannerRuntimeConfig.from_env()
        self.assertEqual(cfg.strict_node_knowledge_workflows, frozenset())
        self.assertFalse(cfg.effective_strict_node_knowledge("writing_full"))


if __name__ == "__main__":
    unittest.main()
