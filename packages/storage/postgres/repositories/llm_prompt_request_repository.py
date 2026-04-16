from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session


class LlmPromptRequestRepository:
    """运维查询：按 llm_task_id 读取发往 LLM 的上下文快照。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, request_id: UUID) -> dict[str, Any] | None:
        row = self.db.execute(
            sa.text(
                """
                SELECT id, created_at, trace_id, workflow_run_id, workflow_step_id,
                       role_id, step_key, workflow_type, model, provider_label,
                       system_prompt, user_prompt, system_chars, user_chars,
                       metadata_json, prompt_guard_applied
                FROM llm_prompt_requests
                WHERE id = :id
                """
            ),
            {"id": request_id},
        ).mappings().first()
        if row is None:
            return None
        d = dict(row)
        ca = d.get("created_at")
        if ca is not None:
            d["created_at"] = ca.isoformat().replace("+00:00", "Z")
        for k in ("id", "workflow_run_id", "workflow_step_id"):
            v = d.get(k)
            if v is not None:
                d[k] = str(v)
        return d
