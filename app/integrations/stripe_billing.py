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

import stripe

from app.config import settings

logger = logging.getLogger(__name__)

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
    for pm in methods.get("data", []):
        card = pm.get("card", {})
        result.append({
            "id": pm["id"],
            "brand": card.get("brand", ""),
            "last4": card.get("last4", ""),
            "exp_month": card.get("exp_month", 0),
            "exp_year": card.get("exp_year", 0),
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



async def create_subscription_from_trial(
    *,
    customer_id: str,
    price_id: str | None = None,
    monthly_amount_cents: int | None = None,
    currency: str = "nzd",
    metadata: dict | None = None,
) -> dict:
    """Create a Stripe Subscription for a customer whose trial has ended.

    Either ``price_id`` (an existing Stripe Price) or ``monthly_amount_cents``
    (to create an ad-hoc price) must be provided.

    Returns a dict with ``subscription_id`` and ``status``.

    Requirements: 41.5
    """
    sub_params: dict = {
        "customer": customer_id,
        "metadata": metadata or {},
    }

    if price_id:
        sub_params["items"] = [{"price": price_id}]
    elif monthly_amount_cents:
        sub_params["items"] = [
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": monthly_amount_cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": "WorkshopPro NZ Subscription"},
                },
            }
        ]
    else:
        raise ValueError("Either price_id or monthly_amount_cents must be provided")

    sub_params["payment_behavior"] = "default_incomplete"
    sub_params["expand"] = ["latest_invoice.payment_intent"]

    await _ensure_stripe_key()
    subscription = stripe.Subscription.create(**sub_params)
    logger.info(
        "Created Stripe subscription %s for customer %s (status=%s)",
        subscription.id,
        customer_id,
        subscription.status,
    )
    return {
        "subscription_id": subscription.id,
        "status": subscription.status,
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

async def get_subscription_details(
    *,
    subscription_id: str,
) -> dict:
    """Retrieve subscription details including next billing date.

    Returns a dict with ``current_period_end`` (Unix timestamp),
    ``status``, and ``cancel_at_period_end``.

    Requirements: 44.1
    """
    await _ensure_stripe_key()
    subscription = stripe.Subscription.retrieve(subscription_id)
    return {
        "current_period_end": subscription.get("current_period_end"),
        "status": subscription.get("status"),
        "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
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
    for inv in invoices.get("data", []):
        result.append({
            "id": inv["id"],
            "number": inv.get("number"),
            "amount_due": inv.get("amount_due", 0),
            "amount_paid": inv.get("amount_paid", 0),
            "currency": inv.get("currency", "nzd"),
            "status": inv.get("status"),
            "created": inv.get("created"),
            "period_start": inv.get("period_start"),
            "period_end": inv.get("period_end"),
            "invoice_pdf": inv.get("invoice_pdf"),
            "hosted_invoice_url": inv.get("hosted_invoice_url"),
            "description": inv.get("description"),
            "lines_summary": [
                {
                    "description": line.get("description", ""),
                    "amount": line.get("amount", 0),
                }
                for line in inv.get("lines", {}).get("data", [])
            ],
        })
    return result



async def handle_subscription_webhook(
    *,
    event_type: str,
    event_data: dict,
) -> dict:
    """Process Stripe subscription webhook events.

    Handles:
    - invoice.payment_succeeded: confirm payment, keep org active
    - invoice.payment_failed: trigger dunning flow
    - customer.subscription.updated: track status changes
    - customer.subscription.deleted: handle cancellation

    Requirements: 42.1, 42.3, 42.4
    """
    result: dict = {"event_type": event_type, "processed": False}

    if event_type == "invoice.created":
        invoice = event_data.get("object", {})
        customer_id = invoice.get("customer")
        invoice_id = invoice.get("id")
        # Only add overage items to subscription invoices (not one-off)
        subscription_id = invoice.get("subscription")
        billing_reason = invoice.get("billing_reason", "")
        result.update({
            "processed": True,
            "action": "invoice_created",
            "customer_id": customer_id,
            "invoice_id": invoice_id,
            "subscription_id": subscription_id,
            "billing_reason": billing_reason,
        })
        logger.info(
            "Invoice created for customer %s (invoice=%s, reason=%s)",
            customer_id,
            invoice_id,
            billing_reason,
        )

    elif event_type == "invoice.payment_succeeded":
        invoice = event_data.get("object", {})
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")
        result.update({
            "processed": True,
            "action": "payment_succeeded",
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "amount_paid": invoice.get("amount_paid", 0),
            "invoice_pdf": invoice.get("invoice_pdf"),
            "hosted_invoice_url": invoice.get("hosted_invoice_url"),
        })
        logger.info(
            "Payment succeeded for customer %s subscription %s",
            customer_id,
            subscription_id,
        )

    elif event_type == "invoice.payment_failed":
        invoice = event_data.get("object", {})
        customer_id = invoice.get("customer")
        subscription_id = invoice.get("subscription")
        attempt_count = invoice.get("attempt_count", 0)
        next_attempt = invoice.get("next_payment_attempt")
        result.update({
            "processed": True,
            "action": "payment_failed",
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "attempt_count": attempt_count,
            "next_payment_attempt": next_attempt,
        })
        logger.warning(
            "Payment failed for customer %s subscription %s (attempt %d)",
            customer_id,
            subscription_id,
            attempt_count,
        )

    elif event_type == "customer.subscription.updated":
        subscription = event_data.get("object", {})
        cancel_at_period_end = subscription.get("cancel_at_period_end", False)
        result.update({
            "processed": True,
            "action": "subscription_updated",
            "subscription_id": subscription.get("id"),
            "status": subscription.get("status"),
            "customer_id": subscription.get("customer"),
            "cancel_at_period_end": cancel_at_period_end,
        })

    elif event_type == "customer.subscription.deleted":
        subscription = event_data.get("object", {})
        result.update({
            "processed": True,
            "action": "subscription_deleted",
            "subscription_id": subscription.get("id"),
            "customer_id": subscription.get("customer"),
        })
        logger.info(
            "Subscription %s deleted for customer %s",
            subscription.get("id"),
            subscription.get("customer"),
        )

    elif event_type == "customer.updated":
        customer = event_data.get("object", {})
        default_pm = (customer.get("invoice_settings") or {}).get("default_payment_method")
        result.update({
            "processed": True,
            "action": "customer_updated",
            "customer_id": customer.get("id"),
            "default_payment_method": default_pm,
        })
        logger.info(
            "Customer %s updated (default_payment_method=%s)",
            customer.get("id"),
            default_pm,
        )

    elif event_type == "setup_intent.succeeded":
        setup_intent = event_data.get("object", {})
        payment_method_id = setup_intent.get("payment_method")
        customer_id = setup_intent.get("customer")

        # Retrieve card details from Stripe
        card_details: dict = {}
        if payment_method_id:
            try:
                await _ensure_stripe_key()
                pm = stripe.PaymentMethod.retrieve(payment_method_id)
                card = pm.get("card", {})
                card_details = {
                    "brand": card.get("brand", "unknown"),
                    "last4": card.get("last4", "0000"),
                    "exp_month": card.get("exp_month", 0),
                    "exp_year": card.get("exp_year", 0),
                }
            except Exception as exc:
                logger.error(
                    "Failed to retrieve payment method %s from Stripe: %s",
                    payment_method_id,
                    exc,
                )

        result.update({
            "processed": True,
            "action": "setup_intent_succeeded",
            "customer_id": customer_id,
            "payment_method_id": payment_method_id,
            "card_details": card_details,
        })
        logger.info(
            "SetupIntent succeeded for customer %s (payment_method=%s)",
            customer_id,
            payment_method_id,
        )

    return result


async def update_subscription_plan(
    *,
    subscription_id: str,
    new_monthly_amount_cents: int,
    proration_behavior: str = "create_prorations",
) -> dict:
    """Update a Stripe subscription's price for plan upgrade/downgrade.

    For upgrades, ``proration_behavior`` should be ``"create_prorations"``
    (immediate with prorated charges).  For downgrades, use
    ``"none"`` and schedule the change at the next billing period via
    ``billing_cycle_anchor``.

    Returns a dict with subscription details and prorated amount info.

    Requirements: 43.2, 43.3
    """
    await _ensure_stripe_key()
    subscription = stripe.Subscription.retrieve(subscription_id)
    if not subscription or not subscription.get("items", {}).get("data"):
        raise ValueError("Subscription not found or has no items")

    # Use the first subscription item (the base plan item)
    current_item = subscription["items"]["data"][0]

    update_params: dict = {
        "items": [
            {
                "id": current_item["id"],
                "price_data": {
                    "currency": "nzd",
                    "unit_amount": new_monthly_amount_cents,
                    "recurring": {"interval": "month"},
                    "product_data": {"name": "WorkshopPro NZ Subscription"},
                },
            }
        ],
        "proration_behavior": proration_behavior,
    }

    updated_sub = stripe.Subscription.modify(subscription_id, **update_params)

    # Retrieve the upcoming invoice to get the prorated amount
    prorated_amount = 0
    if proration_behavior == "create_prorations":
        try:
            upcoming = stripe.Invoice.upcoming(
                customer=updated_sub["customer"],
                subscription=subscription_id,
            )
            prorated_amount = upcoming.get("amount_due", 0)
        except Exception:
            logger.warning(
                "Could not retrieve upcoming invoice for proration amount "
                "(subscription %s)",
                subscription_id,
            )

    logger.info(
        "Updated subscription %s to %d cents/month (proration=%s)",
        subscription_id,
        new_monthly_amount_cents,
        proration_behavior,
    )

    return {
        "subscription_id": updated_sub["id"],
        "status": updated_sub.get("status"),
        "current_period_end": updated_sub.get("current_period_end"),
        "prorated_amount_cents": prorated_amount,
    }

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

