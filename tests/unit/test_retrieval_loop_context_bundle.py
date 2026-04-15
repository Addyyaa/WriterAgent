from __future__ import annotations

import unittest

from packages.workflows.orchestration.types import EvidenceItem
from packages.workflows.orchestration.retrieval_loop import RetrievalLoopService


class TestRetrievalContextBundle(unittest.TestCase):
    def test_build_context_lines_truncated_when_over_max_items(self) -> None:
        items = [
            EvidenceItem(
                source_type="memory_fact",
                source_id="1",
                chunk_id="c1",
                text="hello",
                score=0.9,
                adopted=True,
                metadata_json={},
            ),
            EvidenceItem(
                source_type="memory_fact",
                source_id="2",
                chunk_id="c2",
                text="world",
                score=0.8,
                adopted=True,
                metadata_json={},
            ),
        ]
        text, truncated, bundle_items = RetrievalLoopService._build_context_lines(items, max_items=1)
        self.assertTrue(truncated)
        self.assertEqual(len(bundle_items), 1)
        self.assertIn("hello", text)

    def test_build_context_lines_truncated_on_long_text(self) -> None:
        long = "x" * 300
        items = [
            EvidenceItem(
                source_type="project",
                source_id="1",
                chunk_id="c1",
                text=long,
                score=1.0,
                adopted=True,
                metadata_json={},
            ),
        ]
        _text, truncated, _items = RetrievalLoopService._build_context_lines(items, max_items=8)
        self.assertTrue(truncated)


if __name__ == "__main__":
    unittest.main()
