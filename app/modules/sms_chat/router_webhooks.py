"""Connexus webhook endpoints for incoming SMS and delivery status updates.

No auth middleware — these are external callbacks from the Connexus API.
Payloads are validated via Pydantic schemas; duplicate messageIds are
silently ignored (idempotent).

HMAC-SHA256 signature verification is enforced when a webhook secret is
configured (``connexus_webhook_secret``).  When no secret is set the
endpoints operate in *dev mode* and skip verification.

Endpoints:
  POST /api/webhooks/connexus/incoming  — receive inbound SMS
  POST /api/webhooks/connexus/status    — receive delivery status updates

Requirements: 4.1, 4.2, 4.3, 4.5, 5.1, 5.5, 5.6, 5.7, 6.1, 6.5, 6.6
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import settings
from app.core.database import async_session_factory
from app.core.webhook_security import verify_webhook_signature
from app.modules.sms_chat.schemas import (
    DeliveryStatusWebhookPayload,
    IncomingWebhookPayload,
)
from app.modules.sms_chat.service import (
    handle_delivery_status,
    handle_incoming_sms,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks/connexus", tags=["webhooks"])


def _verify_connexus_signature(request: Request, body: bytes) -> bool:
    """Verify HMAC signature if webhook secret is configured.

    Returns ``True`` when the signature is valid **or** when no secret is
    configured (dev mode).  Returns ``False`` and logs a warning on failure.
    """
    secret = settings.connexus_webhook_secret
    if not secret:
        return True  # No secret configured — skip verification (dev mode)
    signature = request.headers.get("x-connexus-signature", "")
    if not verify_webhook_signature(body, signature, secret):
        logger.warning("Connexus webhook HMAC verification failed")
        return False
    return True


@router.post("/incoming")
async def incoming_sms(request: Request):
    """Receive an incoming SMS from Connexus.

    Reads the raw body first for HMAC verification, then parses JSON.
    Accepts empty or minimal test payloads as verification pings.

    Requirements: 4.1, 4.2, 4.3, 5.1, 5.5, 5.6, 5.7
    """
    raw_body = await request.body()

    # --- HMAC signature verification (Requirements 4.1, 4.2, 4.3) ---
    if not _verify_connexus_signature(request, raw_body):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid webhook signature"},
        )

    # --- Parse JSON body ---
    try:
        import json
        body = json.loads(raw_body) if raw_body else None
    except Exception:
        # Empty body or non-JSON — treat as verification ping
        logger.info("Incoming webhook: empty/non-JSON body — returning 200 (verification)")
        return {"status": "ok"}

    if not body or not body.get("messageId"):
        # Verification or test payload — acknowledge without processing
        logger.info("Incoming webhook: no messageId — returning 200 (verification)")
        return {"status": "ok"}

    try:
        payload = IncomingWebhookPayload(**body)
    except ValidationError as exc:
        logger.warning("Incoming SMS webhook validation failed: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    try:
        async with async_session_factory() as db:
            async with db.begin():
                await handle_incoming_sms(db, payload.model_dump(by_alias=True))
    except ValueError as exc:
        logger.warning("Incoming SMS webhook rejected: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception:
        # Log but still return 200 so Connexus doesn't retry endlessly
        logger.exception("Unexpected error processing incoming SMS webhook")

    return {"status": "ok"}


@router.post("/status")
async def delivery_status(request: Request):
    """Receive a delivery status update from Connexus.

    Reads the raw body first for HMAC verification, then parses JSON.
    Accepts empty or minimal test payloads as verification pings.

    Requirements: 4.1, 4.2, 4.3, 6.1, 6.5, 6.6
    """
    raw_body = await request.body()

    # --- HMAC signature verification (Requirements 4.1, 4.2, 4.3) ---
    if not _verify_connexus_signature(request, raw_body):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid webhook signature"},
        )

    # --- Parse JSON body ---
    try:
        import json
        body = json.loads(raw_body) if raw_body else None
    except Exception:
        logger.info("Status webhook: empty/non-JSON body — returning 200 (verification)")
        return {"status": "ok"}

    if not body or not body.get("messageId"):
        logger.info("Status webhook: no messageId — returning 200 (verification)")
        return {"status": "ok"}

    try:
        payload = DeliveryStatusWebhookPayload(**body)
    except ValidationError as exc:
        logger.warning("Delivery status webhook validation failed: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    try:
        async with async_session_factory() as db:
            async with db.begin():
                await handle_delivery_status(db, payload.model_dump())
    except ValueError as exc:
        logger.warning("Delivery status webhook rejected: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception:
        # Log but still return 200 so Connexus doesn't retry endlessly
        logger.exception("Unexpected error processing delivery status webhook")

    return {"status": "ok"}
