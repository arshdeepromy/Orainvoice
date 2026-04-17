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
    ManagePayoutsResponse,
    OnlinePaymentsDisconnectResponse,
    OnlinePaymentsStatusResponse,
    PaymentHistoryResponse,
    PaymentMethodsResponse,
    PaymentMethodInfo,
    PayoutInfoResponse,
    RefundRequest,
    RefundResponse,
    RegeneratePaymentLinkResponse,
    StripePaymentLinkRequest,
    StripePaymentLinkResponse,
    StripeWebhookResponse,
    UpdatePaymentMethodsRequest,
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
    ip_address = getattr(request.state, "client_ip", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.get(
    "/online-payments/status",
    response_model=OnlinePaymentsStatusResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get Stripe Connect online payments status for the org",
    dependencies=[require_role("org_admin", "global_admin")],
)
async def get_online_payments_status(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the org's Stripe Connect status for the Online Payments settings page.

    The account ID is masked — only the last 4 characters are exposed,
    never the full ID.

    Requirements: 1.6, 1.7, 2.6
    """
    from decimal import Decimal
    from app.modules.admin.models import Organisation, IntegrationConfig
    from app.integrations.stripe_billing import get_stripe_connect_client_id
    from app.core.encryption import envelope_decrypt_str
    import json

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Fetch organisation
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    # Determine connection status and mask account ID
    is_connected = org.stripe_connect_account_id is not None
    account_id_last4 = ""
    if is_connected and org.stripe_connect_account_id:
        account_id_last4 = org.stripe_connect_account_id[-4:]

    # Check if Stripe Connect client ID is configured
    connect_client_id = await get_stripe_connect_client_id()
    connect_client_id_configured = bool(connect_client_id)

    # Read application_fee_percent from Stripe integration config
    # (get_application_fee_percent helper is added in Task 2.2 — read directly for now)
    application_fee_percent = None
    try:
        config_result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
        )
        config_row = config_result.scalar_one_or_none()
        if config_row:
            data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            fee_str = data.get("application_fee_percent")
            if fee_str is not None:
                application_fee_percent = Decimal(str(fee_str))
    except Exception:
        logger.warning("Failed to read application_fee_percent from Stripe config")

    # Fetch account name from Stripe when connected
    account_name = ""
    if is_connected and org.stripe_connect_account_id:
        account_name = await _fetch_stripe_account_name(org.stripe_connect_account_id)

    return OnlinePaymentsStatusResponse(
        is_connected=is_connected,
        account_id_last4=account_id_last4,
        account_name=account_name,
        connect_client_id_configured=connect_client_id_configured,
        application_fee_percent=application_fee_percent,
    )


@router.post(
    "/online-payments/disconnect",
    response_model=OnlinePaymentsDisconnectResponse,
    status_code=200,
    responses={
        400: {"description": "No Stripe account connected"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Disconnect the org's Stripe Connect account",
    dependencies=[require_role("org_admin")],
)
async def disconnect_online_payments(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Disconnect the org's Stripe Connect account.

    Clears the connected account from the organisation record and writes
    an audit log entry.  The previous account ID is masked in the response
    — only the last 4 characters are returned.

    Requirements: 3.2, 3.4
    """
    from app.modules.admin.models import Organisation
    from app.core.audit import write_audit_log

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Fetch organisation
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    # Return 400 if no Stripe account is connected
    if not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe account is connected."},
        )

    # Capture previous account ID for audit, then clear it
    previous_account_id = org.stripe_connect_account_id
    previous_account_last4 = previous_account_id[-4:] if len(previous_account_id) >= 4 else previous_account_id

    org.stripe_connect_account_id = None
    await db.flush()
    await db.refresh(org)

    # Write audit log entry
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="stripe_connect.disconnected",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={"stripe_connect_account_id_last4": previous_account_last4},
        after_value={"stripe_connect_account_id": None},
        ip_address=ip_address,
    )

    return OnlinePaymentsDisconnectResponse(
        message="Stripe account disconnected successfully",
        previous_account_last4=previous_account_last4,
    )


# ---------------------------------------------------------------------------
# Payment method metadata — maps Stripe payment method types to display info
# ---------------------------------------------------------------------------

