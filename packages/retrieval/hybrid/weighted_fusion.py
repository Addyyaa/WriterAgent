from __future__ import annotations

from dataclasses import dataclass

from packages.retrieval.hybrid.base import FusionStrategy
from packages.retrieval.types import ScoredDoc


@dataclass(frozen=True)
class WeightedFusionConfig:
    """对已归一化 score 进行加权融合。"""

    score_fields: tuple[str, ...] = ("hybrid_score", "keyword_score")
    weights: tuple[float, ...] = (0.7, 0.3)


class WeightedFusionStrategy(FusionStrategy):
    def __init__(self, config: WeightedFusionConfig | None = None) -> None:
        self.config = config or WeightedFusionConfig()

    def fuse(self, candidate_lists: list[list[ScoredDoc]], *, top_k: int) -> list[ScoredDoc]:
        if top_k <= 0:
            return []

        merged: dict[str, ScoredDoc] = {}
        for docs in candidate_lists:
            for doc in docs:
                key = str(doc.id)
                if key not in merged:
                    merged[key] = ScoredDoc(**doc.__dict__)
                else:
                    # 合并可用分数字段
                    current = merged[key]
                    current.keyword_score = max(
                        current.keyword_score or 0.0,
                        doc.keyword_score or 0.0,
                    )
                    current.hybrid_score = max(
                        current.hybrid_score or 0.0,
                        doc.hybrid_score or 0.0,
                    )
                    if doc.distance is not None:
                        if current.distance is None or doc.distance < current.distance:
                            current.distance = doc.distance

        rows = list(merged.values())
        for row in rows:
            row.hybrid_score = self._weighted_score(row)

        rows.sort(
            key=lambda x: (
                -(x.hybrid_score or 0.0),
                x.distance if x.distance is not None else 1.0,
            )
        )
        return rows[:top_k]

    def _weighted_score(self, row: ScoredDoc) -> float:
        score = 0.0
        for idx, field in enumerate(self.config.score_fields):
            weight = self.config.weights[idx] if idx < len(self.config.weights) else 1.0
            value = getattr(row, field, 0.0) or 0.0
            score += float(weight) * float(value)
        return score
