"""Async webhook delivery with retry logic.

Retry schedule: 1 min, 5 min, 15 min, 1 hr, 4 hr (5 retries total).
Called directly — no Celery.

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.database import async_session_factory
from app.core.webhook_security import sign_webhook_payload

logger = logging.getLogger(__name__)

RETRY_DELAYS = [60, 300, 900, 3600, 14400]
MAX_RETRIES = 5
DELIVERY_TIMEOUT = 10


async def deliver_webhook(
    webhook_id: str,
    event_type: str,
    payload: dict,
    retry_count: int = 0,
) -> dict:
    """Deliver a single outbound webhook. Retries are handled by the caller."""
    from sqlalchemy import select
    from app.modules.webhooks_v2.models import OutboundWebhook, WebhookDeliveryLog

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(OutboundWebhook).where(OutboundWebhook.id == webhook_id))
            webhook = result.scalar_one_or_none()
            if webhook is None:
                return {"status": "skipped", "reason": "webhook_not_found"}
            if not webhook.is_active:
                return {"status": "skipped", "reason": "webhook_inactive"}

            payload_bytes = json.dumps(payload).encode("utf-8")
            secret = webhook.secret_encrypted.decode("utf-8")
            signature = sign_webhook_payload(payload_bytes, secret)

            headers = {"Content-Type": "application/json", "X-OraInvoice-Signature": signature, "X-OraInvoice-Event": event_type}
            log = WebhookDeliveryLog(webhook_id=webhook.id, event_type=event_type, payload=payload, retry_count=retry_count, status="pending")

            start = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
                    resp = await client.post(webhook.target_url, content=payload_bytes, headers=headers)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                log.response_status = resp.status_code
                log.response_time_ms = elapsed_ms
                if 200 <= resp.status_code < 300:
                    log.status = "success"
                    webhook.consecutive_failures = 0
                else:
                    log.status = "failed"
                    log.error_details = (resp.text or "")[:500]
                    webhook.consecutive_failures += 1
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                log.response_time_ms = elapsed_ms
                log.status = "failed"
                log.error_details = str(exc)[:500]
                webhook.consecutive_failures += 1

            webhook.last_delivery_at = datetime.now(timezone.utc)
            webhook.updated_at = datetime.now(timezone.utc)
            session.add(log)

            disabled = False
            if webhook.consecutive_failures >= 50 and webhook.is_active:
                webhook.is_active = False
                disabled = True
                logger.warning("Webhook %s auto-disabled after %d consecutive failures", webhook_id, webhook.consecutive_failures)

            return {"status": log.status, "response_status": log.response_status, "retry_count": retry_count, "consecutive_failures": webhook.consecutive_failures, "disabled": disabled, "org_id": str(webhook.org_id), "target_url": webhook.target_url}
