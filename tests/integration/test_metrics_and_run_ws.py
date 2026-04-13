from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.main import create_app


class _FakeResult:
    def __init__(self, *, scalar_value=None, rows=None) -> None:
        self._scalar_value = scalar_value
        self._rows = list(rows or [])

    def scalar(self):
        return self._scalar_value

    def all(self):
        return list(self._rows)


class _FakeDB:
    def execute(self, statement):
        sql = str(statement).lower()
        if "workflow_runs where status in ('queued','running','waiting_review')" in sql:
            return _FakeResult(scalar_value=2)
        if "workflow_runs where status = 'success'" in sql:
            return _FakeResult(scalar_value=5)
        if "workflow_runs where status = 'failed'" in sql:
            return _FakeResult(scalar_value=1)
        if "workflow_steps where status = 'failed'" in sql:
            return _FakeResult(scalar_value=3)
        if "from retrieval_rounds" in sql and "avg(coverage_score)" in sql:
            return _FakeResult(scalar_value=0.81)
        if "from retrieval_rounds" in sql and "count(*)" in sql:
            return _FakeResult(scalar_value=12)
        if "from tool_calls" in sql and "status = 'success'" in sql:
            return _FakeResult(scalar_value=20)
        if "from tool_calls" in sql and "status = 'failed'" in sql:
            return _FakeResult(scalar_value=2)
        if "from skill_runs" in sql and "status = 'success'" in sql and "count(*)" in sql:
            return _FakeResult(scalar_value=18)
        if "from skill_runs" in sql and "effective_delta" in sql:
            return _FakeResult(scalar_value=11)
        if "from skill_runs" in sql and "fallback_used" in sql:
            return _FakeResult(scalar_value=2)
        if "from skill_runs" in sql and "no_effect_reason" in sql:
            return _FakeResult(scalar_value=3)
        if "from skill_runs" in sql and "group by 1" in sql:
            return _FakeResult(rows=[("active", 15), ("shadow", 3)])
        if "from skill_findings" in sql:
            return _FakeResult(scalar_value=8)
        if "from skill_evidence" in sql and "source_scope" in sql:
            return _FakeResult(scalar_value=4)
        if "from skill_evidence" in sql:
            return _FakeResult(scalar_value=21)
        if "from skill_metrics" in sql:
            return _FakeResult(scalar_value=13)
        if "from webhook_deliveries" in sql and "status = 'success'" in sql:
            return _FakeResult(scalar_value=9)
        if "from webhook_deliveries" in sql and "status = 'dead'" in sql:
            return _FakeResult(scalar_value=1)
        return _FakeResult(scalar_value=0)

    def close(self) -> None:
        return None


class _FakeWorkflowRunRepository:
    def __init__(self, db) -> None:
        self.db = db

    def list_recent(self, limit: int = 100):
        return [
            SimpleNamespace(status="success"),
            SimpleNamespace(status="success"),
            SimpleNamespace(status="failed"),
            SimpleNamespace(status="waiting_review"),
        ]


class _FakeAuthService:
    def authenticate_access_token(self, token: str):
        _ = token
        return {
            "id": str(uuid4()),
            "username": "tester",
            "email": "t@example.com",
            "preferences": {"is_admin": True},
            "claims": {"sub": "tester"},
        }


class _FakeMembershipRepo:
    def __init__(self, db) -> None:
        self.db = db

    def has_role(self, *, project_id, user_id, min_role: str = "viewer") -> bool:
        _ = (project_id, user_id, min_role)
        return True


class _FakeAgentRegistry:
    def consumption_coverage_summary(self):
        return {
            "covered_rate": 1.0,
            "dead_required_count": 0,
            "deprecated_unowned_count": 0,
            "deprecated_missing_retire_by_count": 0,
            "invalid_declaration_count": 0,
            "consumed_by_breakdown": {"code": 8, "downstream_prompt": 2, "audit_only": 1},
        }


