"""Branch billing — pure pricing + DB/Stripe helpers for per-branch billing.

Pure functions:
  - calculate_branch_cost: base × count × interval_multiplier (no side effects)

DB + Stripe helpers:
  - preview_branch_addition: cost preview for adding one branch
  - sync_stripe_branch_quantity: update Stripe subscription quantity
  - get_branch_cost_breakdown: per-branch cost breakdown for billing dashboard
  - create_branch_with_billing: transactional branch creation + Stripe sync

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.2, 5.3, 5.5, 6.2
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone as tz_utc
from decimal import Decimal, ROUND_HALF_UP

from app.modules.billing.interval_pricing import (
    BillingInterval,
    compute_effective_price,
    INTERVAL_PERIODS_PER_YEAR,
)

logger = logging.getLogger(__name__)

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWELVE = Decimal("12")
_HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# Pure function — no DB, no Stripe, easy to test
# ---------------------------------------------------------------------------


def calculate_branch_cost(
    base_price: Decimal,
    branch_count: int,
    interval: BillingInterval,
    discount: Decimal = _ZERO,
) -> Decimal:
    """Calculate total subscription cost for branches.

    Formula:
        per_cycle = compute_effective_price(base_price, interval, discount)
        total     = per_cycle × branch_count

    Returns Decimal rounded to 2 decimal places.

    Requirements: 4.1, 4.2, 4.6
    """
    if branch_count <= 0:
        return _ZERO
    per_cycle = compute_effective_price(base_price, interval, discount)
    total = per_cycle * Decimal(branch_count)
    return total.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def calculate_proration(
    per_branch_cost: Decimal,
    days_remaining: int,
    total_days_in_period: int,
) -> Decimal:
    """Calculate prorated charge or credit for a mid-cycle branch change.

    proration = per_branch_cost × (days_remaining / total_days_in_period)

    Returns Decimal rounded to 2 decimal places.

    Requirements: 4.3, 4.4
    """
    if total_days_in_period <= 0 or days_remaining <= 0:
        return _ZERO
    fraction = Decimal(days_remaining) / Decimal(total_days_in_period)
    return (per_branch_cost * fraction).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# DB + Stripe helpers
# ---------------------------------------------------------------------------


async def preview_branch_addition(
    db,  # AsyncSession
    org_id: uuid.UUID,
) -> dict:
    """Return a cost preview for adding one branch to the organisation.

    Loads the org's plan, billing interval, and discount to compute:
    - per_branch_cost: cost of one additional branch per billing cycle
    - prorated_charge: prorated cost for the remainder of the current period
    - new_total: projected total after adding the branch

    Requirements: 4.5, 5.1, 5.2
    """
    from sqlalchemy import select, func as sa_func

    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.organisations.models import Branch

    # Load org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Load plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Subscription plan not found")

    # Count active branches
    count_result = await db.execute(
        select(sa_func.count(Branch.id)).where(
            Branch.org_id == org_id,
            Branch.is_active.is_(True),
        )
    )
    active_count = count_result.scalar() or 0

    # Determine interval discount
    current_interval = getattr(org, "billing_interval", "monthly") or "monthly"
    interval_discount = _ZERO
    if plan.interval_config:
        for cfg in plan.interval_config:
            if cfg.get("interval") == current_interval and cfg.get("enabled"):
                interval_discount = Decimal(str(cfg.get("discount_percent", 0)))
                break

    base_price = Decimal(str(plan.monthly_price_nzd))

    # Cost of one branch per billing cycle
    per_branch_cost = compute_effective_price(base_price, current_interval, interval_discount)

    # Proration: days remaining in current billing period
    now = datetime.now(tz_utc)
    prorated_charge = _ZERO
    days_remaining = 0
    total_days = 0

    if org.next_billing_date:
        delta = org.next_billing_date - now
        days_remaining = max(0, delta.days)
        # Estimate total days in period from interval
        periods_per_year = INTERVAL_PERIODS_PER_YEAR[current_interval]
        total_days = round(365 / periods_per_year)
        prorated_charge = calculate_proration(per_branch_cost, days_remaining, total_days)

    # New total = current total + one more branch
    new_branch_count = active_count + 1
    new_total = calculate_branch_cost(base_price, new_branch_count, current_interval, interval_discount)
    current_total = calculate_branch_cost(base_price, active_count, current_interval, interval_discount)

    return {
        "current_branch_count": active_count,
        "new_branch_count": new_branch_count,
        "per_branch_cost": float(per_branch_cost),
        "prorated_charge": float(prorated_charge),
        "current_total": float(current_total),
        "new_total": float(new_total),
        "billing_interval": current_interval,
        "currency": "nzd",
    }


async def sync_stripe_branch_quantity(
    db,  # AsyncSession
    org_id: uuid.UUID,
) -> dict:
    """Update the Stripe subscription quantity to match active branch count.

    Uses Stripe's subscription item quantity update with proration.
    Returns a dict with the sync result.

    Requirements: 4.1, 4.3, 4.4, 6.2
    """
    import stripe
    from sqlalchemy import select, func as sa_func

    from app.modules.admin.models import Organisation
    from app.modules.organisations.models import Branch
    from app.integrations.stripe_billing import _ensure_stripe_key

    # Load org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    if not org.stripe_subscription_id:
        logger.warning("Org %s has no Stripe subscription — skipping sync", org_id)
        return {"synced": False, "reason": "no_subscription"}

    # Count active branches
    count_result = await db.execute(
        select(sa_func.count(Branch.id)).where(
            Branch.org_id == org_id,
            Branch.is_active.is_(True),
        )
    )
    active_count = count_result.scalar() or 0
    quantity = max(1, active_count)  # Minimum 1 branch (HQ)

    # Update Stripe subscription quantity
    await _ensure_stripe_key()
    try:
        subscription = stripe.Subscription.retrieve(org.stripe_subscription_id)
        if not subscription.get("items") or not subscription["items"].get("data"):
            logger.error("Subscription %s has no items", org.stripe_subscription_id)
            return {"synced": False, "reason": "no_subscription_items"}

        item_id = subscription["items"]["data"][0]["id"]
        stripe.SubscriptionItem.modify(
            item_id,
            quantity=quantity,
            proration_behavior="create_prorations",
        )

        logger.info(
            "Synced Stripe quantity for org %s: subscription=%s, quantity=%d",
            org_id,
            org.stripe_subscription_id,
            quantity,
        )
        return {
            "synced": True,
            "subscription_id": org.stripe_subscription_id,
            "quantity": quantity,
        }
    except stripe.error.StripeError as exc:
        logger.error(
            "Stripe sync failed for org %s: %s",
            org_id,
            exc,
        )
        raise


async def get_branch_cost_breakdown(
    db,  # AsyncSession
    org_id: uuid.UUID,
) -> dict:
    """Return per-branch cost breakdown for the billing dashboard.

    Lists each active branch with its name, cost contribution, and HQ label.

    Requirements: 4.5, 6.4
    """
    from sqlalchemy import select, func as sa_func

    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.organisations.models import Branch

    # Load org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Load plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Subscription plan not found")

    # Determine interval discount
    current_interval = getattr(org, "billing_interval", "monthly") or "monthly"
    interval_discount = _ZERO
    if plan.interval_config:
        for cfg in plan.interval_config:
            if cfg.get("interval") == current_interval and cfg.get("enabled"):
                interval_discount = Decimal(str(cfg.get("discount_percent", 0)))
                break

    base_price = Decimal(str(plan.monthly_price_nzd))
    per_branch_cost = compute_effective_price(base_price, current_interval, interval_discount)

    # Load active branches
    branches_result = await db.execute(
        select(Branch)
        .where(Branch.org_id == org_id, Branch.is_active.is_(True))
        .order_by(Branch.created_at.asc())
    )
    branches = branches_result.scalars().all()

    breakdown = []
    for branch in branches:
        breakdown.append({
            "branch_id": str(branch.id),
            "branch_name": branch.name,
            "is_hq": branch.is_hq,
            "cost_per_cycle": float(per_branch_cost),
        })

    total = float(per_branch_cost * Decimal(len(branches)))

    return {
        "branches": breakdown,
        "per_branch_cost": float(per_branch_cost),
        "total_cost": total,
        "branch_count": len(branches),
        "billing_interval": current_interval,
        "currency": "nzd",
    }


async def create_branch_with_billing(
    db,  # AsyncSession
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    address: str | None = None,
    phone: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a branch and sync Stripe quantity in a single transaction.

    If the Stripe update fails, the branch creation is rolled back.

    Requirements: 5.3, 5.5
    """
    from app.modules.organisations.service import create_branch

    # Create the branch within the current transaction
    branch_data = await create_branch(
        db,
        org_id=org_id,
        user_id=user_id,
        name=name,
        address=address,
        phone=phone,
        ip_address=ip_address,
    )

    # Attempt Stripe sync — rollback on failure
    try:
        await sync_stripe_branch_quantity(db, org_id)
    except Exception as exc:
        logger.error(
            "Stripe sync failed after branch creation for org %s: %s — rolling back",
            org_id,
            exc,
        )
        await db.rollback()
        raise ValueError(
            "Payment failed — branch not created"
        ) from exc

    return branch_data