PAYMENT_METHOD_DISPLAY = {
    "card": {
        "name": "Credit & Debit Cards",
        "description": "Visa, Mastercard, American Express, UnionPay",
        "always_on": True,
        "card_brands": ["visa", "mastercard", "amex", "unionpay"],
    },
    "apple_pay": {
        "name": "Apple Pay",
        "description": "Available on Safari and Apple devices",
        "always_on": False,
        "card_brands": [],
    },
    "google_pay": {
        "name": "Google Pay",
        "description": "Available on Chrome and Android devices",
        "always_on": False,
        "card_brands": [],
    },
    "link": {
        "name": "Stripe Link",
        "description": "One-click checkout for returning customers",
        "always_on": False,
        "card_brands": [],
    },
    "afterpay_clearpay": {
        "name": "Afterpay",
        "description": "Buy now, pay later in 4 instalments",
        "always_on": False,
        "card_brands": [],
    },
    "klarna": {
        "name": "Klarna",
        "description": "Pay later or in instalments",
        "always_on": False,
        "card_brands": [],
    },
}

# Wallet methods that are automatically available when cards are enabled
# (Stripe enables these via the card capability, not as separate capabilities)
WALLET_METHODS = {"apple_pay", "google_pay"}


async def _fetch_stripe_account_name(stripe_account_id: str) -> str:
    """Fetch the business name from a connected Stripe account.

    Tries multiple fields in order:
    1. business_profile.name
    2. settings.dashboard.display_name
    3. company.name
    4. email (last resort)
    Returns empty string on any error (fail gracefully).
    """
    import httpx
    from app.integrations.stripe_billing import get_stripe_secret_key

    try:
        secret_key = await get_stripe_secret_key()
        if not secret_key:
            return ""

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.stripe.com/v1/accounts/{stripe_account_id}",
                auth=(secret_key, ""),
            )
            resp.raise_for_status()
            data = resp.json()

        # Try each name field in priority order
        name = (
            (data.get("business_profile") or {}).get("name")
            or (data.get("settings") or {}).get("dashboard", {}).get("display_name")
            or (data.get("company") or {}).get("name")
            or data.get("email")
            or ""
        )
        return name
    except Exception:
        logger.warning(
            "Failed to fetch account name for Stripe account %s",
            stripe_account_id,
        )
        return ""


async def _fetch_available_payment_methods(
    stripe_account_id: str,
) -> list[dict]:
    """Fetch available payment methods from the connected Stripe account.

    Queries the Stripe Account API to get the account's active capabilities,
    then maps them to our display metadata. Wallets (Apple Pay, Google Pay)
    are included when card_payments capability is active.

    Returns a list of dicts with type, name, description, always_on, card_brands.
    """
    import httpx
    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        logger.warning("Stripe secret key not configured — returning default payment methods")
        return [{"type": "card", **PAYMENT_METHOD_DISPLAY["card"]}]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.stripe.com/v1/accounts/{stripe_account_id}",
                auth=(secret_key, ""),
            )
            resp.raise_for_status()
            account_data = resp.json()
    except Exception:
        logger.exception(
            "Failed to fetch Stripe account %s — returning default payment methods",
            stripe_account_id,
        )
        return [{"type": "card", **PAYMENT_METHOD_DISPLAY["card"]}]

    # Extract active capabilities from the account
    capabilities = account_data.get("capabilities", {})
    available_methods: list[dict] = []
    seen_types: set[str] = set()

    # Map Stripe capabilities to our payment method types
    capability_to_type = {
        "card_payments": "card",
        "link_payments": "link",
        "afterpay_clearpay_payments": "afterpay_clearpay",
        "klarna_payments": "klarna",
    }

    for capability_name, method_type in capability_to_type.items():
        status = capabilities.get(capability_name)
        if status == "active" and method_type in PAYMENT_METHOD_DISPLAY:
            if method_type not in seen_types:
                available_methods.append({
                    "type": method_type,
                    **PAYMENT_METHOD_DISPLAY[method_type],
                })
                seen_types.add(method_type)

    # If card_payments is active, also add wallet methods (Apple Pay, Google Pay)
    if capabilities.get("card_payments") == "active":
        for wallet_type in ["apple_pay", "google_pay"]:
            if wallet_type not in seen_types and wallet_type in PAYMENT_METHOD_DISPLAY:
                available_methods.append({
                    "type": wallet_type,
                    **PAYMENT_METHOD_DISPLAY[wallet_type],
                })
                seen_types.add(wallet_type)

    # Ensure card is always first if present
    available_methods.sort(key=lambda m: (m["type"] != "card", m["type"]))

    # Fallback: if no capabilities found, at least show card
    if not available_methods:
        available_methods = [{"type": "card", **PAYMENT_METHOD_DISPLAY["card"]}]

    return available_methods


