from __future__ import annotations

from packages.retrieval.indexers.base import IndexBuildStats, Indexer


class WorldEntryIndexer(Indexer):
    name = "world_entry"

    def full_build(self) -> IndexBuildStats:
        return IndexBuildStats(indexed=0, skipped=0)

    def incremental_update(self) -> IndexBuildStats:
        return IndexBuildStats(indexed=0, skipped=0)

    def delete_by_ids(self, ids: list[str]) -> int:
        return len(ids)
