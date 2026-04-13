from __future__ import annotations

from packages.core.tracing import get_request_id, get_trace_id
from packages.storage.postgres.repositories.audit_event_repository import AuditEventRepository


class AuditService:
    def __init__(self, *, repo: AuditEventRepository) -> None:
        self.repo = repo

    def log(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        project_id=None,
        user_id=None,
        payload_json: dict | None = None,
    ) -> None:
        self.repo.create_event(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            user_id=user_id,
            trace_id=get_trace_id(),
            request_id=get_request_id(),
            payload_json=payload_json or {},
        )
