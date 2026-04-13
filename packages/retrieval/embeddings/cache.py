from __future__ import annotations

import hashlib
from dataclasses import dataclass

from packages.retrieval.embeddings.base import RetrievalEmbeddingProvider


@dataclass(frozen=True)
class EmbeddingCacheStats:
    hits: int
    misses: int


class CachedEmbeddingProvider(RetrievalEmbeddingProvider):
    def __init__(self, provider: RetrievalEmbeddingProvider) -> None:
        self.provider = provider
        self._cache: dict[str, list[float]] = {}
        self._hits = 0
        self._misses = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_single(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_single(text)

    def stats(self) -> EmbeddingCacheStats:
        return EmbeddingCacheStats(hits=self._hits, misses=self._misses)

    def _embed_single(self, text: str) -> list[float]:
        key = self._hash(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._hits += 1
            return cached
        self._misses += 1
        vec = self.provider.embed_query(text)
        self._cache[key] = vec
        return vec

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
