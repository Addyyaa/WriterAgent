from __future__ import annotations

import json

import httpx

from packages.storage.postgres.repositories.webhook_delivery_repository import (
    WebhookDeliveryRepository,
)
from packages.storage.postgres.repositories.webhook_subscription_repository import (
    WebhookSubscriptionRepository,
)


class WebhookDeliveryRunner:
    def __init__(
        self,
        *,
        delivery_repo: WebhookDeliveryRepository,
        subscription_repo: WebhookSubscriptionRepository,
    ) -> None:
        self.delivery_repo = delivery_repo
        self.subscription_repo = subscription_repo

    def run_once(self, *, limit: int = 50) -> dict:
        rows = self.delivery_repo.claim_pending(limit=limit)
        attempted = 0
        success = 0
        failed = 0

        for row in rows:
            attempted += 1
            sub = self.subscription_repo.get(row.subscription_id)
            if sub is None or str(sub.status) != "active":
                self.delivery_repo.mark_retry(row.id, error_message="subscription 不可用")
                failed += 1
                continue

            headers = {
                "Content-Type": "application/json",
                "X-WriterAgent-Event": str(row.event_type),
                "X-WriterAgent-Event-Id": str(row.event_id),
                "X-WriterAgent-Signature": str(row.signature or ""),
            }
            for key, value in dict(sub.headers_json or {}).items():
                if not key:
                    continue
                headers[str(key)] = str(value)

            body = json.dumps(dict(row.payload_json or {}), ensure_ascii=False)
            try:
                resp = httpx.post(
                    str(sub.target_url),
                    content=body.encode("utf-8"),
                    headers=headers,
                    timeout=max(1, int(sub.timeout_seconds or 10)),
                )
                if 200 <= resp.status_code < 300:
                    self.delivery_repo.mark_success(
                        row.id,
                        response_status=int(resp.status_code),
                        response_body=resp.text[:4000],
                    )
                    success += 1
                else:
                    self.delivery_repo.mark_retry(
                        row.id,
                        error_message=f"status={resp.status_code}",
                        response_status=int(resp.status_code),
                        response_body=resp.text[:4000],
                    )
                    failed += 1
            except Exception as exc:
                self.delivery_repo.mark_retry(
                    row.id,
                    error_message=str(exc),
                )
                failed += 1

        return {
            "attempted": attempted,
            "success": success,
            "failed": failed,
        }
