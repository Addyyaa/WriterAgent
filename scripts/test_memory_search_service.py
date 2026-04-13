"""
MemorySearchService 集成测试（高样本版本）。

运行（需在仓库根目录，且数据库可连）::

    python scripts/test_memory_search_service.py

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.memory.long_term.search.search_service import MemorySearchService
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository
from packages.storage.postgres.repositories.project_repository import ProjectRepository
from scripts._db_engine import create_engine_with_driver_fallback

_DEFAULT_DATABASE_URL = "postgresql+psycopg2://addy:sf123123@localhost:5432/writer_agent_db"
_DEFAULT_EMBEDDING_SERVICE_BASE_URL = "http://127.0.0.1:8000"
_DEFAULT_EMBEDDING_API_KEY = "dummy-key"
_DEFAULT_EMBEDDING_MODEL = "/Users/shenfeng/Project/embeddingsModel/bge-m3"


def _build_large_corpus() -> list[dict]:
    rows: list[dict] = []
    base = datetime.now(tz=timezone.utc).replace(microsecond=0)

    for i in range(16):
        source_timestamp = (base - timedelta(days=i)).isoformat().replace("+00:00", "Z")
        rows.append(
            {
                "source_type": "world_entry",
                "chunk_type": "summary",
                "text": (
                    f"联邦档案第{i}号：星港协议第七条明确禁用深渊引擎，"
                    "违者将被剥夺航道准入资格。"
                ),
                "metadata_json": {
                    "label": "policy_relevant",
                    "group": "world",
                    "source_timestamp": source_timestamp,
                },
            }
        )

    for i in range(10):
        source_timestamp = (
            base - timedelta(days=i, hours=6)
        ).isoformat().replace("+00:00", "Z")
        rows.append(
            {
                "source_type": "chapter",
                "chunk_type": "paragraph",
                "text": (
                    f"第{i+1}章纪要：主角在北港钟楼下破译星港协议，"
                    "确认第七条与深渊引擎事故有关。"
                ),
                "metadata_json": {
                    "label": "policy_relevant",
                    "group": "chapter",
                    "source_timestamp": source_timestamp,
                },
            }
        )

    for i in range(24):
        rows.append(
            {
                "source_type": "chapter" if i % 2 == 0 else "world_entry",
                "chunk_type": "note" if i % 3 == 0 else "paragraph",
                "text": (
                    f"无关样本{i}: 集市物价、天气记录、粮仓维护、"
                    "修表匠访谈与港口税单整理。"
                ),
                "metadata_json": {
                    "label": "noise",
                    "group": "noise",
                    "source_timestamp": (
                        base - timedelta(days=60 + i)
                    ).isoformat().replace("+00:00", "Z"),
                },
            }
        )

    return rows


class TestMemorySearchServiceIntegration(unittest.TestCase):
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

        self.embedding_provider = EmbeddingServiceAPIProvider(
            api_key=self.embedding_api_key,
            model=self.embedding_model,
            service_base_url=self.embedding_base_url,
            forward_base_url=self.embedding_forward_base_url,
            normalize_embeddings=True,
        )
        self.search_service = MemorySearchService(
            embedding_provider=self.embedding_provider,
            memory_repo=self.memory_repo,
        )

        self.project = self.project_repo.create(
            title="Memory Search High-Sample Test",
            genre="科幻",
            premise="验证高样本检索质量与过滤准确性。",
        )
        self.empty_project = self.project_repo.create(
            title="Memory Search Empty Project",
            genre="测试",
            premise="用于验证项目隔离。",
        )

        corpus = _build_large_corpus()
        embeddings = self.embedding_provider.embed_texts([item["text"] for item in corpus])

        rows: list[dict] = []
        for item, emb in zip(corpus, embeddings, strict=True):
            rows.append(
                {
                    "source_type": item["source_type"],
                    "source_id": uuid4(),
                    "chunk_type": item["chunk_type"],
                    "text": item["text"],
                    "metadata_json": item["metadata_json"],
                    "embedding": emb,
                    "embedding_status": "done",
                }
            )

        self.memory_repo.create_chunks(project_id=self.project.id, chunks=rows)

    def test_retrieval_quality_with_large_corpus(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="请解释星港协议第七条为什么禁用深渊引擎",
            top_k=12,
        )
        self.assertEqual(len(results), 12)

        relevant = [
            r
            for r in results
            if (r.get("metadata_json") or {}).get("label") == "policy_relevant"
        ]
        self.assertGreaterEqual(
            len(relevant),
            8,
            msg=f"top_k 相关占比偏低，relevant={len(relevant)}, total={len(results)}",
        )

    def test_source_type_filter_precision(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="联邦档案中的星港协议条款",
            top_k=10,
            source_type="world_entry",
        )
        self.assertEqual(len(results), 10)
        for item in results:
            self.assertEqual(item["source_type"], "world_entry")

    def test_chunk_type_filter_precision(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="深渊引擎相关规则",
            top_k=8,
            chunk_type="summary",
        )
        self.assertEqual(len(results), 8)
        for item in results:
            self.assertEqual(item["chunk_type"], "summary")

    def test_project_isolation(self) -> None:
        empty_results = self.search_service.search_texts(
            project_id=self.empty_project.id,
            query="星港协议",
            top_k=5,
        )
        self.assertEqual(empty_results, [])

    def test_no_match_returns_empty_when_threshold_applied(self) -> None:
        no_match = self.search_service.search_texts(
            project_id=self.project.id,
            query="量子菜谱和宠物美容大赛奖杯",
            top_k=10,
            max_distance=0.05,
        )
        self.assertEqual(no_match, [])

    def test_consequence_question_can_hit_with_adaptive_fallback(self) -> None:
        results = self.search_service.search_texts(
            project_id=self.project.id,
            query="违背协议的处罚有哪些",
            top_k=3,
            max_distance=0.08,
            fallback_max_distance=0.35,
            enable_query_rewrite=True,
        )
        print("=========>", results)
        self.assertGreater(len(results), 0)
        joined = " ".join(results)
        self.assertIn("剥夺航道准入资格", joined)

    def test_recent_sort_prefers_latest_source_timestamp(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="星港协议第七条相关事件",
            top_k=10,
            sort_by="recent",
        )
        self.assertGreater(len(results), 0)

        ts_values = [item.get("source_timestamp") for item in results]
        self.assertTrue(all(ts is not None for ts in ts_values))

        normalized = [
            datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            for ts in ts_values
        ]
        self.assertEqual(normalized, sorted(normalized, reverse=True))

    def test_recent_within_days_filters_old_facts(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="星港协议第七条相关事件",
            top_k=20,
            sort_by="recent",
            recent_within_days=2,
        )
        self.assertGreater(len(results), 0)

        # 允许秒级边界抖动，避免执行时钟与写入时钟在边界上造成偶发失败。
        floor = (datetime.now(tz=timezone.utc) - timedelta(days=2, seconds=1)).replace(microsecond=0)
        for item in results:
            ts = item.get("source_timestamp")
            self.assertIsNotNone(ts)
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            self.assertGreaterEqual(dt, floor)

    def test_hybrid_search_contains_hybrid_score(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="星港协议 航道准入资格",
            top_k=10,
            sort_by="relevance",
            enable_hybrid=True,
            enable_rerank=False,
        )
        self.assertGreater(len(results), 0)
        self.assertTrue(all("hybrid_score" in item for item in results))

    def test_rerank_contains_rerank_score(self) -> None:
        results = self.search_service.search_with_scores(
            project_id=self.project.id,
            query="星港协议第七条禁用深渊引擎",
            top_k=10,
            sort_by="relevance_then_recent",
            enable_hybrid=True,
            enable_rerank=True,
        )
        self.assertGreater(len(results), 0)
        self.assertTrue(all("rerank_score" in item for item in results))


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