@router.get(
    "/online-payments/payment-methods",
    response_model=PaymentMethodsResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Get available payment methods and their enabled status",
    dependencies=[require_role("org_admin")],
)
async def get_payment_methods(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the list of available payment method types with their enabled status.

    Fetches the connected account's capabilities from Stripe to determine
    which payment methods are actually available for the merchant, then
    overlays the org's enabled/disabled preferences.
    """
    from app.modules.admin.models import Organisation

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe account connected."},
        )

    # Fetch available methods from Stripe based on account capabilities
    available = await _fetch_available_payment_methods(org.stripe_connect_account_id)

    # Read enabled methods from org settings, default to ["card"]
    org_settings = org.settings or {}
    enabled_methods: list[str] = org_settings.get("enabled_payment_methods", ["card"])

    # Cards are always enabled regardless of stored value
    if "card" not in enabled_methods:
        enabled_methods.append("card")

    payment_methods = [
        PaymentMethodInfo(
            type=pm["type"],
            name=pm["name"],
            description=pm["description"],
            enabled=pm["type"] in enabled_methods,
            always_on=pm.get("always_on", False),
            card_brands=pm.get("card_brands", []),
        )
        for pm in available
    ]

    return PaymentMethodsResponse(payment_methods=payment_methods)


@router.put(
    "/online-payments/payment-methods",
    response_model=PaymentMethodsResponse,
    status_code=200,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Update enabled payment methods",
    dependencies=[require_role("org_admin")],
)
async def update_payment_methods(
    payload: UpdatePaymentMethodsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update which payment methods are enabled for the org.

    Cards ('card') cannot be disabled — they are always included.
    Only methods available on the connected Stripe account can be enabled.
    Stores the preference in org.settings['enabled_payment_methods'].
    """
    from app.modules.admin.models import Organisation
    from app.core.audit import write_audit_log
    from sqlalchemy.orm.attributes import flag_modified

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe account connected."},
        )

    # Fetch available methods from Stripe to validate
    available = await _fetch_available_payment_methods(org.stripe_connect_account_id)
    valid_types = {pm["type"] for pm in available}

    for method in payload.enabled_methods:
        if method not in valid_types:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Payment method '{method}' is not available on your Stripe account."},
            )

    # Ensure 'card' is always included
    enabled_methods = list(set(payload.enabled_methods) | {"card"})

    # Read previous value for audit
    org_settings = dict(org.settings or {})
    previous_methods = org_settings.get("enabled_payment_methods", ["card"])

    # Update settings
    org_settings["enabled_payment_methods"] = enabled_methods
    org.settings = org_settings
    flag_modified(org, "settings")

    await db.flush()
    await db.refresh(org)

    # Write audit log
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="payment_methods.updated",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={"enabled_payment_methods": previous_methods},
        after_value={"enabled_payment_methods": enabled_methods},
        ip_address=ip_address,
    )

    # Build response using Stripe-fetched available methods
    payment_methods = [
        PaymentMethodInfo(
            type=pm["type"],
            name=pm["name"],
            description=pm["description"],
            enabled=pm["type"] in enabled_methods,
            always_on=pm.get("always_on", False),
            card_brands=pm.get("card_brands", []),
        )
        for pm in available
    ]

    return PaymentMethodsResponse(payment_methods=payment_methods)


