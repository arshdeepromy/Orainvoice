"""Stripe Subscriptions + metered billing integration.

Provides helpers for creating Stripe customers, PaymentIntents (for
charging during signup), and subscription lifecycle management.

Stripe keys are loaded from the ``integration_configs`` table (set via
the Global Admin → Integrations page) and cached in-memory.  Falls back
to the ``STRIPE_SECRET_KEY`` env var if no DB config exists.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal

import stripe

from app.config import settings

logger = logging.getLogger(__name__)

# --- Custom exceptions for payment handling --------------------------------


class PaymentFailedError(Exception):
    """Raised when a PaymentIntent fails due to a card error."""

    def __init__(self, message: str, decline_code: str | None = None):
        self.decline_code = decline_code
        super().__init__(message)


class PaymentActionRequiredError(Exception):
    """Raised when a PaymentIntent requires additional authentication."""

    pass


# --- Dynamic Stripe key loader (reads from DB, caches for 5 min) ----------

_cached_stripe_secret: str | None = None
_cached_stripe_publishable: str | None = None
_cache_ts: float = 0
_CACHE_TTL = 300  # 5 minutes


async def _load_stripe_keys_from_db() -> tuple[str, str]:
    """Load Stripe secret_key and publishable_key from integration_configs."""
    from app.core.database import async_session_factory
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
        )
        config_row = result.scalar_one_or_none()
        if config_row is None:
            return "", ""
        try:
            data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            return data.get("secret_key", ""), data.get("publishable_key", "")
        except Exception as exc:
            logger.warning("Failed to decrypt Stripe config from DB: %s", exc)
            return "", ""

async def _load_webhook_secret_from_db() -> str:
    """Load the Stripe webhook signing secret from integration_configs.

    Returns the ``signing_secret`` value stored in the encrypted Stripe
    config row, or an empty string if not configured.
    """
    from app.core.database import async_session_factory
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
        )
        config_row = result.scalar_one_or_none()
        if config_row is None:
            return ""
        try:
            data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            return data.get("signing_secret", "")
        except Exception as exc:
            logger.warning("Failed to decrypt Stripe webhook secret from DB: %s", exc)
            return ""


async def get_stripe_connect_client_id() -> str:
    """Return the Stripe Connect client ID from DB config or env fallback."""
    from app.core.database import async_session_factory
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
        )
        config_row = result.scalar_one_or_none()
        if config_row:
            try:
                data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
                client_id = data.get("connect_client_id", "")
                if client_id:
                    return client_id
            except Exception:
                pass
    return settings.stripe_connect_client_id


async def get_application_fee_percent() -> Decimal | None:
    """Return the configured application fee percentage, or None if not set.

    Reads the ``application_fee_percent`` value from the encrypted Stripe
    integration config row.  Returns ``None`` when the value is absent,
    empty, or cannot be parsed as a Decimal.

    Requirements: 7.1, 7.2
    """
    from app.core.database import async_session_factory
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
        )
        config_row = result.scalar_one_or_none()
        if config_row is None:
            return None
        try:
            data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            raw_value = data.get("application_fee_percent")
            if raw_value is None or raw_value == "":
                return None
            return Decimal(str(raw_value))
        except Exception as exc:
            logger.warning(
                "Failed to read application_fee_percent from Stripe config: %s", exc
            )
            return None


async def get_stripe_secret_key() -> str:
    """Return the Stripe secret key, loading from DB with caching."""
    global _cached_stripe_secret, _cached_stripe_publishable, _cache_ts

    now = time.time()
    if _cached_stripe_secret and (now - _cache_ts) < _CACHE_TTL:
        return _cached_stripe_secret

    secret, publishable = await _load_stripe_keys_from_db()
    if secret:
        _cached_stripe_secret = secret
        _cached_stripe_publishable = publishable
        _cache_ts = now
        return secret

    # Fallback to env var
    return settings.stripe_secret_key


async def get_stripe_publishable_key() -> str:
    """Return the Stripe publishable key, loading from DB with caching."""
    global _cached_stripe_secret, _cached_stripe_publishable, _cache_ts

    now = time.time()
    if _cached_stripe_publishable and (now - _cache_ts) < _CACHE_TTL:
        return _cached_stripe_publishable

    secret, publishable = await _load_stripe_keys_from_db()
    if publishable:
        _cached_stripe_secret = secret
        _cached_stripe_publishable = publishable
        _cache_ts = now
        return publishable

    return settings.stripe_publishable_key


async def _ensure_stripe_key() -> None:
    """Set stripe.api_key from DB config before making API calls."""
    key = await get_stripe_secret_key()
    if not key:
        raise RuntimeError(
            "Stripe secret key not configured. "
            "Set it in Global Admin → Integrations → Stripe."
        )
    stripe.api_key = key


async def create_stripe_customer(
    *,
    email: str,
    name: str,
    metadata: dict | None = None,
) -> str:
    """Create a Stripe Customer and return the customer ID.

    Raises ``stripe.error.StripeError`` on API failures.
    """
    await _ensure_stripe_key()
    customer = stripe.Customer.create(
        email=email,
        name=name,
        metadata=metadata or {},
    )
    logger.info("Created Stripe customer %s for %s", customer.id, email)
    return customer.id


async def create_setup_intent(
    *,
    customer_id: str,
    metadata: dict | None = None,
) -> dict:
    """Create a Stripe SetupIntent for collecting card details without charging.

    Returns a dict with ``setup_intent_id`` and ``client_secret`` (the
    client_secret is passed to the frontend for Stripe.js confirmation).
    """
    await _ensure_stripe_key()
    intent = stripe.SetupIntent.create(
        customer=customer_id,
        payment_method_types=["card"],
        usage="off_session",
        metadata=metadata or {},
    )
    logger.info(
        "Created SetupIntent %s for customer %s",
        intent.id,
        customer_id,
    )
    return {
        "setup_intent_id": intent.id,
        "client_secret": intent.client_secret,
    }

async def list_payment_methods(
    *,
    customer_id: str,
    type: str = "card",
) -> list[dict]:
    """List all payment methods attached to a Stripe customer.

    Returns a list of dicts with payment method details (id, brand,
    last4, exp_month, exp_year).

    Requirements: 5.1
    """
    await _ensure_stripe_key()
    methods = stripe.PaymentMethod.list(
        customer=customer_id,
        type=type,
    )
    result = []
    for pm in methods.data:
        card = pm.card or {}
        result.append({
            "id": pm.id,
            "brand": getattr(card, "brand", "") or "",
            "last4": getattr(card, "last4", "") or "",
            "exp_month": getattr(card, "exp_month", 0) or 0,
            "exp_year": getattr(card, "exp_year", 0) or 0,
        })
    logger.info(
        "Listed %d payment methods for customer %s",
        len(result),
        customer_id,
    )
    return result


async def set_default_payment_method(
    *,
    customer_id: str,
    payment_method_id: str,
) -> dict:
    """Set a payment method as the default for a Stripe customer.

    Updates the customer's ``invoice_settings.default_payment_method``
    so future invoices charge this card.

    Requirements: 5.3
    """
    await _ensure_stripe_key()
    customer = stripe.Customer.modify(
        customer_id,
        invoice_settings={"default_payment_method": payment_method_id},
    )
    logger.info(
        "Set default payment method %s for customer %s",
        payment_method_id,
        customer_id,
    )
    return {
        "customer_id": customer["id"],
        "default_payment_method": payment_method_id,
    }


async def detach_payment_method(
    *,
    payment_method_id: str,
) -> dict:
    """Detach a payment method from its Stripe customer.

    Once detached, the card can no longer be used for payments.

    Requirements: 5.4
    """
    await _ensure_stripe_key()
    pm = stripe.PaymentMethod.detach(payment_method_id)
    logger.info("Detached payment method %s", payment_method_id)
    return {
        "id": pm["id"],
        "detached": True,
    }



async def create_payment_intent_no_customer(
    *,
    amount_cents: int,
    currency: str = "nzd",
    metadata: dict | None = None,
) -> dict:
    """Create a Stripe PaymentIntent *without* a Stripe Customer.

    Used during the deferred-signup flow for paid plans: the Customer is
    only created after payment succeeds (in confirm-payment).  This avoids
    orphaned Stripe Customer records when users abandon the payment step.

    Returns a dict with ``payment_intent_id`` and ``client_secret``.
    """
    await _ensure_stripe_key()
    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=currency,
        payment_method_types=["card"],
        setup_future_usage="off_session",
        metadata=metadata or {},
    )
    logger.info(
        "Created PaymentIntent %s (no customer) for %d %s",
        intent.id,
        amount_cents,
        currency,
    )
    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
    }

async def charge_org_payment_method(
    *,
    customer_id: str,
    payment_method_id: str,
    amount_cents: int,
    currency: str = "nzd",
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Charge a saved payment method off-session.

    Creates a PaymentIntent with off_session=True, confirm=True.

    Parameters
    ----------
    idempotency_key:
        Optional Stripe idempotency key to prevent double-charges on
        retries.  Stripe deduplicates requests with the same key within
        24 hours, returning the original PaymentIntent.

    Returns:
        {"payment_intent_id": str, "status": str, "amount_cents": int}

    Raises:
        PaymentFailedError: on CardError (includes decline_code)
        PaymentActionRequiredError: when authentication is needed
    """
    await _ensure_stripe_key()
    create_kwargs: dict = dict(
        customer=customer_id,
        payment_method=payment_method_id,
        amount=amount_cents,
        currency=currency,
        off_session=True,
        confirm=True,
        metadata=metadata or {},
    )
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key
    try:
        intent = stripe.PaymentIntent.create(**create_kwargs)
    except stripe.error.CardError as e:
        err = e.error
        decline_code = err.decline_code if err else None
        raise PaymentFailedError(str(e), decline_code=decline_code) from e

    if intent.status == "requires_action":
        raise PaymentActionRequiredError(
            f"Payment {intent.id} requires additional authentication"
        )

    logger.info(
        "Charged customer %s via payment method %s: PaymentIntent %s (%d %s)",
        customer_id,
        payment_method_id,
        intent.id,
        amount_cents,
        currency,
    )
    return {
        "payment_intent_id": intent.id,
        "status": intent.status,
        "amount_cents": amount_cents,
    }



