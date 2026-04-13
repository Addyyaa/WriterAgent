from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from .base import BaseRepository
from packages.storage.postgres.models.workflow_run import WorkflowRun


class WorkflowRunRepository(BaseRepository):
    _TERMINAL_STATUSES = {"success", "failed", "cancelled"}

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

    def claim_next(self, *, limit: int = 1) -> list[WorkflowRun]:
        now = datetime.now(tz=timezone.utc)
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
        if rows:
            self.db.commit()
            for row in rows:
                self.db.refresh(row)
        return rows

    def recover_stale_running(
        self,
        *,
        stale_after_seconds: int,
        auto_commit: bool = True,
    ) -> list[WorkflowRun]:
        now = datetime.now(tz=timezone.utc)
        stale_after = max(1, int(stale_after_seconds))
        threshold = now - timedelta(seconds=stale_after)

        stmt = (
            select(WorkflowRun)
            .where(
                WorkflowRun.status == "running",
                WorkflowRun.started_at.is_not(None),
                WorkflowRun.started_at <= threshold,
            )
            .with_for_update(skip_locked=True)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        for row in rows:
            row.error_code = "RUN_TIMEOUT"
            row.error_message = f"run 超时回收，超过 {stale_after} 秒未完成"
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
        else:
            row.status = "failed"
            row.finished_at = datetime.now(tz=timezone.utc)

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
        row.status = "queued"
        row.error_code = None
        row.error_message = None
        row.next_attempt_at = datetime.now(tz=timezone.utc)
        row.finished_at = None
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
