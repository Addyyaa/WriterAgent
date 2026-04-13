from __future__ import annotations

from packages.llm.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from packages.retrieval.embeddings.base import RetrievalEmbeddingProvider


class OpenAIEmbeddingProvider(RetrievalEmbeddingProvider):
    def __init__(self, *, api_key: str, model: str, base_url: str | None = None) -> None:
        self.provider = OpenAICompatibleEmbeddingProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.provider.embed_query(text)
