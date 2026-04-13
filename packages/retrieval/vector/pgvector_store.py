from __future__ import annotations

from typing import Any

from packages.retrieval.errors import RetrievalInputError
from packages.retrieval.vector.base import VectorStore
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository


class PgVectorStore(VectorStore):
    """对 MemoryChunkRepository 的向量检索适配。"""

    def __init__(
        self,
        memory_repo: MemoryChunkRepository,
        *,
        default_project_id=None,
    ) -> None:
        self.memory_repo = memory_repo
        self.default_project_id = default_project_id

    def upsert(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return

        for item in items:
            chunk_id = item.get("id")
            project_id = item.get("project_id", self.default_project_id)
            if project_id is None:
                raise RetrievalInputError("PgVectorStore.upsert 缺少 project_id")

            payload = {
                "source_type": item.get("source_type"),
                "source_id": item.get("source_id"),
                "chunk_type": item.get("chunk_type"),
                "text": item.get("text") or item.get("chunk_text"),
                "summary_text": item.get("summary_text"),
                "metadata_json": item.get("metadata_json") or {},
                "embedding": item.get("embedding"),
                "embedding_status": item.get(
                    "embedding_status",
                    "done" if item.get("embedding") is not None else "pending",
                ),
            }

            existing = self.memory_repo.get(chunk_id) if chunk_id is not None else None
            if existing is not None:
                self.memory_repo.update_chunk(chunk_id, **payload)
                continue

            self.memory_repo.create_chunks(project_id=project_id, chunks=[payload])

    def delete(self, ids: list[str]) -> int:
        deleted = 0
        for chunk_id in ids:
            if self.memory_repo.delete(chunk_id):
                deleted += 1
        return deleted

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[dict]:
        if top_k <= 0:
            return []
        filters = filters or {}
        project_id = filters.get("project_id", self.default_project_id)
        if project_id is None:
            raise RetrievalInputError("PgVectorStore.search 缺少 project_id")

        return self.memory_repo.similarity_search(
            project_id=project_id,
            query_embedding=query_vector,
            top_k=top_k,
            source_type=filters.get("source_type"),
            chunk_type=filters.get("chunk_type"),
            max_distance=filters.get("max_distance"),
            source_timestamp_gte=filters.get("source_timestamp_gte"),
            source_timestamp_lte=filters.get("source_timestamp_lte"),
            sort_by=filters.get("sort_by", "distance"),
        )
