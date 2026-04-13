"""MemorySearchService 与 RetrievalPipeline 契约测试（无数据库依赖）。

运行：
    python scripts/test_retrieval_pipeline_contract.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.llm.embeddings.base import EmbeddingProvider
from packages.memory.long_term.search.search_service import MemorySearchService


class _FakeEmbeddingProvider(EmbeddingProvider):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        # query 包含 "严格" 时返回更远向量，触发回退路径
        if "严格" in text:
            return [0.9, 0.9, 0.9]
        return [0.1, 0.2, 0.3]


class _FakeMemoryRepo:
    def similarity_search(self, **kwargs):
        max_distance = kwargs.get("max_distance")
        if max_distance is not None and max_distance < 0.2:
            return []
        return [
            {
                "id": "1",
                "project_id": kwargs.get("project_id"),
                "source_type": "memory_fact",
                "source_id": "f1",
                "chunk_type": "canonical_fact",
                "text": "违者将被剥夺航道准入资格。",
                "metadata_json": {"source_timestamp": "2026-04-01T00:00:00Z"},
                "embedding_status": "done",
                "created_at": None,
                "updated_at": None,
                "source_timestamp": "2026-04-01T00:00:00Z",
                "distance": 0.12,
            }
        ]

    def keyword_search(self, **kwargs):
        query = str(kwargs.get("query_text") or "")
        if "处罚" in query or "后果" in query:
            return [
                {
                    "id": "1",
                    "project_id": kwargs.get("project_id"),
                    "source_type": "memory_fact",
                    "source_id": "f1",
                    "chunk_type": "canonical_fact",
                    "text": "违者将被剥夺航道准入资格。",
                    "metadata_json": {"source_timestamp": "2026-04-01T00:00:00Z"},
                    "embedding_status": "done",
                    "created_at": None,
                    "updated_at": None,
                    "source_timestamp": "2026-04-01T00:00:00Z",
                    "keyword_score": 0.8,
                }
            ]
        return []


class TestRetrievalPipelineContract(unittest.TestCase):
    def setUp(self) -> None:
        self.search = MemorySearchService(
            embedding_provider=_FakeEmbeddingProvider(),
            memory_repo=_FakeMemoryRepo(),
        )

    def test_fallback_can_recover_results(self) -> None:
        rows = self.search.search_with_scores(
            project_id="p1",
            query="严格模式：违反协议会有什么处罚",
            top_k=3,
            max_distance=0.08,
            fallback_max_distance=0.3,
            enable_query_rewrite=True,
            enable_hybrid=True,
        )
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("剥夺航道准入资格", rows[0]["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