@router.get(
    "/online-payments/payout-info",
    response_model=PayoutInfoResponse,
    status_code=200,
    responses={
        400: {"description": "No Stripe account connected"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Get payout bank details and schedule for the connected Stripe account",
    dependencies=[require_role("org_admin")],
)
async def get_payout_info(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the connected account's payout bank details and schedule.

    Fetches the Stripe account to extract external_accounts (bank info)
    and payout schedule settings. Bank account numbers are masked — only
    the last 4 digits are exposed.
    """
    import httpx
    from app.modules.admin.models import Organisation
    from app.integrations.stripe_billing import get_stripe_secret_key

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe account connected."},
        )

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        return JSONResponse(
            status_code=500,
            content={"detail": "Stripe secret key not configured."},
        )

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.stripe.com/v1/accounts/{org.stripe_connect_account_id}",
                auth=(secret_key, ""),
            )
            resp.raise_for_status()
            account_data = resp.json()
    except Exception:
        logger.exception(
            "Failed to fetch Stripe account %s for payout info",
            org.stripe_connect_account_id,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to fetch payout information from Stripe."},
        )

    # Extract bank account info from external_accounts
    bank_name = ""
    bank_last4 = ""
    bank_currency = ""
    external_accounts = (account_data.get("external_accounts") or {}).get("data") or []
    if external_accounts:
        bank = external_accounts[0]
        bank_name = bank.get("bank_name") or ""
        bank_last4 = bank.get("last4") or ""
        bank_currency = (bank.get("currency") or "").upper()

    # Extract payout schedule
    payout_settings = (account_data.get("settings") or {}).get("payouts") or {}
    schedule = payout_settings.get("schedule") or {}
    interval = schedule.get("interval") or ""
    delay_days = schedule.get("delay_days") or 0

    # Build human-readable schedule string
    if interval == "daily":
        payout_schedule = f"Daily ({delay_days}-day delay)"
    elif interval == "weekly":
        day = schedule.get("weekly_anchor") or ""
        payout_schedule = f"Weekly ({day.capitalize()})" if day else "Weekly"
    elif interval == "monthly":
        anchor = schedule.get("monthly_anchor")
        if anchor:
            suffix = "th"
            if anchor == 1:
                suffix = "st"
            elif anchor == 2:
                suffix = "nd"
            elif anchor == 3:
                suffix = "rd"
            payout_schedule = f"Monthly ({anchor}{suffix})"
        else:
            payout_schedule = "Monthly"
    elif interval == "manual":
        payout_schedule = "Manual"
    else:
        payout_schedule = interval.capitalize() if interval else ""

    payouts_enabled = account_data.get("payouts_enabled") or False

    return PayoutInfoResponse(
        payouts_enabled=payouts_enabled,
        bank_name=bank_name,
        bank_last4=bank_last4,
        bank_currency=bank_currency,
        payout_schedule=payout_schedule,
        payout_interval=interval,
        payout_delay_days=delay_days,
    )


@router.post(
    "/online-payments/manage-payouts",
    response_model=ManagePayoutsResponse,
    status_code=200,
    responses={
        400: {"description": "No Stripe account connected"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Create a Stripe Account Link for managing payouts",
    dependencies=[require_role("org_admin")],
)
async def manage_payouts(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a Stripe Account Link for the connected account and return the URL.

    Uses account_update type for already-onboarded accounts, falling back
    to account_onboarding if needed. The return and refresh URLs point
    back to the Online Payments settings page.
    """
    import httpx
    from app.modules.admin.models import Organisation
    from app.integrations.stripe_billing import get_stripe_secret_key

    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe account connected."},
        )

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        return JSONResponse(
            status_code=500,
            content={"detail": "Stripe secret key not configured."},
        )

    frontend_base = (settings.frontend_base_url or "http://localhost:5173").rstrip("/")
    return_url = f"{frontend_base}/settings?tab=online-payments"
    refresh_url = f"{frontend_base}/settings?tab=online-payments"

    # Try account_update first (for already-onboarded accounts),
    # fall back to account_onboarding
    link_url = ""
    for link_type in ("account_update", "account_onboarding"):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.stripe.com/v1/account_links",
                    auth=(secret_key, ""),
                    data={
                        "account": org.stripe_connect_account_id,
                        "type": link_type,
                        "return_url": return_url,
                        "refresh_url": refresh_url,
                    },
                )
                resp.raise_for_status()
                link_data = resp.json()
                link_url = link_data.get("url") or ""
                if link_url:
                    break
        except httpx.HTTPStatusError:
            # account_update may fail if not fully onboarded — try next type
            continue
        except Exception:
            logger.exception(
                "Failed to create Stripe Account Link (%s) for account %s",
                link_type,
                org.stripe_connect_account_id,
            )
            continue

    if not link_url:
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to create Stripe account management link."},
        )

    return ManagePayoutsResponse(url=link_url)


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
    from app.integrations.stripe_billing import get_stripe_webhook_secret

    # Read raw body for signature verification
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing Stripe-Signature header"},
        )

    # Load webhook signing secret from DB (not env var)
    webhook_secret = await get_stripe_webhook_secret()
    if not webhook_secret:
        logger.error("Stripe webhook secret not configured — cannot verify signature")
        return JSONResponse(
            status_code=500,
            content={"detail": "Webhook verification not configured"},
        )

    try:
        event = verify_webhook_signature(
            payload=payload,
            sig_header=sig_header,
            webhook_secret=webhook_secret,
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
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Prepare Xero refund sync data while session is still open
    import asyncio as _asyncio
    from app.modules.invoices.models import Invoice as _Invoice
    from app.modules.customers.models import Customer as _Customer

    refund_record = result.get("refund")
    # Query invoice number and customer_id
    _inv_result = await db.execute(
        select(_Invoice.invoice_number, _Invoice.customer_id).where(
            _Invoice.id == payload.invoice_id
        )
    )
    _inv_row = _inv_result.one_or_none()
    _inv_number = _inv_row.invoice_number if _inv_row else ""
    _customer_id = _inv_row.customer_id if _inv_row else None

    # Resolve customer name (same pattern as create_invoice_endpoint)
    _customer_name = "Unknown"
    if _customer_id:
        try:
            _cust_result = await db.execute(
                select(
                    _Customer.display_name,
                    _Customer.first_name,
                    _Customer.last_name,
                ).where(_Customer.id == _customer_id)
            )
            _cust_row = _cust_result.one_or_none()
            if _cust_row:
                _customer_name = (
                    _cust_row.display_name
                    or f"{_cust_row.first_name} {_cust_row.last_name}".strip()
                    or "Unknown"
                )
        except Exception:
            logger.warning(
                "Failed to resolve customer name for refund sync, invoice %s",
                payload.invoice_id,
            )

    # Build Xero sync payload
    _refund_sync_data = {
        "id": str(refund_record.id),
        "invoice_number": _inv_number or "",
        "customer_name": _customer_name,
        "amount": float(refund_record.amount),
        "date": refund_record.created_at.strftime("%Y-%m-%d") if refund_record.created_at else "",
        "reason": refund_record.refund_note or "Refund",
    }

    # Fire-and-forget: sync refund to Xero if connected
    from app.modules.accounting.auto_sync import sync_refund_bg
    _asyncio.create_task(sync_refund_bg(org_uuid, _refund_sync_data))

    return result


@router.post(
    "/invoice/{invoice_id}/regenerate-payment-link",
    response_model=RegeneratePaymentLinkResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Regenerate a Stripe payment link for an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def regenerate_payment_link_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Regenerate a Stripe payment link for an invoice.

    Creates a new PaymentIntent and payment token, invalidating any
    previous tokens.  The invoice must be in a payable state (issued,
    partially_paid, or overdue) and the org must have a Connected Account.

    Requirements: 8.1, 8.2, 8.3, 8.4
    """
    from app.modules.admin.models import Organisation
    from app.modules.invoices.models import Invoice
    from app.integrations.stripe_connect import create_payment_intent
    from app.integrations.stripe_billing import get_application_fee_percent
    from app.modules.payments.token_service import generate_payment_token
    from sqlalchemy.orm.attributes import flag_modified

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Fetch invoice and validate it belongs to the org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_uuid,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invoice not found"},
        )

    # Validate invoice is in a payable state
    payable_statuses = {"issued", "partially_paid", "overdue"}
    if invoice.status not in payable_statuses:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cannot regenerate payment link for this invoice status."},
        )

    # Validate org has a Connected Account
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = org_result.scalar_one_or_none()
    if org is None or not org.stripe_connect_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Please connect a Stripe account first."},
        )

    stripe_account_id = org.stripe_connect_account_id

    # Calculate amount in cents
    amount_cents = int(invoice.balance_due * 100)
    if amount_cents <= 0:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invoice balance due must be greater than zero."},
        )

    # Calculate application fee if configured
    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(amount_cents * fee_percent / 100)

    # Create new PaymentIntent on Connected Account
    pi_result = await create_payment_intent(
        amount=amount_cents,
        currency=invoice.currency,
        invoice_id=str(invoice.id),
        stripe_account_id=stripe_account_id,
        application_fee_amount=application_fee_amount,
    )

    # Generate new payment token + URL (invalidates old tokens)
    _token, payment_url = await generate_payment_token(
        db,
        org_id=org_uuid,
        invoice_id=invoice.id,
    )

    # Update invoice record
    invoice.stripe_payment_intent_id = pi_result["payment_intent_id"]
    invoice.payment_page_url = payment_url

    # Store client_secret in invoice_data_json
    data_json = dict(invoice.invoice_data_json or {})
    data_json["stripe_client_secret"] = pi_result["client_secret"]
    invoice.invoice_data_json = data_json
    flag_modified(invoice, "invoice_data_json")

    await db.flush()
    await db.refresh(invoice)

    logger.info(
        "Regenerated payment link for invoice %s (PI=%s, account=%s)",
        invoice.id,
        pi_result["payment_intent_id"],
        stripe_account_id,
    )

    return RegeneratePaymentLinkResponse(
        payment_page_url=payment_url,
        invoice_id=invoice.id,
    )
