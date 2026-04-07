"""Payment router — cash payment recording endpoint.

Requirements: 24.1, 24.2, 24.3
"""

from __future__ import annotations

import uuid

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.payments.schemas import (
    CashPaymentRequest,
    CashPaymentResponse,
    PaymentHistoryResponse,
    RefundRequest,
    RefundResponse,
    StripePaymentLinkRequest,
    StripePaymentLinkResponse,
    StripeWebhookResponse,
)
from app.modules.payments.service import (
    record_cash_payment,
    generate_stripe_payment_link,
    get_payment_history,
    handle_stripe_webhook,
    process_refund,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = request.client.host if request.client else None
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.post(
    "/cash",
    response_model=CashPaymentResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Record a cash payment against an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def record_cash_payment_endpoint(
    payload: CashPaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Record a cash payment. Updates invoice status to Paid or Partially Paid.

    After recording, sends an updated invoice email to the customer.

    Requirements: 24.1, 24.2, 24.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await record_cash_payment(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=payload.invoice_id,
            amount=payload.amount,
            notes=payload.notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Prepare Xero sync data BEFORE committing (session is still open)
    from app.modules.invoices.models import Invoice as _Invoice
    payment_info = result.get("payment", {})
    _inv_result = await db.execute(
        select(_Invoice.invoice_number).where(_Invoice.id == payload.invoice_id)
    )
    _inv_number = _inv_result.scalar_one_or_none() or ""
    _xero_payment_data = {
        "id": str(payment_info.get("id", "")),
        "invoice_number": _inv_number,
        "amount": float(payment_info.get("amount", 0)),
        "date": payment_info.get("created_at"),
        "account_code": "800",
        "reference": f"Payment {payment_info.get('id', '')}",
    }

    # Commit the payment so the fresh email session sees updated balances
    await db.commit()

    # Send updated invoice email in background (fire-and-forget)
    import asyncio as _asyncio
    async def _send_payment_email():
        try:
            from app.core.database import async_session_factory, _set_rls_org_id
            from app.modules.invoices.service import email_invoice
            async with async_session_factory() as fresh_session:
                async with fresh_session.begin():
                    await _set_rls_org_id(fresh_session, str(org_uuid))
                    await email_invoice(fresh_session, org_id=org_uuid, invoice_id=payload.invoice_id)
            logger.info("Payment receipt email sent for invoice %s", payload.invoice_id)
        except Exception as email_exc:
            logger.warning("Payment email failed for invoice %s: %s", payload.invoice_id, email_exc)
    _asyncio.create_task(_send_payment_email())

    # Fire-and-forget: sync payment to Xero if connected
    from app.modules.accounting.auto_sync import sync_payment_bg
    _asyncio.create_task(sync_payment_bg(org_uuid, _xero_payment_data))

    return result


@router.post(
    "/stripe/create-link",
    response_model=StripePaymentLinkResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Generate a Stripe payment link for an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_stripe_payment_link_endpoint(
    payload: StripePaymentLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a secure Stripe Checkout payment link.

    Supports partial payments for deposit scenarios. The link can
    optionally be sent to the customer via email or SMS.

    Requirements: 25.3, 25.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await generate_stripe_payment_link(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=payload.invoice_id,
            amount=payload.amount,
            send_via=payload.send_via,
            ip_address=ip_address,
        )
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post(
    "/stripe/webhook",
    response_model=StripeWebhookResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid signature or payload"},
    },
    summary="Stripe webhook receiver",
)
async def stripe_webhook_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Receive and process Stripe webhook events.

    This endpoint does NOT require authentication — Stripe calls it
    directly.  The request is verified using the Stripe webhook signing
    secret (HMAC-SHA256).

    Requirements: 25.4
    """
    from app.integrations.stripe_connect import verify_webhook_signature

    # Read raw body for signature verification
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing Stripe-Signature header"},
        )

    try:
        event = verify_webhook_signature(
            payload=payload,
            sig_header=sig_header,
            webhook_secret=settings.stripe_webhook_secret,
        )
    except ValueError as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})

    try:
        result = await handle_stripe_webhook(
            db,
            event_type=event_type,
            event_data=event_data,
        )
        return result
    except Exception as exc:
        logger.exception("Error processing Stripe webhook: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": f"Webhook processing error: {exc}"},
        )


@router.get(
    "/invoice/{invoice_id}/history",
    response_model=PaymentHistoryResponse,
    status_code=200,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get full payment history for an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_payment_history_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the full payment history for an invoice.

    Includes all payments and refunds with date, amount, method,
    and the user who recorded each event.

    Requirements: 26.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_payment_history(
            db,
            org_id=org_uuid,
            invoice_id=invoice_id,
        )
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post(
    "/refund",
    response_model=RefundResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Process a refund (cash or Stripe)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def process_refund_endpoint(
    payload: RefundRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Process a refund against an invoice.

    For Stripe refunds, the refund is processed via the Stripe API.
    For cash refunds, the refund is recorded manually with a note.
    Both update the invoice balance and are logged in the audit trail.

    Requirements: 26.2, 26.3, 26.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await process_refund(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=payload.invoice_id,
            amount=payload.amount,
            method=payload.method,
            notes=payload.notes,
            ip_address=ip_address,
        )
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
