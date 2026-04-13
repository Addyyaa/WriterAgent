from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.memory.long_term.temporal import SOURCE_TIMESTAMP_KEY, source_timestamp_to_epoch
from packages.storage.postgres.repositories.memory_repository import MemoryChunkRepository


@dataclass(frozen=True)
class HybridSearchConfig:
    """
    混合检索配置。

    - candidate_multiplier: 扩大候选集合，给融合与重排留足空间。
    - rrf_k: RRF 常量，值越大，头部名次差异越平滑。
    - vector_weight / keyword_weight: 两路召回权重。
    """

    candidate_multiplier: int = 4
    rrf_k: int = 60
    vector_weight: float = 1.0
    keyword_weight: float = 0.7


class HybridSearchEngine:
    """
    混合检索引擎：
    1) 向量召回（pgvector）
    2) 关键词召回（PostgreSQL FTS）
    3) RRF 融合输出候选
    """

    def __init__(
        self,
        memory_repo: MemoryChunkRepository,
        config: HybridSearchConfig | None = None,
    ) -> None:
        self.memory_repo = memory_repo
        self.config = config or HybridSearchConfig()

    def search(
        self,
        *,
        project_id,
        query_text: str,
        query_embedding: list[float],
        top_k: int,
        source_type: str | None,
        chunk_type: str | None,
        max_distance: float | None,
        source_timestamp_gte: str | datetime | None,
        source_timestamp_lte: str | datetime | None,
        sort_by: str,
    ) -> list[dict]:
        if top_k <= 0:
            return []

        candidate_k = max(top_k, top_k * self.config.candidate_multiplier)

        vector_rows = self.memory_repo.similarity_search(
            project_id=project_id,
            query_embedding=query_embedding,
            top_k=candidate_k,
            source_type=source_type,
            chunk_type=chunk_type,
            max_distance=max_distance,
            source_timestamp_gte=source_timestamp_gte,
            source_timestamp_lte=source_timestamp_lte,
            sort_by=sort_by,
        )

        # 当显式使用 max_distance 时，语义阈值已在向量层约束，
        # 这里不额外引入关键词分支，避免越过召回边界。
        keyword_rows: list[dict] = []
        if max_distance is None and isinstance(query_text, str) and query_text.strip():
            keyword_rows = self.memory_repo.keyword_search(
                project_id=project_id,
                query_text=query_text,
                top_k=candidate_k,
                source_type=source_type,
                chunk_type=chunk_type,
                source_timestamp_gte=source_timestamp_gte,
                source_timestamp_lte=source_timestamp_lte,
                sort_by=self._to_keyword_sort(sort_by),
            )

        return self._fuse_rrf(
            vector_rows=vector_rows,
            keyword_rows=keyword_rows,
            top_k=top_k,
            sort_by=sort_by,
        )

    def _fuse_rrf(
        self,
        *,
        vector_rows: list[dict],
        keyword_rows: list[dict],
        top_k: int,
        sort_by: str,
    ) -> list[dict]:
        fused: dict[str, dict] = {}

        for rank, row in enumerate(vector_rows, start=1):
            key = str(row["id"])
            score = self.config.vector_weight / (self.config.rrf_k + rank)
            item = fused.get(key)
            if item is None:
                item = dict(row)
                item["hybrid_score"] = 0.0
                item["keyword_score"] = float(item.get("keyword_score", 0.0) or 0.0)
                fused[key] = item
            item["hybrid_score"] += score

        for rank, row in enumerate(keyword_rows, start=1):
            key = str(row["id"])
            score = self.config.keyword_weight / (self.config.rrf_k + rank)
            item = fused.get(key)
            if item is None:
                item = dict(row)
                # 关键词召回行可能没有 distance，给一个保守默认值，便于统一排序。
                item["distance"] = float(item.get("distance", 1.0))
                item["hybrid_score"] = 0.0
                fused[key] = item
            if "keyword_score" in row:
                item["keyword_score"] = float(row["keyword_score"])
            item["hybrid_score"] += score

        rows = list(fused.values())
        if not rows:
            return []

        return self._sort_fused_rows(rows, sort_by=sort_by)[:top_k]

    def _sort_fused_rows(self, rows: list[dict], *, sort_by: str) -> list[dict]:
        def ts_epoch(item: dict) -> float | None:
            return source_timestamp_to_epoch(item.get(SOURCE_TIMESTAMP_KEY))

        if sort_by == "source_timestamp_desc":
            return sorted(
                rows,
                key=lambda x: (
                    ts_epoch(x) is None,
                    -(ts_epoch(x) or 0.0),
                    -(x.get("hybrid_score") or 0.0),
                    x.get("distance", 1.0),
                ),
            )
        if sort_by == "source_timestamp_asc":
            return sorted(
                rows,
                key=lambda x: (
                    ts_epoch(x) is None,
                    ts_epoch(x) or 0.0,
                    -(x.get("hybrid_score") or 0.0),
                    x.get("distance", 1.0),
                ),
            )
        if sort_by == "distance_then_source_timestamp_desc":
            return sorted(
                rows,
                key=lambda x: (
                    -(x.get("hybrid_score") or 0.0),
                    ts_epoch(x) is None,
                    -(ts_epoch(x) or 0.0),
                    x.get("distance", 1.0),
                ),
            )
        return sorted(
            rows,
            key=lambda x: (
                -(x.get("hybrid_score") or 0.0),
                x.get("distance", 1.0),
            ),
        )

    @staticmethod
    def _to_keyword_sort(vector_sort: str) -> str:
        if vector_sort == "source_timestamp_desc":
            return "source_timestamp_desc"
        if vector_sort == "source_timestamp_asc":
            return "source_timestamp_asc"
        return "keyword_score_desc"
