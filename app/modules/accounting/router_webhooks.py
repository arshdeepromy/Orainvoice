"""Xero webhook receiver — public endpoint, no auth required.

Mounted at /api/webhooks/xero in main.py (outside the org-scoped
auth middleware, same pattern as Connexus SMS webhooks).

Validates x-xero-signature using HMAC-SHA256 (base64) with the
webhook key stored in platform_settings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks/xero", tags=["xero-webhooks"])


@router.post("")
async def xero_webhook_endpoint(request: Request):
    """Receive Xero webhook notifications.

    Validates the x-xero-signature header, responds 200 for valid
    intent-to-receive, and processes events in the background.
    """
    from app.modules.platform_settings.service import get_setting

    body = await request.body()
    signature = request.headers.get("x-xero-signature", "")

    # Fetch webhook key from encrypted platform settings
    async with async_session_factory() as db:
        webhook_key = await get_setting(db, "XERO_WEBHOOK_KEY")

    if not webhook_key:
        logger.warning("Xero webhook received but XERO_WEBHOOK_KEY not configured")
        return JSONResponse(status_code=401, content={})

    # Xero uses base64-encoded HMAC-SHA256
    expected = base64.b64encode(
        _hmac.new(webhook_key.encode(), body, hashlib.sha256).digest()
    ).decode()

    if not _hmac.compare_digest(expected, signature):
        logger.warning("Xero webhook signature mismatch")
        return JSONResponse(status_code=401, content={})

    # Signature valid — parse payload
    try:
        payload = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=400, content={})

    events = payload.get("events", [])
    if not events:
        # Empty events = intent-to-receive validation — respond 200
        return JSONResponse(status_code=200, content={})

    # Process events in background (fire-and-forget)
    import asyncio
    asyncio.create_task(_process_events(events))

    return JSONResponse(status_code=200, content={})


async def _process_events(events: list) -> None:
    """Background: process Xero webhook events."""
    from sqlalchemy import select
    from app.modules.accounting.models import AccountingIntegration
    from app.modules.accounting.service import _log_sync
    import uuid as _uuid

    try:
        async with async_session_factory() as session:
            async with session.begin():
                for event in events:
                    event_type = event.get("eventType", "")
                    event_category = event.get("eventCategory", "")
                    tenant_id = event.get("tenantId", "")
                    resource_id = event.get("resourceId", "")

                    if event_category == "INVOICE":
                        entity_type = "invoice"
                    elif event_category == "CONTACT":
                        entity_type = "contact"
                    elif event_category == "PAYMENT":
                        entity_type = "payment"
                    else:
                        logger.info("Ignoring Xero webhook category: %s", event_category)
                        continue

                    stmt = select(AccountingIntegration).where(
                        AccountingIntegration.provider == "xero",
                        AccountingIntegration.xero_tenant_id == tenant_id,
                        AccountingIntegration.is_connected == True,  # noqa: E712
                    )
                    result = await session.execute(stmt)
                    conn = result.scalar_one_or_none()
                    if conn is None:
                        logger.warning("Xero webhook: no connection for tenant %s", tenant_id)
                        continue

                    try:
                        entity_uuid = _uuid.UUID(resource_id) if resource_id else _uuid.uuid4()
                    except ValueError:
                        entity_uuid = _uuid.uuid4()

                    await _log_sync(
                        session,
                        org_id=conn.org_id,
                        provider="xero",
                        entity_type=entity_type,
                        entity_id=entity_uuid,
                        status="synced",
                        external_id=resource_id,
                        error_message=f"Inbound webhook: {event_type}",
                    )
                    logger.info("Xero webhook: %s %s tenant=%s", event_type, event_category, tenant_id)
    except Exception:
        logger.exception("Failed to process Xero webhook events")
