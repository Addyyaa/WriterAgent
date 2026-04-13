from __future__ import annotations

from dataclasses import dataclass

from packages.retrieval.hybrid.base import FusionStrategy
from packages.retrieval.types import ScoredDoc


@dataclass(frozen=True)
class RRFFusionConfig:
    rrf_k: int = 60
    weights: tuple[float, ...] = (1.0, 0.7)


class RRFFusionStrategy(FusionStrategy):
    """Reciprocal Rank Fusion 实现。"""

    def __init__(self, config: RRFFusionConfig | None = None) -> None:
        self.config = config or RRFFusionConfig()

    def fuse(self, candidate_lists: list[list[ScoredDoc]], *, top_k: int) -> list[ScoredDoc]:
        if top_k <= 0:
            return []

        merged: dict[str, ScoredDoc] = {}
        scores: dict[str, float] = {}

        for list_idx, docs in enumerate(candidate_lists):
            if not docs:
                continue
            weight = self._weight_for_list(list_idx)
            for rank, doc in enumerate(docs, start=1):
                key = str(doc.id)
                if key not in merged:
                    merged[key] = doc
                    scores[key] = 0.0
                scores[key] += weight / (self.config.rrf_k + rank)

                # 优先保留距离更小的文档版本，避免同 id 的弱信号覆盖。
                current = merged[key]
                current_distance = current.distance if current.distance is not None else 1.0
                new_distance = doc.distance if doc.distance is not None else 1.0
                if new_distance < current_distance:
                    merged[key] = doc

                # 透传关键词分数（如果有）。
                if doc.keyword_score is not None:
                    merged[key].keyword_score = doc.keyword_score

        ranked: list[ScoredDoc] = []
        for key, doc in merged.items():
            item = self._clone(doc)
            item.hybrid_score = float(scores.get(key, 0.0))
            ranked.append(item)

        ranked.sort(
            key=lambda x: (
                -(x.hybrid_score or 0.0),
                x.distance if x.distance is not None else 1.0,
            )
        )
        return ranked[:top_k]

    def _weight_for_list(self, index: int) -> float:
        if index < len(self.config.weights):
            return float(self.config.weights[index])
        return 1.0

    @staticmethod
    def _clone(doc: ScoredDoc) -> ScoredDoc:
        return ScoredDoc(**doc.__dict__)
