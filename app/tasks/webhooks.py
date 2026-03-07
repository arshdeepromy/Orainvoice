"""Celery tasks for outbound webhook delivery with retry logic.

Retry schedule: 1 min, 5 min, 15 min, 1 hr, 4 hr (5 retries total).

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import httpx

from app.core.database import async_session_factory
from app.core.webhook_security import sign_webhook_payload
from app.tasks import celery_app

logger = logging.getLogger(__name__)

# Retry delays in seconds: 1min, 5min, 15min, 1hr, 4hr
RETRY_DELAYS = [60, 300, 900, 3600, 14400]
MAX_RETRIES = 5
DELIVERY_TIMEOUT = 10


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _deliver_webhook_async(
    webhook_id: str, event_type: str, payload: dict, retry_count: int,
) -> dict:
    """Perform the actual HTTP delivery and record the result."""
    from sqlalchemy import select
    from app.modules.webhooks_v2.models import OutboundWebhook, WebhookDeliveryLog

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboundWebhook).where(
                    OutboundWebhook.id == webhook_id,
                )
            )
            webhook = result.scalar_one_or_none()
            if webhook is None:
                return {"status": "skipped", "reason": "webhook_not_found"}

            if not webhook.is_active:
                return {"status": "skipped", "reason": "webhook_inactive"}

            payload_bytes = json.dumps(payload).encode("utf-8")
            secret = webhook.secret_encrypted.decode("utf-8")
            signature = sign_webhook_payload(payload_bytes, secret)

            headers = {
                "Content-Type": "application/json",
                "X-OraInvoice-Signature": signature,
                "X-OraInvoice-Event": event_type,
            }

            log = WebhookDeliveryLog(
                webhook_id=webhook.id,
                event_type=event_type,
                payload=payload,
                retry_count=retry_count,
                status="pending",
            )

            start = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as client:
                    resp = await client.post(
                        webhook.target_url,
                        content=payload_bytes,
                        headers=headers,
                    )
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

            # Check auto-disable threshold
            disabled = False
            if webhook.consecutive_failures >= 50 and webhook.is_active:
                webhook.is_active = False
                disabled = True
                logger.warning(
                    "Webhook %s auto-disabled after %d consecutive failures",
                    webhook_id, webhook.consecutive_failures,
                )

            return {
                "status": log.status,
                "response_status": log.response_status,
                "retry_count": retry_count,
                "consecutive_failures": webhook.consecutive_failures,
                "disabled": disabled,
                "org_id": str(webhook.org_id),
                "target_url": webhook.target_url,
            }


@celery_app.task(
    name="app.tasks.webhooks.deliver_webhook",
    bind=True,
    queue="default",
    acks_late=True,
    max_retries=MAX_RETRIES,
)
def deliver_webhook(
    self,
    webhook_id: str,
    event_type: str,
    payload: dict,
    retry_count: int = 0,
) -> dict:
    """Deliver a single outbound webhook with exponential backoff retries.

    Retry schedule: 1min, 5min, 15min, 1hr, 4hr.
    """
    logger.info(
        "Delivering webhook %s event=%s retry=%d",
        webhook_id, event_type, retry_count,
    )

    result = _run_async(
        _deliver_webhook_async(webhook_id, event_type, payload, retry_count)
    )

    # Send email notification to Org_Admin when webhook is auto-disabled
    if result.get("disabled"):
        try:
            from app.tasks.notifications import send_email_task

            send_email_task.delay(
                org_id=result.get("org_id", ""),
                log_id="",
                to_email="",  # resolved by notification service from org admin
                to_name="Org Admin",
                subject="Webhook auto-disabled due to repeated failures",
                html_body=(
                    f"<p>Your webhook endpoint <strong>{result.get('target_url', '')}</strong> "
                    f"has been automatically disabled after 50 consecutive delivery failures.</p>"
                    f"<p>Please check the endpoint and re-enable it from Settings → Webhooks.</p>"
                ),
                text_body=(
                    f"Your webhook endpoint {result.get('target_url', '')} "
                    f"has been automatically disabled after 50 consecutive delivery failures. "
                    f"Please check the endpoint and re-enable it from Settings → Webhooks."
                ),
            )
        except Exception:
            logger.exception("Failed to send webhook auto-disable notification")

    if result["status"] == "failed" and retry_count < MAX_RETRIES:
        delay = RETRY_DELAYS[retry_count] if retry_count < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
        logger.warning(
            "Webhook %s delivery failed (attempt %d), retrying in %ds",
            webhook_id, retry_count + 1, delay,
        )
        self.retry(
            args=[webhook_id, event_type, payload, retry_count + 1],
            countdown=delay,
            max_retries=MAX_RETRIES,
        )

    return result
