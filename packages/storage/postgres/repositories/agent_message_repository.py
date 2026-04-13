from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.agent_message import AgentMessage


class AgentMessageRepository(BaseRepository):
    def create_message(
        self,
        *,
        workflow_run_id,
        role: str,
        content: str,
        workflow_step_id=None,
        sender: str | None = None,
        receiver: str | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> AgentMessage:
        row = AgentMessage(
            workflow_run_id=workflow_run_id,
            workflow_step_id=workflow_step_id,
            role=role,
            sender=sender,
            receiver=receiver,
            content=content,
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_by_run(self, *, workflow_run_id, limit: int = 500) -> list[AgentMessage]:
        stmt = (
            select(AgentMessage)
            .where(AgentMessage.workflow_run_id == workflow_run_id)
            .order_by(AgentMessage.created_at.asc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())
