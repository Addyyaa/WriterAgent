from __future__ import annotations

from abc import ABC, abstractmethod


class KeywordRetriever(ABC):
    @abstractmethod
    def index(self, docs: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """返回 (doc_index, score)。"""
        raise NotImplementedError
