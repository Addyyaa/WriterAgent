"""
ChapterRepository 与 ProjectRepository 的集成测试。

运行（需在仓库根目录，且数据库可连）::

    python scripts/test_chapter_repository.py

可选环境变量::

    DATABASE_URL   覆盖默认连接串
    SQL_ECHO=1     打印 SQL
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.storage.postgres.repositories.chapter_repository import ChapterRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository

_DEFAULT_DATABASE_URL = (
    "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"
)

_TEXT_V1 = "天空灰暗，废墟中传来低沉的风声……"
_TEXT_V2 = "天空灰暗，废墟中传来低沉的风声……少年站在断壁之上。"


def _status_value(status) -> str:
    """统一比较章节状态（兼容原生 ENUM 与字符串）。"""
    return status.value if hasattr(status, "value") else str(status)


class TestChapterRepositoryIntegration(unittest.TestCase):
    """章节仓储生命周期：创建 → 改稿与版本 → 回滚 → 发布 → 列表 → 删除。"""

    @classmethod
    def setUpClass(cls) -> None:
        url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        echo = os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes")
        cls.engine = create_engine(url, echo=echo)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    def setUp(self) -> None:
        self.db = self.SessionLocal()
        self.addCleanup(self.db.close)
        self.project_repo = ProjectRepository(self.db)
        self.chapter_repo = ChapterRepository(self.db)

    def test_chapter_full_lifecycle(self) -> None:
        # 1. 创建项目
        project = self.project_repo.create(
            title="测试小说",
            genre="奇幻",
            premise="废土世界",
        )
        self.assertIsNotNone(project.id)
        self.assertIsInstance(project.id, UUID)
        self.assertEqual(project.title, "测试小说")

        # 2. 创建章节
        chapter = self.chapter_repo.create(
            project_id=project.id,
            title="第一章：废墟",
        )
        self.assertIsNotNone(chapter.id)
        self.assertEqual(chapter.chapter_no, 1)
        self.assertEqual(chapter.title, "第一章：废墟")
        self.assertEqual(_status_value(chapter.status), "draft")
        self.assertIsNone(chapter.content)

        cid = chapter.id

        # 3. 第一次写正文：应产生版本快照并提升 draft_version
        updated = self.chapter_repo.update_content(cid, _TEXT_V1)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, _TEXT_V1)
        self.assertEqual(updated.draft_version, 2)

        # 4. 第二次修改：再快照 + 版本递增
        updated2 = self.chapter_repo.update_content(cid, _TEXT_V2)
        self.assertIsNotNone(updated2)
        self.assertEqual(updated2.content, _TEXT_V2)
        self.assertEqual(updated2.draft_version, 3)

        # 5. 版本列表（按 version_no 降序）
        versions = self.chapter_repo.list_versions(cid)
        self.assertGreaterEqual(len(versions), 2)
        self.assertEqual(versions[0].version_no, 2)
        self.assertEqual(versions[0].content, _TEXT_V1)
        self.assertEqual(versions[1].version_no, 1)
        self.assertIsNone(versions[1].content)

        # 6. 回滚到版本 1（快照正文为空）
        rolled = self.chapter_repo.rollback_to_version(cid, 1)
        self.assertIsNotNone(rolled)
        after = self.chapter_repo.get(cid)
        self.assertIsNotNone(after)
        self.assertIsNone(after.content)

        # 7. 发布
        published = self.chapter_repo.publish(cid)
        self.assertIsNotNone(published)
        self.assertEqual(_status_value(published.status), "published")

        # 8. 按项目列出
        chapters = self.chapter_repo.list_by_project(project.id)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0].id, cid)

        # 9. 删除
        self.assertTrue(self.chapter_repo.delete(cid))
        self.assertIsNone(self.chapter_repo.get(cid))


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
