from __future__ import annotations

from abc import ABC, abstractmethod

from packages.retrieval.types import ScoredDoc


class FusionStrategy(ABC):
    """候选融合策略抽象接口。"""

    @abstractmethod
    def fuse(self, candidate_lists: list[list[ScoredDoc]], *, top_k: int) -> list[ScoredDoc]:
        raise NotImplementedError
