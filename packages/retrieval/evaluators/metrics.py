from __future__ import annotations

import math


def recall_at_k(hits: list[int], k: int) -> float:
    if k <= 0 or not hits:
        return 0.0
    top = hits[:k]
    return 1.0 if any(top) else 0.0


def mrr(hits: list[int], k: int | None = None) -> float:
    if not hits:
        return 0.0
    bound = k if k is not None and k > 0 else len(hits)
    for idx, value in enumerate(hits[:bound], start=1):
        if value:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(hits: list[int], k: int) -> float:
    if k <= 0 or not hits:
        return 0.0

    top = hits[:k]
    dcg = 0.0
    for idx, rel in enumerate(top, start=1):
        if rel <= 0:
            continue
        dcg += (2**rel - 1) / math.log2(idx + 1)

    ideal = sorted(top, reverse=True)
    idcg = 0.0
    for idx, rel in enumerate(ideal, start=1):
        if rel <= 0:
            continue
        idcg += (2**rel - 1) / math.log2(idx + 1)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg
