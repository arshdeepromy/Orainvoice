"""Outbound webhook management service layer.

Provides:
- register()                — create a new webhook subscription
- update()                  — update an existing webhook
- delete()                  — remove a webhook
- dispatch_event()          — fan-out an event to all matching webhooks
- test_webhook()            — send a sample payload to a webhook URL
- get_delivery_log()        — retrieve delivery history for a webhook
- auto_disable_after_failures() — disable webhook after 50 consecutive failures

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.webhook_security import sign_webhook_payload
from app.modules.webhooks_v2.models import OutboundWebhook, WebhookDeliveryLog

AUTO_DISABLE_THRESHOLD = 50
DELIVERY_TIMEOUT_SECONDS = 10


class WebhookService:
    """Encapsulates all outbound webhook business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def register(
        self,
        org_id: uuid.UUID,
        *,
        target_url: str,
        event_types: list[str],
        is_active: bool = True,
    ) -> OutboundWebhook:
        """Register a new outbound webhook for an organisation."""
        signing_secret = secrets.token_hex(32)
        webhook = OutboundWebhook(
            org_id=org_id,
            target_url=target_url,
            event_types=event_types,
            secret_encrypted=signing_secret.encode("utf-8"),
            is_active=is_active,
        )
        self.db.add(webhook)
        await self.db.flush()
        return webhook

    async def get(self, webhook_id: uuid.UUID) -> OutboundWebhook | None:
        result = await self.db.execute(
            select(OutboundWebhook).where(OutboundWebhook.id == webhook_id)
        )
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: uuid.UUID) -> list[OutboundWebhook]:
        result = await self.db.execute(
            select(OutboundWebhook)
            .where(OutboundWebhook.org_id == org_id)
            .order_by(OutboundWebhook.created_at.desc())
        )
        return list(result.scalars().all())

    async def update(
        self,
        webhook_id: uuid.UUID,
        *,
        target_url: str | None = None,
        event_types: list[str] | None = None,
        is_active: bool | None = None,
    ) -> OutboundWebhook | None:
        webhook = await self.get(webhook_id)
        if webhook is None:
            return None
        if target_url is not None:
            webhook.target_url = target_url
        if event_types is not None:
            webhook.event_types = event_types
        if is_active is not None:
            webhook.is_active = is_active
        webhook.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return webhook

    async def delete(self, webhook_id: uuid.UUID) -> bool:
        webhook = await self.get(webhook_id)
        if webhook is None:
            return False
        await self.db.delete(webhook)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Dispatch & delivery
    # ------------------------------------------------------------------

    async def get_webhooks_for_event(
        self, org_id: uuid.UUID, event_type: str,
    ) -> list[OutboundWebhook]:
        """Return all active webhooks for *org_id* subscribed to *event_type*."""
        result = await self.db.execute(
            select(OutboundWebhook).where(
                OutboundWebhook.org_id == org_id,
                OutboundWebhook.is_active.is_(True),
            )
        )
        webhooks = result.scalars().all()
        return [w for w in webhooks if event_type in (w.event_types or [])]

    async def dispatch_event(
        self,
        org_id: uuid.UUID,
        event_type: str,
        payload: dict,
    ) -> list[uuid.UUID]:
        """Fan-out an event to all matching webhooks.

        Returns list of webhook IDs that were dispatched to.
        Actual delivery is handled by the Celery task.
        """
        webhooks = await self.get_webhooks_for_event(org_id, event_type)
        dispatched_ids: list[uuid.UUID] = []
        for webhook in webhooks:
            # Create a pending delivery log entry
            log = WebhookDeliveryLog(
                webhook_id=webhook.id,
                event_type=event_type,
                payload=payload,
                status="pending",
            )
            self.db.add(log)
            dispatched_ids.append(webhook.id)
        await self.db.flush()
        return dispatched_ids

    async def deliver_single(
        self,
        webhook: OutboundWebhook,
        event_type: str,
        payload: dict,
        retry_count: int = 0,
    ) -> WebhookDeliveryLog:
        """Attempt to deliver a webhook payload via HTTP POST."""
        payload_bytes = json.dumps(payload).encode("utf-8")
        secret = webhook.secret_encrypted.decode("utf-8")
        signature = sign_webhook_payload(payload_bytes, secret)

        headers = {
            "Content-Type": "application/json",
            "X-OraInvoice-Signature": signature,
            "X-OraInvoice-Event": event_type,
        }

        start = time.monotonic()
        log = WebhookDeliveryLog(
            webhook_id=webhook.id,
            event_type=event_type,
            payload=payload,
            retry_count=retry_count,
            status="pending",
        )

        try:
            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    webhook.target_url, content=payload_bytes, headers=headers,
                )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.response_status = resp.status_code
            log.response_time_ms = elapsed_ms

            if 200 <= resp.status_code < 300:
                log.status = "success"
                webhook.consecutive_failures = 0
            else:
                log.status = "failed"
                log.error_details = resp.text[:500] if resp.text else None
                webhook.consecutive_failures += 1
        except (ConnectionError, TimeoutError, OSError) as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            log.response_time_ms = elapsed_ms
            log.status = "failed"
            log.error_details = str(exc)[:500]
            webhook.consecutive_failures += 1

        webhook.last_delivery_at = datetime.now(timezone.utc)
        webhook.updated_at = datetime.now(timezone.utc)
        self.db.add(log)
        await self.db.flush()
        return log

    # ------------------------------------------------------------------
    # Test webhook
    # ------------------------------------------------------------------

    async def test_webhook(self, webhook_id: uuid.UUID) -> dict:
        """Send a sample event payload to the webhook URL and return result."""
        webhook = await self.get(webhook_id)
        if webhook is None:
            return {"success": False, "error": "Webhook not found"}

        sample_payload = {
            "event": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "org_id": str(webhook.org_id),
            "data": {"message": "This is a test webhook delivery from OraInvoice"},
        }

        log = await self.deliver_single(webhook, "test", sample_payload)
        return {
            "success": log.status == "success",
            "response_status": log.response_status,
            "response_time_ms": log.response_time_ms,
            "error": log.error_details,
        }

    # ------------------------------------------------------------------
    # Delivery log
    # ------------------------------------------------------------------

    async def get_delivery_log(
        self,
        webhook_id: uuid.UUID,
        limit: int = 50,
    ) -> list[WebhookDeliveryLog]:
        result = await self.db.execute(
            select(WebhookDeliveryLog)
            .where(WebhookDeliveryLog.webhook_id == webhook_id)
            .order_by(WebhookDeliveryLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Auto-disable
    # ------------------------------------------------------------------

    async def auto_disable_after_failures(
        self, webhook_id: uuid.UUID,
    ) -> bool:
        """Disable webhook if consecutive failures >= threshold.

        Returns True if the webhook was disabled.
        """
        webhook = await self.get(webhook_id)
        if webhook is None or not webhook.is_active:
            return False

        if webhook.consecutive_failures >= AUTO_DISABLE_THRESHOLD:
            webhook.is_active = False
            webhook.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            return True
        return False
