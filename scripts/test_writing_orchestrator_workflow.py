"""WritingOrchestratorService 集成测试。"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.storage.postgres.repositories.chapter_candidate_repository import (
    ChapterCandidateRepository,
)
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.consistency_report_repository import (
    ConsistencyReportRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.outline_repository import OutlineRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.user_repository import UserRepository
from scripts._db_engine import create_engine_with_driver_fallback
from scripts._orchestrator_support import build_test_orchestrator_service
from packages.workflows.orchestration.types import WorkflowRunRequest

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


class TestWritingOrchestratorWorkflow(unittest.TestCase):
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
        self.outline_repo = OutlineRepository(self.db)
        self.chapter_repo = ChapterRepository(self.db)
        self.candidate_repo = ChapterCandidateRepository(self.db)
        self.report_repo = ConsistencyReportRepository(self.db)
        self.memory_repo = MemoryChunkRepository(self.db)
        self.user_repo = UserRepository(self.db)
        self.user = self.user_repo.create(
            username=f"orch_user_{uuid4().hex[:8]}",
            preferences={"role": "tester"},
        )

        self.project = self.project_repo.create(
            title="Orchestrator Workflow Test",
            genre="悬疑",
            premise="验证全流程编排",
            owner_user_id=self.user.id,
        )
        self.service = build_test_orchestrator_service(self.db)

    def _approve_pending_candidate(self, run_id: str) -> None:
        candidates = self.candidate_repo.list_by_run(workflow_run_id=UUID(str(run_id)))
        pending = [item for item in candidates if str(item.status) == "pending"]
        self.assertGreaterEqual(len(pending), 1, msg="waiting_review 阶段应至少产生一个 pending candidate")
        approved = self.service.approve_candidate(pending[0].id, approved_by=self.user.id)
        self.assertIsNotNone(approved, msg="candidate 审批应成功")

    def test_full_writing_run_success(self) -> None:
        created = self.service.create_run(
            request=WorkflowRunRequest(
                project_id=self.project.id,
                workflow_type="writing_full",
                writing_goal="主角追查古堡失踪案，并发现家族秘密",
                chapter_no=1,
                target_words=900,
                style_hint="紧张克制",
            )
        )
        self.assertEqual(created.status, "queued")

        processed = self.service.process_once(limit=1)
        self.assertEqual(processed, 1)

        waiting_detail = self.service.get_run_detail(created.run_id)
        self.assertIsNotNone(waiting_detail)
        assert waiting_detail is not None
        self.assertEqual(waiting_detail["status"], "waiting_review")
        self._approve_pending_candidate(created.run_id)

        processed = self.service.process_once(limit=1)
        self.assertEqual(processed, 1)

        detail = self.service.get_run_detail(created.run_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["status"], "success")
        self.assertIn("evaluation_run_id", detail.get("output_json", {}))
        self.assertIn("evaluation_score_breakdown", detail.get("output_json", {}))
        self.assertIn("retrieval_rounds", detail)
        self.assertGreaterEqual(len(detail["retrieval_rounds"]), 1)
        self.assertIn("retrieval_stop_reason", detail)
        self.assertIn("evidence_coverage", detail)

        step_keys = [item["step_key"] for item in detail["steps"]]
        self.assertIn("outline_generation", step_keys)
        self.assertIn("retrieval_context", step_keys)
        self.assertIn("writer_draft", step_keys)
        self.assertIn("consistency_review", step_keys)
        self.assertIn("writer_revision", step_keys)
        workflow_types = {item["step_key"]: item["workflow_type"] for item in detail["steps"]}
        self.assertEqual(workflow_types.get("outline_generation"), "outline_generation")
        self.assertEqual(workflow_types.get("writer_draft"), "chapter_generation")

        outline = self.outline_repo.get_latest(project_id=self.project.id)
        self.assertIsNotNone(outline)

        chapters = self.chapter_repo.list_by_project(self.project.id)
        self.assertGreaterEqual(len(chapters), 1)

        report_rows = self.report_repo.list_by_project(project_id=self.project.id, limit=10)
        self.assertGreaterEqual(len(report_rows), 1)

        chunk_rows = self.memory_repo.list_by_project(self.project.id, limit=50)
        self.assertGreaterEqual(len(chunk_rows), 1)

    def test_cancel_before_execute(self) -> None:
        created = self.service.create_run(
            request=WorkflowRunRequest(
                project_id=self.project.id,
                workflow_type="writing_full",
                writing_goal="取消测试",
            )
        )
        cancelled = self.service.cancel_run(created.run_id)
        self.assertTrue(cancelled)

        self.service.process_once(limit=1)
        detail = self.service.get_run_detail(created.run_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["status"], "cancelled")

    def test_recover_stale_running_then_continue(self) -> None:
        created = self.service.create_run(
            request=WorkflowRunRequest(
                project_id=self.project.id,
                workflow_type="writing_full",
                writing_goal="超时恢复测试",
            )
        )
        self.service._ensure_plan_and_steps(created.run_id)  # noqa: SLF001

        run_row = self.service.workflow_run_repo.get(created.run_id)
        assert run_row is not None
        run_row.status = "running"
        run_row.started_at = datetime.now(tz=timezone.utc) - timedelta(seconds=999)

        steps = self.service.workflow_step_repo.list_by_run(workflow_run_id=run_row.id)
        self.assertGreater(len(steps), 0)
        steps[0].status = "running"
        steps[0].started_at = datetime.now(tz=timezone.utc) - timedelta(seconds=999)
        self.db.commit()

        processed = self.service.process_once(limit=1)
        self.assertEqual(processed, 1)
        waiting_detail = self.service.get_run_detail(created.run_id)
        self.assertIsNotNone(waiting_detail)
        assert waiting_detail is not None
        self.assertEqual(waiting_detail["status"], "waiting_review")

        self._approve_pending_candidate(created.run_id)
        processed = self.service.process_once(limit=1)
        self.assertEqual(processed, 1)

        detail = self.service.get_run_detail(created.run_id)
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["status"], "success")


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
