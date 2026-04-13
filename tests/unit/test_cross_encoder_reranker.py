from __future__ import annotations

import unittest
from unittest import mock

from packages.retrieval.errors import RetrieverUnavailableError
from packages.retrieval.rerank.cross_encoder import (
    ExternalCrossEncoderConfig,
    ExternalCrossEncoderReranker,
)
from packages.retrieval.types import ScoredDoc


class _FakeResp:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class TestExternalCrossEncoderReranker(unittest.TestCase):
    def setUp(self) -> None:
        self.reranker = ExternalCrossEncoderReranker(
            ExternalCrossEncoderConfig(
                base_url="http://127.0.0.1:9000",
                api_key="k",
                model="m",
                timeout_seconds=3.0,
            )
        )

    @mock.patch("packages.retrieval.rerank.cross_encoder.httpx.post")
    def test_rerank_success(self, mock_post) -> None:
        mock_post.return_value = _FakeResp(
            200,
            {
                "data": [
                    {"id": "2", "score": 0.9, "rank": 1},
                    {"id": "1", "score": 0.5, "rank": 2},
                ]
            },
        )

        rows = self.reranker.rerank(
            query="q",
            candidates=[
                ScoredDoc(id="1", text="a", distance=0.2),
                ScoredDoc(id="2", text="b", distance=0.1),
            ],
            top_k=2,
            sort_by="distance",
        )
        self.assertEqual([item.id for item in rows], ["2", "1"])
        self.assertAlmostEqual(rows[0].rerank_score or 0.0, 0.9, places=6)

    @mock.patch("packages.retrieval.rerank.cross_encoder.httpx.post")
    def test_rerank_http_error(self, mock_post) -> None:
        mock_post.return_value = _FakeResp(500, {"error": "boom"})
        with self.assertRaises(RetrieverUnavailableError):
            self.reranker.rerank(
                query="q",
                candidates=[ScoredDoc(id="1", text="a")],
                top_k=1,
                sort_by="distance",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)

