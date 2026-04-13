from __future__ import annotations

import unittest

from packages.retrieval.evaluators.online_eval_service import OnlineEvalService


class _FakeRepo:
    def __init__(self) -> None:
        self.impressions: list[dict] = []
        self.feedbacks: list[dict] = []

    def create_impression(self, **kwargs):
        self.impressions.append(kwargs)
        return None

    def record_feedback(self, **kwargs):
        self.feedbacks.append(kwargs)
        return True

    def get_daily_stats(self, **kwargs):
        del kwargs
        return []


class TestOnlineEvalService(unittest.TestCase):
    def test_assign_and_record(self) -> None:
        repo = _FakeRepo()
        svc = OnlineEvalService(repo)
        assignment = svc.assign_variant(
            project_id="p1",
            user_id="u1",
            query="hello",
            b_ratio=0.5,
        )
        self.assertIn(assignment.variant, {"A", "B"})
        self.assertTrue(assignment.request_id)

        svc.record_impression(
            project_id="p1",
            request_id=assignment.request_id,
            user_id="u1",
            query="hello",
            variant=assignment.variant,
            rerank_backend="rule",
            impressed_doc_ids=["1", "2"],
            context_json={"attempt": "strict"},
        )
        ok = svc.record_feedback(
            project_id="p1",
            request_id=assignment.request_id,
            user_id="u1",
            clicked_doc_id="1",
            clicked=True,
        )
        self.assertTrue(ok)
        self.assertEqual(len(repo.impressions), 1)
        self.assertEqual(len(repo.feedbacks), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

