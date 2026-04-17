"""Public payment page router — unauthenticated access via payment token.

Serves the GET /api/v1/public/pay/{token} endpoint that returns invoice
preview data, org branding, and Stripe configuration for the custom
payment page.

Requirements: 3.3, 3.4, 3.5, 6.1, 6.2, 6.3, 6.4, 6.5, 9.3, 9.4
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.database import get_db_session
from app.modules.invoices.models import Invoice
from app.modules.admin.models import Organisation
from app.modules.payments.schemas import (
    PaymentPageLineItem,
    PaymentPageResponse,
)
from app.modules.payments.token_service import validate_payment_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Rate limit: 20 requests per minute per IP for the payment page endpoint.
_PAYMENT_PAGE_RATE_LIMIT = 20
_PAYMENT_PAGE_WINDOW = 60  # seconds


async def _check_payment_page_rate_limit(request: Request) -> bool:
    """Check per-IP rate limit for the payment page endpoint.

    Returns True if the request is allowed, False if rate-limited.
    When rate-limited, sends a 429 response directly.
    Uses Redis sliding-window, same pattern as the global rate limiter.
    Falls open if Redis is unavailable.
    """
    try:
        from app.core.redis import redis_pool

        from app.middleware.auth import get_client_ip

        client_ip = get_client_ip(request) or "unknown"
        key = f"rl:payment_page:ip:{client_ip}"
        now = time.time()

        from app.middleware.rate_limit import _check_rate_limit

        allowed, retry_after = await _check_rate_limit(
            redis_pool, key, _PAYMENT_PAGE_RATE_LIMIT, now
        )
        if not allowed:
            return False
        return True
    except Exception:
        # Fail open — allow the request if Redis is unavailable
        logger.warning("Payment page rate limit check failed — allowing request")
        return True


# Payable invoice statuses
_PAYABLE_STATUSES = {"issued", "partially_paid", "overdue"}


@router.get(
    "/pay/{token}",
    response_model=PaymentPageResponse,
    status_code=200,
    responses={
        404: {"description": "Invalid payment link"},
        410: {"description": "Payment link expired"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Public payment page data for a payment token",
)
async def get_payment_page(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate a payment token and return invoice preview + Stripe config.

    This is a public endpoint — no authentication required.
    The ``/api/v1/public/`` prefix is already in ``PUBLIC_PREFIXES``.

    Requirements: 3.3, 3.4, 3.5, 6.1, 6.2, 6.3, 6.4, 6.5, 9.3, 9.4
    """
    # --- Rate limit check ---
    allowed = await _check_payment_page_rate_limit(request)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please try again later."},
            headers={"Retry-After": str(_PAYMENT_PAGE_WINDOW)},
        )

    # --- Token validation ---
    try:
        payment_token = await validate_payment_token(db, token=token)
    except ValueError as exc:
        if str(exc) == "expired":
            return JSONResponse(
                status_code=410,
                content={
                    "detail": (
                        "This payment link has expired. "
                        "Please contact the business for a new link."
                    )
                },
            )
        # Any other ValueError — treat as invalid
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    if payment_token is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # --- Fetch invoice with line items ---
    invoice_result = await db.execute(
        select(Invoice)
        .options(selectinload(Invoice.line_items))
        .where(Invoice.id == payment_token.invoice_id)
    )
    invoice = invoice_result.scalar_one_or_none()

    if invoice is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # --- Fetch organisation for branding ---
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == payment_token.org_id)
    )
    org = org_result.scalar_one_or_none()

    if org is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # Extract branding from org settings JSONB
    org_settings = org.settings or {}
    org_logo_url = org_settings.get("logo_url")
    org_primary_colour = org_settings.get("primary_colour")

    # --- Build line items from invoice relationship ---
    line_items = [
        PaymentPageLineItem(
            description=li.description,
            quantity=li.quantity,
            unit_price=li.unit_price,
            line_total=li.line_total,
        )
        for li in (invoice.line_items or [])
    ]

    # --- Base response data (always returned) ---
    base_data = dict(
        org_name=org.name,
        org_logo_url=org_logo_url,
        org_primary_colour=org_primary_colour,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        currency=invoice.currency or "NZD",
        line_items=line_items,
        subtotal=invoice.subtotal,
        gst_amount=invoice.gst_amount,
        total=invoice.total,
        amount_paid=invoice.amount_paid,
        balance_due=invoice.balance_due,
        status=invoice.status,
    )

    # --- Invoice already paid ---
    if invoice.status == "paid":
        return PaymentPageResponse(
            **base_data,
            is_paid=True,
            is_payable=False,
        )

    # --- Invoice voided or draft — not payable ---
    if invoice.status in ("voided", "draft"):
        error_msg = (
            "This invoice has been voided and is no longer payable."
            if invoice.status == "voided"
            else "This invoice is still in draft and cannot be paid yet."
        )
        return PaymentPageResponse(
            **base_data,
            is_paid=False,
            is_payable=False,
            error_message=error_msg,
        )

    # --- Payable invoice — return Stripe config ---
    if invoice.status in _PAYABLE_STATUSES:
        # client_secret comes from the PaymentIntent stored on the invoice
        client_secret = None
        if invoice.stripe_payment_intent_id:
            # The client_secret is the PI ID + "_secret_..." suffix.
            # We need to retrieve it from Stripe or it should be stored.
            # Per the design, the client_secret is returned from
            # create_payment_intent() and should be available.
            # For now, we fetch it from the invoice's invoice_data_json
            # where it may have been stored, or retrieve from Stripe.
            invoice_data = invoice.invoice_data_json or {}
            client_secret = invoice_data.get("stripe_client_secret")

        # Connected account ID (safe to expose — equivalent to publishable key)
        connected_account_id = org.stripe_connect_account_id

        return PaymentPageResponse(
            **base_data,
            is_paid=False,
            is_payable=True,
            client_secret=client_secret,
            connected_account_id=connected_account_id,
            publishable_key=settings.stripe_publishable_key or None,
        )

    # --- Fallback for any other status (e.g. refunded, partially_refunded) ---
    return PaymentPageResponse(
        **base_data,
        is_paid=False,
        is_payable=False,
        error_message=f"This invoice has status '{invoice.status}' and cannot be paid online.",
    )
