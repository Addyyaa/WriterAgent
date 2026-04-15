from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.workflow_run import WorkflowRun
from packages.storage.postgres.models.workflow_step import WorkflowStep


class WorkflowStepRepository(BaseRepository):
    def create_step(
        self,
        *,
        workflow_run_id,
        step_key: str,
        step_type: str,
        agent_name: str | None = None,
        role_id: str | None = None,
        strategy_version: str | None = None,
        prompt_hash: str | None = None,
        schema_version: str | None = None,
        depends_on_keys: list[str] | None = None,
        input_json: dict | None = None,
        status: str = "pending",
        auto_commit: bool = True,
    ) -> WorkflowStep:
        row = WorkflowStep(
            workflow_run_id=workflow_run_id,
            step_key=step_key,
            step_type=step_type,
            agent_name=agent_name,
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            depends_on_keys=list(depends_on_keys or []),
            input_json=input_json or {},
            output_json={},
            status=status,
            attempt_count=0,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, step_id) -> WorkflowStep | None:
        return self.db.get(WorkflowStep, step_id)

    def get_by_key(self, *, workflow_run_id, step_key: str) -> WorkflowStep | None:
        stmt = select(WorkflowStep).where(
            WorkflowStep.workflow_run_id == workflow_run_id,
            WorkflowStep.step_key == step_key,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_run(self, *, workflow_run_id) -> list[WorkflowStep]:
        stmt = (
            select(WorkflowStep)
            .where(WorkflowStep.workflow_run_id == workflow_run_id)
            .order_by(WorkflowStep.id.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def merge_live_progress(
        self,
        *,
        step_id,
        live_progress: dict[str, Any] | None,
        lease_extend_seconds: int = 900,
        worker_id: str | None = None,
        auto_commit: bool = True,
    ) -> WorkflowStep | None:
        """合并或清除步骤 input_json.live_progress，供运行中 UI 展示（如草稿字数重试）。"""
        row = self.get(step_id)
        if row is None:
            return None
        base = dict(row.input_json or {})
        if live_progress is None or str(live_progress.get("kind") or "").lower() == "idle":
            base.pop("live_progress", None)
        else:
            base["live_progress"] = dict(live_progress)
        row.input_json = base
        now = datetime.now(tz=timezone.utc)
        row.last_progress_at = now
        row.heartbeat_at = now
        run_row = self.db.get(WorkflowRun, row.workflow_run_id)
        if run_row is not None and str(run_row.status) == "running":
            ext = max(60, int(lease_extend_seconds))
            run_row.heartbeat_at = now
            run_row.lease_expires_at = now + timedelta(seconds=ext)
            if worker_id:
                run_row.claimed_by = worker_id.strip() or run_row.claimed_by
            if run_row.claimed_at is None:
                run_row.claimed_at = now
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def merge_checkpoint(
        self,
        *,
        step_id,
        checkpoint: dict[str, Any],
        auto_commit: bool = True,
    ) -> WorkflowStep | None:
        """合并可恢复中间产物（writer_draft 等）；reset_for_retry 默认保留。"""
        row = self.get(step_id)
        if row is None:
            return None
        base = dict(row.checkpoint_json or {})
        base.update(dict(checkpoint or {}))
        row.checkpoint_json = base
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def update_output_json(
        self,
        *,
        workflow_run_id,
        step_key: str,
        output_json: dict,
        auto_commit: bool = True,
    ) -> WorkflowStep | None:
        row = self.get_by_key(workflow_run_id=workflow_run_id, step_key=step_key)
        if row is None:
            return None
        row.output_json = dict(output_json or {})
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_ready_steps(self, *, workflow_run_id) -> list[WorkflowStep]:
        steps = self.list_by_run(workflow_run_id=workflow_run_id)
        by_key = {str(item.step_key): item for item in steps}
        out: list[WorkflowStep] = []
        for step in steps:
            if str(step.status) not in {"pending", "queued"}:
                continue
            depends_on = list(step.depends_on_keys or [])
            if all(str(by_key[key].status) == "success" for key in depends_on if key in by_key):
                out.append(step)
        return out

    def start(self, step_id, *, auto_commit: bool = True) -> WorkflowStep | None:
        row = self.get(step_id)
        if row is None:
            return None
        row.status = "running"
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.started_at = row.started_at or datetime.now(tz=timezone.utc)
        row.heartbeat_at = datetime.now(tz=timezone.utc)
        row.error_code = None
        row.error_message = None
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def succeed(self, step_id, *, output_json: dict | None = None, auto_commit: bool = True) -> WorkflowStep | None:
        row = self.get(step_id)
        if row is None:
            return None
        row.status = "success"
        row.output_json = output_json or {}
        row.checkpoint_json = {}
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
        step_id,
        *,
        error_code: str,
        error_message: str | None = None,
        auto_commit: bool = True,
    ) -> WorkflowStep | None:
        row = self.get(step_id)
        if row is None:
            return None
        row.status = "failed"
        row.error_code = error_code
        row.error_message = error_message
        row.finished_at = datetime.now(tz=timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_skipped(self, step_id, *, reason: str | None = None, auto_commit: bool = True) -> WorkflowStep | None:
        row = self.get(step_id)
        if row is None:
            return None
        row.status = "skipped"
        row.error_message = reason
        row.finished_at = datetime.now(tz=timezone.utc)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def cancel_pending_steps(self, *, workflow_run_id, auto_commit: bool = True) -> int:
        steps = self.list_by_run(workflow_run_id=workflow_run_id)
        count = 0
        for step in steps:
            if str(step.status) in {"pending", "queued", "running"}:
                step.status = "cancelled"
                step.finished_at = datetime.now(tz=timezone.utc)
                count += 1
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return count

    def reset_for_retry(self, *, workflow_run_id, auto_commit: bool = True) -> int:
        """将未完成步骤恢复为 pending，供 run 重试。"""
        steps = self.list_by_run(workflow_run_id=workflow_run_id)
        count = 0
        for step in steps:
            if str(step.status) in {"success", "skipped", "cancelled"}:
                continue
            step.status = "pending"
            step.error_code = None
            step.error_message = None
            step.started_at = None
            step.finished_at = None
            step.output_json = {}
            step.heartbeat_at = None
            step.last_progress_at = None
            count += 1
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return count
