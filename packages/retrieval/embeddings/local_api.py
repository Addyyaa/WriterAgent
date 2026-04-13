from __future__ import annotations

from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.retrieval.embeddings.base import RetrievalEmbeddingProvider


class LocalAPIEmbeddingProvider(RetrievalEmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        service_base_url: str,
        normalize_embeddings: bool = True,
        forward_base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.provider = EmbeddingServiceAPIProvider(
            api_key=api_key,
            model=model,
            service_base_url=service_base_url,
            normalize_embeddings=normalize_embeddings,
            forward_base_url=forward_base_url,
            timeout=timeout,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.provider.embed_query(text)
