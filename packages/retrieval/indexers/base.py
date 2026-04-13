from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexBuildStats:
    indexed: int
    deleted: int = 0
    skipped: int = 0


class Indexer(ABC):
    name: str = "indexer"

    @abstractmethod
    def full_build(self) -> IndexBuildStats:
        raise NotImplementedError

    @abstractmethod
    def incremental_update(self) -> IndexBuildStats:
        raise NotImplementedError

    @abstractmethod
    def delete_by_ids(self, ids: list[str]) -> int:
        raise NotImplementedError
