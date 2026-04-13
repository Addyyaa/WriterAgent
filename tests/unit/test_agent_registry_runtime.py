from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.schemas import SchemaRegistry
from packages.schemas.registry import SchemaValidationError
from packages.skills import SkillRegistry
from packages.workflows.orchestration.agent_registry import AgentRegistry


class TestAgentRegistryRuntime(unittest.TestCase):
    def test_load_builtin_agent_profiles(self) -> None:
        root = Path(__file__).resolve().parents[2]
        schema_registry = SchemaRegistry(root / "packages/schemas")
        skill_registry = SkillRegistry(
            root=root / "packages/skills",
            schema_registry=schema_registry,
            strict=True,
            degrade_mode=False,
        )
        registry = AgentRegistry(
            root=root / "apps/agents",
            schema_registry=schema_registry,
            skill_registry=skill_registry,
            strict=True,
            degrade_mode=False,
        )

        role_ids = set(registry.list_role_ids())
        expected = {
            "planner_agent",
            "retrieval_agent",
            "plot_agent",
            "character_agent",
            "world_agent",
            "style_agent",
            "writer_agent",
            "consistency_agent",
        }
        self.assertTrue(expected.issubset(role_ids))
        profile = registry.get("character_agent")
        self.assertIsNotNone(profile)
        self.assertTrue(str(profile.schema_ref).startswith("inline://"))
        self.assertIsInstance(profile.output_schema, dict)

        _, draft_strategy, _, _ = registry.resolve(
            role_id="writer_agent",
            workflow_type="chapter_generation",
            step_key="writer_draft",
            strategy_mode=None,
        )
        _, revision_strategy, _, _ = registry.resolve(
            role_id="writer_agent",
            workflow_type="revision",
            step_key="writer_revision",
            strategy_mode=None,
        )
        self.assertNotEqual(draft_strategy.mode, revision_strategy.mode)
        coverage = registry.consumption_coverage_summary()
        self.assertEqual(int(coverage.get("dead_required_count") or 0), 0)

    def test_missing_skill_strict_and_degrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            schema_root = tmp_root / "schemas"
            skill_root = tmp_root / "skills"
            agent_root = tmp_root / "agents"

            (schema_root / "tools").mkdir(parents=True)
            (schema_root / "agents").mkdir(parents=True)
            (skill_root / "ok_skill").mkdir(parents=True)
            (agent_root / "x_agent").mkdir(parents=True)

            (schema_root / "tools/skill_manifest.schema.json").write_text(
                '{"type":"object","required":["id","name","version","description"],"properties":{"id":{"type":"string"},"name":{"type":"string"},"version":{"type":"string"},"description":{"type":"string"}}}',
                encoding="utf-8",
            )
            (schema_root / "agents/agent_strategy.schema.json").write_text(
                '{"type":"object","required":["version","temperature","max_tokens"],"properties":{"version":{"type":"string"},"temperature":{"type":"number"},"max_tokens":{"type":"integer"}}}',
                encoding="utf-8",
            )
            (schema_root / "agents/agent_profile.schema.json").write_text(
                '{"type":"object","required":["role_id","prompt","strategy","skills","schema_ref","schema_version"],"properties":{"role_id":{"type":"string"},"prompt":{"type":"string"},"strategy":{"type":"object"},"skills":{"type":"array"},"schema_ref":{"type":"string"},"schema_version":{"type":"string"}}}',
                encoding="utf-8",
            )

            (skill_root / "ok_skill/manifest.json").write_text(
                '{"id":"ok_skill","name":"ok","version":"v1","description":"ok"}',
                encoding="utf-8",
            )
            (agent_root / "x_agent/prompt.md").write_text("test", encoding="utf-8")
            (agent_root / "x_agent/strategy.yaml").write_text(
                "version: v1\ntemperature: 0.3\nmax_tokens: 100\n",
                encoding="utf-8",
            )
            (agent_root / "x_agent/output_schema.json").write_text(
                '{"schema_ref":"agents/agent_step_output.schema.json","schema_version":"v1"}',
                encoding="utf-8",
            )
            (agent_root / "x_agent/skills.yaml").write_text(
                "skills:\n  - missing_skill\n",
                encoding="utf-8",
            )

            schema_registry = SchemaRegistry(schema_root)
            strict_skill_registry = SkillRegistry(
                root=skill_root,
                schema_registry=schema_registry,
                strict=True,
                degrade_mode=False,
            )
            strict_registry = AgentRegistry(
                root=agent_root,
                schema_registry=schema_registry,
                skill_registry=strict_skill_registry,
                strict=True,
                degrade_mode=False,
            )
            with self.assertRaises(SchemaValidationError):
                strict_registry.resolve(
                    role_id="x_agent",
                    workflow_type="test",
                    step_key="test",
                )

            degrade_skill_registry = SkillRegistry(
                root=skill_root,
                schema_registry=schema_registry,
                strict=True,
                degrade_mode=True,
            )
            degrade_registry = AgentRegistry(
                root=agent_root,
                schema_registry=schema_registry,
                skill_registry=degrade_skill_registry,
                strict=True,
                degrade_mode=True,
            )
            _, _, _, warnings = degrade_registry.resolve(
                role_id="x_agent",
                workflow_type="test",
                step_key="test",
            )
            self.assertTrue(any("missing_skill" in item for item in warnings))

    def test_skill_overrides_from_skills_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            schema_root = tmp_root / "schemas"
            skill_root = tmp_root / "skills"
            agent_root = tmp_root / "agents"

            (schema_root / "tools").mkdir(parents=True)
            (schema_root / "agents").mkdir(parents=True)
            (skill_root / "ok_skill").mkdir(parents=True)
            (agent_root / "x_agent").mkdir(parents=True)

            (schema_root / "tools/skill_manifest.schema.json").write_text(
                '{"type":"object","required":["id","name","version","description"],"properties":{"id":{"type":"string"},"name":{"type":"string"},"version":{"type":"string"},"description":{"type":"string"}}}',
                encoding="utf-8",
            )
            (schema_root / "agents/agent_strategy.schema.json").write_text(
                '{"type":"object","required":["version","temperature","max_tokens"],"properties":{"version":{"type":"string"},"temperature":{"type":"number"},"max_tokens":{"type":"integer"}}}',
                encoding="utf-8",
            )
            (schema_root / "agents/agent_profile.schema.json").write_text(
                '{"type":"object","required":["role_id","prompt","strategy","skills","schema_ref","schema_version"],"properties":{"role_id":{"type":"string"},"prompt":{"type":"string"},"strategy":{"type":"object"},"skills":{"type":"array"},"schema_ref":{"type":"string"},"schema_version":{"type":"string"}}}',
                encoding="utf-8",
            )
            (skill_root / "ok_skill/manifest.json").write_text(
                '{"id":"ok_skill","name":"ok","version":"v1","description":"ok","mode":"prompt_only"}',
                encoding="utf-8",
            )
            (agent_root / "x_agent/prompt.md").write_text("test", encoding="utf-8")
            (agent_root / "x_agent/strategy.yaml").write_text(
                "version: v1\ntemperature: 0.3\nmax_tokens: 100\n",
                encoding="utf-8",
            )
            (agent_root / "x_agent/output_schema.json").write_text(
                '{"schema_ref":"agents/agent_step_output.schema.json","schema_version":"v1"}',
                encoding="utf-8",
            )
            (agent_root / "x_agent/skills.yaml").write_text(
                "skills:\n  - ok_skill\nskill_overrides:\n  ok_skill:\n    mode: local_code\n    execution_mode: active\n    adapters:\n      - constraint\n",
                encoding="utf-8",
            )

            schema_registry = SchemaRegistry(schema_root)
            skill_registry = SkillRegistry(
                root=skill_root,
                schema_registry=schema_registry,
                strict=True,
                degrade_mode=False,
            )
            registry = AgentRegistry(
                root=agent_root,
                schema_registry=schema_registry,
                skill_registry=skill_registry,
                strict=True,
                degrade_mode=False,
            )
            _, _, skills, _ = registry.resolve(
                role_id="x_agent",
                workflow_type="test",
                step_key="test",
            )
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].mode, "local_code")
            self.assertEqual(skills[0].execution_mode_default, "active")
            self.assertEqual(skills[0].adapters, ["constraint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
