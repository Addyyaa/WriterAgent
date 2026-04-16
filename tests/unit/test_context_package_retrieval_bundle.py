from __future__ import annotations

import unittest

from packages.memory.working_memory.context_builder import ContextItem, ContextPackage


class TestContextPackageRetrievalBundle(unittest.TestCase):
    def test_to_retrieval_bundle_shape(self) -> None:
        pkg = ContextPackage(
            query="q",
            token_budget=100,
            used_tokens=42,
            truncated=True,
            items=[
                ContextItem(source="memory_fact", text="hi", priority=0.9),
            ],
        )
        b = pkg.to_retrieval_bundle()
        self.assertEqual(b["summary"]["key_facts"], ["hi"])
        self.assertEqual(b["summary"]["confirmed_facts"], ["hi"])
        self.assertEqual(b["summary"]["current_states"], [])
        self.assertEqual(b["summary"]["conflicts"], [])
        self.assertEqual(b["summary"]["information_gaps"], [])
        self.assertEqual(b["key_facts"], b["summary"]["key_facts"])
        self.assertEqual(b["confirmed_facts"], b["summary"]["confirmed_facts"])
        self.assertIsNot(b["confirmed_facts"], b["summary"]["confirmed_facts"])
        self.assertEqual(len(b["items"]), 1)
        self.assertEqual(b["items"][0]["source"], "memory_fact")
        self.assertEqual(b["meta"]["used_tokens"], 42)
        self.assertTrue(b["meta"]["truncated"])
        self.assertEqual(b["meta"]["token_budget"], 100)

    def test_to_retrieval_bundle_merges_retrieval_agent_conflicts_and_gaps(self) -> None:
        """传入 retrieval_context 步骤时，决策型字段与 build_retrieval_bundle_from_raw_state 一致。"""
        pkg = ContextPackage(
            query="q",
            token_budget=100,
            used_tokens=10,
            truncated=False,
            items=[
                ContextItem(source="memory_fact", text="事实A", priority=0.9),
            ],
        )
        step = {
            "view": {
                "writing_context_summary": {
                    "key_facts": ["KF"],
                    "current_states": ["ST"],
                },
                "potential_conflicts": [{"description": "时间线矛盾"}],
                "information_gaps": ["未确认动机"],
                "key_evidence": [{"category": "chapter", "snippet": "证据句"}],
            }
        }
        b = pkg.to_retrieval_bundle(retrieval_context_step=step)
        self.assertEqual(b["summary"]["conflicts"], ["时间线矛盾"])
        self.assertEqual(b["summary"]["information_gaps"], ["未确认动机"])
        self.assertEqual(b["summary"]["key_facts"], ["KF"])
        self.assertEqual(b["summary"]["current_states"], ["ST"])
        self.assertEqual(b["conflicts"], b["summary"]["conflicts"])
        self.assertEqual(b["information_gaps"], b["summary"]["information_gaps"])
        self.assertTrue(any("证据句" in str(i.get("text", "")) for i in b["items"]))


if __name__ == "__main__":
    unittest.main()
