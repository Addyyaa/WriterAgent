from __future__ import annotations

from dataclasses import dataclass

from packages.retrieval.indexers.base import IndexBuildStats, Indexer


@dataclass(frozen=True)
class ScheduleRunReport:
    ran: int
    total_indexed: int
    total_deleted: int
    total_skipped: int


class IndexScheduler:
    """索引任务调度器（同步轻量版）。"""

    def __init__(self) -> None:
        self._indexers: dict[str, Indexer] = {}

    def register(self, indexer: Indexer) -> None:
        self._indexers[indexer.name] = indexer

    def run_full(self) -> ScheduleRunReport:
        return self._run("full")

    def run_incremental(self) -> ScheduleRunReport:
        return self._run("incremental")

    def _run(self, mode: str) -> ScheduleRunReport:
        reports: list[IndexBuildStats] = []
        for indexer in self._indexers.values():
            if mode == "full":
                reports.append(indexer.full_build())
            else:
                reports.append(indexer.incremental_update())

        return ScheduleRunReport(
            ran=len(reports),
            total_indexed=sum(item.indexed for item in reports),
            total_deleted=sum(item.deleted for item in reports),
            total_skipped=sum(item.skipped for item in reports),
        )
