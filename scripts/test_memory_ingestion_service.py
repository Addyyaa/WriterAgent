"""
MemoryIngestionService 集成测试（外部 embedding_service API 版本）。

运行（需在仓库根目录，且数据库可连）::

    python scripts/test_memory_ingestion_service.py

可选环境变量::

    DATABASE_URL                   覆盖默认连接串
    SQL_ECHO=1                     打印 SQL
    EMBEDDING_SERVICE_BASE_URL     外部 embedding 服务地址（默认 http://127.0.0.1:8000）
    EMBEDDING_API_KEY              请求中的 api_key 字段（默认 dummy-key）
    EMBEDDING_MODEL                请求中的 model 字段（默认本地 bge-m3 路径，输出 1024 维）
    EMBEDDING_FORWARD_BASE_URL     可选，转发到上游 OpenAI 兼容服务
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.orm import sessionmaker

from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.vector_settings import MEMORY_EMBEDDING_DIM
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"
_DEFAULT_EMBEDDING_SERVICE_BASE_URL = "http://127.0.0.1:8000"
_DEFAULT_EMBEDDING_API_KEY = "dummy-key"
_DEFAULT_EMBEDDING_MODEL = "bge-m3"

_SYNC_TEXT = (
    "废墟城市被黄沙吞没，断壁之间偶尔能看到旧时代的霓虹牌。"
    "少年背着破损的地图，沿着地铁隧道向北行进。"
    "他相信地图尽头有一座仍在运转的图书馆。"
)
_PENDING_TEXT = (
    "夜里风更冷了。远处传来机械轰鸣，像是某种自动防御系统被重新唤醒。"
    "少年在混凝土掩体后记录下坐标，准备天亮后继续前进。"
)


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _embedding_dim(embedding) -> int:
    """
    兼容 pgvector 在不同驱动/类型处理器下的返回格式：
    - list[float]
    - tuple[float, ...]
    - str: "[0.1,0.2,...]"
    """
    if embedding is None:
        return 0
    if isinstance(embedding, (list, tuple)):
        return len(embedding)
    if isinstance(embedding, str):
        stripped = embedding.strip().strip("[]").strip()
        if not stripped:
            return 0
        return len([part for part in stripped.split(",") if part.strip()])
    raise TypeError(f"不支持的 embedding 类型: {type(embedding)!r}")


class TestMemoryIngestionServiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        db_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
        echo = os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes")
        cls.engine = create_engine_with_driver_fallback(db_url, echo=echo)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        cls.embedding_base_url = os.environ.get(
            "EMBEDDING_SERVICE_BASE_URL",
            _DEFAULT_EMBEDDING_SERVICE_BASE_URL,
        )
        cls.embedding_api_key = os.environ.get(
            "EMBEDDING_API_KEY",
            _DEFAULT_EMBEDDING_API_KEY,
        )
        cls.embedding_model = os.environ.get("EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)
        cls.embedding_forward_base_url = os.environ.get("EMBEDDING_FORWARD_BASE_URL")

    def setUp(self) -> None:
        self.db = self.SessionLocal()
        self.addCleanup(self.db.close)

        self.project_repo = ProjectRepository(self.db)
        self.memory_repo = MemoryChunkRepository(self.db)
        self.chunker = SimpleTextChunker(chunk_size=30, chunk_overlap=6)
        self.embedding_provider = EmbeddingServiceAPIProvider(
            api_key=self.embedding_api_key,
            model=self.embedding_model,
            service_base_url=self.embedding_base_url,
            forward_base_url=self.embedding_forward_base_url,
            normalize_embeddings=True,
        )
        self.service = MemoryIngestionService(
            chunker=self.chunker,
            embedding_provider=self.embedding_provider,
            memory_repo=self.memory_repo,
            embedding_batch_size=8,
            replace_existing_by_default=True,
        )

        self.project = self.project_repo.create(
            title="Memory Ingestion Integration Test",
            genre="科幻",
            premise="验证 embedding_service API 接入下的摄入流程。",
        )

    def test_sync_ingestion_and_similarity_search(self) -> None:
        source_id = uuid4()
        semantic_time = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

        rows = self.service.ingest_text(
            project_id=self.project.id,
            text=_SYNC_TEXT,
            source_type="chapter",
            source_id=source_id,
            chunk_type="paragraph",
            metadata_json={"case": "sync"},
            source_timestamp=semantic_time,
        )
        self.assertGreater(len(rows), 0)

        for row in rows:
            self.assertEqual(_status_value(row.embedding_status), "done")
            self.assertIsNotNone(row.embedding)
            self.assertEqual(_embedding_dim(row.embedding), MEMORY_EMBEDDING_DIM)
            self.assertEqual((row.metadata_json or {}).get("source_timestamp"), semantic_time)

        found = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=self.embedding_provider.embed_query("废墟城市与地铁隧道"),
            top_k=3,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertGreater(len(found), 0)
        self.assertIn("text", found[0])
        self.assertIn("distance", found[0])

    def test_pending_ingestion_then_process(self) -> None:
        source_id = uuid4()

        rows = self.service.ingest_text_as_pending(
            project_id=self.project.id,
            text=_PENDING_TEXT,
            source_type="chapter",
            source_id=source_id,
            chunk_type="paragraph",
            metadata_json={"case": "pending"},
        )
        self.assertGreater(len(rows), 0)

        initial_stats = self.memory_repo.stats_by_status(self.project.id)
        self.assertGreater(initial_stats["pending"], 0)

        process_stats = self.service.process_pending_embeddings(
            project_id=self.project.id,
            limit=100,
            batch_size=8,
            continue_on_error=False,
        )
        self.assertGreater(process_stats.requested, 0)
        self.assertGreater(process_stats.processed, 0)
        self.assertEqual(process_stats.failed, 0)

        after_rows = self.memory_repo.list_by_project(
            self.project.id,
            source_type="memory_fact",
            chunk_type="canonical_fact",
            limit=200,
        )
        self.assertGreater(len(after_rows), 0)
        for row in after_rows:
            self.assertEqual(_status_value(row.embedding_status), "done")
            self.assertIsNotNone(row.embedding)
            self.assertEqual(_embedding_dim(row.embedding), MEMORY_EMBEDDING_DIM)
            self.assertEqual((row.metadata_json or {}).get("dedup_strategy"), "exact_then_semantic")


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
