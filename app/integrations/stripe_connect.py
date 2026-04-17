"""Stripe Connect OAuth + payment operations.

Provides helpers for the Stripe Connect OAuth flow so organisations can
connect their own Stripe accounts for payment processing.

- ``generate_connect_url`` — builds the Stripe Connect OAuth authorisation URL
- ``handle_connect_callback`` — exchanges the authorisation code for a
  connected account ID via the Stripe API

The platform never handles raw card data (Stripe.js hosted fields only).

Requirements: 25.1, 25.2
"""

from __future__ import annotations

import secrets
import uuid

import httpx

from app.config import settings

# Stripe OAuth endpoints
STRIPE_CONNECT_AUTHORIZE_URL = "https://connect.stripe.com/oauth/authorize"
STRIPE_CONNECT_TOKEN_URL = "https://connect.stripe.com/oauth/token"


async def generate_connect_url(org_id: uuid.UUID) -> tuple[str, str]:
    """Generate a Stripe Connect OAuth authorisation URL.

    Parameters
    ----------
    org_id:
        The organisation initiating the connection.

    Returns
    -------
    tuple[str, str]
        ``(authorize_url, state_token)`` — the URL to redirect the user to
        and the CSRF state token to verify on callback.
    """
    from app.integrations.stripe_billing import get_stripe_connect_client_id

    state = f"{org_id}:{secrets.token_urlsafe(32)}"

    client_id = await get_stripe_connect_client_id()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "redirect_uri": settings.stripe_connect_redirect_uri,
        "state": state,
        "stripe_landing": "login",
    }

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{STRIPE_CONNECT_AUTHORIZE_URL}?{query}"

    return url, state


