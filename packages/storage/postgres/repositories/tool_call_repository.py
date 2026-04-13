from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.tool_call import ToolCall


class ToolCallRepository(BaseRepository):
    def create_call(
        self,
        *,
        trace_id: str,
        agent_run_id,
        tool_name: str,
        role_id: str | None = None,
        strategy_version: str | None = None,
        prompt_hash: str | None = None,
        schema_version: str | None = None,
        input_json: dict | None = None,
        auto_commit: bool = True,
    ) -> ToolCall:
        row = ToolCall(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            role_id=role_id,
            strategy_version=strategy_version,
            prompt_hash=prompt_hash,
            schema_version=schema_version,
            input_json=input_json or {},
            output_json={},
            status="pending",
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, call_id) -> ToolCall | None:
        return self.db.get(ToolCall, call_id)

    def start(self, call_id, *, auto_commit: bool = True) -> ToolCall | None:
        row = self.get(call_id)
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
        call_id,
        *,
        output_json: dict | None = None,
        latency_ms: int | None = None,
        auto_commit: bool = True,
    ) -> ToolCall | None:
        row = self.get(call_id)
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
        call_id,
        *,
        error_code: str,
        output_json: dict | None = None,
        latency_ms: int | None = None,
        auto_commit: bool = True,
    ) -> ToolCall | None:
        row = self.get(call_id)
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

    def list_by_agent_run(self, *, agent_run_id, limit: int = 200) -> list[ToolCall]:
        if limit <= 0:
            return []
        stmt = (
            select(ToolCall)
            .where(ToolCall.agent_run_id == agent_run_id)
            .order_by(ToolCall.created_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
