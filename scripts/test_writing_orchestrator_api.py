"""Writing Orchestrator v2 API 集成测试。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.api.main import create_app
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.storage.postgres.repositories.consistency_report_repository import (
    ConsistencyReportRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.user_repository import UserRepository
from scripts._chapter_workflow_support import DeterministicEmbeddingProvider
from scripts._db_engine import create_engine_with_driver_fallback
from scripts._orchestrator_support import build_test_orchestrator_service

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


def _build_test_search_service(db):
    return MemorySearchService(
        embedding_provider=DeterministicEmbeddingProvider(),
        memory_repo=MemoryChunkRepository(db),
    )


class TestWritingOrchestratorAPIIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        echo = os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes")
        cls.engine = create_engine_with_driver_fallback(db_url, echo=echo)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.SessionLocal()
        self.addCleanup(self.db.close)
        self.project_repo = ProjectRepository(self.db)
        self.user_repo = UserRepository(self.db)
        self.outline_repo = OutlineRepository(self.db)
        self.report_repo = ConsistencyReportRepository(self.db)

        app = create_app(
            orchestrator_factory=lambda db: build_test_orchestrator_service(db),
            search_factory=_build_test_search_service,
        )
        self.client = TestClient(app)
        self._bootstrap_auth_and_project()

    def _bootstrap_auth_and_project(self) -> None:
        username = f"api_user_{uuid4().hex[:10]}"
        register = self.client.post(
            "/v2/auth/register",
            json={
                "username": username,
                "email": f"{username}@test.local",
                "password": "test-pass-123",
                "preferences": {"tone": "克制", "taboo": ["血腥描写"]},
            },
        )
        self.assertEqual(register.status_code, 200, msg=register.text)
        auth_body = register.json()
        self.auth_headers = {"Authorization": f"Bearer {auth_body['access_token']}"}
        self.user_id = UUID(str(auth_body["user"]["id"]))

        project_resp = self.client.post(
            "/v2/projects",
            json={
                "title": "Orchestrator API Test",
                "genre": "奇幻",
                "premise": "验证 v2 编排接口全链路",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(project_resp.status_code, 200, msg=project_resp.text)
        self.project_id = UUID(str(project_resp.json()["id"]))

    def _drive_run_to_success(self, run_id: str) -> dict:
        for _ in range(10):
            self._process_worker_once(limit=1)
            detail_resp = self.client.get(
                f"/v2/writing/runs/{run_id}",
                headers=self.auth_headers,
            )
            self.assertEqual(detail_resp.status_code, 200, msg=detail_resp.text)
            detail = detail_resp.json()
            status = str(detail.get("status") or "")
            if status == "success":
                return detail
            if status in {"queued", "running"}:
                continue
            if status == "waiting_review":
                candidates_resp = self.client.get(
                    f"/v2/projects/{self.project_id}/chapter-candidates",
                    params={"status": "pending", "limit": 50},
                    headers=self.auth_headers,
                )
                self.assertEqual(candidates_resp.status_code, 200, msg=candidates_resp.text)
                candidates = list(candidates_resp.json().get("items") or [])
                target = None
                for item in candidates:
                    if str(item.get("workflow_run_id") or "") == str(run_id) and str(item.get("status")) == "pending":
                        target = item
                        break
                self.assertIsNotNone(target, msg="waiting_review 状态应存在可审批 candidate")
                approve = self.client.post(
                    f"/v2/projects/{self.project_id}/chapter-candidates/{target['id']}/approve",
                    headers=self.auth_headers,
                )
                self.assertEqual(approve.status_code, 200, msg=approve.text)
                continue
            self.fail(f"run 进入非预期状态: {status}")
        self.fail("run 未在预期轮次内完成 success")

    def _process_worker_once(self, *, limit: int = 1) -> int:
        worker_db = self.SessionLocal()
        try:
            return build_test_orchestrator_service(worker_db).process_once(limit=limit)
        finally:
            worker_db.close()

    def test_v2_writing_run_end_to_end(self) -> None:
        resp = self.client.post(
            f"/v2/projects/{self.project_id}/writing/runs",
            json={
                "workflow_type": "writing_full",
                "writing_goal": "主角在雨夜追踪假面信使，揭露王城档案库失火真相",
                "chapter_no": 1,
                "target_words": 1000,
                "style_hint": "悬疑、克制、镜头感",
                "include_memory_top_k": 8,
                "temperature": 0.6,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "queued")
        run_id = body["run_id"]

        detail = self._drive_run_to_success(run_id)
        self.assertEqual(detail["status"], "success")
        self.assertIn("retrieval_rounds", detail)
        self.assertGreaterEqual(len(detail["retrieval_rounds"]), 1)
        self.assertIn("retrieval_stop_reason", detail)
        self.assertIn("evidence_coverage", detail)
        self.assertIn("open_slots", detail)
        step_keys = [item["step_key"] for item in detail["steps"]]
        self.assertIn("outline_generation", step_keys)
        self.assertIn("retrieval_context", step_keys)
        self.assertIn("writer_draft", step_keys)
        self.assertIn("consistency_review", step_keys)
        self.assertIn("writer_revision", step_keys)

        outline_resp = self.client.get(
            f"/v2/projects/{self.project_id}/outlines/latest",
            headers=self.auth_headers,
        )
        self.assertEqual(outline_resp.status_code, 200, msg=outline_resp.text)
        self.assertGreaterEqual(int(outline_resp.json()["version_no"]), 1)

        report_resp = self.client.get(
            f"/v2/projects/{self.project_id}/consistency-reports",
            headers=self.auth_headers,
        )
        self.assertEqual(report_resp.status_code, 200, msg=report_resp.text)
        self.assertGreaterEqual(len(report_resp.json()["items"]), 1)

    def test_v2_single_workflow_and_cancel(self) -> None:
        outline_run = self.client.post(
            f"/v2/projects/{self.project_id}/workflows/outline_generation/runs",
            json={
                "workflow_type": "outline_generation",
                "writing_goal": "先生成大纲",
                "target_words": 800,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(outline_run.status_code, 200, msg=outline_run.text)
        outline_run_id = outline_run.json()["run_id"]
        for _ in range(5):
            self._process_worker_once(limit=1)
            detail_resp = self.client.get(
                f"/v2/writing/runs/{outline_run_id}",
                headers=self.auth_headers,
            )
            self.assertEqual(detail_resp.status_code, 200, msg=detail_resp.text)
            detail = detail_resp.json()
            if detail.get("status") == "success":
                break

        detail = self.client.get(
            f"/v2/writing/runs/{outline_run_id}",
            headers=self.auth_headers,
        ).json()
        self.assertEqual(detail["status"], "success")
        self.assertEqual(len(detail["steps"]), 1)
        self.assertEqual(detail["steps"][0]["step_key"], "outline_generation")

        cancel_resp = self.client.post(
            f"/v2/projects/{self.project_id}/writing/runs",
            json={
                "workflow_type": "writing_full",
                "writing_goal": "用于取消的测试任务",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(cancel_resp.status_code, 200, msg=cancel_resp.text)
        cancel_run_id = cancel_resp.json()["run_id"]

        cancelled = self.client.post(
            f"/v2/writing/runs/{cancel_run_id}/cancel",
            headers=self.auth_headers,
        )
        self.assertEqual(cancelled.status_code, 200, msg=cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")

        detail_after_cancel = self.client.get(
            f"/v2/writing/runs/{cancel_run_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(detail_after_cancel.status_code, 200, msg=detail_after_cancel.text)
        self.assertEqual(detail_after_cancel.json()["status"], "cancelled")

    def test_v2_user_preferences_update_and_memory_rebuild(self) -> None:
        resp = self.client.post(
            f"/v2/projects/{self.project_id}/users/{self.user_id}/preferences",
            json={"preferences": {"tone": "冷峻", "pacing": "慢热", "must_keep": ["角色一致性"]}},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["user_id"], str(self.user_id))
        self.assertGreaterEqual(int(body["rebuild_chunks"]), 0)

    def test_v2_retrieval_feedback_endpoint(self) -> None:
        resp = self.client.post(
            "/v2/retrieval/feedback",
            json={
                "project_id": str(self.project_id),
                "request_id": f"req-{uuid4()}",
                "user_id": "api-test-user",
                "clicked_doc_id": None,
                "clicked": False,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        self.assertIn("ok", resp.json())

    def test_v2_evaluation_feedback_and_daily_endpoints(self) -> None:
        run_resp = self.client.post(
            f"/v2/projects/{self.project_id}/writing/runs",
            json={
                "workflow_type": "writing_full",
                "writing_goal": "评测闭环测试",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(run_resp.status_code, 200, msg=run_resp.text)
        run_id = run_resp.json()["run_id"]
        _ = self._drive_run_to_success(run_id)

        writing_feedback = self.client.post(
            f"/v2/projects/{self.project_id}/evaluation/feedback",
            json={
                "evaluation_type": "writing",
                "workflow_run_id": run_id,
                "score": 0.9,
                "comment": "质量良好",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(writing_feedback.status_code, 200, msg=writing_feedback.text)
        self.assertTrue(writing_feedback.json()["ok"])

        run_detail = self.client.get(
            f"/v2/writing/runs/{run_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(run_detail.status_code, 200, msg=run_detail.text)
        eval_run_id = run_detail.json().get("output_json", {}).get("evaluation_run_id")
        self.assertIsNotNone(eval_run_id)
        eval_detail = self.client.get(
            f"/v2/projects/{self.project_id}/evaluation/runs/{eval_run_id}",
            headers=self.auth_headers,
        )
        self.assertEqual(eval_detail.status_code, 200, msg=eval_detail.text)
        self.assertIn("events", eval_detail.json())

        retrieval_feedback = self.client.post(
            f"/v2/projects/{self.project_id}/evaluation/feedback",
            json={
                "evaluation_type": "retrieval",
                "request_id": f"req-{uuid4()}",
                "clicked": False,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(retrieval_feedback.status_code, 200, msg=retrieval_feedback.text)
        self.assertIn("ok", retrieval_feedback.json())

        daily_resp = self.client.get(
            f"/v2/projects/{self.project_id}/evaluation/daily",
            params={"days": 30},
            headers=self.auth_headers,
        )
        self.assertEqual(daily_resp.status_code, 200, msg=daily_resp.text)
        self.assertIn("items", daily_resp.json())

    def test_v2_create_run_invalid_user_id(self) -> None:
        resp = self.client.post(
            f"/v2/projects/{self.project_id}/writing/runs",
            json={
                "workflow_type": "writing_full",
                "writing_goal": "测试非法用户",
                "user_id": "not-a-uuid",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        self.assertEqual(resp.json().get("status"), "queued")


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
