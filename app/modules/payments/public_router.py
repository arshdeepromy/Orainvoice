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

from app.core.database import get_db_session
from app.modules.invoices.models import Invoice
from app.modules.admin.models import Organisation
from app.modules.payments.schemas import (
    PaymentPageLineItem,
    PaymentPageResponse,
    SurchargeRateInfo,
    UpdateSurchargeRequest,
    UpdateSurchargeResponse,
)
from app.modules.payments.surcharge import (
    DEFAULT_SURCHARGE_RATES,
    deserialise_rates,
    get_surcharge_for_method,
    serialise_rates,
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

    # --- Read surcharge config from org settings ---
    surcharge_enabled = bool(org_settings.get("surcharge_enabled", False))
    surcharge_rates_for_response: dict[str, SurchargeRateInfo] = {}

    if surcharge_enabled:
        raw_rates = org_settings.get("surcharge_rates", {})
        if raw_rates and isinstance(raw_rates, dict):
            try:
                deserialised = deserialise_rates(raw_rates, DEFAULT_SURCHARGE_RATES)
                serialised = serialise_rates(deserialised)
                surcharge_rates_for_response = {
                    method: SurchargeRateInfo(
                        percentage=rate["percentage"],
                        fixed=rate["fixed"],
                        enabled=rate["enabled"],
                    )
                    for method, rate in serialised.items()
                }
            except Exception:
                logger.warning(
                    "Malformed surcharge_rates for org %s — falling back to empty rates",
                    org.id,
                )
                surcharge_rates_for_response = {}
        else:
            logger.warning(
                "surcharge_enabled=True but surcharge_rates missing/invalid for org %s",
                org.id,
            )
            surcharge_rates_for_response = {}

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
        surcharge_enabled=surcharge_enabled,
        surcharge_rates=surcharge_rates_for_response,
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

        # Get publishable key from DB config (same source as secret key)
        from app.integrations.stripe_billing import get_stripe_publishable_key
        publishable_key = await get_stripe_publishable_key()

        return PaymentPageResponse(
            **base_data,
            is_paid=False,
            is_payable=True,
            client_secret=client_secret,
            connected_account_id=connected_account_id,
            publishable_key=publishable_key or None,
        )

    # --- Fallback for any other status (e.g. refunded, partially_refunded) ---
    return PaymentPageResponse(
        **base_data,
        is_paid=False,
        is_payable=False,
        error_message=f"This invoice has status '{invoice.status}' and cannot be paid online.",
    )


# ── Payment confirmation endpoint ─────────────────────────────────────────
# Called by the frontend after stripe.confirmCardPayment() succeeds.
# Verifies the PaymentIntent status with Stripe and records the payment
# if the webhook hasn't already done so.  This is the synchronous fallback
# for when webhooks are delayed or undeliverable (e.g. local dev).
# ISSUE-111


@router.post(
    "/pay/{token}/confirm",
    status_code=200,
    responses={
        404: {"description": "Invalid payment link"},
        410: {"description": "Payment link expired"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Confirm payment after client-side Stripe confirmation",
)
async def confirm_payment(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify PaymentIntent status with Stripe and record the payment.

    This endpoint is called by the frontend after ``stripe.confirmCardPayment()``
    returns success.  It retrieves the PaymentIntent from Stripe to verify
    its status, then records the payment using the same logic as the webhook
    handler.  Idempotent — if the webhook already recorded the payment, this
    is a no-op.

    ISSUE-111: Webhooks can't reach localhost in dev, and may be delayed
    in production.  This provides a synchronous confirmation path.
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
                content={"detail": "This payment link has expired."},
            )
        return JSONResponse(status_code=404, content={"detail": "Invalid payment link"})

    if payment_token is None:
        return JSONResponse(status_code=404, content={"detail": "Invalid payment link"})

    # --- Fetch invoice ---
    invoice_result = await db.execute(
        select(Invoice).where(Invoice.id == payment_token.invoice_id)
    )
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        return JSONResponse(status_code=404, content={"detail": "Invalid payment link"})

    # Already paid or not payable — nothing to do
    if invoice.status not in ("issued", "partially_paid", "overdue"):
        return {"status": "already_processed", "invoice_status": invoice.status}

    # No PaymentIntent on this invoice — can't verify
    pi_id = invoice.stripe_payment_intent_id
    if not pi_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No payment intent associated with this invoice."},
        )

    # --- Fetch org's Connected Account ---
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == payment_token.org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None or not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Stripe account not configured."},
        )

    # --- Retrieve PaymentIntent from Stripe to verify status ---
    import httpx
    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        return JSONResponse(
            status_code=500,
            content={"detail": "Payment verification unavailable."},
        )

    try:
        async with httpx.AsyncClient() as client:
            stripe_resp = await client.get(
                f"https://api.stripe.com/v1/payment_intents/{pi_id}",
                auth=(secret_key, ""),
                headers={"Stripe-Account": org.stripe_connect_account_id},
            )
            stripe_resp.raise_for_status()
            pi_data = stripe_resp.json()
    except Exception:
        logger.exception("Failed to retrieve PaymentIntent %s from Stripe", pi_id)
        return JSONResponse(
            status_code=502,
            content={"detail": "Could not verify payment with Stripe. Please wait a moment and refresh."},
        )

    # --- Check PaymentIntent status ---
    pi_status = pi_data.get("status", "")
    if pi_status != "succeeded":
        return {
            "status": "pending",
            "payment_intent_status": pi_status,
            "message": "Payment has not been confirmed by Stripe yet.",
        }

    # --- Record the payment (same logic as webhook handler) ---
    # Use handle_stripe_webhook with a synthetic event — this is idempotent.
    # Surcharge data (surcharge_amount, surcharge_method, original_amount)
    # is already present in pi_data["metadata"] because the update-surcharge
    # endpoint stored it on the PaymentIntent.  handle_stripe_webhook()
    # extracts it automatically — no additional extraction needed here.
    from app.modules.payments.service import handle_stripe_webhook

    result = await handle_stripe_webhook(
        db,
        event_type="payment_intent.succeeded",
        event_data=pi_data,
    )

    return {
        "status": result.get("status", "unknown"),
        "invoice_status": result.get("invoice_status", invoice.status),
        "payment_id": result.get("payment_id"),
        "amount": result.get("amount"),
        "surcharge_amount": result.get("surcharge_amount"),
        "payment_method_type": result.get("payment_method_type"),
    }


# ── Surcharge update endpoint ──────────────────────────────────────────────
# Called by the frontend when the customer selects or changes a payment
# method on the public payment page.  Computes the surcharge server-side
# and updates the Stripe PaymentIntent amount accordingly.
# Requirements: 5.1, 5.2, 5.3, 5.5


@router.post(
    "/pay/{token}/update-surcharge",
    response_model=UpdateSurchargeResponse,
    status_code=200,
    responses={
        404: {"description": "Invalid payment link"},
        410: {"description": "Payment link expired"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Update PaymentIntent surcharge for selected payment method",
)
async def update_surcharge(
    token: str,
    body: UpdateSurchargeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Compute surcharge and update the Stripe PaymentIntent amount.

    This is a public endpoint — no authentication required.  Security is
    provided by the payment token.  The frontend sends only the
    ``payment_method_type``; the backend computes the surcharge server-side
    to prevent client-side tampering.

    Requirements: 5.1, 5.2, 5.3, 5.5
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
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    if payment_token is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # --- Fetch invoice ---
    invoice_result = await db.execute(
        select(Invoice).where(Invoice.id == payment_token.invoice_id)
    )
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # --- Fetch organisation ---
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == payment_token.org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Invalid payment link"},
        )

    # --- Read surcharge config from org settings ---
    org_settings = org.settings or {}
    surcharge_enabled = org_settings.get("surcharge_enabled", False)
    raw_rates = org_settings.get("surcharge_rates", {})

    # --- Compute surcharge server-side ---
    from decimal import Decimal

    balance_due = invoice.balance_due or Decimal("0")

    if surcharge_enabled and raw_rates:
        rates = deserialise_rates(raw_rates, DEFAULT_SURCHARGE_RATES)
        surcharge = get_surcharge_for_method(
            balance_due, body.payment_method_type, rates,
        )
    else:
        surcharge = Decimal("0.00")

    total_amount = balance_due + surcharge

    # --- Update PaymentIntent via Stripe API ---
    pi_id = invoice.stripe_payment_intent_id
    pi_updated = False

    if pi_id and org.stripe_connect_account_id:
        import httpx
        from app.integrations.stripe_billing import get_stripe_secret_key

        secret_key = await get_stripe_secret_key()
        if secret_key:
            new_amount_cents = int(total_amount * 100)
            payload = {
                "amount": str(new_amount_cents),
                "metadata[surcharge_amount]": str(surcharge),
                "metadata[surcharge_method]": body.payment_method_type,
                "metadata[original_amount]": str(balance_due),
            }
            try:
                async with httpx.AsyncClient() as client:
                    stripe_resp = await client.post(
                        f"https://api.stripe.com/v1/payment_intents/{pi_id}",
                        data=payload,
                        auth=(secret_key, ""),
                        headers={
                            "Stripe-Account": org.stripe_connect_account_id,
                        },
                    )
                    stripe_resp.raise_for_status()
                    pi_updated = True
            except Exception:
                logger.exception(
                    "Failed to update PaymentIntent %s with surcharge", pi_id,
                )
                return JSONResponse(
                    status_code=502,
                    content={
                        "detail": (
                            "Could not update payment amount with Stripe. "
                            "Please try again."
                        )
                    },
                )

    return UpdateSurchargeResponse(
        surcharge_amount=str(surcharge),
        total_amount=str(total_amount),
        payment_intent_updated=pi_updated,
    )
