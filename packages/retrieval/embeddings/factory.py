from __future__ import annotations

from packages.retrieval.embeddings.base import RetrievalEmbeddingProvider
from packages.retrieval.embeddings.cache import CachedEmbeddingProvider
from packages.retrieval.embeddings.local_api import LocalAPIEmbeddingProvider
from packages.retrieval.embeddings.openai_compatible import OpenAIEmbeddingProvider


def create_embedding_provider(kind: str, *, use_cache: bool = False, **kwargs) -> RetrievalEmbeddingProvider:
    normalized = (kind or "local_api").strip().lower()
    if normalized in {"local_api", "local", "service"}:
        provider: RetrievalEmbeddingProvider = LocalAPIEmbeddingProvider(**kwargs)
    elif normalized in {"openai", "openai_compatible"}:
        provider = OpenAIEmbeddingProvider(**kwargs)
    else:
        raise ValueError(f"未知 embedding provider 类型: {kind}")

    if use_cache:
        return CachedEmbeddingProvider(provider)
    return provider
