"""Connexus webhook endpoints for incoming SMS and delivery status updates.

No auth middleware — these are external callbacks from the Connexus API.
Payloads are validated via Pydantic schemas; duplicate messageIds are
silently ignored (idempotent).

Endpoints:
  POST /api/webhooks/connexus/incoming  — receive inbound SMS
  POST /api/webhooks/connexus/status    — receive delivery status updates

Requirements: 5.1, 5.5, 5.6, 5.7, 6.1, 6.5, 6.6
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.database import async_session_factory
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


@router.post("/incoming")
async def incoming_sms(request: Request):
    """Receive an incoming SMS from Connexus.

    Accepts the raw request so that WebSMS verification POSTs (empty or
    minimal test payloads) receive a 200 instead of a 422 validation error.
    Real payloads are validated via Pydantic before processing.

    Requirements: 5.1, 5.5, 5.6, 5.7
    """
    try:
        body = await request.json()
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

    Accepts the raw request so that WebSMS verification POSTs (empty or
    minimal test payloads) receive a 200 instead of a 422 validation error.
    Real payloads are validated via Pydantic before processing.

    Requirements: 6.1, 6.5, 6.6
    """
    try:
        body = await request.json()
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
