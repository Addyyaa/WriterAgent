"""
章节生成 API 集成测试（FastAPI）。

运行：
    ./venv/bin/python scripts/test_chapter_generation_api.py
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.api.main import create_app
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from scripts._chapter_workflow_support import build_test_chapter_workflow
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


class TestChapterGenerationAPIIntegration(unittest.TestCase):
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
        self.project = self.project_repo.create(
            title="API Workflow Test Project",
            genre="悬疑",
            premise="验证章节生成 API。",
        )

        app = create_app(workflow_factory=lambda db: build_test_chapter_workflow(db))
        self.client = TestClient(app)

    def test_v1_endpoint_disabled_by_default(self) -> None:
        payload = {
            "writing_goal": "在暴雨夜揭露钟楼守夜人的真实身份",
            "chapter_no": 1,
            "target_words": 900,
            "style_hint": "紧张压迫感",
            "include_memory_top_k": 6,
            "temperature": 0.5,
        }
        resp = self.client.post(
            f"/v1/projects/{self.project.id}/chapters/generate",
            json=payload,
        )
        self.assertEqual(resp.status_code, 404, msg=resp.text)

    def test_generate_endpoint_validation_error(self) -> None:
        resp = self.client.post(
            f"/v1/projects/{self.project.id}/chapters/generate",
            json={
                "writing_goal": "",
                "target_words": 300,
            },
        )
        self.assertEqual(resp.status_code, 404)


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
