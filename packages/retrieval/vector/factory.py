from __future__ import annotations

from packages.retrieval.config import RetrievalRuntimeConfig
from packages.retrieval.errors import RetrievalConfigError
from packages.retrieval.vector.base import VectorStore
from packages.retrieval.vector.faiss_store import FaissStore
from packages.retrieval.vector.milvus_store import MilvusStore
from packages.retrieval.vector.pgvector_store import PgVectorStore
from packages.retrieval.vector.qdrant_store import QdrantStore
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository


def create_vector_store(
    *,
    memory_repo: MemoryChunkRepository,
    runtime_config: RetrievalRuntimeConfig,
    default_project_id=None,
) -> VectorStore:
    backend = runtime_config.vector.backend.strip().lower()
    if backend == "pgvector":
        return PgVectorStore(memory_repo=memory_repo, default_project_id=default_project_id)
    if backend == "faiss":
        return FaissStore(
            dimension=runtime_config.vector.dimension,
            metric=runtime_config.vector.faiss_metric,
        )
    if backend == "milvus":
        return MilvusStore(
            uri=runtime_config.vector.milvus_uri,
            collection_name=runtime_config.vector.milvus_collection,
            dimension=runtime_config.vector.dimension,
        )
    if backend == "qdrant":
        return QdrantStore(
            url=runtime_config.vector.qdrant_url,
            collection_name=runtime_config.vector.qdrant_collection,
            dimension=runtime_config.vector.dimension,
        )
    raise RetrievalConfigError(f"不支持的向量后端: {runtime_config.vector.backend}")

