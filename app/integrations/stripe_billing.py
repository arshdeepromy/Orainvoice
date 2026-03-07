"""Stripe Subscriptions + metered billing integration.

Provides helpers for creating Stripe customers, SetupIntents (for card
collection without charging), and subscription lifecycle management.
"""

from __future__ import annotations

import logging

import stripe

from app.config import settings

logger = logging.getLogger(__name__)

# Configure the Stripe library with the platform secret key.
stripe.api_key = settings.stripe_secret_key


async def create_stripe_customer(
    *,
    email: str,
    name: str,
    metadata: dict | None = None,
) -> str:
    """Create a Stripe Customer and return the customer ID.

    Raises ``stripe.error.StripeError`` on API failures.
    """
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
    intent = stripe.SetupIntent.create(
        customer=customer_id,
        payment_method_types=["card"],
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

    if event_type == "invoice.payment_succeeded":
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
        result.update({
            "processed": True,
            "action": "subscription_updated",
            "subscription_id": subscription.get("id"),
            "status": subscription.get("status"),
            "customer_id": subscription.get("customer"),
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
