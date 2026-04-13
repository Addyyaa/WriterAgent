from __future__ import annotations

from sqlalchemy import select

from .base import BaseRepository
from packages.storage.postgres.models.webhook_subscription import WebhookSubscription


class WebhookSubscriptionRepository(BaseRepository):
    def create(
        self,
        *,
        project_id,
        event_type: str,
        target_url: str,
        secret: str,
        created_by=None,
        status: str = "active",
        max_retries: int = 8,
        timeout_seconds: int = 10,
        headers_json: dict | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> WebhookSubscription:
        row = WebhookSubscription(
            project_id=project_id,
            event_type=event_type,
            target_url=target_url,
            secret=secret,
            created_by=created_by,
            status=status,
            max_retries=max(1, int(max_retries)),
            timeout_seconds=max(1, int(timeout_seconds)),
            headers_json=headers_json or {},
            metadata_json=metadata_json or {},
        )
        self.db.add(row)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def get(self, subscription_id) -> WebhookSubscription | None:
        return self.db.get(WebhookSubscription, subscription_id)

    def list_by_project(self, *, project_id, include_paused: bool = True) -> list[WebhookSubscription]:
        stmt = select(WebhookSubscription).where(WebhookSubscription.project_id == project_id)
        if not include_paused:
            stmt = stmt.where(WebhookSubscription.status == "active")
        stmt = stmt.order_by(WebhookSubscription.created_at.desc())
        return list(self.db.execute(stmt).scalars().all())

    def list_active_by_project_event(self, *, project_id, event_type: str) -> list[WebhookSubscription]:
        stmt = (
            select(WebhookSubscription)
            .where(
                WebhookSubscription.project_id == project_id,
                WebhookSubscription.event_type == event_type,
                WebhookSubscription.status == "active",
            )
            .order_by(WebhookSubscription.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def update(
        self,
        subscription_id,
        *,
        status: str | None = None,
        max_retries: int | None = None,
        timeout_seconds: int | None = None,
        headers_json: dict | None = None,
        metadata_json: dict | None = None,
        auto_commit: bool = True,
    ) -> WebhookSubscription | None:
        row = self.get(subscription_id)
        if row is None:
            return None
        if status is not None:
            row.status = status
        if max_retries is not None:
            row.max_retries = max(1, int(max_retries))
        if timeout_seconds is not None:
            row.timeout_seconds = max(1, int(timeout_seconds))
        if headers_json is not None:
            row.headers_json = dict(headers_json)
        if metadata_json is not None:
            row.metadata_json = dict(metadata_json)
        if auto_commit:
            self.db.commit()
            self.db.refresh(row)
        else:
            self.db.flush()
        return row

    def delete(self, subscription_id, *, auto_commit: bool = True) -> bool:
        row = self.get(subscription_id)
        if row is None:
            return False
        self.db.delete(row)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
        return True
