from __future__ import annotations

import unittest
from dataclasses import dataclass

from packages.evaluation.service import OnlineEvaluationService


@dataclass
class _FakeRun:
    id: str
    project_id: str = "p1"
    workflow_run_id: str | None = None
    request_id: str | None = None
    evaluation_type: str = "writing"
    status: str = "running"
    total_score: float | None = None
    score_breakdown_json: dict | None = None
    context_json: dict | None = None
    error_message: str | None = None
    created_at: object | None = None
    updated_at: object | None = None


class _FakeRepo:
    def __init__(self) -> None:
        self.created_runs: list[_FakeRun] = []
        self.events: list[dict] = []
        self.daily: list[dict] = []

    def create_run(self, **kwargs):
        run = _FakeRun(
            id=f"eval-{len(self.created_runs)+1}",
            project_id=str(kwargs.get("project_id")),
            workflow_run_id=str(kwargs.get("workflow_run_id")) if kwargs.get("workflow_run_id") is not None else None,
            request_id=kwargs.get("request_id"),
            evaluation_type=str(kwargs.get("evaluation_type")),
            context_json=dict(kwargs.get("context_json") or {}),
            score_breakdown_json={},
        )
        self.created_runs.append(run)
        return run

    def append_event(self, **kwargs):
        self.events.append(kwargs)

    def succeed_run(self, run_id, **kwargs):
        return run_id, kwargs

    def fail_run(self, run_id, **kwargs):
        return run_id, kwargs

    def upsert_daily_metric(self, **kwargs):
        self.daily.append(kwargs)

    def get_or_create_retrieval_run(self, **kwargs):
        return _FakeRun(
            id="retrieval-1",
            project_id=str(kwargs.get("project_id")),
            request_id=kwargs.get("request_id"),
            evaluation_type="retrieval",
            score_breakdown_json={},
            context_json=dict(kwargs.get("context_json") or {}),
        )

    def get_latest_writing_run_by_workflow(self, **kwargs):
        workflow_run_id = kwargs.get("workflow_run_id")
        if workflow_run_id is None:
            return None
        return _FakeRun(
            id="writing-1",
            project_id="p1",
            workflow_run_id=str(workflow_run_id),
            evaluation_type="writing",
            score_breakdown_json={},
            context_json={},
        )

    def get_run(self, run_id):
        for row in self.created_runs:
            if row.id == run_id:
                return row
        return None

    def list_events(self, **kwargs):
        del kwargs
        return []

    def list_daily(self, **kwargs):
        del kwargs
        return []


class TestEvaluationService(unittest.TestCase):
    def test_writing_run_and_feedback(self) -> None:
        repo = _FakeRepo()
        service = OnlineEvaluationService(repo=repo)

        run = service.start_writing_run(
            project_id="p1",
            workflow_run_id="wf-1",
            request_id="req-1",
            context_json={"x": 1},
        )
        self.assertEqual(run.evaluation_type, "writing")

        service.record_writing_step(
            evaluation_run_id=run.id,
            project_id="p1",
            workflow_run_id="wf-1",
            step_key="writer_draft",
            success=True,
            latency_ms=120,
            payload_json={"k": "v"},
        )
        self.assertEqual(len(repo.events), 1)

        service.complete_writing_run(
            evaluation_run_id=run.id,
            project_id="p1",
            workflow_run_id="wf-1",
            score_breakdown={
                "structure_integrity": 1.0,
                "retrieval_hit_score": 1.0,
                "consistency_score": 0.8,
                "revision_gain": 0.9,
            },
        )
        self.assertGreaterEqual(len(repo.daily), 1)

        ok = service.record_writing_feedback(
            project_id="p1",
            workflow_run_id="wf-1",
            score=0.95,
            payload_json={"comment": "good"},
        )
        self.assertTrue(ok)

    def test_retrieval_feedback(self) -> None:
        repo = _FakeRepo()
        service = OnlineEvaluationService(repo=repo)

        service.record_retrieval_impression(
            project_id="p1",
            request_id="req-r1",
            payload_json={"rows_count": 5},
            metric_value=5.0,
        )
        service.record_retrieval_feedback(
            project_id="p1",
            request_id="req-r1",
            clicked=True,
            payload_json={"clicked_doc_id": "doc-1"},
        )
        self.assertGreaterEqual(len(repo.events), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
