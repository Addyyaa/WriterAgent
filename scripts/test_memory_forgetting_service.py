"""
MemoryForgettingService 集成测试（不依赖外部 embedding API）。

运行（需在仓库根目录，且数据库可连）::

    python scripts/test_memory_forgetting_service.py

可选环境变量::

    DATABASE_URL   覆盖默认连接串
    SQL_ECHO=1     打印 SQL
"""

from __future__ import annotations

import hashlib
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.embeddings.base import EmbeddingProvider
from packages.memory.long_term.ingestion.ingestion_service import MemoryIngestionService
from packages.memory.long_term.lifecycle.forgetting import MemoryForgettingService
from packages.memory.long_term.runtime_config import (
    ForgettingRuntimeConfig,
    IngestionRuntimeConfig,
    MemoryRuntimeConfig,
    ObservabilityRuntimeConfig,
)
from packages.retrieval.chunking.simple_text_chunker import SimpleTextChunker
from packages.retrieval.config import RetrievalRuntimeConfig
from packages.storage.postgres.repositories.memory_fact_repository import (
    MemoryFactRepository,
)
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from packages.storage.postgres.vector_settings import MEMORY_EMBEDDING_DIM
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """
    轻量可重复 embedding provider：
    - 同一文本 => 稳定同一向量
    - 维度固定为 MEMORY_EMBEDDING_DIM
    """

    @staticmethod
    def _embed_one(text: str) -> list[float]:
        digest = hashlib.sha256((text or "").strip().encode("utf-8")).digest()
        vec = [0.0] * MEMORY_EMBEDDING_DIM
        for i in range(MEMORY_EMBEDDING_DIM):
            vec[i] = (digest[i % len(digest)] / 255.0) - 0.5
        norm = math.sqrt(sum(item * item for item in vec)) or 1.0
        return [item / norm for item in vec]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class TestMemoryForgettingServiceIntegration(unittest.TestCase):
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
        self.memory_repo = MemoryChunkRepository(self.db)
        self.memory_fact_repo = MemoryFactRepository(self.db)
        self.embedding_provider = DeterministicEmbeddingProvider()
        self.chunker = SimpleTextChunker(chunk_size=256, chunk_overlap=0)

        self.runtime_config = MemoryRuntimeConfig(
            ingestion=IngestionRuntimeConfig(),
            retrieval=RetrievalRuntimeConfig(),
            observability=ObservabilityRuntimeConfig(enable_logging=False),
            forgetting=ForgettingRuntimeConfig(
                enable=True,
                cooling_days=1,
                suppress_days=3,
                archive_days=8,
                delete_days=14,
                min_mentions_to_keep=2,
                run_limit=200,
            ),
        )

        self.forgetting_service = MemoryForgettingService(
            memory_repo=self.memory_repo,
            memory_fact_repo=self.memory_fact_repo,
            runtime_config=self.runtime_config,
        )
        self.ingestion_service = MemoryIngestionService(
            chunker=self.chunker,
            embedding_provider=self.embedding_provider,
            memory_repo=self.memory_repo,
            memory_fact_repo=self.memory_fact_repo,
            runtime_config=self.runtime_config,
            enable_semantic_dedup=True,
            semantic_dedup_threshold=0.12,
            embedding_batch_size=16,
        )

        self.project = self.project_repo.create(
            title="Memory Forgetting Integration Test",
            genre="测试",
            premise="验证记忆遗忘状态机与恢复能力。",
        )

    def _seed_fact_with_chunk(
        self,
        *,
        text: str,
        days_old: int,
        mention_count: int = 1,
        fact_metadata: dict | None = None,
    ):
        embedding = self.embedding_provider.embed_query(text)
        source_id = uuid4()
        result = self.memory_fact_repo.upsert_fact_with_mention(
            project_id=self.project.id,
            source_type="chapter",
            source_id=source_id,
            chunk_type="paragraph",
            raw_text=text,
            embedding=embedding,
            metadata_json=dict(fact_metadata or {}),
            semantic_threshold=0.12,
        )
        fact = result.fact

        aged_time = datetime.now(tz=timezone.utc) - timedelta(days=days_old)
        fact.first_seen_at = aged_time
        fact.last_seen_at = aged_time
        fact.mention_count = mention_count
        fact.metadata_json = dict(fact_metadata or {})
        self.db.commit()
        self.db.refresh(fact)

        chunk = self.memory_repo.create_chunks(
            project_id=self.project.id,
            chunks=[
                {
                    "source_type": "memory_fact",
                    "source_id": fact.id,
                    "chunk_type": "canonical_fact",
                    "text": fact.canonical_text,
                    "metadata_json": {
                        "dedup_strategy": "exact_then_semantic",
                        "canonical_fact_id": str(fact.id),
                    },
                    "embedding": embedding,
                    "embedding_status": "done",
                }
            ],
        )[0]
        return fact, chunk, embedding

    def test_suppressed_then_remention_revives_visibility(self) -> None:
        text = "星港协议第七条规定，深渊引擎不得在民用航道内启用。"
        fact, chunk, embedding = self._seed_fact_with_chunk(
            text=text,
            days_old=6,
            mention_count=1,
        )

        before = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=embedding,
            top_k=5,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertEqual(len(before), 1)

        run_result = self.forgetting_service.run_once(
            project_id=self.project.id,
            dry_run=False,
            allow_hard_delete=False,
        )
        self.assertGreaterEqual(run_result.suppressed, 1)

        fact_after = self.memory_fact_repo.get(fact.id)
        chunk_after = self.memory_repo.get(chunk.id)
        self.assertEqual((fact_after.metadata_json or {}).get("forgetting_stage"), "suppressed")
        self.assertEqual((chunk_after.metadata_json or {}).get("forgetting_stage"), "suppressed")

        hidden = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=embedding,
            top_k=5,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertEqual(hidden, [])

        rows = self.ingestion_service.ingest_text(
            project_id=self.project.id,
            text=text,
            source_type="dialogue",
            source_id=uuid4(),
            chunk_type="utterance",
            metadata_json={"case": "revive"},
        )
        self.assertEqual(rows, [])

        revived = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=embedding,
            top_k=5,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertGreaterEqual(len(revived), 1)

        fact_revived = self.memory_fact_repo.get(fact.id)
        chunk_revived = self.memory_repo.get(chunk.id)
        self.assertIsNone((fact_revived.metadata_json or {}).get("forgetting_stage"))
        self.assertIsNone((chunk_revived.metadata_json or {}).get("forgetting_stage"))

    def test_pin_memory_is_protected(self) -> None:
        text = "主角的第一条誓言：不与深渊引擎的制造方合作。"
        fact, chunk, embedding = self._seed_fact_with_chunk(
            text=text,
            days_old=30,
            mention_count=1,
            fact_metadata={"pin_memory": True},
        )
        fact_metadata = dict(fact.metadata_json or {})
        fact_metadata.update(
            {
                "pin_memory": True,
                "forgetting_stage": "suppressed",
                "forgetting_reason": "manual_test",
                "forgetting_score": 9.9,
            }
        )
        fact.metadata_json = fact_metadata
        chunk_metadata = dict(chunk.metadata_json or {})
        chunk_metadata.update(
            {
                "forgetting_stage": "suppressed",
                "forgetting_reason": "manual_test",
                "forgetting_score": 9.9,
            }
        )
        self.memory_repo.update_chunk(chunk.id, metadata_json=chunk_metadata)
        self.db.commit()
        self.db.refresh(fact)

        run_result = self.forgetting_service.run_once(
            project_id=self.project.id,
            dry_run=False,
            allow_hard_delete=True,
        )
        decision = next(
            (item for item in run_result.decisions if item.fact_id == str(fact.id)),
            None,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "protected")

        fact_after = self.memory_fact_repo.get(fact.id)
        self.assertTrue(bool((fact_after.metadata_json or {}).get("pin_memory")))
        self.assertIsNone((fact_after.metadata_json or {}).get("forgetting_stage"))
        chunk_after = self.memory_repo.get(chunk.id)
        self.assertIsNone((chunk_after.metadata_json or {}).get("forgetting_stage"))

        still_visible = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=embedding,
            top_k=5,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertGreaterEqual(len(still_visible), 1)

    def test_hard_delete_removes_old_low_signal_fact(self) -> None:
        text = "旧时代仓库盘点：第九码头损耗账册。"
        fact, _, embedding = self._seed_fact_with_chunk(
            text=text,
            days_old=60,
            mention_count=1,
        )

        run_result = self.forgetting_service.run_once(
            project_id=self.project.id,
            dry_run=False,
            allow_hard_delete=True,
        )
        self.assertGreaterEqual(run_result.deleted, 1)

        self.assertIsNone(self.memory_fact_repo.get(fact.id))
        linked = self.memory_repo.list_by_source(
            project_id=self.project.id,
            source_type="memory_fact",
            source_id=fact.id,
            limit=10,
        )
        self.assertEqual(linked, [])

        deleted_query = self.memory_repo.similarity_search(
            project_id=self.project.id,
            query_embedding=embedding,
            top_k=5,
            source_type="memory_fact",
            chunk_type="canonical_fact",
        )
        self.assertEqual(deleted_query, [])


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
