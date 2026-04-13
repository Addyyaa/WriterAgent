from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    @abstractmethod
    def upsert(self, items: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, ids: list[str]) -> int:
        raise NotImplementedError

    @abstractmethod
    def search(self, *, query_vector: list[float], top_k: int, filters: dict | None = None) -> list[dict]:
        raise NotImplementedError
