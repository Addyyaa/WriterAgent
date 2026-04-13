from __future__ import annotations

import unittest

from packages.retrieval.evaluators.dataset import build_dataset
from packages.retrieval.evaluators.offline_eval import OfflineEvaluator
from packages.retrieval.evaluators.online_eval import OnlineEvalEvent, OnlineEvaluator


class TestEvalModules(unittest.TestCase):
    def test_offline_eval(self) -> None:
        dataset = build_dataset(
            "demo",
            [
                {"query": "q1", "positives": ["a", "b"]},
                {"query": "q2", "positives": ["x"]},
            ],
        )

        def retriever(query: str, filters, k: int):
            del filters, k
            return ["a"] if query == "q1" else ["x"]

        report = OfflineEvaluator().evaluate(dataset=dataset, retriever=retriever, k=3)
        self.assertEqual(report.total_samples, 2)
        self.assertGreater(report.recall_at_k, 0.0)

    def test_online_eval(self) -> None:
        evaluator = OnlineEvaluator(["A", "B"])
        variant = evaluator.assign_variant(user_id="u1", query="hello")
        evaluator.record(OnlineEvalEvent(user_id="u1", query="hello", variant=variant, clicked=True))
        report = evaluator.report()
        self.assertEqual(len(report), 2)
        self.assertTrue(any(item.impressions >= 1 for item in report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