class _MetricsOrchestrator:
    def __init__(self) -> None:
        self.agent_registry = _FakeAgentRegistry()

    def get_run_detail(self, run_id):  # pragma: no cover - metrics test does not use it
        _ = run_id
        return None


class _WSOrchestrator:
    def __init__(self, detail: dict) -> None:
        self._detail = detail
        self.agent_registry = _FakeAgentRegistry()

    def get_run_detail(self, run_id):
        _ = run_id
        return dict(self._detail)


class TestMetricsAndRunWS(unittest.TestCase):
    @patch("apps.api.main.ProjectMembershipRepository", _FakeMembershipRepo)
    @patch("apps.api.main.WorkflowRunRepository", _FakeWorkflowRunRepository)
    @patch("apps.api.main._build_auth_service", lambda db: _FakeAuthService())
    @patch("apps.api.main.create_session_factory", lambda: (lambda: _FakeDB()))
    def test_metrics_json_endpoint(self) -> None:
        app = create_app(orchestrator_factory=lambda db: _MetricsOrchestrator())
        client = TestClient(app)
        resp = client.get("/v2/system/metrics/json", headers={"Authorization": "Bearer test-token"})
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("generated_at", payload)
        self.assertEqual(payload["workflow"]["queue_depth"], 2)
        self.assertEqual(payload["skills"]["executed_count"], 18)
        self.assertEqual(payload["skills"]["mode_coverage"]["active"], 15)
        self.assertEqual(payload["schema_contract"]["dead_required_count"], 0)

    @patch("apps.api.main.ProjectMembershipRepository", _FakeMembershipRepo)
    @patch("apps.api.main.WorkflowRunRepository", _FakeWorkflowRunRepository)
    @patch("apps.api.main._build_auth_service", lambda db: _FakeAuthService())
    @patch("apps.api.main.create_session_factory", lambda: (lambda: _FakeDB()))
    def test_run_ws_stream(self) -> None:
        run_id = str(uuid4())
        project_id = str(uuid4())
        detail = {
            "id": run_id,
            "project_id": project_id,
            "trace_id": "trace-ws-1",
            "status": "success",
            "error_code": None,
            "error_message": None,
            "created_at": "2026-04-13T10:00:00Z",
            "updated_at": "2026-04-13T10:00:03Z",
            "started_at": "2026-04-13T10:00:01Z",
            "finished_at": "2026-04-13T10:00:03Z",
            "steps": [
                {
                    "id": 1,
                    "step_key": "chapter_generation",
                    "step_type": "chapter_generation",
                    "workflow_type": "chapter_generation",
                    "status": "success",
                    "attempt_count": 1,
                    "role_id": "writer_agent",
                    "started_at": "2026-04-13T10:00:01Z",
                    "finished_at": "2026-04-13T10:00:02Z",
                    "error_code": None,
                    "error_message": None,
                }
            ],
            "candidates": [
                {
                    "id": str(uuid4()),
                    "workflow_step_id": 1,
                    "chapter_no": 5,
                    "title": "Chapter 5",
                    "status": "approved",
                    "approved_chapter_id": str(uuid4()),
                    "approved_version_id": 9,
                    "created_at": "2026-04-13T10:00:02Z",
                    "approved_at": "2026-04-13T10:00:03Z",
                    "rejected_at": None,
                }
            ],
        }
        app = create_app(orchestrator_factory=lambda db: _WSOrchestrator(detail))
        client = TestClient(app)

        with client.websocket_connect(f"/v2/writing/runs/{run_id}/ws?access_token=test-token") as ws:
            received = []
            for _ in range(10):
                try:
                    received.append(ws.receive_json())
                except Exception:
                    break
            self.assertGreaterEqual(len(received), 1)
            self.assertEqual(received[0]["run_id"], run_id)
            event_types = {item["event_type"] for item in received}
            self.assertIn("run_completed", event_types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
