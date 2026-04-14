from __future__ import annotations

import logging
import os

from packages.llm.embeddings.base import EmbeddingProvider
from packages.llm.embeddings.embedding_service_api import EmbeddingServiceAPIProvider
from packages.llm.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from packages.retrieval.embeddings.factory import create_embedding_provider as create_retrieval_embedding_provider

logger = logging.getLogger("writeragent.embedding.factory")


class _RetrievalEmbeddingAdapter(EmbeddingProvider):
    def __init__(self, provider) -> None:
        self.provider = provider

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.provider.embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.provider.embed_query(text)


def _env(key: str, default: str | None = None) -> str:
    """读取环境变量，仅从 EMBEDDING_* 命名空间取值，不 fallback 到 WRITER_LLM_*。"""
    value = os.environ.get(key, "").strip()
    if value:
        return value
    if default is not None:
        return default
    raise EnvironmentError(
        f"缺少必需的 embedding 环境变量: {key}。"
        "Embedding 与 LLM 是独立服务，不得复用 WRITER_LLM_* 配置。"
    )


def create_embedding_provider_from_env() -> EmbeddingProvider:
    kind = os.environ.get("WRITER_EMBEDDING_PROVIDER", "local_api").strip().lower()
    logger.info("embedding_provider=%s", kind)

    if kind in {"local_api", "embedding_service", "service"}:
        return EmbeddingServiceAPIProvider(
            api_key=_env("EMBEDDING_API_KEY", "dummy-key"),
            model=_env("EMBEDDING_MODEL", "bge-m3"),
            service_base_url=_env("EMBEDDING_SERVICE_BASE_URL", "http://127.0.0.1:8000"),
            normalize_embeddings=True,
            forward_base_url=os.environ.get("EMBEDDING_FORWARD_BASE_URL") or None,
            timeout=float(_env("EMBEDDING_TIMEOUT", "120")),
        )

    if kind in {"openai", "openai_compatible"}:
        return OpenAICompatibleEmbeddingProvider(
            api_key=_env("EMBEDDING_OPENAI_API_KEY"),
            model=_env("EMBEDDING_OPENAI_MODEL", "text-embedding-3-small"),
            base_url=_env("EMBEDDING_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    if kind in {"retrieval_local", "retrieval_openai"}:
        backend = "local_api" if kind == "retrieval_local" else "openai"
        provider = create_retrieval_embedding_provider(
            backend,
            api_key=_env("EMBEDDING_API_KEY", "dummy-key"),
            model=_env("EMBEDDING_MODEL", "bge-m3"),
            service_base_url=_env("EMBEDDING_SERVICE_BASE_URL", "http://127.0.0.1:8000"),
            base_url=_env("EMBEDDING_OPENAI_BASE_URL", "https://api.openai.com/v1"),
            use_cache=os.environ.get("WRITER_RETRIEVAL_EMBED_USE_CACHE", "0") in {"1", "true", "yes"},
        )
        return _RetrievalEmbeddingAdapter(provider)

    raise ValueError(f"未知 WRITER_EMBEDDING_PROVIDER: {kind}")
