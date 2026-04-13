from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import uuid4

from packages.storage.postgres.repositories.webhook_delivery_repository import (
    WebhookDeliveryRepository,
)
from packages.storage.postgres.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)


class WebhookService:
    def __init__(
        self,
        *,
        subscription_repo: WebhookSubscriptionRepository,
        delivery_repo: WebhookDeliveryRepository,
    ) -> None:
        self.subscription_repo = subscription_repo
        self.delivery_repo = delivery_repo

    @staticmethod
    def sign_payload(payload_json: dict[str, Any], secret: str) -> str:
        body = json.dumps(payload_json, ensure_ascii=False, separators=(",", ":"))
        digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def enqueue_event(
        self,
        *,
        project_id,
        event_type: str,
        payload_json: dict[str, Any],
        trace_id: str | None = None,
        request_id: str | None = None,
    ) -> int:
        subscriptions = self.subscription_repo.list_active_by_project_event(
            project_id=project_id,
            event_type=event_type,
        )
        created = 0
        for sub in subscriptions:
            signature = self.sign_payload(payload_json, str(sub.secret))
            self.delivery_repo.create(
                event_id=str(uuid4()),
                subscription_id=sub.id,
                project_id=project_id,
                event_type=event_type,
                payload_json=payload_json,
                signature=signature,
                max_attempts=int(sub.max_retries or 8),
                trace_id=trace_id,
                request_id=request_id,
            )
            created += 1
        return created
