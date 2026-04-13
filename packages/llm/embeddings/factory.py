from __future__ import annotations

import os

from packages.llm.embeddings.base import EmbeddingProvider
from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.llm.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from packages.retrieval.embeddings.factory import create_embedding_provider as create_retrieval_embedding_provider


class _RetrievalEmbeddingAdapter(EmbeddingProvider):
    def __init__(self, provider) -> None:
        self.provider = provider

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.provider.embed_query(text)


def create_embedding_provider_from_env() -> EmbeddingProvider:
    kind = os.environ.get("WRITER_EMBEDDING_PROVIDER", "local_api").strip().lower()
    if kind in {"local_api", "embedding_service", "service"}:
        return EmbeddingServiceAPIProvider(
            api_key=os.environ.get("EMBEDDING_API_KEY", "dummy-key"),
            model=os.environ.get("EMBEDDING_MODEL", "/Users/shenfeng/Project/embeddingsModel/bge-m3"),
            service_base_url=os.environ.get("EMBEDDING_SERVICE_BASE_URL", "http://127.0.0.1:8000"),
            normalize_embeddings=True,
            forward_base_url=os.environ.get("EMBEDDING_FORWARD_BASE_URL") or None,
            timeout=float(os.environ.get("EMBEDDING_TIMEOUT", "120")),
        )

    if kind in {"openai", "openai_compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            api_key=os.environ.get("EMBEDDING_OPENAI_API_KEY", os.environ.get("WRITER_LLM_API_KEY", "dummy-key")),
            model=os.environ.get("EMBEDDING_OPENAI_MODEL", "text-embedding-3-small"),
            base_url=os.environ.get("EMBEDDING_OPENAI_BASE_URL", os.environ.get("WRITER_LLM_BASE_URL", "https://api.openai.com/v1")),
        )

    if kind in {"retrieval_local", "retrieval_openai"}:
        backend = "local_api" if kind == "retrieval_local" else "openai"
        provider = create_retrieval_embedding_provider(
            backend,
            api_key=os.environ.get("EMBEDDING_API_KEY", "dummy-key"),
            model=os.environ.get("EMBEDDING_MODEL", "/Users/shenfeng/Project/embeddingsModel/bge-m3"),
            service_base_url=os.environ.get("EMBEDDING_SERVICE_BASE_URL", "http://127.0.0.1:8000"),
            base_url=os.environ.get("EMBEDDING_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            use_cache=os.environ.get("WRITER_RETRIEVAL_EMBED_USE_CACHE", "0") in {"1", "true", "yes"},
        )
        return _RetrievalEmbeddingAdapter(provider)

    raise ValueError(f"未知 WRITER_EMBEDDING_PROVIDER: {kind}")
