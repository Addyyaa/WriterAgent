from __future__ import annotations

from typing import Any

from packages.retrieval.errors import RetrievalInputError, RetrieverUnavailableError
from packages.retrieval.vector.base import VectorStore


class MilvusStore(VectorStore):
    """
    Milvus 向量存储实现（可选依赖）。

    说明：
    - 依赖 `pymilvus`。
    - 过滤语义统一由本地二次过滤兜底，确保与其他后端一致。
    """

    def __init__(
        self,
        *,
        uri: str,
        collection_name: str,
        dimension: int,
    ) -> None:
        try:
            from pymilvus import MilvusClient  # type: ignore
        except Exception as exc:
            raise RetrieverUnavailableError(
                "MilvusStore 不可用，请安装可选依赖 `pymilvus`"
            ) from exc

        if dimension <= 0:
            raise RetrievalInputError("dimension 必须大于 0")

        self.uri = uri
        self.collection_name = collection_name
        self.dimension = int(dimension)
        self._client = MilvusClient(uri=uri)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        try:
            exists = bool(self._client.has_collection(self.collection_name))
        except Exception:
            exists = False
        if exists:
            return
        try:
            self._client.create_collection(
                collection_name=self.collection_name,
                dimension=self.dimension,
                metric_type="COSINE",
                consistency_level="Strong",
            )
        except Exception as exc:
            raise RetrieverUnavailableError(
                f"Milvus collection 初始化失败: {exc}"
            ) from exc

    def upsert(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        rows: list[dict[str, Any]] = []
        for item in items:
            row_id = str(item.get("id") or "").strip()
            vector = item.get("embedding")
            if not row_id:
                raise RetrievalInputError("MilvusStore.upsert 缺少 id")
            if not isinstance(vector, list) or len(vector) != self.dimension:
                raise RetrievalInputError(
                    f"MilvusStore.upsert embedding 维度错误，期望 {self.dimension}"
                )

            metadata = item.get("metadata_json") or {}
            rows.append(
                {
                    "id": row_id,
                    "vector": [float(v) for v in vector],
                    "text": str(item.get("text") or item.get("chunk_text") or ""),
                    "project_id": str(item.get("project_id") or ""),
                    "source_type": item.get("source_type"),
                    "source_id": str(item.get("source_id")) if item.get("source_id") else None,
                    "chunk_type": item.get("chunk_type"),
                    "metadata_json": metadata,
                    "source_timestamp": metadata.get("source_timestamp"),
                }
            )
        try:
            self._client.upsert(collection_name=self.collection_name, data=rows)
        except Exception as exc:
            raise RetrieverUnavailableError(f"Milvus upsert 失败: {exc}") from exc

    def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        try:
            result = self._client.delete(collection_name=self.collection_name, ids=[str(i) for i in ids])
        except Exception as exc:
            raise RetrieverUnavailableError(f"Milvus delete 失败: {exc}") from exc

        if isinstance(result, dict):
            raw = result.get("delete_count") or result.get("deleted")
            if raw is not None:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    pass
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
                f"MilvusStore.search query_vector 维度错误，期望 {self.dimension}"
            )

        filters = filters or {}
        max_distance = filters.get("max_distance")
        search_k = max(top_k * 5, top_k)

        expr = self._build_expr(filters)
        try:
            result = self._client.search(
                collection_name=self.collection_name,
                data=[[float(v) for v in query_vector]],
                limit=search_k,
                filter=expr or "",
                output_fields=[
                    "text",
                    "project_id",
                    "source_type",
                    "source_id",
                    "chunk_type",
                    "metadata_json",
                    "source_timestamp",
                ],
            )
        except Exception as exc:
            raise RetrieverUnavailableError(f"Milvus search 失败: {exc}") from exc

        hits = result[0] if isinstance(result, list) and result else []
        out: list[dict] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            entity = hit.get("entity") if isinstance(hit.get("entity"), dict) else {}
            row = {
                "id": str(hit.get("id") or entity.get("id") or ""),
                "text": entity.get("text") or "",
                "project_id": entity.get("project_id") or None,
                "source_type": entity.get("source_type"),
                "source_id": entity.get("source_id"),
                "chunk_type": entity.get("chunk_type"),
                "metadata_json": entity.get("metadata_json") or {},
                "source_timestamp": entity.get("source_timestamp"),
            }
            if not row["id"]:
                continue
            if not self._match_filters(row, filters):
                continue

            if hit.get("distance") is not None:
                distance = float(hit["distance"])
            else:
                score = float(hit.get("score", 0.0))
                distance = 1.0 - score
            row["distance"] = distance

            if max_distance is not None and distance > float(max_distance):
                continue
            out.append(row)

        out.sort(key=lambda item: float(item.get("distance", 1.0)))
        return out[:top_k]

    @staticmethod
    def _build_expr(filters: dict[str, Any]) -> str:
        parts: list[str] = []
        project_id = filters.get("project_id")
        source_type = filters.get("source_type")
        chunk_type = filters.get("chunk_type")
        if project_id is not None:
            parts.append(f'project_id == "{str(project_id)}"')
        if source_type is not None:
            parts.append(f'source_type == "{str(source_type)}"')
        if chunk_type is not None:
            parts.append(f'chunk_type == "{str(chunk_type)}"')
        return " and ".join(parts)

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