async def create_payment_intent(
    *,
    customer_id: str,
    amount_cents: int,
    currency: str = "nzd",
    metadata: dict | None = None,
) -> dict:
    """Create a Stripe PaymentIntent to charge the customer immediately.

    Used during signup for no-trial plans — the first month's payment
    is collected before the account is activated.

    Returns a dict with ``payment_intent_id`` and ``client_secret``.
    """
    await _ensure_stripe_key()
    intent = stripe.PaymentIntent.create(
        customer=customer_id,
        amount=amount_cents,
        currency=currency,
        payment_method_types=["card"],
        metadata=metadata or {},
    )
    logger.info(
        "Created PaymentIntent %s for customer %s (%d %s)",
        intent.id,
        customer_id,
        amount_cents,
        currency,
    )
    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
    }




async def create_invoice_item(
    *,
    customer_id: str,
    description: str,
    quantity: int,
    unit_amount_cents: int,
    currency: str = "nzd",
    metadata: dict | None = None,
) -> dict:
    """Create a one-off Stripe InvoiceItem attached to the customer.

    The item will appear on the customer's next invoice (e.g. the upcoming
    subscription renewal).  This is used for overage charges like SMS.

    Returns a dict with ``invoice_item_id`` and ``amount``.

    Requirements: 4.2
    """
    await _ensure_stripe_key()
    item = stripe.InvoiceItem.create(
        customer=customer_id,
        description=description,
        quantity=quantity,
        unit_amount=unit_amount_cents,
        currency=currency,
        metadata=metadata or {},
    )
    logger.info(
        "Created InvoiceItem %s for customer %s: %s (qty=%d, unit=%d)",
        item.id,
        customer_id,
        description,
        quantity,
        unit_amount_cents,
    )
    return {
        "invoice_item_id": item.id,
        "amount": item.get("amount", 0),
        "description": description,
    }