async def handle_connect_callback(code: str, state: str) -> dict:
    """Exchange an OAuth authorisation code for a connected account ID.

    Parameters
    ----------
    code:
        The authorisation code returned by Stripe in the callback.
    state:
        The state parameter returned by Stripe (must match the one we sent).

    Returns
    -------
    dict
        ``{"stripe_user_id": "acct_...", "scope": "read_write", ...}``

    Raises
    ------
    ValueError
        If the state token is malformed (missing org_id).
    httpx.HTTPStatusError
        If the Stripe token exchange fails.
    """
    # Validate state format: "org_id:random_token"
    parts = state.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Invalid state token format")

    try:
        org_id = uuid.UUID(parts[0])
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid org_id in state token") from exc

    # Exchange authorisation code for connected account
    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            STRIPE_CONNECT_TOKEN_URL,
            data={
                "client_secret": secret_key,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()

    token_data = response.json()
    token_data["org_id"] = str(org_id)
    return token_data


async def create_payment_link(
    *,
    amount: int,
    currency: str,
    invoice_id: str,
    stripe_account_id: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
    application_fee_amount: int | None = None,
) -> dict:
    """Create a Stripe Checkout Session for an invoice payment.

    Uses the connected organisation's Stripe account to create a hosted
    checkout page.  The ``amount`` is in the smallest currency unit (e.g.
    cents for NZD).  Supports partial payments for deposit scenarios.

    Parameters
    ----------
    amount:
        Payment amount in the smallest currency unit (e.g. cents).
    currency:
        Three-letter ISO currency code (e.g. ``"nzd"``).
    invoice_id:
        The platform invoice ID — stored in Checkout Session metadata.
    stripe_account_id:
        The connected Stripe account ID (``acct_...``).
    success_url:
        URL to redirect to after successful payment.
    cancel_url:
        URL to redirect to if the customer cancels.
    application_fee_amount:
        Optional platform application fee in the smallest currency unit
        (e.g. cents).  When provided and > 0, included as
        ``payment_intent_data[application_fee_amount]`` in the Checkout
        Session so Stripe splits the fee to the platform.

    Returns
    -------
    dict
        ``{"session_id": "cs_...", "payment_url": "https://checkout.stripe.com/..."}``

    Raises
    ------
    httpx.HTTPStatusError
        If the Stripe API call fails.

    Requirements: 25.3, 25.5
    """
    default_base = settings.frontend_base_url or "http://localhost:3000"
    final_success_url = (
        success_url
        or f"{default_base}/payments/success?session_id={{CHECKOUT_SESSION_ID}}"
    )
    final_cancel_url = cancel_url or f"{default_base}/payments/cancel"

    payload = {
        "mode": "payment",
        "payment_method_types[]": "card",
        "line_items[0][price_data][currency]": currency.lower(),
        "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": (
            f"Invoice payment ({invoice_id})"
        ),
        "success_url": final_success_url,
        "cancel_url": final_cancel_url,
        "metadata[invoice_id]": invoice_id,
        "metadata[platform]": "workshoppro_nz",
    }

    if application_fee_amount and application_fee_amount > 0:
        payload["payment_intent_data[application_fee_amount]"] = str(application_fee_amount)

    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError("Stripe secret key not configured. Set it via Global Admin > Integrations.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            auth=(secret_key, ""),
            headers={"Stripe-Account": stripe_account_id},
        )
        response.raise_for_status()

    session_data = response.json()
    return {
        "session_id": session_data["id"],
        "payment_url": session_data["url"],
    }

async def create_payment_intent(
    *,
    amount: int,
    currency: str,
    invoice_id: str,
    stripe_account_id: str,
    application_fee_amount: int | None = None,
) -> dict:
    """Create a Stripe PaymentIntent on a Connected Account.

    Unlike ``create_payment_link()`` which creates a hosted Checkout Session,
    this function creates a PaymentIntent directly — the frontend handles
    payment confirmation client-side via ``stripe.confirmPayment()``.

    Parameters
    ----------
    amount:
        Payment amount in the smallest currency unit (e.g. cents).
    currency:
        Three-letter ISO currency code (e.g. ``"nzd"``).
    invoice_id:
        The platform invoice ID — stored in PaymentIntent metadata.
    stripe_account_id:
        The connected Stripe account ID (``acct_...``).
    application_fee_amount:
        Optional platform application fee in the smallest currency unit.
        When provided and > 0, included as ``application_fee_amount`` on
        the PaymentIntent so Stripe splits the fee to the platform.

    Returns
    -------
    dict
        ``{"payment_intent_id": "pi_...", "client_secret": "pi_..._secret_..."}``

    Raises
    ------
    httpx.HTTPStatusError
        If the Stripe API call fails.

    Requirements: 1.1, 1.3, 1.4, 1.6
    """
    payload = {
        "amount": str(amount),
        "currency": currency.lower(),
        "metadata[invoice_id]": invoice_id,
        "metadata[platform]": "workshoppro_nz",
    }

    if application_fee_amount and application_fee_amount > 0:
        payload["application_fee_amount"] = str(application_fee_amount)

    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError("Stripe secret key not configured. Set it via Global Admin > Integrations.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.stripe.com/v1/payment_intents",
            data=payload,
            auth=(secret_key, ""),
            headers={"Stripe-Account": stripe_account_id},
        )
        response.raise_for_status()

    pi_data = response.json()
    return {
        "payment_intent_id": pi_data["id"],
        "client_secret": pi_data["client_secret"],
    }


async def create_stripe_refund(
    *,
    payment_intent_id: str,
    amount: int,
    stripe_account_id: str,
) -> dict:
    """Create a Stripe refund for a payment intent.

    Uses the connected organisation's Stripe account to process a refund.
    The ``amount`` is in the smallest currency unit (e.g. cents for NZD).

    Parameters
    ----------
    payment_intent_id:
        The Stripe PaymentIntent ID to refund (``pi_...``).
    amount:
        Refund amount in the smallest currency unit (e.g. cents).
    stripe_account_id:
        The connected Stripe account ID (``acct_...``).

    Returns
    -------
    dict
        ``{"refund_id": "re_...", "status": "succeeded", "amount": ...}``

    Raises
    ------
    httpx.HTTPStatusError
        If the Stripe API call fails.
    ValueError
        If the payment_intent_id is empty.

    Requirements: 26.2
    """
    if not payment_intent_id:
        raise ValueError("payment_intent_id is required for Stripe refund")

    payload = {
        "payment_intent": payment_intent_id,
        "amount": str(amount),
    }

    from app.integrations.stripe_billing import get_stripe_secret_key

    secret_key = await get_stripe_secret_key()
    if not secret_key:
        raise RuntimeError("Stripe secret key not configured. Set it via Global Admin > Integrations.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.stripe.com/v1/refunds",
            data=payload,
            auth=(secret_key, ""),
            headers={"Stripe-Account": stripe_account_id},
        )
        response.raise_for_status()

    refund_data = response.json()
    return {
        "refund_id": refund_data.get("id", ""),
        "status": refund_data.get("status", ""),
        "amount": refund_data.get("amount", 0),
    }


def verify_webhook_signature(
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
) -> dict:
    """Verify a Stripe webhook signature using HMAC-SHA256.

    Stripe signs each webhook payload with the endpoint's signing secret.
    The ``Stripe-Signature`` header contains a timestamp (``t``) and one
    or more signatures (``v1``).  We recompute the expected signature and
    compare using constant-time comparison to prevent timing attacks.

    Parameters
    ----------
    payload:
        The raw request body bytes.
    sig_header:
        The value of the ``Stripe-Signature`` HTTP header.
    webhook_secret:
        The webhook endpoint signing secret (``whsec_...``).

    Returns
    -------
    dict
        The parsed JSON event payload.

    Raises
    ------
    ValueError
        If the signature is missing, malformed, or does not match.

    Requirements: 25.4
    """
    import hashlib
    import hmac
    import json
    import time

    # Parse the Stripe-Signature header
    elements: dict[str, str] = {}
    for item in sig_header.split(","):
        key_value = item.strip().split("=", 1)
        if len(key_value) == 2:
            elements[key_value[0]] = key_value[1]

    timestamp = elements.get("t")
    signature = elements.get("v1")

    if not timestamp or not signature:
        raise ValueError("Invalid Stripe-Signature header: missing t or v1")

    # Guard against replay attacks — reject events older than 5 minutes
    try:
        ts_int = int(timestamp)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid timestamp in Stripe-Signature header") from exc

    if abs(time.time() - ts_int) > 300:
        raise ValueError("Webhook timestamp too old; possible replay attack")

    # Compute expected signature
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(
        webhook_secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise ValueError("Webhook signature verification failed")

    return json.loads(payload)

