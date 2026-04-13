from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VectorFilterExpr:
    project_id: object | None = None
    source_type: str | None = None
    chunk_type: str | None = None
    source_timestamp_gte: str | None = None
    source_timestamp_lte: str | None = None


def to_dict(expr: VectorFilterExpr | None) -> dict:
    if expr is None:
        return {}
    return {
        "project_id": expr.project_id,
        "source_type": expr.source_type,
        "chunk_type": expr.chunk_type,
        "source_timestamp_gte": expr.source_timestamp_gte,
        "source_timestamp_lte": expr.source_timestamp_lte,
    }
