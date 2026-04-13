from __future__ import annotations

import unittest

from packages.retrieval.evaluators.metrics import mrr, ndcg_at_k, recall_at_k


class TestRetrievalMetrics(unittest.TestCase):
    def test_recall_at_k(self) -> None:
        self.assertEqual(recall_at_k([0, 0, 1], 2), 0.0)
        self.assertEqual(recall_at_k([0, 1, 0], 2), 1.0)

    def test_mrr(self) -> None:
        self.assertAlmostEqual(mrr([0, 1, 0]), 0.5)
        self.assertEqual(mrr([0, 0, 0]), 0.0)

    def test_ndcg(self) -> None:
        value = ndcg_at_k([1, 0, 1], 3)
        self.assertGreater(value, 0.0)
        self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
