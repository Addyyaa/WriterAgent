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
        self.assertEqual(b["summary"], {"key_facts": [], "current_states": []})
        self.assertEqual(len(b["items"]), 1)
        self.assertEqual(b["items"][0]["source"], "memory_fact")
        self.assertEqual(b["meta"]["used_tokens"], 42)
        self.assertTrue(b["meta"]["truncated"])
        self.assertEqual(b["meta"]["token_budget"], 100)


if __name__ == "__main__":
    unittest.main()
