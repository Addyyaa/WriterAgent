from __future__ import annotations

import unittest

from packages.workflows.orchestration.prompt_payload_assembler import (
    PromptPayloadAssembler,
    build_retrieval_bundle_from_raw_state,
)
from packages.workflows.orchestration.prompt_payload_types import (
    RetrievalViewSpec,
    StateDependencySpec,
    StepInputSpec,
)


class TestPromptPayloadAssembler(unittest.TestCase):
    def test_build_projects_only_dependencies_not_full_state(self) -> None:
        specs = {
            "test_agent": StepInputSpec(
                role_id="test_agent",
                include_project=True,
                include_outline=False,
                dependencies=[
                    StateDependencySpec(
                        step_key="step_a",
                        required=True,
                        fields=["keep_me"],
                        compact=False,
                    ),
                ],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        raw_state = {
            "step_a": {
                "agent_output": {"keep_me": 1, "drop_me": "x" * 5000},
                "noise": {"nested": True},
            },
            "step_b": {"agent_output": {"only_in_full": True}},
        }
        payload = asm.build(
            role_id="test_agent",
            step_key="step_x",
            workflow_type="t",
            project_context={"id": "p1", "title": "T"},
            raw_state=raw_state,
            retrieval_bundle={"summary": {"key_facts": [], "current_states": []}, "items": []},
            outline_state={},
        )
        self.assertEqual(payload["state"]["step_a"], {"keep_me": 1})
        self.assertNotIn("step_b", payload["state"])

    def test_compact_long_strings(self) -> None:
        specs = {
            "a": StepInputSpec(
                role_id="a",
                include_project=False,
                include_outline=False,
                dependencies=[
                    StateDependencySpec(
                        step_key="w",
                        required=True,
                        fields=["world_logic_summary"],
                        compact=True,
                    )
                ],
                retrieval=RetrievalViewSpec(mode="none"),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        long_text = "字" * 900
        payload = asm.build(
            role_id="a",
            step_key="k",
            workflow_type="t",
            project_context={},
            raw_state={"w": {"view": {"world_logic_summary": long_text}}},
            retrieval_bundle={},
            outline_state={},
        )
        v = payload["state"]["w"]["world_logic_summary_summary"]
        self.assertLess(len(v), len(long_text))
        self.assertTrue(v.endswith("..."))

    def test_missing_required_dependency_raises(self) -> None:
        asm = PromptPayloadAssembler(
            specs={
                "a": StepInputSpec(
                    role_id="a",
                    dependencies=[
                        StateDependencySpec(step_key="need_me", required=True, fields=["x"])
                    ],
                    retrieval=RetrievalViewSpec(mode="none"),
                )
            }
        )
        with self.assertRaises(ValueError):
            asm.build(
                role_id="a",
                step_key="s",
                workflow_type="t",
                project_context={},
                raw_state={},
                retrieval_bundle={},
                outline_state={},
            )

    def test_retrieval_bundle_summary_and_items(self) -> None:
        raw_state = {
            "retrieval_context": {
                "agent_output": {
                    "writing_context_summary": {
                        "key_facts": ["a"],
                        "current_states": ["b"],
                    },
                    "key_evidence": [{"category": "memory_fact", "snippet": "hello world"}],
                }
            }
        }
        bundle = build_retrieval_bundle_from_raw_state(raw_state)
        self.assertEqual(bundle["summary"]["key_facts"], ["a"])
        self.assertTrue(any("hello" in str(i.get("text")) for i in bundle["items"]))

    def test_retrieval_view_compact_items_respects_max(self) -> None:
        specs = {
            "r": StepInputSpec(
                role_id="r",
                include_project=False,
                include_outline=False,
                dependencies=[],
                retrieval=RetrievalViewSpec(mode="compact_items", max_items=2, max_chars_per_item=10),
            )
        }
        asm = PromptPayloadAssembler(specs=specs)
        bundle = {
            "summary": {"key_facts": [], "current_states": []},
            "items": [
                {"source": "s1", "text": "0123456789abcdef"},
                {"source": "s2", "text": "bbbbbbbb"},
                {"source": "s3", "text": "c"},
            ],
        }
        payload = asm.build(
            role_id="r",
            step_key="x",
            workflow_type="t",
            project_context={},
            raw_state={},
            retrieval_bundle=bundle,
            outline_state={},
        )
        self.assertEqual(len(payload["retrieval"]["items"]), 2)
        self.assertLessEqual(len(payload["retrieval"]["items"][0]["text"]), 10)


if __name__ == "__main__":
    unittest.main()
