from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from packages.memory.long_term.ingestion.ingestion_service import (
    MemoryIngestionService,
    PendingEmbeddingProcessStats,
)
from packages.storage.postgres.repositories.embedding_job_run_repository import (
    EmbeddingJobRunRepository,
)


@dataclass(frozen=True)
class EmbeddingJobRunResult:
    started_at: str
    ended_at: str
    duration_seconds: float
    requested: int
    processed: int
    failed: int
    skipped: int
    retried: int
    recovered_processing: int
    status: str
    run_id: str | None = None


class EmbeddingJobRunner:
    """Embedding 作业编排器（批处理 pending + 重试 + 可调度循环）。"""

    def __init__(
        self,
        ingestion_service: MemoryIngestionService,
        job_run_repo: EmbeddingJobRunRepository | None = None,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.job_run_repo = job_run_repo

    def run_once(
        self,
        *,
        limit: int = 200,
        batch_size: int | None = None,
        project_id=None,
        continue_on_error: bool = True,
        retry_failed_first: bool = True,
        retry_failed_limit: int | None = None,
        recover_stuck_processing: bool = True,
        processing_stale_after_seconds: int = 900,
    ) -> EmbeddingJobRunResult:
        start_dt = datetime.now(tz=timezone.utc)

        try:
            stats: PendingEmbeddingProcessStats = self.ingestion_service.process_pending_embeddings(
                project_id=project_id,
                limit=limit,
                batch_size=batch_size,
                continue_on_error=continue_on_error,
                retry_failed_first=retry_failed_first,
                retry_failed_limit=retry_failed_limit,
                recover_stuck_processing=recover_stuck_processing,
                processing_stale_after_seconds=processing_stale_after_seconds,
            )
            end_dt = datetime.now(tz=timezone.utc)
            duration = (end_dt - start_dt).total_seconds()
            status = self._derive_status(stats)
            run_id = self._persist_run(
                project_id=project_id,
                status=status,
                stats=stats,
                duration_seconds=duration,
                started_at=start_dt,
                ended_at=end_dt,
            )
            return EmbeddingJobRunResult(
                started_at=start_dt.isoformat().replace("+00:00", "Z"),
                ended_at=end_dt.isoformat().replace("+00:00", "Z"),
                duration_seconds=duration,
                requested=stats.requested,
                processed=stats.processed,
                failed=stats.failed,
                skipped=stats.skipped,
                retried=stats.retried,
                recovered_processing=stats.recovered_processing,
                status=status,
                run_id=run_id,
            )
        except Exception as exc:
            end_dt = datetime.now(tz=timezone.utc)
            duration = (end_dt - start_dt).total_seconds()
            if self.job_run_repo is not None:
                self.job_run_repo.create_run(
                    project_id=project_id,
                    status="failed",
                    requested=0,
                    processed=0,
                    failed=0,
                    skipped=0,
                    retried=0,
                    recovered_processing=0,
                    duration_seconds=duration,
                    started_at=start_dt,
                    ended_at=end_dt,
                    error_message=str(exc),
                )
            raise

    def run_loop(
        self,
        *,
        interval_seconds: int = 60,
        max_runs: int | None = None,
        stop_when_idle: bool = False,
        limit: int = 200,
        batch_size: int | None = None,
        project_id=None,
        continue_on_error: bool = True,
        retry_failed_first: bool = True,
        retry_failed_limit: int | None = None,
        recover_stuck_processing: bool = True,
        processing_stale_after_seconds: int = 900,
    ) -> list[EmbeddingJobRunResult]:
        if interval_seconds < 0:
            raise ValueError("interval_seconds 不能小于 0")

        reports: list[EmbeddingJobRunResult] = []
        run_count = 0
        while True:
            result = self.run_once(
                limit=limit,
                batch_size=batch_size,
                project_id=project_id,
                continue_on_error=continue_on_error,
                retry_failed_first=retry_failed_first,
                retry_failed_limit=retry_failed_limit,
                recover_stuck_processing=recover_stuck_processing,
                processing_stale_after_seconds=processing_stale_after_seconds,
            )
            reports.append(result)
            run_count += 1

            if max_runs is not None and run_count >= max_runs:
                break
            if stop_when_idle and result.requested <= 0:
                break
            if interval_seconds > 0:
                time.sleep(interval_seconds)

        return reports

    def _persist_run(
        self,
        *,
        project_id,
        status: str,
        stats: PendingEmbeddingProcessStats,
        duration_seconds: float,
        started_at: datetime,
        ended_at: datetime,
    ) -> str | None:
        if self.job_run_repo is None:
            return None
        row = self.job_run_repo.create_run(
            project_id=project_id,
            status=status,
            requested=stats.requested,
            processed=stats.processed,
            failed=stats.failed,
            skipped=stats.skipped,
            retried=stats.retried,
            recovered_processing=stats.recovered_processing,
            duration_seconds=duration_seconds,
            started_at=started_at,
            ended_at=ended_at,
            error_message=None,
        )
        return str(row.id)

    @staticmethod
    def _derive_status(stats: PendingEmbeddingProcessStats) -> str:
        if stats.failed <= 0:
            return "success"
        if stats.processed > 0:
            return "partial"
        return "failed"