async def report_metered_usage(
    *,
    subscription_id: str,
    quantity: int,
    action: str = "set",
    timestamp: int | None = None,
) -> dict:
    """Report metered usage (Carjam overages) to a Stripe subscription item.

    Stripe metered billing records usage and includes it on the next invoice.

    Requirements: 42.2
    """
    await _ensure_stripe_key()
    subscription = stripe.Subscription.retrieve(subscription_id)
    metered_item = None
    for item in subscription["items"]["data"]:
        price = item.get("price", {})
        if price.get("recurring", {}).get("usage_type") == "metered":
            metered_item = item
            break

    if not metered_item:
        logger.warning(
            "No metered subscription item found for subscription %s",
            subscription_id,
        )
        return {"reported": False, "reason": "no_metered_item"}

    params: dict = {
        "quantity": quantity,
        "action": action,
    }
    if timestamp:
        params["timestamp"] = timestamp

    usage_record = stripe.SubscriptionItem.create_usage_record(
        metered_item["id"],
        **params,
    )
    logger.info(
        "Reported %d metered usage for subscription %s (item %s)",
        quantity,
        subscription_id,
        metered_item["id"],
    )
    return {
        "reported": True,
        "usage_record_id": usage_record.get("id"),
        "quantity": quantity,
    }



