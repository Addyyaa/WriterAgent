"""
ChapterGenerationWorkflowService 集成测试（单 agent + 单 workflow）。

运行：
    ./venv/bin/python scripts/test_chapter_generation_workflow.py
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.text_generation.base import TextGenerationProvider, TextGenerationRequest
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.storage.postgres.repositories.agent_run_repository import AgentRunRepository
from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.repositories.skill_run_repository import SkillRunRepository
from packages.storage.postgres.repositories.tool_call_repository import ToolCallRepository
from packages.workflows.chapter_generation.types import ChapterGenerationRequest
from scripts._chapter_workflow_support import (
    DeterministicEmbeddingProvider,
    build_test_chapter_workflow,
    build_test_chapter_workflow_with_overrides,
)
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


class _FailingTextProvider(TextGenerationProvider):
    def generate(self, request: TextGenerationRequest):
        raise RuntimeError("mock llm failed")


class _FailingIngestionService:
    def ingest_text(self, **kwargs):
        raise RuntimeError("mock ingestion failed")


class TestChapterGenerationWorkflowIntegration(unittest.TestCase):
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
        self.chapter_repo = ChapterRepository(self.db)
        self.agent_run_repo = AgentRunRepository(self.db)
        self.tool_call_repo = ToolCallRepository(self.db)
        self.skill_run_repo = SkillRunRepository(self.db)
        self.memory_repo = MemoryChunkRepository(self.db)

        self.project = self.project_repo.create(
            title="Workflow Test Project",
            genre="科幻",
            premise="验证章节生成 workflow 全链路。",
        )

    def test_workflow_success_full_chain(self) -> None:
        workflow = build_test_chapter_workflow(self.db)
        result = workflow.run(
            ChapterGenerationRequest(
                project_id=self.project.id,
                writing_goal="主角在钟楼下解开禁令真相",
                chapter_no=1,
                target_words=1000,
                style_hint="第三人称，冷静克制",
                include_memory_top_k=5,
                temperature=0.6,
            )
        )

        self.assertEqual(result.mock_mode, True)
        self.assertEqual(result.chapter["chapter_no"], 1)
        self.assertGreater(len(result.chapter["content"]), 100)
        self.assertGreaterEqual(result.memory_ingestion["created_chunks"], 0)

        runs = self.agent_run_repo.list_recent(project_id=self.project.id, limit=1)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(_status_value(run.status), "success")

        calls = self.tool_call_repo.list_by_agent_run(agent_run_id=run.id, limit=20)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(_status_value(item.status) == "success" for item in calls))
        skill_runs = self.skill_run_repo.list_by_agent_run(agent_run_id=run.id, limit=20)
        self.assertEqual(len(skill_runs), 1)
        self.assertEqual(_status_value(skill_runs[0].status), "success")

        emb = DeterministicEmbeddingProvider().embed_query("钟楼 真相 禁令")
        rows = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=emb,
            top_k=3,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertGreater(len(rows), 0)

    def test_workflow_llm_failure_marks_agent_failed(self) -> None:
        workflow = build_test_chapter_workflow_with_overrides(
            self.db,
            text_provider=_FailingTextProvider(),
        )
        with self.assertRaises(RuntimeError):
            workflow.run(
                ChapterGenerationRequest(
                    project_id=self.project.id,
                    writing_goal="测试失败链路",
                )
            )

        runs = self.agent_run_repo.list_recent(project_id=self.project.id, limit=1)
        self.assertEqual(len(runs), 1)
        self.assertEqual(_status_value(runs[0].status), "failed")
        skill_runs = self.skill_run_repo.list_by_agent_run(agent_run_id=runs[0].id, limit=20)
        self.assertEqual(len(skill_runs), 1)
        self.assertEqual(_status_value(skill_runs[0].status), "failed")
        chapters = self.chapter_repo.list_by_project(self.project.id)
        self.assertEqual(len(chapters), 0)

    def test_workflow_memory_failure_rolls_back_chapter_update(self) -> None:
        chapter = self.chapter_repo.create(
            project_id=self.project.id,
            title="原始标题",
            content="原始正文",
        )
        chapter.summary = "原始摘要"
        self.db.commit()
        self.db.refresh(chapter)
        baseline_versions = list(self.chapter_repo.list_versions(chapter.id))
        baseline_version_count = len(baseline_versions)
        baseline_draft_version = int(chapter.draft_version)

        embedding_provider = DeterministicEmbeddingProvider()
        memory_repo = MemoryChunkRepository(self.db)
        failing_ingestion = _FailingIngestionService()
        workflow = build_test_chapter_workflow_with_overrides(
            self.db,
            embedding_provider=embedding_provider,
            ingestion_service=failing_ingestion,  # type: ignore[arg-type]
        )

        with self.assertRaises(RuntimeError):
            workflow.run(
                ChapterGenerationRequest(
                    project_id=self.project.id,
                    chapter_no=chapter.chapter_no,
                    writing_goal="应触发回滚",
                )
            )

        after = self.chapter_repo.get(chapter.id)
        self.assertIsNotNone(after)
        self.assertEqual(after.title, "原始标题")
        self.assertEqual(after.content, "原始正文")
        self.assertEqual(after.summary, "原始摘要")
        self.assertEqual(int(after.draft_version), baseline_draft_version)
        after_versions = list(self.chapter_repo.list_versions(chapter.id))
        self.assertEqual(len(after_versions), baseline_version_count)

        runs = self.agent_run_repo.list_recent(project_id=self.project.id, limit=1)
        self.assertEqual(_status_value(runs[0].status), "failed")
        skill_runs = self.skill_run_repo.list_by_agent_run(agent_run_id=runs[0].id, limit=20)
        self.assertEqual(len(skill_runs), 1)
        self.assertEqual(_status_value(skill_runs[0].status), "success")


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
