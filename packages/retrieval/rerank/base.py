from __future__ import annotations

from abc import ABC, abstractmethod

from packages.retrieval.types import ScoredDoc


class Reranker(ABC):
    """重排器抽象接口。"""

    @abstractmethod
    def rerank(
        self,
        *,
        query: str,
        candidates: list[ScoredDoc],
        top_k: int,
        sort_by: str,
    ) -> list[ScoredDoc]:
        raise NotImplementedError
