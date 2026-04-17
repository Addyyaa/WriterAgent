from __future__ import annotations

from datetime import datetime, timedelta, timezone

import os

from sqlalchemy import and_, or_, select

from .base import BaseRepository
from packages.storage.postgres.models.workflow_run import WorkflowRun


class WorkflowRunRepository(BaseRepository):
    _TERMINAL_STATUSES = {"success", "failed", "cancelled"}

    @staticmethod
    def _clear_lease_fields(row: WorkflowRun) -> None:
        row.claimed_by = None
        row.claimed_at = None
        row.heartbeat_at = None
        row.lease_expires_at = None

    def _apply_manual_retry_requeue_fields(self, row: WorkflowRun) -> None:
        """将 run 字段重置为可再次出队执行（不校验当前 status，由调用方负责）。"""
        row.status = "queued"
        row.error_code = None
        row.error_message = None
        row.next_attempt_at = datetime.now(tz=timezone.utc)
        row.finished_at = None
        self._clear_lease_fields(row)

    def create_run(
        self,
        *,
        project_id,
        workflow_type: str,
        trace_id: str,
        request_id: str | None = None,
        initiated_by=None,
        parent_run_id=None,
        idempotency_key: str | None = None,
        input_json: dict | None = None,
        plan_json: dict | None = None,
        priority: int = 100,
        max_retries: int = 2,
        auto_commit: bool = True,
    ) -> WorkflowRun:
        if idempotency_key:
            existing = self.get_by_idempotency(idempotency_key)
            if existing is not None:
                return existing

        row = WorkflowRun(
            project_id=project_id,
            workflow_type=workflow_type,
            trace_id=trace_id,
            request_id=request_id,
            initiated_by=initiated_by,
            parent_run_id=parent_run_id,
            idempotency_key=idempotency_key,
            input_json=input_json or {},
            plan_json=plan_json or {},
            output_json={},
            priority=max(1, int(priority)),
            max_retries=max(0, int(max_retries)),
            status="queued",
            next_attempt_at=datetime.now(tz=timezone.utc),
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, run_id) -> WorkflowRun | None:
        return self.db.get(WorkflowRun, run_id)

    def get_by_idempotency(self, idempotency_key: str) -> WorkflowRun | None:
        stmt = select(WorkflowRun).where(WorkflowRun.idempotency_key == idempotency_key)
        return self.db.execute(stmt).scalar_one_or_none()

    def claim_next(
        self,
        *,
        limit: int = 1,
        worker_id: str | None = None,
        initial_lease_seconds: int | None = None,
    ) -> list[WorkflowRun]:
        now = datetime.now(tz=timezone.utc)
        wid = (worker_id or os.getenv("WRITER_WORKER_ID", "").strip() or f"pid-{os.getpid()}").strip()
        initial = max(60, int(initial_lease_seconds or int(os.getenv("WRITER_ORCH_RUN_INITIAL_LEASE_SECONDS", "900"))))
        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.status == "queued",
                or_(WorkflowRun.next_attempt_at.is_(None), WorkflowRun.next_attempt_at <= now),
            )
            .order_by(WorkflowRun.priority.asc(), WorkflowRun.created_at.asc())
            .limit(max(1, int(limit)))
            .with_for_update(skip_locked=True)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.status = "running"
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            row.claimed_by = wid
            row.claimed_at = now
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=initial)
        if rows:
            self.db.commit()
            for row in rows:
                self.db.refresh(row)
        return rows

    def touch_execution_lease(
        self,
        run_id,
        *,
        worker_id: str | None = None,
        extend_seconds: int = 900,
        auto_commit: bool = True,
    ) -> WorkflowRun | None:
        """延长 running run 的租约并刷新心跳（步骤开始 / live_progress 等路径调用）。"""
        row = self.get(run_id)
        if row is None or str(row.status) != "running":
            return None
        now = datetime.now(tz=timezone.utc)
        ext = max(60, int(extend_seconds))
        row.heartbeat_at = now
        if worker_id:
            row.claimed_by = worker_id.strip() or row.claimed_by
        if row.claimed_at is None:
            row.claimed_at = now
        row.lease_expires_at = now + timedelta(seconds=ext)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def recover_stale_running(
        self,
        *,
        heartbeat_stale_seconds: int,
        legacy_run_started_stale_seconds: int | None = None,
        auto_commit: bool = True,
    ) -> list[WorkflowRun]:
        """回收僵尸 running：租约到期、心跳过旧，或无新列时的 legacy started_at 兜底。"""
        now = datetime.now(tz=timezone.utc)
        hb_sec = max(1, int(heartbeat_stale_seconds))
        legacy_sec = max(1, int(legacy_run_started_stale_seconds or heartbeat_stale_seconds))
        heartbeat_threshold = now - timedelta(seconds=hb_sec)
        legacy_threshold = now - timedelta(seconds=legacy_sec)

        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.status == "running",
                or_(
                    and_(WorkflowRun.lease_expires_at.isnot(None), WorkflowRun.lease_expires_at < now),
                    and_(WorkflowRun.heartbeat_at.isnot(None), WorkflowRun.heartbeat_at < heartbeat_threshold),
                    and_(
                        WorkflowRun.lease_expires_at.is_(None),
                        WorkflowRun.heartbeat_at.is_(None),
                        WorkflowRun.started_at.isnot(None),
                        WorkflowRun.started_at <= legacy_threshold,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.error_code = "RUN_LEASE_STALE"
            row.error_message = (
                f"运行租约/心跳回收（lease到期或超过 {hb_sec}s 无心跳；"
                f"详见 WRITER_ORCH_RECOVER_HEARTBEAT_STALE_SECONDS）"
            )
            self._clear_lease_fields(row)
            if int(row.retry_count or 0) < int(row.max_retries or 0):
                row.retry_count = int(row.retry_count or 0) + 1
                row.status = "queued"
                row.next_attempt_at = now
                row.finished_at = None
            else:
                row.status = "failed"
                row.finished_at = now

        if rows and auto_commit:
            self.db.commit()
            for row in rows:
                self.db.refresh(row)
        elif rows:
            self.db.flush()
        return rows

    def set_plan(self, run_id, *, plan_json: dict, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.plan_json = plan_json or {}
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def succeed(self, run_id, *, output_json: dict | None = None, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "success"
        row.output_json = output_json or {}
        row.error_code = None
        row.error_message = None
        row.finished_at = datetime.now(tz=timezone.utc)
        self._clear_lease_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def fail(
        self,
        run_id,
        *,
        error_code: str,
        error_message: str | None = None,
        retryable: bool = False,
        retry_delay_seconds: int = 30,
        auto_commit: bool = True,
    ) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None

        row.error_code = error_code
        row.error_message = error_message

        if retryable and int(row.retry_count or 0) < int(row.max_retries or 0):
            row.retry_count = int(row.retry_count or 0) + 1
            row.status = "queued"
            row.next_attempt_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
            row.next_attempt_at = row.next_attempt_at + timedelta(seconds=max(1, int(retry_delay_seconds)))
            self._clear_lease_fields(row)
        else:
            row.status = "failed"
            row.finished_at = datetime.now(tz=timezone.utc)
            self._clear_lease_fields(row)

        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def cancel(self, run_id, *, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        if str(row.status) in self._TERMINAL_STATUSES:
            return row
        row.status = "cancelled"
        row.finished_at = datetime.now(tz=timezone.utc)
        self._clear_lease_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_waiting_review(self, run_id, *, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        if str(row.status) in self._TERMINAL_STATUSES:
            return row
        row.status = "waiting_review"
        row.next_attempt_at = None
        self._clear_lease_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def resume_from_waiting_review(self, run_id, *, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        if str(row.status) != "waiting_review":
            return row
        row.status = "queued"
        row.next_attempt_at = datetime.now(tz=timezone.utc)
        row.error_code = None
        row.error_message = None
        self._clear_lease_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def retry_run(self, run_id, *, auto_commit: bool = True) -> WorkflowRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        if str(row.status) not in {"failed", "cancelled"}:
            return None
        self._apply_manual_retry_requeue_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def requeue_after_manual_retry(self, run_id, *, auto_commit: bool = True) -> WorkflowRun | None:
        """用户手动重试：在业务层已允许时强制重新入队（例如曾错误标记为 success 的 run）。"""
        row = self.get(run_id)
        if row is None:
            return None
        self._apply_manual_retry_requeue_fields(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_recent(self, *, project_id=None, workflow_type: str | None = None, limit: int = 100) -> list[WorkflowRun]:
        stmt = select(WorkflowRun)
        if project_id is not None:
            stmt = stmt.where(WorkflowRun.project_id == project_id)
        if workflow_type is not None:
            stmt = stmt.where(WorkflowRun.workflow_type == workflow_type)
        stmt = stmt.order_by(WorkflowRun.created_at.desc()).limit(max(1, int(limit)))
        return list(self.db.execute(stmt).scalars().all())
