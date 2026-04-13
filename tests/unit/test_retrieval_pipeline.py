from __future__ import annotations

import unittest

from packages.retrieval.hybrid.rrf_fusion import RRFFusionStrategy
from packages.retrieval.pipeline import RetrievalPipeline
from packages.retrieval.rerank.rule_based import RuleBasedReranker
from packages.retrieval.types import FilterExpr, RetrievalOptions, ScoredDoc


class TestRetrievalPipeline(unittest.TestCase):
    def test_pipeline_run(self) -> None:
        def vector_retriever(query: str, filters: FilterExpr, options: RetrievalOptions) -> list[ScoredDoc]:
            del filters, options
            return [
                ScoredDoc(id="1", text=f"v:{query}", distance=0.1, source_type="memory_fact"),
                ScoredDoc(id="2", text="vector-only", distance=0.2, source_type="chapter"),
            ]

        def keyword_retriever(query: str, filters: FilterExpr, options: RetrievalOptions) -> list[ScoredDoc]:
            del filters, options
            return [
                ScoredDoc(id="1", text=f"k:{query}", keyword_score=0.9, source_type="memory_fact"),
                ScoredDoc(id="3", text="keyword-only", keyword_score=0.6, source_type="world_entry"),
            ]

        pipeline = RetrievalPipeline(
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            query_rewriter=lambda q: [q, q + " rewrite"],
            fusion_strategy=RRFFusionStrategy(),
            reranker=RuleBasedReranker(),
        )

        rows, trace = pipeline.run_with_trace(
            query="hello",
            filters=FilterExpr(project_id="p1"),
            options=RetrievalOptions(top_k=3, enable_query_rewrite=True, enable_hybrid=True, enable_rerank=True),
        )

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(trace.query_variants, 2)
        self.assertTrue(any(item.hybrid_score is not None for item in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
