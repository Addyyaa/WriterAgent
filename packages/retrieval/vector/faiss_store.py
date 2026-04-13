from __future__ import annotations

import hashlib
from typing import Any

from packages.retrieval.errors import RetrievalInputError, RetrieverUnavailableError
from packages.retrieval.vector.base import VectorStore


class FaissStore(VectorStore):
    """
    FAISS 向量存储实现。

    说明：
    - 依赖 `faiss-cpu` 可选安装。
    - 通过内存元数据字典实现过滤语义（project_id/source_type/chunk_type）。
    """

    def __init__(
        self,
        *,
        dimension: int,
        metric: str = "cosine",
    ) -> None:
        try:
            import faiss  # type: ignore
            import numpy as np  # type: ignore
        except Exception as exc:
            raise RetrieverUnavailableError(
                "FaissStore 不可用，请安装可选依赖 `faiss-cpu` 与 `numpy`"
            ) from exc

        if dimension <= 0:
            raise RetrievalInputError("dimension 必须大于 0")

        self.dimension = int(dimension)
        self.metric = metric.strip().lower() if isinstance(metric, str) else "cosine"
        self._faiss = faiss
        self._np = np

        if self.metric == "l2":
            base = self._faiss.IndexFlatL2(self.dimension)
        else:
            self.metric = "cosine"
            base = self._faiss.IndexFlatIP(self.dimension)
        self._index = self._faiss.IndexIDMap2(base)

        self._records: dict[str, dict[str, Any]] = {}
        self._int_to_id: dict[int, str] = {}

    def upsert(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return

        vectors: list[list[float]] = []
        ids: list[int] = []
        payloads: list[dict[str, Any]] = []

        for item in items:
            row_id = str(item.get("id") or "").strip()
            vector = item.get("embedding")
            if not row_id:
                raise RetrievalInputError("FaissStore.upsert 缺少 id")
            if not isinstance(vector, list) or len(vector) != self.dimension:
                raise RetrievalInputError(
                    f"FaissStore.upsert embedding 维度错误，期望 {self.dimension}"
                )

            numeric_id = self._to_numeric_id(row_id)
            self._remove_by_numeric_id(numeric_id)
            ids.append(numeric_id)

            vectors.append([float(v) for v in vector])
            payloads.append(
                {
                    "id": row_id,
                    "text": str(item.get("text") or item.get("chunk_text") or ""),
                    "project_id": item.get("project_id"),
                    "source_type": item.get("source_type"),
                    "source_id": item.get("source_id"),
                    "chunk_type": item.get("chunk_type"),
                    "metadata_json": item.get("metadata_json") or {},
                }
            )

        mat = self._np.array(vectors, dtype="float32")
        if self.metric == "cosine":
            self._faiss.normalize_L2(mat)
        id_array = self._np.array(ids, dtype="int64")
        self._index.add_with_ids(mat, id_array)

        for numeric_id, payload in zip(ids, payloads, strict=True):
            row_id = str(payload["id"])
            self._records[row_id] = payload
            self._int_to_id[numeric_id] = row_id

    def delete(self, ids: list[str]) -> int:
        if not ids:
            return 0
        deleted = 0
        for row_id in ids:
            numeric_id = self._to_numeric_id(str(row_id))
            if self._remove_by_numeric_id(numeric_id):
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
        if not isinstance(query_vector, list) or len(query_vector) != self.dimension:
            raise RetrievalInputError(
                f"FaissStore.search query_vector 维度错误，期望 {self.dimension}"
            )
        if self._index.ntotal == 0:
            return []

        filters = filters or {}
        max_distance = filters.get("max_distance")

        q = self._np.array([query_vector], dtype="float32")
        if self.metric == "cosine":
            self._faiss.normalize_L2(q)

        search_k = min(max(top_k * 5, top_k), max(self._index.ntotal, 1))
        scores, idxs = self._index.search(q, search_k)

        out: list[dict[str, Any]] = []
        for score, idx in zip(scores[0], idxs[0], strict=False):
            if int(idx) == -1:
                continue
            row_id = self._int_to_id.get(int(idx))
            if row_id is None:
                continue
            payload = self._records.get(row_id)
            if payload is None:
                continue
            if not self._match_filters(payload, filters):
                continue

            if self.metric == "cosine":
                distance = float(1.0 - float(score))
            else:
                distance = float(score)

            if max_distance is not None and distance > float(max_distance):
                continue

            row = dict(payload)
            row["distance"] = distance
            out.append(row)
            if len(out) >= top_k:
                break
        return out

    def _remove_by_numeric_id(self, numeric_id: int) -> bool:
        existing_id = self._int_to_id.get(numeric_id)
        if existing_id is None:
            return False
        id_array = self._np.array([numeric_id], dtype="int64")
        self._index.remove_ids(id_array)
        self._int_to_id.pop(numeric_id, None)
        self._records.pop(existing_id, None)
        return True

    @staticmethod
    def _to_numeric_id(row_id: str) -> int:
        digest = hashlib.sha1(row_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=False) & 0x7FFFFFFFFFFFFFFF

    @staticmethod
    def _match_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        project_id = filters.get("project_id")
        source_type = filters.get("source_type")
        chunk_type = filters.get("chunk_type")

        if project_id is not None and str(payload.get("project_id")) != str(project_id):
            return False
        if source_type is not None and payload.get("source_type") != source_type:
            return False
        if chunk_type is not None and payload.get("chunk_type") != chunk_type:
            return False
        return True

