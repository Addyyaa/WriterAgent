from __future__ import annotations


def build_retrieval_impression_payload(
    *,
    variant: str,
    rerank_backend: str,
    rows_count: int,
    context_json: dict,
) -> dict:
    return {
        "variant": str(variant),
        "rerank_backend": str(rerank_backend),
        "rows_count": int(rows_count),
        "context_json": dict(context_json or {}),
    }