async def get_subscription_invoices(
    *,
    customer_id: str,
    limit: int = 24,
) -> list[dict]:
    """Retrieve past Stripe invoices for a customer.

    Returns a list of invoice dicts with id, number, amount, status,
    date, PDF URL, and hosted URL.

    Requirements: 42.3
    """
    await _ensure_stripe_key()
    invoices = stripe.Invoice.list(
        customer=customer_id,
        limit=limit,
        status="paid",
        expand=["data.charge"],
    )

    result = []
    inv_data = invoices.data if hasattr(invoices, 'data') else invoices.get("data", [])
    for inv in inv_data:
        # Stripe SDK objects support both dict-style and attribute access
        def _get(obj: object, key: str, default: object = None) -> object:
            if hasattr(obj, 'get'):
                return obj.get(key, default)
            return getattr(obj, key, default)

        lines_obj = _get(inv, "lines", None)
        lines_data = getattr(lines_obj, 'data', []) if lines_obj else []

        result.append({
            "id": _get(inv, "id"),
            "number": _get(inv, "number"),
            "amount_due": _get(inv, "amount_due", 0),
            "amount_paid": _get(inv, "amount_paid", 0),
            "currency": _get(inv, "currency", "nzd"),
            "status": _get(inv, "status"),
            "created": _get(inv, "created"),
            "period_start": _get(inv, "period_start"),
            "period_end": _get(inv, "period_end"),
            "invoice_pdf": _get(inv, "invoice_pdf"),
            "hosted_invoice_url": _get(inv, "hosted_invoice_url"),
            "description": _get(inv, "description"),
            "lines_summary": [
                {
                    "description": _get(line, "description", ""),
                    "amount": _get(line, "amount", 0),
                }
                for line in lines_data
            ],
        })
    return result








async def create_billing_portal_session(
    *,
    customer_id: str,
    return_url: str,
) -> str:
    """Create a Stripe Billing Portal session and return the URL.

    The portal lets customers update their payment method, view invoices,
    and (if configured) cancel their subscription.

    Requires the Customer Portal to be enabled in the Stripe Dashboard:
    https://dashboard.stripe.com/settings/billing/portal
    """
    await _ensure_stripe_key()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    logger.info("Created billing portal session for customer %s", customer_id)
    return session.url

