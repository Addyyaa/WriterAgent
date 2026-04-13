from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.agent_run import AgentRun


class AgentRunRepository(BaseRepository):
    def create_run(
        self,
        *,
        trace_id: str,
        request_id: str | None,
        project_id,
        agent_name: str,
        task_type: str,
        role_id: str | None = None,
        strategy_version: str | None = None,
        prompt_hash: str | None = None,
        schema_version: str | None = None,
        input_json: dict | None = None,
        auto_commit: bool = True,
    ) -> AgentRun:
        row = AgentRun(
            trace_id=trace_id,
            request_id=request_id,
            project_id=project_id,
            agent_name=agent_name,
            task_type=task_type,
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            input_json=input_json or {},
            status="pending",
            retry_count=0,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, run_id) -> AgentRun | None:
        return self.db.get(AgentRun, run_id)

    def start(self, run_id, *, auto_commit: bool = True) -> AgentRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "running"
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def succeed(
        self,
        run_id,
        *,
        output_json: dict | None = None,
        latency_ms: int | None = None,
        auto_commit: bool = True,
    ) -> AgentRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "success"
        row.error_code = None
        if output_json is not None:
            row.output_json = output_json
        if latency_ms is not None:
            row.latency_ms = int(latency_ms)
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
        output_json: dict | None = None,
        latency_ms: int | None = None,
        auto_commit: bool = True,
    ) -> AgentRun | None:
        row = self.get(run_id)
        if row is None:
            return None
        row.status = "failed"
        row.error_code = error_code
        if output_json is not None:
            row.output_json = output_json
        if latency_ms is not None:
            row.latency_ms = int(latency_ms)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_recent(self, *, project_id=None, limit: int = 100) -> list[AgentRun]:
        if limit <= 0:
            return []
        stmt = select(AgentRun)
        if project_id is not None:
            stmt = stmt.where(AgentRun.project_id == project_id)
        stmt = stmt.order_by(AgentRun.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())
