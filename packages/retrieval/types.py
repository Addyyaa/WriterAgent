from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from packages.core.types import JsonDict, ProjectId, TimestampLike


@dataclass(frozen=True)
class FilterExpr:
    """检索过滤表达式。"""

    project_id: ProjectId | None = None
    source_type: str | None = None
    chunk_type: str | None = None
    source_timestamp_gte: TimestampLike | None = None
    source_timestamp_lte: TimestampLike | None = None


@dataclass(frozen=True)
class RetrievalOptions:
    """检索运行选项。"""

    top_k: int = 5
    max_distance: float | None = None
    sort_by: str = "distance"
    enable_query_rewrite: bool = True
    enable_hybrid: bool = True
    enable_rerank: bool = True
    candidate_multiplier: int = 4


@dataclass
class RetrievalDoc:
    """基础检索文档表示。"""

    id: str
    text: str
    project_id: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    chunk_type: str | None = None
    metadata_json: JsonDict = field(default_factory=dict)
    summary_text: str | None = None
    source_timestamp: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ScoredDoc(RetrievalDoc):
    """带评分信号的检索文档。"""

    distance: float | None = None
    keyword_score: float | None = None
    hybrid_score: float | None = None
    rerank_score: float | None = None

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "ScoredDoc":
        metadata_json = row.get("metadata_json") or {}
        source_timestamp = row.get("source_timestamp")
        if source_timestamp is None and isinstance(metadata_json, dict):
            source_timestamp = metadata_json.get("source_timestamp")

        return cls(
            id=str(row.get("id")),
            text=str(row.get("text") or ""),
            project_id=str(row.get("project_id")) if row.get("project_id") is not None else None,
            source_type=row.get("source_type"),
            source_id=str(row.get("source_id")) if row.get("source_id") is not None else None,
            chunk_type=row.get("chunk_type"),
            metadata_json=metadata_json if isinstance(metadata_json, dict) else {},
            summary_text=(
                str(row.get("summary_text")).strip()
                if row.get("summary_text") is not None
                else None
            ),
            source_timestamp=source_timestamp,
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            distance=float(row["distance"]) if row.get("distance") is not None else None,
            keyword_score=(
                float(row["keyword_score"]) if row.get("keyword_score") is not None else None
            ),
            hybrid_score=float(row["hybrid_score"]) if row.get("hybrid_score") is not None else None,
            rerank_score=float(row["rerank_score"]) if row.get("rerank_score") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "project_id": self.project_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_type": self.chunk_type,
            "metadata_json": self.metadata_json,
            "summary_text": self.summary_text,
            "source_timestamp": self.source_timestamp,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "distance": self.distance,
            "keyword_score": self.keyword_score,
            "hybrid_score": self.hybrid_score,
            "rerank_score": self.rerank_score,
        }
        return payload
