"""
双层去重（facts + mentions）集成测试。

运行（需在仓库根目录，且数据库可连）::

    python scripts/test_memory_dedup_pipeline.py

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
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.storage.postgres.models.memory_fact import MemoryFact
from packages.storage.postgres.models.memory_mention import MemoryMention
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"
_DEFAULT_EMBEDDING_SERVICE_BASE_URL = "http://127.0.0.1:8000"
_DEFAULT_EMBEDDING_API_KEY = "dummy-key"
_DEFAULT_EMBEDDING_MODEL = "/Users/shenfeng/Project/embeddingsModel/bge-m3"


class TestMemoryDedupPipelineIntegration(unittest.TestCase):
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

        provider = EmbeddingServiceAPIProvider(
            api_key=self.embedding_api_key,
            model=self.embedding_model,
            service_base_url=self.embedding_base_url,
            forward_base_url=self.embedding_forward_base_url,
            normalize_embeddings=True,
        )
        self.service = MemoryIngestionService(
            chunker=SimpleTextChunker(chunk_size=1000, chunk_overlap=0),
            embedding_provider=provider,
            memory_repo=self.memory_repo,
            # 语义阈值稍放宽，提升语义去重稳定性
            semantic_dedup_threshold=0.35,
            enable_semantic_dedup=True,
        )

        self.project = self.project_repo.create(
            title="Memory Dedup Pipeline Test",
            genre="科幻",
            premise="验证 exact + semantic 去重。",
        )

    def _count_facts(self) -> int:
        stmt = select(MemoryFact).where(MemoryFact.project_id == self.project.id)
        return len(self.db.execute(stmt).scalars().all())

    def _all_mentions(self) -> list[MemoryMention]:
        stmt = select(MemoryMention).where(MemoryMention.project_id == self.project.id)
        return list(self.db.execute(stmt).scalars().all())

    def test_exact_dedup_should_not_create_new_fact(self) -> None:
        source_id = uuid4()

        first = self.service.ingest_text(
            project_id=self.project.id,
            text="星港协议第七条禁止启动深渊引擎。",
            source_type="chapter",
            source_id=source_id,
            metadata_json={"case": "exact"},
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(self._count_facts(), 1)

        second = self.service.ingest_text(
            project_id=self.project.id,
            text="  星港协议第七条禁止启动深渊引擎。  ",
            source_type="chapter",
            source_id=source_id,
            metadata_json={"case": "exact"},
        )
        # 第二次命中 exact dedup，不应新增 canonical chunk
        self.assertEqual(len(second), 0)
        self.assertEqual(self._count_facts(), 1)

        mentions = self._all_mentions()
        self.assertEqual(len(mentions), 1)
        self.assertGreaterEqual(mentions[0].occurrence_count, 2)

    def test_semantic_dedup_should_merge_paraphrase(self) -> None:
        source_id_1 = uuid4()
        source_id_2 = uuid4()

        self.service.ingest_text(
            project_id=self.project.id,
            text="星港协议第七条禁止启动深渊引擎。",
            source_type="chapter",
            source_id=source_id_1,
            metadata_json={"case": "semantic"},
        )
        facts_after_first = self._count_facts()

        second = self.service.ingest_text(
            project_id=self.project.id,
            text="根据星港协议第7条，深渊引擎不得被启动。",
            source_type="world_entry",
            source_id=source_id_2,
            metadata_json={"case": "semantic"},
        )

        # 语义命中时，第二次不新增 canonical chunk
        self.assertEqual(len(second), 0)
        self.assertEqual(self._count_facts(), facts_after_first)

        mentions = self._all_mentions()
        self.assertGreaterEqual(len(mentions), 2)


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
