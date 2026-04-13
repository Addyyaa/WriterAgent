from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from packages.retrieval.errors import (
    RetrievalDataError,
    RetrievalTimeoutError,
    RetrieverUnavailableError,
)
from packages.retrieval.rerank.base import Reranker
from packages.retrieval.types import ScoredDoc


@dataclass(frozen=True)
class ExternalCrossEncoderConfig:
    """
    外部 Cross-Encoder 重排服务配置。

    协议：
    - POST /rerank
    - Request: {api_key, model, query, candidates[{id,text}], top_k}
    - Response: {data: [{id, score, rank}]}
    """

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 8.0


class ExternalCrossEncoderReranker(Reranker):
    """通过外部 HTTP 服务执行 Cross-Encoder 重排。"""

    def __init__(self, config: ExternalCrossEncoderConfig) -> None:
        self.config = config

    def rerank(
        self,
        *,
        query: str,
        candidates: list[ScoredDoc],
        top_k: int,
        sort_by: str,
    ) -> list[ScoredDoc]:
        del sort_by
        if top_k <= 0 or not candidates:
            return []

        payload = {
            "api_key": self.config.api_key,
            "model": self.config.model,
            "query": query,
            "top_k": min(top_k, len(candidates)),
            "candidates": [{"id": str(item.id), "text": item.text} for item in candidates],
        }
        body = self._post_rerank(payload)
        rows = self._parse_rows(body)
        if not rows:
            raise RetrievalDataError("cross-encoder 返回空 data")

        by_id: dict[str, tuple[float, int | None]] = {}
        for item in rows:
            row_id = str(item.get("id") or "")
            if not row_id:
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            rank: int | None = None
            raw_rank = item.get("rank")
            if raw_rank is not None:
                try:
                    rank = int(raw_rank)
                except (TypeError, ValueError):
                    rank = None
            by_id[row_id] = (score, rank)

        enriched: list[ScoredDoc] = []
        for idx, doc in enumerate(candidates):
            row_id = str(doc.id)
            score, rank = by_id.get(row_id, (0.0, None))
            item = ScoredDoc(**doc.__dict__)
            item.rerank_score = score
            if rank is None:
                # 未返回 rank 时，使用原顺序作为稳定后备序。
                rank = 10**9 + idx
            # 借用 metadata_json 传递稳定排序锚点，避免引入额外结构体。
            item.metadata_json = dict(item.metadata_json)
            item.metadata_json["_cross_encoder_rank"] = rank
            enriched.append(item)

        enriched.sort(
            key=lambda x: (
                int((x.metadata_json or {}).get("_cross_encoder_rank", 10**9)),
                -(x.rerank_score or 0.0),
            )
        )

        for item in enriched:
            if "_cross_encoder_rank" in item.metadata_json:
                del item.metadata_json["_cross_encoder_rank"]

        return enriched[:top_k]

    def _post_rerank(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.base_url.strip():
            raise RetrieverUnavailableError("cross-encoder base_url 未配置")

        url = f"{self.config.base_url.rstrip('/')}/rerank"
        try:
            resp = httpx.post(url, json=payload, timeout=self.config.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise RetrievalTimeoutError(f"cross-encoder 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetrieverUnavailableError(f"cross-encoder 请求失败: {exc}") from exc

        try:
            body = resp.json()
        except Exception as exc:
            raise RetrievalDataError(
                f"cross-encoder 返回非 JSON，status={resp.status_code}"
            ) from exc

        if resp.status_code >= 400:
            detail = body.get("error") if isinstance(body, dict) else body
            raise RetrieverUnavailableError(
                f"cross-encoder 返回错误 status={resp.status_code}: {detail}"
            )

        return body if isinstance(body, dict) else {}

    @staticmethod
    def _parse_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
        data = body.get("data")
        if not isinstance(data, list):
            raise RetrievalDataError("cross-encoder 响应缺少 data 列表")
        return [item for item in data if isinstance(item, dict)]


class CrossEncoderReranker(ExternalCrossEncoderReranker):
    """兼容旧命名。"""

