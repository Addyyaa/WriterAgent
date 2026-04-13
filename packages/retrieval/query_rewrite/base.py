from __future__ import annotations

from abc import ABC, abstractmethod


class QueryRewriter(ABC):
    """Query Rewrite 抽象接口。"""

    @abstractmethod
    def rewrite(self, query: str) -> list[str]:
        raise NotImplementedError
