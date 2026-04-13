from __future__ import annotations

from typing import Any

import httpx

from packages.core.utils import ensure_non_empty_string
from packages.llm.embeddings.base import EmbeddingProvider


class EmbeddingServiceAPIProvider(EmbeddingProvider):
    """
    通过外部 embedding_service API 获取向量。

    适配服务：
    `/Users/shenfeng/Project/embeddingsModel/embedding_service.py`
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        service_base_url: str = "http://127.0.0.1:8000",
        *,
        normalize_embeddings: bool = True,
        forward_base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = ensure_non_empty_string(api_key, field_name="api_key")
        self.model = ensure_non_empty_string(model, field_name="model")
        base_url = ensure_non_empty_string(service_base_url, field_name="service_base_url")
        self.service_base_url = base_url.rstrip("/")
        self.normalize_embeddings = normalize_embeddings
        self.forward_base_url = forward_base_url
        self.timeout = timeout

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not all(isinstance(item, str) for item in texts):
            raise ValueError("texts 必须全部为字符串")

        payload = self._build_payload(texts)
        body = self._post_embeddings(payload)
        return self._extract_embeddings(body, expected_len=len(texts))

    def embed_query(self, text: str) -> list[float]:
        clean_text = ensure_non_empty_string(text, field_name="text")

        payload = self._build_payload(clean_text)
        body = self._post_embeddings(payload)
        vectors = self._extract_embeddings(body, expected_len=1)
        return vectors[0]

    def _build_payload(self, input_data: str | list[str]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "model": self.model,
            "input": input_data,
            "normalize_embeddings": self.normalize_embeddings,
        }
        if self.forward_base_url:
            payload["base_url"] = self.forward_base_url
        return payload

    def _post_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.service_base_url}/embed"
        try:
            resp = httpx.post(url, json=payload, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"embedding service 请求失败: {exc}") from exc

        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(
                f"embedding service 返回非 JSON，status={resp.status_code}"
            ) from exc

        if resp.status_code >= 400:
            msg = body.get("error") if isinstance(body, dict) else None
            raise RuntimeError(
                f"embedding service 返回错误 status={resp.status_code}: {msg or body}"
            )
        return body

    @staticmethod
    def _extract_embeddings(body: dict[str, Any], expected_len: int) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list):
            raise RuntimeError("embedding service 响应缺少 data 列表")

        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict) or "embedding" not in item:
                raise RuntimeError("embedding service 响应格式非法（缺少 embedding）")
            vec = item["embedding"]
            if not isinstance(vec, list):
                raise RuntimeError("embedding 字段必须是数组")
            vectors.append(vec)

        if len(vectors) != expected_len:
            raise RuntimeError(
                f"embedding 数量不匹配，期望 {expected_len}，实际 {len(vectors)}"
            )
        return vectors
