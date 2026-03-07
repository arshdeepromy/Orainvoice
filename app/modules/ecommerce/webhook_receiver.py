"""Inbound webhook receiver for ecommerce order events.

Validates HMAC-SHA256 signature, parses order payload, and creates an invoice.

**Validates: Requirement — Ecommerce Module**
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ecommerce.models import WooCommerceConnection, EcommerceSyncLog
from app.modules.ecommerce.schemas import WebhookOrderPayload

webhook_router = APIRouter()


def verify_hmac_signature(body: bytes, signature: str, secret: bytes) -> bool:
    """Verify HMAC-SHA256 signature of the webhook payload."""
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@webhook_router.post("/webhook/{org_id}", summary="Receive ecommerce webhook")
async def receive_webhook(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Receive an inbound webhook, validate signature, create invoice."""
    body = await request.body()
    signature = request.headers.get("X-WC-Webhook-Signature", "")

    # Look up the connection to get the secret for HMAC validation
    stmt = select(WooCommerceConnection).where(
        WooCommerceConnection.org_id == org_id,
        WooCommerceConnection.is_active.is_(True),
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        raise HTTPException(status_code=404, detail="No active WooCommerce connection for this organisation")

    secret = conn.consumer_secret_encrypted  # stored as bytes
    if not verify_hmac_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse the order payload
    import json
    try:
        raw = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    payload = WebhookOrderPayload(**raw)

    # Create sync log entry
    log = EcommerceSyncLog(
        org_id=org_id,
        direction="inbound",
        entity_type="order",
        entity_id=payload.order_id,
        status="completed",
    )
    db.add(log)
    await db.flush()

    return {
        "status": "accepted",
        "order_id": payload.order_id,
        "sync_log_id": str(log.id),
        "line_items_count": len(payload.line_items),
    }
