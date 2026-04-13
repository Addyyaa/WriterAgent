from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.audit_event import AuditEvent


class AuditEventRepository(BaseRepository):
    def create_event(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        project_id=None,
        user_id=None,
        trace_id: str | None = None,
        request_id: str | None = None,
        payload_json: dict | None = None,
        auto_commit: bool = True,
    ) -> AuditEvent:
        row = AuditEvent(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            user_id=user_id,
            trace_id=trace_id,
            request_id=request_id,
            payload_json=payload_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_by_project(self, *, project_id, limit: int = 200) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())
