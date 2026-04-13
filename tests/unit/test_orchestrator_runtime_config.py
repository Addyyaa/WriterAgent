from __future__ import annotations

import os
import unittest
from unittest import mock

from packages.workflows.orchestration.runtime_config import OrchestratorRuntimeConfig


class TestOrchestratorRuntimeConfig(unittest.TestCase):
    @mock.patch.dict(
        os.environ,
        {
            "WRITER_AGENT_CONFIG_ROOT": "apps/agents",
            "WRITER_SCHEMA_ROOT": "packages/schemas",
            "WRITER_SCHEMA_STRICT": "true",
            "WRITER_SCHEMA_DEGRADE_MODE": "false",
            "WRITER_SKILL_CONFIG_ROOT": "packages/skills",
            "WRITER_SKILL_RUNTIME_DEFAULT_EXECUTION_MODE": "shadow",
            "WRITER_SKILL_RUNTIME_DEFAULT_FALLBACK_POLICY": "warn_only",
            "WRITER_SKILL_RUNTIME_REQUIRE_EFFECT_TRACE": "1",
            "WRITER_EVAL_ONLINE_ENABLED": "true",
            "WRITER_EVAL_DAILY_CRON": "0 1 * * *",
            "WRITER_RETRIEVAL_MAX_ROUNDS": "20",
            "WRITER_RETRIEVAL_ROUND_TOP_K": "8",
            "WRITER_RETRIEVAL_MAX_UNIQUE_EVIDENCE": "64",
            "WRITER_RETRIEVAL_STOP_MIN_COVERAGE": "0.85",
            "WRITER_RETRIEVAL_STOP_MIN_GAIN": "0.05",
            "WRITER_RETRIEVAL_STOP_STALE_ROUNDS": "2",
            "WRITER_WORKFLOW_RUN_TIMEOUT_SECONDS": "480",
            "WRITER_CONTEXT_CHAPTER_WINDOW_BEFORE": "2",
            "WRITER_CONTEXT_CHAPTER_WINDOW_AFTER": "1",
            "WRITER_API_V1_ENABLED": "0",
        },
        clear=False,
    )
    def test_from_env(self) -> None:
        cfg = OrchestratorRuntimeConfig.from_env()
        self.assertEqual(cfg.agent_config_root, "apps/agents")
        self.assertEqual(cfg.schema_root, "packages/schemas")
        self.assertTrue(cfg.schema_strict)
        self.assertFalse(cfg.schema_degrade_mode)
        self.assertEqual(cfg.skill_config_root, "packages/skills")
        self.assertEqual(cfg.skill_runtime_default_execution_mode, "shadow")
        self.assertEqual(cfg.skill_runtime_default_fallback_policy, "warn_only")
        self.assertTrue(cfg.skill_runtime_require_effect_trace)
        self.assertTrue(cfg.eval_online_enabled)
        self.assertEqual(cfg.eval_daily_cron, "0 1 * * *")
        self.assertEqual(cfg.retrieval_max_rounds, 20)
        self.assertEqual(cfg.retrieval_round_top_k, 8)
        self.assertEqual(cfg.retrieval_max_unique_evidence, 64)
        self.assertAlmostEqual(cfg.retrieval_stop_min_coverage, 0.85)
        self.assertAlmostEqual(cfg.retrieval_stop_min_gain, 0.05)
        self.assertEqual(cfg.retrieval_stop_stale_rounds, 2)
        self.assertEqual(cfg.workflow_run_timeout_seconds, 480)
        self.assertEqual(cfg.context_chapter_window_before, 2)
        self.assertEqual(cfg.context_chapter_window_after, 1)
        self.assertFalse(cfg.api_v1_enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
