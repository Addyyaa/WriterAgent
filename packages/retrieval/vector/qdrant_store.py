from __future__ import annotations

from typing import Any

from packages.retrieval.errors import RetrievalInputError, RetrieverUnavailableError
from packages.retrieval.vector.base import VectorStore


class QdrantStore(VectorStore):
    """Qdrant 向量存储实现（可选依赖）。"""

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        dimension: int,
    ) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore
            from qdrant_client.http import models  # type: ignore
        except Exception as exc:
            raise RetrieverUnavailableError(
                "QdrantStore 不可用，请安装可选依赖 `qdrant-client`"
            ) from exc

        if dimension <= 0:
            raise RetrievalInputError("dimension 必须大于 0")

        self.dimension = int(dimension)
        self.collection_name = collection_name
        self._models = models
        self._client = QdrantClient(url=url)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            exists = self._client.collection_exists(self.collection_name)
        except Exception as exc:
            raise RetrieverUnavailableError(f"Qdrant 连接失败: {exc}") from exc
        if exists:
            return
        try:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=self._models.VectorParams(
                    size=self.dimension,
                    distance=self._models.Distance.COSINE,
                ),
            )
        except Exception as exc:
            raise RetrieverUnavailableError(
                f"Qdrant collection 初始化失败: {exc}"
            ) from exc

    def upsert(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        points: list[Any] = []
        for item in items:
            row_id = str(item.get("id") or "").strip()
            vector = item.get("embedding")
            if not row_id:
                raise RetrievalInputError("QdrantStore.upsert 缺少 id")
            if not isinstance(vector, list) or len(vector) != self.dimension:
                raise RetrievalInputError(
                    f"QdrantStore.upsert embedding 维度错误，期望 {self.dimension}"
                )
            payload = {
                "id": row_id,
                "text": str(item.get("text") or item.get("chunk_text") or ""),
                "project_id": str(item.get("project_id") or ""),
                "source_type": item.get("source_type"),
                "source_id": str(item.get("source_id")) if item.get("source_id") else None,
                "chunk_type": item.get("chunk_type"),
                "metadata_json": item.get("metadata_json") or {},
            }
            points.append(
                self._models.PointStruct(
                    id=row_id,
                    vector=[float(v) for v in vector],
                    payload=payload,
                )
            )
        try:
            self._client.upsert(collection_name=self.collection_name, points=points, wait=True)
        except Exception as exc:
            raise RetrieverUnavailableError(f"Qdrant upsert 失败: {exc}") from exc

    def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        try:
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=self._models.PointIdsList(points=[str(i) for i in ids]),
                wait=True,
            )
        except Exception as exc:
            raise RetrieverUnavailableError(f"Qdrant delete 失败: {exc}") from exc
        return len(ids)

    def search(
        self,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict | None = None,
    ) -> list[dict]:
        if top_k <= 0:
            return []
        if not isinstance(query_vector, list) or len(query_vector) != self.dimension:
            raise RetrievalInputError(
                f"QdrantStore.search query_vector 维度错误，期望 {self.dimension}"
            )

        filters = filters or {}
        max_distance = filters.get("max_distance")

        query_filter = self._build_filter(filters)
        limit = max(top_k * 5, top_k)
        try:
            hits = self._client.search(
                collection_name=self.collection_name,
                query_vector=[float(v) for v in query_vector],
                query_filter=query_filter,
                with_payload=True,
                limit=limit,
            )
        except Exception as exc:
            raise RetrieverUnavailableError(f"Qdrant search 失败: {exc}") from exc

        out: list[dict] = []
        for hit in hits:
            payload = getattr(hit, "payload", None) or {}
            row = {
                "id": str(payload.get("id") or getattr(hit, "id", "") or ""),
                "text": payload.get("text") or "",
                "project_id": payload.get("project_id"),
                "source_type": payload.get("source_type"),
                "source_id": payload.get("source_id"),
                "chunk_type": payload.get("chunk_type"),
                "metadata_json": payload.get("metadata_json") or {},
            }
            if not row["id"]:
                continue
            if not self._match_filters(row, filters):
                continue

            score = float(getattr(hit, "score", 0.0))
            distance = 1.0 - score
            row["distance"] = distance
            if max_distance is not None and distance > float(max_distance):
                continue
            out.append(row)

        out.sort(key=lambda item: float(item.get("distance", 1.0)))
        return out[:top_k]

    def _build_filter(self, filters: dict[str, Any]):
        conditions: list[Any] = []
        project_id = filters.get("project_id")
        source_type = filters.get("source_type")
        chunk_type = filters.get("chunk_type")

        if project_id is not None:
            conditions.append(
                self._models.FieldCondition(
                    key="project_id",
                    match=self._models.MatchValue(value=str(project_id)),
                )
            )
        if source_type is not None:
            conditions.append(
                self._models.FieldCondition(
                    key="source_type",
                    match=self._models.MatchValue(value=str(source_type)),
                )
            )
        if chunk_type is not None:
            conditions.append(
                self._models.FieldCondition(
                    key="chunk_type",
                    match=self._models.MatchValue(value=str(chunk_type)),
                )
            )
        if not conditions:
            return None
        return self._models.Filter(must=conditions)

    @staticmethod
    def _match_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
        project_id = filters.get("project_id")
        source_type = filters.get("source_type")
        chunk_type = filters.get("chunk_type")
        if project_id is not None and str(row.get("project_id")) != str(project_id):
            return False
        if source_type is not None and row.get("source_type") != source_type:
            return False
        if chunk_type is not None and row.get("chunk_type") != chunk_type:
            return False
        return True

