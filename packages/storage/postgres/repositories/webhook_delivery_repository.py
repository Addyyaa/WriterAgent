from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from .base import BaseRepository
from packages.storage.postgres.models.webhook_delivery import WebhookDelivery


class WebhookDeliveryRepository(BaseRepository):
    def create(
        self,
        *,
        event_id: str,
        subscription_id,
        project_id,
        event_type: str,
        payload_json: dict,
        signature: str,
        max_attempts: int = 8,
        trace_id: str | None = None,
        request_id: str | None = None,
        auto_commit: bool = True,
    ) -> WebhookDelivery:
        row = WebhookDelivery(
            event_id=event_id,
            subscription_id=subscription_id,
            project_id=project_id,
            event_type=event_type,
            payload_json=dict(payload_json or {}),
            signature=signature,
            status="pending",
            attempt_count=0,
            max_attempts=max(1, int(max_attempts)),
            next_attempt_at=datetime.now(tz=timezone.utc),
            trace_id=trace_id,
            request_id=request_id,
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, delivery_id) -> WebhookDelivery | None:
        return self.db.get(WebhookDelivery, delivery_id)

    def claim_pending(self, *, limit: int = 20) -> list[WebhookDelivery]:
        now = datetime.now(tz=timezone.utc)
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(["pending", "retrying"]),
                or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= now),
            )
            .order_by(WebhookDelivery.created_at.asc())
            .limit(max(1, int(limit)))
            .with_for_update(skip_locked=True)
        )
        rows = list(self.db.execute(stmt).scalars().all())
        if rows:
            self.db.flush()
        return rows

    def mark_success(
        self,
        delivery_id,
        *,
        response_status: int | None = None,
        response_body: str | None = None,
        auto_commit: bool = True,
    ) -> WebhookDelivery | None:
        row = self.get(delivery_id)
        if row is None:
            return None
        row.status = "success"
        row.response_status = response_status
        row.response_body = response_body
        row.error_message = None
        row.delivered_at = datetime.now(tz=timezone.utc)
        row.next_attempt_at = None
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def mark_retry(
        self,
        delivery_id,
        *,
        error_message: str,
        response_status: int | None = None,
        response_body: str | None = None,
        auto_commit: bool = True,
    ) -> WebhookDelivery | None:
        row = self.get(delivery_id)
        if row is None:
            return None
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.response_status = response_status
        row.response_body = response_body
        row.error_message = error_message

        if row.attempt_count >= int(row.max_attempts or 1):
            row.status = "dead"
            row.next_attempt_at = None
        else:
            row.status = "retrying"
            delay = min(3600, 2 ** min(row.attempt_count, 10))
            row.next_attempt_at = datetime.now(tz=timezone.utc) + timedelta(seconds=delay)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def list_by_project(self, *, project_id, limit: int = 100) -> list[WebhookDelivery]:
        stmt = (
            select(WebhookDelivery)
            .where(WebhookDelivery.project_id == project_id)
            .order_by(WebhookDelivery.created_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.db.execute(stmt).scalars().all())
