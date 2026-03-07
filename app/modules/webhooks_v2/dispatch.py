"""Webhook event dispatch helper.

Provides a simple function to fan-out events to all matching webhooks
via the Celery deliver_webhook task.

Usage in any service module::

    from app.modules.webhooks_v2.dispatch import dispatch_webhook_event

    await dispatch_webhook_event(db, org_id, "invoice.created", {
        "invoice_id": str(invoice.id),
        "total": str(invoice.total_amount),
    })

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.webhooks_v2.models import OutboundWebhook


async def dispatch_webhook_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_type: str,
    data: dict,
) -> list[str]:
    """Queue webhook deliveries for all active webhooks subscribed to *event_type*.

    Returns list of webhook IDs that were dispatched to.
    """
    result = await db.execute(
        select(OutboundWebhook).where(
            OutboundWebhook.org_id == org_id,
            OutboundWebhook.is_active.is_(True),
        )
    )
    webhooks = result.scalars().all()
    matching = [w for w in webhooks if event_type in (w.event_types or [])]

    dispatched: list[str] = []
    for webhook in matching:
        payload = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "org_id": str(org_id),
            "data": data,
        }
        try:
            from app.tasks.webhooks import deliver_webhook

            deliver_webhook.delay(
                webhook_id=str(webhook.id),
                event_type=event_type,
                payload=payload,
            )
            dispatched.append(str(webhook.id))
        except Exception:
            # Don't let webhook dispatch failures break the main flow
            import logging
            logging.getLogger(__name__).exception(
                "Failed to queue webhook delivery for %s", webhook.id,
            )

    return dispatched
