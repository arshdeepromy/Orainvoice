"""Billing router — Stripe Connect OAuth, storage add-on, trial status, subscription invoices, webhook.

Provides:
- POST /api/v1/billing/stripe/connect — initiate Stripe Connect OAuth
- GET  /api/v1/billing/stripe/connect/callback — handle OAuth callback
- POST /api/v1/billing/storage/purchase — purchase storage add-on (legacy)
- GET  /api/v1/billing/storage-addon — storage add-on status + available packages
- POST /api/v1/billing/storage-addon — purchase new storage add-on (package-based)
- PUT  /api/v1/billing/storage-addon — resize existing storage add-on
- DELETE /api/v1/billing/storage-addon — remove storage add-on
- GET  /api/v1/billing/trial — trial countdown data
- GET  /api/v1/billing/invoices — list past subscription invoices
- POST /api/v1/billing/webhook — Stripe subscription webhook handler

Requirements: 4.1–4.7, 5.1–5.7, 25.1, 25.2, 30.1, 30.2, 30.3, 30.4, 41.3, 42.1, 42.2, 42.3, 42.4
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.integrations.stripe_billing import (
    create_billing_portal_session,
    create_invoice_item,
    create_setup_intent,
    detach_payment_method,
    get_subscription_invoices,
    set_default_payment_method,
)
from app.integrations.stripe_connect import (
    generate_connect_url,
    handle_connect_callback,
)
from app.modules.admin.models import Organisation, OrgStorageAddon, SmsPackagePurchase, StoragePackage, SubscriptionPlan, Coupon, OrganisationCoupon
from app.modules.auth.models import User
from app.modules.auth.rbac import require_role
from app.modules.billing.models import OrgPaymentMethod
from app.modules.billing.schemas import (
    BillingDashboardResponse,
    IntervalChangeRequest,
    IntervalChangeResponse,
    PaymentMethodListResponse,
    PaymentMethodResponse,
    PlanChangeRequest,
    PlanDowngradeResponse,
    PlanUpgradeResponse,
    SetupIntentResponse,
    StorageAddonPurchaseRequest,
    StorageAddonResizeRequest,
    StorageAddonResponse,
    StorageAddonStatusResponse,
    SubscriptionInvoiceResponse,
    TrialStatusResponse,
)
from app.modules.billing.interval_pricing import (
    compute_effective_price,
    compute_equivalent_monthly,
    compute_interval_duration,
    compute_savings_amount,
    convert_coupon_duration_to_cycles,
    build_default_interval_config,
    INTERVAL_PERIODS_PER_YEAR,
)
from app.modules.payments.schemas import (
    StripeConnectCallbackResponse,
    StripeConnectInitResponse,
)
from app.modules.storage.schemas import (
    StoragePurchaseRequest,
    StoragePurchaseResponse,
)
from app.modules.storage.service import (
    get_storage_addon_status,
    purchase_storage_addon,
    purchase_storage_addon_v2,
    remove_storage_addon,
    resize_storage_addon,
)

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


# ---------------------------------------------------------------------------
# Trial status — Requirements: 41.3
# ---------------------------------------------------------------------------


@router.get(
    "/trial",
    response_model=TrialStatusResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Get trial countdown data",
    dependencies=[require_role("org_admin")],
)
async def get_trial_status(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return trial countdown data for the Org_Admin dashboard.

    Includes whether the org is on trial, days remaining, trial end date,
    plan name, and the monthly price that will be charged after trial ends.

    Requirements: 41.3
    """
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    # Load the plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()

    is_trial = org.status == "trial"
    days_remaining = 0
    if is_trial and org.trial_ends_at:
        now = datetime.now(timezone.utc)
        delta = org.trial_ends_at - now
        days_remaining = max(0, math.ceil(delta.total_seconds() / 86400))

    return TrialStatusResponse(
        is_trial=is_trial,
        trial_ends_at=org.trial_ends_at,
        days_remaining=days_remaining,
        plan_name=plan.name if plan else "Unknown",
        plan_monthly_price_nzd=float(plan.monthly_price_nzd) if plan else 0.0,
        status=org.status,
    )


# ---------------------------------------------------------------------------
# Billing dashboard — Requirements: 44.1, 44.2
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# Carjam overage rate per lookup in NZD (configurable via platform settings)
_CARJAM_OVERAGE_RATE_NZD = 0.70


@router.get(
    "",
    response_model=BillingDashboardResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Billing dashboard",
    dependencies=[require_role("org_admin")],
)
async def get_billing_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return billing dashboard data for the Org_Admin.

    Aggregates current plan info, next billing date, estimated next invoice
    breakdown (plan + storage add-ons + Carjam overage), storage usage,
    Carjam usage this month, and past invoices — all in plain language.

    Requirements: 44.1, 44.2
    """
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    # Load subscription plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()

    plan_name = plan.name if plan else "Unknown"
    plan_price = float(plan.monthly_price_nzd) if plan else 0.0
    carjam_included = plan.carjam_lookups_included if plan else 0

    # Next billing date from local Organisation field (Requirements: 8.1, 8.2, 8.3, 9.2, 9.3)
    next_billing_date = None if org.status == "trial" else org.next_billing_date

    # Storage usage
    storage_used_gb = org.storage_used_bytes / (1024 ** 3)

    # Storage add-on: query org_storage_addons for actual add-on data
    addon_result = await db.execute(
        select(OrgStorageAddon)
        .where(OrgStorageAddon.org_id == org_uuid)
    )
    addon = addon_result.scalar_one_or_none()

    storage_addon_gb: int | None = None
    storage_addon_price_nzd: float | None = None
    storage_addon_package_name: str | None = None
    storage_addon_charge = 0.0

    if addon:
        storage_addon_gb = addon.quantity_gb
        storage_addon_price_nzd = float(addon.price_nzd_per_month)
        storage_addon_charge = float(addon.price_nzd_per_month)

        # Join with storage_packages for the package name
        if addon.storage_package_id:
            pkg_result = await db.execute(
                select(StoragePackage).where(StoragePackage.id == addon.storage_package_id)
            )
            pkg = pkg_result.scalar_one_or_none()
            if pkg:
                storage_addon_package_name = pkg.name

    # Carjam overage charge
    carjam_used = org.carjam_lookups_this_month
    carjam_overage = max(0, carjam_used - carjam_included)
    carjam_overage_charge = carjam_overage * _CARJAM_OVERAGE_RATE_NZD

    # SMS usage
    sms_included = plan.sms_included if plan else False
    sms_included_quota = plan.sms_included_quota if plan else 0
    per_sms_cost = float(plan.per_sms_cost_nzd) if plan else 0.0
    sms_sent = org.sms_sent_this_month

    # Prepaid SMS credits remaining
    credits_result = await db.execute(
        select(func.coalesce(func.sum(SmsPackagePurchase.credits_remaining), 0))
        .where(
            SmsPackagePurchase.org_id == org_uuid,
            SmsPackagePurchase.credits_remaining > 0,
        )
    )
    sms_credits_remaining = int(credits_result.scalar() or 0)

    # SMS overage: messages beyond included quota and prepaid credits
    sms_beyond_included = max(0, sms_sent - sms_included_quota)
    sms_beyond_credits = max(0, sms_beyond_included - sms_credits_remaining)
    sms_overage_charge = sms_beyond_credits * per_sms_cost

    # Estimated next invoice — use interval effective price (computed below)
    # Placeholder; will be recalculated after interval pricing is computed.
    estimated_total = plan_price + storage_addon_charge + carjam_overage_charge + sms_overage_charge

    # Active coupon for this org
    active_coupon_code = None
    discount_type = None
    discount_value = None
    duration_months = None
    coupon_duration_cycles = None
    effective_price_nzd = None
    coupon_is_expired = False

    coupon_result = await db.execute(
        select(OrganisationCoupon, Coupon)
        .join(Coupon, OrganisationCoupon.coupon_id == Coupon.id)
        .where(
            OrganisationCoupon.org_id == org_uuid,
            OrganisationCoupon.is_expired.is_(False),
        )
        .order_by(OrganisationCoupon.applied_at.desc())
        .limit(1)
    )
    coupon_row = coupon_result.one_or_none()

    # --- Billing interval fields (Requirements: 9.1, 9.2, 9.3, 9.4) ---
    # Compute interval effective price BEFORE coupon so coupon applies after interval discount
    current_interval = getattr(org, "billing_interval", "monthly") or "monthly"

    # Find discount for the org's current interval from the plan's interval_config
    interval_discount = Decimal("0")
    if plan and getattr(plan, "interval_config", None):
        for cfg_item in plan.interval_config:
            if cfg_item.get("interval") == current_interval and cfg_item.get("enabled"):
                interval_discount = Decimal(str(cfg_item.get("discount_percent", 0)))
                break

    base_price_dec = Decimal(str(plan_price))
    interval_eff_price = compute_effective_price(base_price_dec, current_interval, interval_discount)
    equiv_monthly = compute_equivalent_monthly(interval_eff_price, current_interval)

    # Recalculate estimated total using the interval effective price (not raw monthly base)
    estimated_total = float(interval_eff_price) + storage_addon_charge + carjam_overage_charge + sms_overage_charge

    # Apply coupon discount on top of the interval effective price (Req 11.1, 11.2)
    if coupon_row:
        org_coupon, coupon = coupon_row
        from app.modules.admin.service import calculate_effective_price
        active_coupon_code = coupon.code
        discount_type = coupon.discount_type
        discount_value = float(coupon.discount_value)
        duration_months = coupon.duration_months
        # Convert coupon duration to billing cycles for the active interval (Req 11.3)
        if duration_months is not None:
            coupon_duration_cycles = convert_coupon_duration_to_cycles(
                duration_months, current_interval,
            )
        coupon_is_expired = org_coupon.is_expired
        effective_price_nzd = calculate_effective_price(
            float(interval_eff_price), discount_type, discount_value, coupon_is_expired,
        )
        # Use coupon-adjusted price for the estimated total
        estimated_total = effective_price_nzd + storage_addon_charge + carjam_overage_charge + sms_overage_charge

    # Past invoices from Stripe
    past_invoices: list[SubscriptionInvoiceResponse] = []
    if org.stripe_customer_id:
        try:
            raw_invoices = await get_subscription_invoices(
                customer_id=org.stripe_customer_id,
                limit=24,
            )
            past_invoices = [SubscriptionInvoiceResponse(**inv) for inv in raw_invoices]
        except Exception:
            logger.warning(
                "Could not fetch past invoices for org %s", org_uuid,
            )

    pending_interval_change = None
    if hasattr(org, "settings") and org.settings:
        pending_interval_change = org.settings.get("pending_interval_change")

    return BillingDashboardResponse(
        current_plan=plan_name,
        plan_monthly_price_nzd=plan_price,
        next_billing_date=next_billing_date,
        estimated_next_invoice_nzd=round(estimated_total, 2),
        storage_addon_charge_nzd=round(storage_addon_charge, 2),
        carjam_overage_charge_nzd=round(carjam_overage_charge, 2),
        carjam_lookups_used=carjam_used,
        carjam_lookups_included=carjam_included,
        storage_used_gb=round(storage_used_gb, 4),
        storage_quota_gb=org.storage_quota_gb,
        user_seats=plan.user_seats if plan else 0,
        org_status=org.status,
        trial_ends_at=org.trial_ends_at if org.status == "trial" else None,
        billing_interval=current_interval,
        interval_effective_price=float(interval_eff_price),
        equivalent_monthly_price=float(equiv_monthly),
        pending_interval_change=pending_interval_change,
        active_coupon_code=active_coupon_code,
        discount_type=discount_type,
        discount_value=discount_value,
        duration_months=duration_months,
        coupon_duration_cycles=coupon_duration_cycles,
        effective_price_nzd=round(effective_price_nzd, 2) if effective_price_nzd is not None else None,
        coupon_is_expired=coupon_is_expired,
        sms_included=sms_included,
        sms_included_quota=sms_included_quota,
        sms_sent_this_month=sms_sent,
        per_sms_cost_nzd=per_sms_cost,
        sms_overage_charge_nzd=round(sms_overage_charge, 2),
        sms_credits_remaining=sms_credits_remaining,
        storage_addon_gb=storage_addon_gb,
        storage_addon_price_nzd=round(storage_addon_price_nzd, 2) if storage_addon_price_nzd is not None else None,
        storage_addon_package_name=storage_addon_package_name,
        past_invoices=past_invoices,
    )


# ---------------------------------------------------------------------------
# Available intervals — Requirements: 7.2
# ---------------------------------------------------------------------------


@router.get(
    "/available-intervals",
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        404: {"description": "Organisation or plan not found"},
    },
    summary="Available billing intervals for current plan",
    dependencies=[require_role("org_admin")],
)
async def get_available_intervals(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return available billing intervals with effective prices and savings.

    Loads the current plan's interval_config and computes pricing for each
    enabled interval using the plan's base monthly price.

    Requirements: 7.2
    """
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Subscription plan not found"},
        )

    # Use plan's interval_config or fall back to default monthly-only
    interval_config = plan.interval_config
    if not interval_config:
        interval_config = build_default_interval_config()

    from decimal import Decimal

    base_price = Decimal(str(plan.monthly_price_nzd))
    intervals = []

    for item in interval_config:
        if not item.get("enabled", False):
            continue

        interval = item["interval"]
        discount = Decimal(str(item.get("discount_percent", 0)))

        effective = compute_effective_price(base_price, interval, discount)
        savings = compute_savings_amount(base_price, interval, discount)
        equiv_monthly = compute_equivalent_monthly(effective, interval)

        intervals.append({
            "interval": interval,
            "enabled": True,
            "discount_percent": float(discount),
            "effective_price": float(effective),
            "savings_amount": float(savings),
            "equivalent_monthly": float(equiv_monthly),
        })

    return {
        "current_interval": getattr(org, "billing_interval", "monthly"),
        "intervals": intervals,
    }


# ---------------------------------------------------------------------------
# Change billing interval — Requirements: 7.3, 7.4, 7.5, 7.6
# ---------------------------------------------------------------------------


@router.post(
    "/change-interval",
    response_model=IntervalChangeResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid interval or no change needed"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        404: {"description": "Organisation or plan not found"},
    },
    summary="Change billing interval for current plan",
    dependencies=[require_role("org_admin")],
)
async def change_billing_interval(
    request: Request,
    body: IntervalChangeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Change the billing interval for the current plan.

    Direction logic (local-only, no Stripe calls):
    - Longer interval (fewer periods/year, e.g. monthly → annual):
      immediate update — set org.billing_interval and recalculate
      next_billing_date from now.
    - Shorter interval (more periods/year, e.g. annual → monthly):
      scheduled change — store pending change in org.settings with
      effective_at = org.next_billing_date. The recurring billing task
      applies it when the current period ends.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1
    """
    from decimal import Decimal as _Dec

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Load org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    # Load plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Subscription plan not found"},
        )

    new_interval = body.billing_interval
    current_interval = getattr(org, "billing_interval", "monthly")

    # No-op check
    if new_interval == current_interval:
        return JSONResponse(
            status_code=400,
            content={"detail": "Already on this billing interval. No change needed."},
        )

    # Validate the requested interval is enabled in the plan's interval_config
    interval_config = plan.interval_config
    if not interval_config:
        interval_config = build_default_interval_config()

    enabled_intervals = {
        item["interval"]
        for item in interval_config
        if item.get("enabled", False)
    }

    if new_interval not in enabled_intervals:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Interval '{new_interval}' is not available for this plan."},
        )

    # Compute new effective price
    discount_percent = _Dec("0")
    for item in interval_config:
        if item["interval"] == new_interval:
            discount_percent = _Dec(str(item.get("discount_percent", 0)))
            break

    base_price = _Dec(str(plan.monthly_price_nzd))
    new_effective_price = compute_effective_price(base_price, new_interval, discount_percent)

    # Determine direction: compare periods per year
    current_periods = INTERVAL_PERIODS_PER_YEAR[current_interval]
    new_periods = INTERVAL_PERIODS_PER_YEAR[new_interval]

    # Longer interval = fewer periods/year → immediate change
    # Shorter interval = more periods/year → scheduled change
    is_immediate = new_periods < current_periods

    previous_interval = current_interval

    if is_immediate:
        # Immediate change: update interval and recalculate next_billing_date
        org.billing_interval = new_interval
        org.next_billing_date = datetime.now(timezone.utc) + compute_interval_duration(new_interval)
        await db.flush()

        # Audit log
        await write_audit_log(
            session=db,
            org_id=org_uuid,
            user_id=user_uuid,
            action="billing.interval_changed_immediate",
            entity_type="organisation",
            entity_id=org_uuid,
            before_value={"billing_interval": previous_interval},
            after_value={
                "billing_interval": new_interval,
                "effective_price": float(new_effective_price),
            },
            ip_address=ip_address,
        )
        await db.commit()

        return IntervalChangeResponse(
            success=True,
            message=f"Billing interval changed to {new_interval} immediately.",
            new_interval=new_interval,
            new_effective_price=float(new_effective_price),
            effective_immediately=True,
            effective_at=None,
        )
    else:
        # Scheduled change: store pending change, keep current interval
        effective_at = org.next_billing_date

        org_settings = dict(org.settings) if org.settings else {}
        org_settings["pending_interval_change"] = {
            "new_interval": new_interval,
            "effective_at": effective_at.isoformat() if effective_at else None,
        }
        org.settings = org_settings
        await db.flush()

        # Audit log
        await write_audit_log(
            session=db,
            org_id=org_uuid,
            user_id=user_uuid,
            action="billing.interval_change_scheduled",
            entity_type="organisation",
            entity_id=org_uuid,
            before_value={"billing_interval": previous_interval},
            after_value={
                "billing_interval": new_interval,
                "effective_price": float(new_effective_price),
                "effective_at": effective_at.isoformat() if effective_at else None,
            },
            ip_address=ip_address,
        )
        await db.commit()

        return IntervalChangeResponse(
            success=True,
            message=f"Billing interval change to {new_interval} scheduled for the end of the current billing period.",
            new_interval=new_interval,
            new_effective_price=float(new_effective_price),
            effective_immediately=False,
            effective_at=effective_at,
        )


@router.post(
    "/billing-portal",
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        400: {"description": "No Stripe customer linked"},
    },
    summary="Create a Stripe Billing Portal session",
    dependencies=[require_role("org_admin")],
)
async def create_billing_portal(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a Stripe Customer Portal session for payment method management.

    Returns a URL that the frontend opens in a new tab or redirects to.
    The customer can update their card, view invoices, etc.
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    if not org.stripe_customer_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No Stripe customer linked to this organisation. Please contact support."},
        )

    # Build return URL — user comes back to the billing page after portal
    origin = request.headers.get("origin", "")
    return_url = f"{origin}/settings/billing" if origin else "/settings/billing"

    try:
        portal_url = await create_billing_portal_session(
            customer_id=org.stripe_customer_id,
            return_url=return_url,
        )
    except Exception as exc:
        logger.error("Failed to create billing portal session for org %s: %s", org_uuid, exc)
        return JSONResponse(
            status_code=502,
            content={"detail": "Could not create billing portal session. Please try again."},
        )

    return {"url": portal_url}


# ---------------------------------------------------------------------------
# Payment method management — Requirements: 1.1, 1.2, 1.6, 5.1, 5.5, 5.6
# ---------------------------------------------------------------------------


@router.get(
    "/payment-methods",
    response_model=PaymentMethodListResponse,
    status_code=200,
    responses={
        400: {"description": "No Stripe customer configured"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="List saved payment methods for the organisation",
    dependencies=[require_role("org_admin")],
)
async def list_payment_methods(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all payment methods from org_payment_methods for the org.

    Computes ``is_expiring_soon`` — true when the card's expiry (last day
    of exp_month/exp_year) is within 2 months of the current date.

    Requirements: 1.1, 1.2, 1.6, 5.1, 5.5, 5.6
    """
    from calendar import monthrange
    from dateutil.relativedelta import relativedelta

    org_uuid, _user_uuid, _ip_address = _extract_org_context(request)
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_customer_id:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "No Stripe customer configured for this organisation. Please contact support."
            },
        )

    pm_result = await db.execute(
        select(OrgPaymentMethod).where(OrgPaymentMethod.org_id == org_uuid)
    )
    payment_methods = list(pm_result.scalars().all())

    # ── Stripe sync fallback ──
    # If the local DB has no payment methods but the Stripe customer has
    # cards attached (e.g. the record was lost during signup), fetch them
    # from Stripe and persist locally so the billing page shows the card.
    if not payment_methods and org.stripe_customer_id:
        try:
            from app.integrations.stripe_billing import list_payment_methods as stripe_list_pms

            stripe_methods = await stripe_list_pms(customer_id=org.stripe_customer_id)
            for sm in stripe_methods:
                new_pm = OrgPaymentMethod(
                    org_id=org_uuid,
                    stripe_payment_method_id=sm["id"],
                    brand=sm.get("brand", "unknown"),
                    last4=sm.get("last4", "0000"),
                    exp_month=sm.get("exp_month", 0),
                    exp_year=sm.get("exp_year", 0),
                    is_default=(sm == stripe_methods[0]),  # first card = default
                    is_verified=True,
                )
                db.add(new_pm)
            if stripe_methods:
                await db.commit()
                # Re-fetch from DB so we have proper UUIDs
                pm_result2 = await db.execute(
                    select(OrgPaymentMethod).where(OrgPaymentMethod.org_id == org_uuid)
                )
                payment_methods = list(pm_result2.scalars().all())
                logger.info(
                    "Synced %d payment methods from Stripe for org %s",
                    len(stripe_methods),
                    org_uuid,
                )
        except Exception as exc:
            logger.warning(
                "Failed to sync payment methods from Stripe for org %s: %s",
                org_uuid,
                exc,
            )

    now = datetime.now(timezone.utc)
    two_months_later = now + relativedelta(months=2)

    items: list[PaymentMethodResponse] = []
    for pm in payment_methods:
        # Card is valid through the last day of its expiry month
        _, last_day = monthrange(pm.exp_year, pm.exp_month)
        expiry_date = datetime(
            pm.exp_year, pm.exp_month, last_day, 23, 59, 59, tzinfo=timezone.utc
        )
        is_expiring_soon = expiry_date <= two_months_later

        items.append(
            PaymentMethodResponse(
                id=pm.id,
                stripe_payment_method_id=pm.stripe_payment_method_id,
                brand=pm.brand,
                last4=pm.last4,
                exp_month=pm.exp_month,
                exp_year=pm.exp_year,
                is_default=pm.is_default,
                is_verified=pm.is_verified,
                is_expiring_soon=is_expiring_soon,
            )
        )

    return PaymentMethodListResponse(payment_methods=items)


# ---------------------------------------------------------------------------
# Setup intent — Requirements: 2.2, 5.2, 5.6, 10.1
# ---------------------------------------------------------------------------


@router.post(
    "/setup-intent",
    response_model=SetupIntentResponse,
    status_code=200,
    responses={
        400: {"description": "No Stripe customer configured"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        502: {"description": "Stripe API error"},
    },
    summary="Create a Stripe SetupIntent for adding a new card",
    dependencies=[require_role("org_admin")],
)
async def create_setup_intent_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a Stripe SetupIntent with ``usage='off_session'`` and return
    the client secret for frontend card confirmation.

    Requirements: 2.2, 5.2, 5.6, 10.1
    """
    org_uuid, _user_uuid, _ip_address = _extract_org_context(request)
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_customer_id:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "No Stripe customer configured for this organisation. Please contact support."
            },
        )

    try:
        intent_data = await create_setup_intent(
            customer_id=org.stripe_customer_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to create SetupIntent for org %s: %s", org_uuid, exc,
        )
        return JSONResponse(
            status_code=502,
            content={"detail": "Failed to create setup intent. Please try again."},
        )

    return SetupIntentResponse(
        client_secret=intent_data["client_secret"],
        setup_intent_id=intent_data["setup_intent_id"],
    )


# ---------------------------------------------------------------------------
# Set default payment method — Requirements: 3.1, 5.3, 7.3
# ---------------------------------------------------------------------------


@router.post(
    "/payment-methods/{payment_method_id}/set-default",
    status_code=200,
    responses={
        400: {"description": "No Stripe customer configured"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required / Access denied"},
        404: {"description": "Payment method not found"},
        502: {"description": "Stripe API error"},
    },
    summary="Set a payment method as the default for the organisation",
    dependencies=[require_role("org_admin")],
)
async def set_default_payment_method_endpoint(
    payment_method_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set the specified payment method as the Stripe customer's default
    and update the org_payment_methods table accordingly.

    Requirements: 3.1, 5.3, 7.3
    """
    org_uuid, _user_uuid, _ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Look up the organisation and validate Stripe customer
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_customer_id:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "No Stripe customer configured for this organisation. Please contact support."
            },
        )

    # Look up the payment method by UUID primary key
    pm_result = await db.execute(
        select(OrgPaymentMethod).where(OrgPaymentMethod.id == payment_method_id)
    )
    payment_method = pm_result.scalar_one_or_none()

    if payment_method is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Payment method not found"},
        )

    # Verify the payment method belongs to the requesting user's org
    if payment_method.org_id != org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied"},
        )

    # Update Stripe customer default payment method
    try:
        await set_default_payment_method(
            customer_id=org.stripe_customer_id,
            payment_method_id=payment_method.stripe_payment_method_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to set default payment method %s for org %s: %s",
            payment_method_id,
            org_uuid,
            exc,
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": "Failed to update default payment method. Please try again."
            },
        )

    # Update org_payment_methods: clear all defaults for this org
    await db.execute(
        update(OrgPaymentMethod)
        .where(OrgPaymentMethod.org_id == org_uuid)
        .values(is_default=False)
    )

    # Set the target payment method as default
    await db.execute(
        update(OrgPaymentMethod)
        .where(OrgPaymentMethod.id == payment_method_id)
        .values(is_default=True)
    )

    await db.commit()

    return {"success": True, "message": "Default payment method updated"}


# ---------------------------------------------------------------------------
# DELETE /billing/payment-methods/{payment_method_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/payment-methods/{payment_method_id}",
    status_code=200,
    responses={
        400: {
            "description": "No Stripe customer configured / sole payment method",
        },
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required / Access denied"},
        404: {"description": "Payment method not found"},
        502: {"description": "Stripe API error"},
    },
    summary="Remove a payment method from the organisation",
    dependencies=[require_role("org_admin")],
)
async def delete_payment_method_endpoint(
    payment_method_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Detach a payment method from Stripe and remove it from the local
    org_payment_methods table.

    Requirements: 4.2, 4.4, 4.7, 5.4, 7.3
    """
    org_uuid, _user_uuid, _ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Look up the organisation and validate Stripe customer
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_customer_id:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "No Stripe customer configured for this organisation. Please contact support."
            },
        )

    # Look up the payment method by UUID primary key
    pm_result = await db.execute(
        select(OrgPaymentMethod).where(OrgPaymentMethod.id == payment_method_id)
    )
    payment_method = pm_result.scalar_one_or_none()

    if payment_method is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Payment method not found"},
        )

    # Verify the payment method belongs to the requesting user's org
    if payment_method.org_id != org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied"},
        )

    # Prevent deletion if this is the only payment method on file
    count_result = await db.execute(
        select(func.count())
        .select_from(OrgPaymentMethod)
        .where(OrgPaymentMethod.org_id == org_uuid)
    )
    total_methods = count_result.scalar()

    if total_methods <= 1:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "You must have at least one valid payment method. Please add a new card before removing this one."
            },
        )

    # Detach from Stripe
    try:
        await detach_payment_method(
            payment_method_id=payment_method.stripe_payment_method_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to detach payment method %s for org %s: %s",
            payment_method_id,
            org_uuid,
            exc,
        )
        return JSONResponse(
            status_code=502,
            content={
                "detail": "Failed to remove payment method. Please try again."
            },
        )

    # Remove the record from org_payment_methods
    await db.execute(
        delete(OrgPaymentMethod).where(
            OrgPaymentMethod.id == payment_method_id
        )
    )

    await db.commit()

    return {"success": True, "message": "Payment method removed"}


@router.post(
    "/stripe/connect",
    response_model=StripeConnectInitResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Initiate Stripe Connect OAuth flow",
    dependencies=[require_role("org_admin")],
)
async def initiate_stripe_connect(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a Stripe Connect OAuth URL for the organisation.

    The Org Admin should be redirected to the returned URL to authorise
    their Stripe account. The platform never handles raw card data.

    Requirements: 25.1, 25.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    authorize_url, state = generate_connect_url(org_uuid)

    # Audit the initiation
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="stripe_connect.initiated",
        entity_type="organisation",
        entity_id=org_uuid,
        after_value={"state_prefix": str(org_uuid)},
        ip_address=ip_address,
    )
    await db.commit()

    return StripeConnectInitResponse(authorize_url=authorize_url)


@router.get(
    "/stripe/connect/callback",
    response_model=StripeConnectCallbackResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid callback parameters"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Handle Stripe Connect OAuth callback",
    dependencies=[require_role("org_admin")],
)
async def stripe_connect_callback(
    request: Request,
    code: str = Query(..., description="Authorisation code from Stripe"),
    state: str = Query(..., description="State token for CSRF verification"),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle the Stripe Connect OAuth callback.

    Exchanges the authorisation code for a connected account ID and stores
    it on the organisation record.

    Requirements: 25.1, 25.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Verify the state token belongs to this org
    parts = state.split(":", 1)
    if len(parts) != 2:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid state token"},
        )
    try:
        state_org_id = uuid.UUID(parts[0])
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid state token"},
        )

    if state_org_id != org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "State token does not match organisation"},
        )

    # Exchange code for connected account
    try:
        token_data = await handle_connect_callback(code, state)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"detail": "Failed to exchange authorisation code with Stripe"},
        )

    stripe_account_id = token_data.get("stripe_user_id")
    if not stripe_account_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Stripe did not return a connected account ID"},
        )

    # Store the connected account ID on the organisation
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation not found"},
        )

    before_account = org.stripe_connect_account_id
    org.stripe_connect_account_id = stripe_account_id
    await db.flush()

    # Audit the connection
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="stripe_connect.connected",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={"stripe_connect_account_id": before_account},
        after_value={"stripe_connect_account_id": stripe_account_id},
        ip_address=ip_address,
    )
    await db.commit()

    return StripeConnectCallbackResponse(
        stripe_account_id=stripe_account_id,
        org_id=org_uuid,
    )



# ---------------------------------------------------------------------------
# Storage add-on purchasing — Requirements: 30.1, 30.2, 30.3, 30.4
# ---------------------------------------------------------------------------


@router.post(
    "/storage/purchase",
    response_model=StoragePurchaseResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid increment or payment failure"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Purchase storage add-on",
    dependencies=[require_role("org_admin")],
)
async def purchase_storage(
    request: Request,
    body: StoragePurchaseRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Purchase additional storage in Global_Admin-configured increments.

    Flow:
    1. Validate the requested increment is allowed.
    2. Charge the org's stored payment method via Stripe immediately.
    3. Increase the org's storage quota instantly.
    4. Record in audit log.
    5. Return confirmation (email sent asynchronously).

    The add-on cost is also added as a line item on the next monthly invoice.

    Requirements: 30.1, 30.2, 30.3, 30.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Execute purchase
    try:
        result = await purchase_storage_addon(
            db,
            org_id=org_uuid,
            quantity_gb=body.quantity_gb,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="storage.addon_purchased",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={"storage_quota_gb": result["previous_quota_gb"]},
        after_value={
            "storage_quota_gb": result["new_total_quota_gb"],
            "quantity_gb": result["quantity_gb"],
            "charge_amount_nzd": result["charge_amount_nzd"],
            "stripe_charge_id": result["stripe_charge_id"],
        },
        ip_address=ip_address,
    )
    await db.commit()

    # TODO: Send confirmation email asynchronously via Celery task
    # TODO: Add storage add-on as line item on next monthly Stripe invoice

    return StoragePurchaseResponse(
        success=True,
        quantity_gb=result["quantity_gb"],
        new_total_quota_gb=result["new_total_quota_gb"],
        charge_amount_nzd=result["charge_amount_nzd"],
        stripe_charge_id=result["stripe_charge_id"],
        message=f"Successfully purchased {result['quantity_gb']} GB additional storage. "
        f"New total quota: {result['new_total_quota_gb']} GB. "
        f"Charged ${result['charge_amount_nzd']:.2f} NZD.",
    )


# ---------------------------------------------------------------------------
# Storage add-on management (package-based) — Requirements: 4.1–4.7, 5.1–5.7
# ---------------------------------------------------------------------------


@router.get(
    "/storage-addon",
    response_model=StorageAddonStatusResponse,
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Get storage add-on status and available packages",
    dependencies=[require_role("org_admin")],
)
async def get_storage_addon(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return current storage add-on status, available packages, and quotas.

    Requirements: 4.1–4.5, 5.1–5.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_storage_addon_status(db, org_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return StorageAddonStatusResponse(**result)


@router.post(
    "/storage-addon",
    response_model=StorageAddonResponse,
    status_code=201,
    responses={
        400: {"description": "Invalid request or package inactive"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        404: {"description": "Storage package not found"},
        409: {"description": "Organisation already has a storage add-on"},
    },
    summary="Purchase a storage add-on",
    dependencies=[require_role("org_admin")],
)
async def create_storage_addon(
    request: Request,
    body: StorageAddonPurchaseRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Purchase a new storage add-on (package or custom GB).

    Only allowed if the organisation has no existing add-on.

    Requirements: 4.1–4.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await purchase_storage_addon_v2(
            db,
            org_uuid,
            package_id=body.package_id,
            custom_gb=body.custom_gb,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already has" in msg:
            return JSONResponse(status_code=409, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    await db.commit()
    return StorageAddonResponse(**result)


@router.put(
    "/storage-addon",
    response_model=StorageAddonResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid request, package inactive, or usage exceeds new quota"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        404: {"description": "No active add-on or package not found"},
    },
    summary="Resize existing storage add-on",
    dependencies=[require_role("org_admin")],
)
async def update_storage_addon(
    request: Request,
    body: StorageAddonResizeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Resize (upgrade or downgrade) the existing storage add-on.

    Requirements: 5.1–5.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await resize_storage_addon(
            db,
            org_uuid,
            package_id=body.package_id,
            custom_gb=body.custom_gb,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "exceeds" in msg:
            return JSONResponse(status_code=400, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    await db.commit()
    return StorageAddonResponse(**result)


@router.delete(
    "/storage-addon",
    status_code=200,
    responses={
        400: {"description": "Usage exceeds base quota"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
        404: {"description": "No active storage add-on"},
    },
    summary="Remove storage add-on",
    dependencies=[require_role("org_admin")],
)
async def delete_storage_addon(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove the active storage add-on, reverting to plan base quota.

    Validates that current usage does not exceed the base quota.

    Requirements: 5.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await remove_storage_addon(
            db,
            org_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "exceeds" in msg:
            return JSONResponse(status_code=400, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Subscription invoices — Requirements: 42.3
# ---------------------------------------------------------------------------


@router.get(
    "/invoices",
    response_model=list[SubscriptionInvoiceResponse],
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="List past subscription invoices",
    dependencies=[require_role("org_admin")],
)
async def list_subscription_invoices(
    request: Request,
    limit: int = Query(default=24, ge=1, le=100, description="Max invoices to return"),
    db: AsyncSession = Depends(get_db_session),
):
    """List past Stripe subscription invoices for the organisation.

    Returns invoice PDFs and details viewable from the Billing page.

    Requirements: 42.3
    """
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
            status_code=404,
            content={"detail": "Organisation not found"},
        )

    if not org.stripe_customer_id:
        return []

    try:
        invoices = await get_subscription_invoices(
            customer_id=org.stripe_customer_id,
            limit=limit,
        )
    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception("Failed to fetch Stripe invoices for org %s", org_uuid)
        return JSONResponse(
            status_code=502,
            content={"detail": "Failed to retrieve invoices from Stripe"},
        )

    return [SubscriptionInvoiceResponse(**inv) for inv in invoices]


# ---------------------------------------------------------------------------
# Plan upgrade — Requirements: 43.1, 43.2
# ---------------------------------------------------------------------------


@router.post(
    "/upgrade",
    response_model=PlanUpgradeResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid plan or upgrade not allowed"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Upgrade subscription plan",
    dependencies=[require_role("org_admin")],
)
async def upgrade_plan(
    request: Request,
    body: PlanChangeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Upgrade the organisation's subscription plan immediately with prorated charges.

    Validates the target plan exists and is not archived, then updates the
    organisation's plan, storage quota, billing interval, and Stripe subscription
    with proration based on the interval effective price.

    Requirements: 43.1, 43.2, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
    """
    from decimal import Decimal as _Dec

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Load org with current plan
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    # Validate target plan
    try:
        new_plan_uuid = uuid.UUID(body.new_plan_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid plan ID"})

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_uuid)
    )
    new_plan = plan_result.scalar_one_or_none()
    if new_plan is None:
        return JSONResponse(status_code=400, content={"detail": "Plan not found"})
    if new_plan.is_archived:
        return JSONResponse(status_code=400, content={"detail": "Cannot upgrade to an archived plan"})
    if new_plan.id == org.plan_id:
        # Same plan — but interval might differ, handled below via effective price check
        pass

    # Determine the billing interval: use request value or fall back to org's current
    current_org_interval = getattr(org, "billing_interval", "monthly") or "monthly"
    selected_interval = body.billing_interval or current_org_interval

    # Validate the target plan supports the selected interval (Req 8.3)
    new_plan_config = new_plan.interval_config if new_plan.interval_config else build_default_interval_config()
    enabled_intervals = {
        item["interval"]
        for item in new_plan_config
        if item.get("enabled", False)
    }
    if selected_interval not in enabled_intervals:
        supported = ", ".join(sorted(enabled_intervals))
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Interval '{selected_interval}' is not available for the target plan. "
                          f"Supported intervals: {supported}."
            },
        )

    # Compute effective prices for comparison
    new_discount = _Dec("0")
    for item in new_plan_config:
        if item["interval"] == selected_interval:
            new_discount = _Dec(str(item.get("discount_percent", 0)))
            break

    new_base_price = _Dec(str(new_plan.monthly_price_nzd))
    new_effective_price = compute_effective_price(new_base_price, selected_interval, new_discount)

    # Load current plan to compute current effective price
    current_plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    current_plan = current_plan_result.scalar_one_or_none()

    current_effective_price = _Dec("0")
    if current_plan:
        current_config = current_plan.interval_config if current_plan.interval_config else build_default_interval_config()
        current_discount = _Dec("0")
        for item in current_config:
            if item["interval"] == current_org_interval and item.get("enabled"):
                current_discount = _Dec(str(item.get("discount_percent", 0)))
                break
        current_effective_price = compute_effective_price(
            _Dec(str(current_plan.monthly_price_nzd)), current_org_interval, current_discount,
        )

    # Same effective price → no change needed (Req 8.7)
    if new_effective_price == current_effective_price and new_plan.id == org.plan_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No change needed — the selected plan and interval result in the same effective price."},
        )

    # Verify this is an upgrade (higher effective price or higher base price)
    if current_plan and float(new_plan.monthly_price_nzd) <= float(current_plan.monthly_price_nzd) and new_plan.id != org.plan_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Target plan is not an upgrade. Use the downgrade endpoint instead."},
        )

    # Store before values for audit / rollback
    before_plan_id = org.plan_id
    before_storage = org.storage_quota_gb
    before_interval = current_org_interval

    # Update org immediately (Req 8.5)
    org.plan_id = new_plan.id
    org.storage_quota_gb = max(org.storage_quota_gb, new_plan.storage_quota_gb)
    org.billing_interval = selected_interval
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="subscription.plan_upgraded",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={
            "plan_id": str(before_plan_id),
            "storage_quota_gb": before_storage,
            "billing_interval": before_interval,
        },
        after_value={
            "plan_id": str(new_plan.id),
            "plan_name": new_plan.name,
            "storage_quota_gb": org.storage_quota_gb,
            "billing_interval": selected_interval,
            "effective_price": float(new_effective_price),
            "prorated_charge_nzd": prorated_charge_nzd,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return PlanUpgradeResponse(
        success=True,
        message=f"Upgraded to {new_plan.name} ({selected_interval}). Prorated charge of ${prorated_charge_nzd:.2f} NZD applied.",
        new_plan_name=new_plan.name,
        prorated_charge_nzd=prorated_charge_nzd,
        effective_immediately=True,
    )


# ---------------------------------------------------------------------------
# Plan downgrade — Requirements: 43.1, 43.3, 43.4
# ---------------------------------------------------------------------------


@router.post(
    "/downgrade",
    response_model=PlanDowngradeResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid plan or downgrade blocked by limits"},
        401: {"description": "Authentication required"},
        403: {"description": "Org Admin role required"},
    },
    summary="Downgrade subscription plan",
    dependencies=[require_role("org_admin")],
)
async def downgrade_plan(
    request: Request,
    body: PlanChangeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Downgrade the organisation's subscription plan at the next billing period.

    Validates the target plan, checks storage and user limits, and schedules
    the downgrade. Stores both new_plan_id and billing_interval in pending settings.
    Returns warnings if the org exceeds the new plan's limits.

    Requirements: 43.1, 43.3, 43.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
    """
    from decimal import Decimal as _Dec

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Load org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    # Validate target plan
    try:
        new_plan_uuid = uuid.UUID(body.new_plan_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid plan ID"})

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_uuid)
    )
    new_plan = plan_result.scalar_one_or_none()
    if new_plan is None:
        return JSONResponse(status_code=400, content={"detail": "Plan not found"})
    if new_plan.is_archived:
        return JSONResponse(status_code=400, content={"detail": "Cannot downgrade to an archived plan"})
    if new_plan.id == org.plan_id:
        # Same plan — but interval might differ, handled below via effective price check
        pass

    # Determine the billing interval: use request value or fall back to org's current
    current_org_interval = getattr(org, "billing_interval", "monthly") or "monthly"
    selected_interval = body.billing_interval or current_org_interval

    # Validate the target plan supports the selected interval (Req 8.3)
    new_plan_config = new_plan.interval_config if new_plan.interval_config else build_default_interval_config()
    enabled_intervals = {
        item["interval"]
        for item in new_plan_config
        if item.get("enabled", False)
    }
    if selected_interval not in enabled_intervals:
        supported = ", ".join(sorted(enabled_intervals))
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Interval '{selected_interval}' is not available for the target plan. "
                          f"Supported intervals: {supported}."
            },
        )

    # Compute effective prices for comparison
    new_discount = _Dec("0")
    for item in new_plan_config:
        if item["interval"] == selected_interval:
            new_discount = _Dec(str(item.get("discount_percent", 0)))
            break

    new_base_price = _Dec(str(new_plan.monthly_price_nzd))
    new_effective_price = compute_effective_price(new_base_price, selected_interval, new_discount)

    # Load current plan to compute current effective price
    current_plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    current_plan = current_plan_result.scalar_one_or_none()

    current_effective_price = _Dec("0")
    if current_plan:
        current_config = current_plan.interval_config if current_plan.interval_config else build_default_interval_config()
        current_discount = _Dec("0")
        for item in current_config:
            if item["interval"] == current_org_interval and item.get("enabled"):
                current_discount = _Dec(str(item.get("discount_percent", 0)))
                break
        current_effective_price = compute_effective_price(
            _Dec(str(current_plan.monthly_price_nzd)), current_org_interval, current_discount,
        )

    # Same effective price → no change needed (Req 8.7)
    if new_effective_price == current_effective_price and new_plan.id == org.plan_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No change needed — the selected plan and interval result in the same effective price."},
        )

    # Verify this is a downgrade (lower effective price or lower base price)
    if current_plan and float(new_plan.monthly_price_nzd) >= float(current_plan.monthly_price_nzd) and new_plan.id != org.plan_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Target plan is not a downgrade. Use the upgrade endpoint instead."},
        )

    # Check storage and user limits (Req 43.4)
    warnings: list[str] = []

    # Storage check
    storage_used_gb = org.storage_used_bytes / (1024 ** 3)
    if storage_used_gb > new_plan.storage_quota_gb:
        warnings.append(
            f"Current storage usage ({storage_used_gb:.2f} GB) exceeds the "
            f"{new_plan.name} plan limit ({new_plan.storage_quota_gb} GB). "
            f"Please reduce storage usage before the downgrade takes effect."
        )

    # User seat check
    active_user_count_result = await db.execute(
        select(func.count(User.id)).where(
            User.org_id == org_uuid,
            User.is_active.is_(True),
        )
    )
    active_users = active_user_count_result.scalar() or 0
    if active_users > new_plan.user_seats:
        warnings.append(
            f"Current active users ({active_users}) exceeds the "
            f"{new_plan.name} plan limit ({new_plan.user_seats} seats). "
            f"Please deactivate {active_users - new_plan.user_seats} user(s) "
            f"before the downgrade takes effect."
        )

    # If there are warnings, return them without scheduling the downgrade
    if warnings:
        return PlanDowngradeResponse(
            success=False,
            message="Downgrade cannot proceed until the following issues are resolved.",
            new_plan_name=new_plan.name,
            effective_at=None,
            warnings=warnings,
        )

    # Schedule downgrade at next billing period (Req 8.6)
    effective_at = org.next_billing_date

    # Store the pending downgrade in org settings with billing_interval (Req 8.6)
    org_settings = dict(org.settings) if org.settings else {}
    org_settings["pending_downgrade"] = {
        "new_plan_id": str(new_plan.id),
        "new_plan_name": new_plan.name,
        "new_storage_quota_gb": new_plan.storage_quota_gb,
        "billing_interval": selected_interval,
        "effective_price": float(new_effective_price),
        "effective_at": effective_at.isoformat() if effective_at else None,
    }
    org.settings = org_settings
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=user_uuid,
        action="subscription.plan_downgrade_scheduled",
        entity_type="organisation",
        entity_id=org_uuid,
        before_value={
            "plan_id": str(org.plan_id),
            "plan_name": current_plan.name if current_plan else "Unknown",
            "billing_interval": current_org_interval,
        },
        after_value={
            "new_plan_id": str(new_plan.id),
            "new_plan_name": new_plan.name,
            "billing_interval": selected_interval,
            "effective_price": float(new_effective_price),
            "effective_at": effective_at.isoformat() if effective_at else None,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return PlanDowngradeResponse(
        success=True,
        message=f"Downgrade to {new_plan.name} ({selected_interval}) scheduled for the start of your next billing period.",
        new_plan_name=new_plan.name,
        effective_at=effective_at,
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Stripe subscription webhook — Requirements: 42.1, 42.3, 42.4, 42.5, 42.6
# ---------------------------------------------------------------------------


@router.post(
    "/webhook",
    status_code=200,
    summary="Stripe subscription webhook handler",
)
async def stripe_subscription_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle Stripe subscription webhook events.

    Processes payment success/failure events, triggers dunning emails,
    manages grace period and suspension transitions.

    Requirements: 42.1, 42.3, 42.4, 42.5, 42.6
    """
    _logger = logging.getLogger(__name__)

    body = await request.body()

    # Verify webhook signature — load signing secret from DB (Global Admin GUI)
    from app.integrations.stripe_billing import _load_webhook_secret_from_db
    webhook_secret = await _load_webhook_secret_from_db()
    if webhook_secret and stripe_signature:
        try:
            event = stripe.Webhook.construct_event(
                body, stripe_signature, webhook_secret
            )
        except stripe.error.SignatureVerificationError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid webhook signature"},
            )
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"detail": "Webhook verification failed"},
            )
    else:
        import json

        event = json.loads(body)

    event_type = event.get("type", "")
    event_data = event.get("data", {})

    # Parse webhook event inline (previously delegated to handle_subscription_webhook)
    obj = event_data.get("object", {})
    customer_id = obj.get("customer")

    _EVENT_ACTION_MAP = {
        "invoice.payment_succeeded": "payment_succeeded",
        "invoice.payment_failed": "payment_failed",
        "customer.subscription.updated": "subscription_updated",
        "customer.subscription.deleted": "subscription_deleted",
        "invoice.created": "invoice_created",
        "customer.updated": "customer_updated",
        "setup_intent.succeeded": "setup_intent_succeeded",
    }

    action = _EVENT_ACTION_MAP.get(event_type)
    if action is None:
        return {"status": "ignored", "event_type": event_type}

    webhook_result: dict = {"processed": True, "action": action, "customer_id": customer_id}

    if action == "payment_succeeded":
        webhook_result["subscription_id"] = obj.get("subscription")
        webhook_result["amount_paid"] = obj.get("amount_paid", 0)
        webhook_result["invoice_pdf"] = obj.get("invoice_pdf")
        webhook_result["hosted_invoice_url"] = obj.get("hosted_invoice_url")
    elif action == "payment_failed":
        webhook_result["attempt_count"] = obj.get("attempt_count", 0)
        webhook_result["next_payment_attempt"] = obj.get("next_payment_attempt")
    elif action == "subscription_updated":
        webhook_result["status"] = obj.get("status")
        webhook_result["cancel_at_period_end"] = obj.get("cancel_at_period_end", False)
    elif action == "subscription_deleted":
        webhook_result["subscription_id"] = obj.get("id")
    elif action == "invoice_created":
        webhook_result["billing_reason"] = obj.get("billing_reason", "")
        webhook_result["invoice_id"] = obj.get("id")
    elif action == "customer_updated":
        inv_settings = obj.get("invoice_settings", {})
        webhook_result["default_payment_method"] = inv_settings.get("default_payment_method")
    elif action == "setup_intent_succeeded":
        webhook_result["payment_method_id"] = obj.get("payment_method")
        webhook_result["card_details"] = {}

    if not customer_id:
        return {"status": "processed", "action": action}

    # Find the organisation by stripe_customer_id
    org_result = await db.execute(
        select(Organisation).where(
            Organisation.stripe_customer_id == customer_id
        )
    )
    org = org_result.scalar_one_or_none()

    if not org:
        _logger.warning(
            "No org found for Stripe customer %s (event: %s)",
            customer_id,
            event_type,
        )
        return {"status": "processed", "action": action, "org_found": False}

    # Handle invoice.created — add overage line items before Stripe charges
    if action == "invoice_created":
        billing_reason = webhook_result.get("billing_reason", "")
        invoice_id = webhook_result.get("invoice_id")

        # Only add overages for subscription renewal invoices
        if billing_reason in ("subscription_cycle", "subscription_create"):
            overage_items_added = []

            try:
                # --- SMS overage ---
                from app.modules.admin.service import compute_sms_overage_for_billing
                sms_result = await compute_sms_overage_for_billing(db, org.id)
                if sms_result["overage_count"] > 0:
                    sms_item = await create_invoice_item(
                        customer_id=org.stripe_customer_id,
                        description=f"SMS overage — {sms_result['overage_count']} messages",
                        quantity=sms_result["overage_count"],
                        unit_amount_cents=int(round(sms_result["per_sms_cost_nzd"] * 100)),
                        metadata={"type": "sms_overage", "org_id": str(org.id)},
                    )
                    overage_items_added.append(sms_item)

                # --- Carjam overage ---
                plan_result = await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
                )
                plan = plan_result.scalar_one_or_none()
                carjam_included = plan.carjam_lookups_included if plan else 0
                carjam_used = org.carjam_lookups_this_month
                carjam_overage = max(0, carjam_used - carjam_included)

                if carjam_overage > 0:
                    carjam_item = await create_invoice_item(
                        customer_id=org.stripe_customer_id,
                        description=f"Carjam overage — {carjam_overage} lookups",
                        quantity=carjam_overage,
                        unit_amount_cents=int(round(_CARJAM_OVERAGE_RATE_NZD * 100)),
                        metadata={"type": "carjam_overage", "org_id": str(org.id)},
                    )
                    overage_items_added.append(carjam_item)

                # --- Storage add-on (recurring charge) ---
                addon_result = await db.execute(
                    select(OrgStorageAddon).where(OrgStorageAddon.org_id == org.id)
                )
                addon = addon_result.scalar_one_or_none()
                if addon and float(addon.price_nzd_per_month) > 0:
                    storage_item = await create_invoice_item(
                        customer_id=org.stripe_customer_id,
                        description=f"Storage add-on — {addon.quantity_gb} GB",
                        quantity=1,
                        unit_amount_cents=int(round(float(addon.price_nzd_per_month) * 100)),
                        metadata={"type": "storage_addon", "org_id": str(org.id)},
                    )
                    overage_items_added.append(storage_item)

                _logger.info(
                    "Added %d overage items to invoice %s for org %s",
                    len(overage_items_added),
                    invoice_id,
                    org.id,
                )

            except Exception as exc:
                _logger.error(
                    "Failed to add overage items to invoice %s for org %s: %s",
                    invoice_id,
                    org.id,
                    exc,
                )

        await db.commit()
        return {
            "status": "processed",
            "action": action,
            "org_id": str(org.id),
            "overage_items": len(overage_items_added) if billing_reason in ("subscription_cycle", "subscription_create") else 0,
        }

    # Handle payment success — restore from grace period if needed
    if action == "payment_succeeded":
        if org.status == "grace_period":
            old_status = org.status
            org.status = "active"
            # Clear grace period metadata
            org_settings = dict(org.settings) if org.settings else {}
            org_settings.pop("grace_period_started_at", None)
            org_settings.pop("payment_failure_count", None)
            org.settings = org_settings
            await db.flush()

            await write_audit_log(
                session=db,
                org_id=org.id,
                action="subscription.payment_recovered",
                entity_type="organisation",
                entity_id=org.id,
                before_value={"status": old_status},
                after_value={"status": "active"},
            )

        # Send invoice PDF email to Org_Admin (Req 42.3)
        invoice_pdf = webhook_result.get("invoice_pdf")
        if invoice_pdf:
            from app.tasks.subscriptions import send_invoice_email_task

            await send_invoice_email_task(
                org_id=str(org.id),
                invoice_pdf_url=invoice_pdf,
                amount_paid=webhook_result.get("amount_paid", 0),
            )

        # Reset monthly usage counters for the new billing cycle
        org.sms_sent_this_month = 0
        org.sms_sent_reset_at = datetime.now(timezone.utc)
        org.carjam_lookups_this_month = 0
        org.carjam_lookups_reset_at = datetime.now(timezone.utc)
        await db.flush()

    # Handle payment failure — dunning flow (Req 42.4)
    elif action == "payment_failed":
        attempt_count = webhook_result.get("attempt_count", 0)
        org_settings = dict(org.settings) if org.settings else {}
        org_settings["payment_failure_count"] = attempt_count
        org.settings = org_settings
        await db.flush()

        await write_audit_log(
            session=db,
            org_id=org.id,
            action="subscription.payment_failed",
            entity_type="organisation",
            entity_id=org.id,
            after_value={
                "attempt_count": attempt_count,
                "status": org.status,
            },
        )

        # Send dunning email (Req 42.4)
        from app.tasks.subscriptions import send_dunning_email_task

        await send_dunning_email_task(
            org_id=str(org.id),
            attempt_count=attempt_count,
        )

        # After final retry (14 days / ~3 attempts), enter grace period (Req 42.5)
        if attempt_count >= 3 and org.status == "active":
            org.status = "grace_period"
            org_settings["grace_period_started_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            org.settings = org_settings
            await db.flush()

            await write_audit_log(
                session=db,
                org_id=org.id,
                action="subscription.grace_period_entered",
                entity_type="organisation",
                entity_id=org.id,
                before_value={"status": "active"},
                after_value={"status": "grace_period"},
            )

    # Handle subscription updated — portal plan changes or cancellation scheduling
    elif action == "subscription_updated":
        cancel_at_period_end = webhook_result.get("cancel_at_period_end", False)
        sub_status = webhook_result.get("status")

        if cancel_at_period_end:
            # Customer scheduled cancellation from portal — mark in settings
            org_settings = dict(org.settings) if org.settings else {}
            org_settings["cancel_at_period_end"] = True
            org.settings = org_settings
            await db.flush()
            _logger.info("Org %s scheduled cancellation at period end", org.id)

            await write_audit_log(
                session=db,
                org_id=org.id,
                action="subscription.cancellation_scheduled",
                entity_type="organisation",
                entity_id=org.id,
                after_value={"cancel_at_period_end": True},
            )
        else:
            # Reactivation or plan change — clear cancellation flag if set
            org_settings = dict(org.settings) if org.settings else {}
            if org_settings.pop("cancel_at_period_end", None):
                org.settings = org_settings
                await db.flush()
                _logger.info("Org %s reactivated subscription", org.id)

    # Handle subscription deleted — customer cancelled or Stripe terminated
    elif action == "subscription_deleted":
        old_status = org.status
        org.status = "suspended"
        org.stripe_subscription_id = None
        await db.flush()

        await write_audit_log(
            session=db,
            org_id=org.id,
            action="subscription.cancelled",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": old_status},
            after_value={"status": "suspended"},
        )
        _logger.info("Org %s subscription deleted, status set to suspended", org.id)

    # Handle customer updated — payment method changes from portal
    elif action == "customer_updated":
        # Log for audit trail — no DB changes needed since Stripe holds the payment method
        await write_audit_log(
            session=db,
            org_id=org.id,
            action="billing.payment_method_updated",
            entity_type="organisation",
            entity_id=org.id,
            after_value={"default_payment_method": webhook_result.get("default_payment_method")},
        )
        _logger.info("Org %s updated payment method via portal", org.id)

    # Handle setup_intent.succeeded — verify/create payment method record
    elif action == "setup_intent_succeeded":
        payment_method_id = webhook_result.get("payment_method_id")
        card_details = webhook_result.get("card_details", {})

        if payment_method_id:
            try:
                # Check if payment method already exists locally
                existing_result = await db.execute(
                    select(OrgPaymentMethod).where(
                        OrgPaymentMethod.stripe_payment_method_id == payment_method_id
                    )
                )
                existing_pm = existing_result.scalar_one_or_none()

                if existing_pm:
                    # Update existing record — mark as verified
                    existing_pm.is_verified = True
                    _logger.info(
                        "Updated payment method %s as verified for org %s",
                        payment_method_id,
                        org.id,
                    )
                else:
                    # Create new record (sync from Stripe)
                    # Check if this is the first card for the org (auto-default)
                    count_result = await db.execute(
                        select(func.count()).select_from(OrgPaymentMethod).where(
                            OrgPaymentMethod.org_id == org.id
                        )
                    )
                    existing_count = count_result.scalar() or 0
                    is_first_card = existing_count == 0

                    new_pm = OrgPaymentMethod(
                        org_id=org.id,
                        stripe_payment_method_id=payment_method_id,
                        brand=card_details.get("brand", "unknown"),
                        last4=card_details.get("last4", "0000"),
                        exp_month=card_details.get("exp_month", 0),
                        exp_year=card_details.get("exp_year", 0),
                        is_default=is_first_card,
                        is_verified=True,
                    )
                    db.add(new_pm)
                    _logger.info(
                        "Created payment method %s for org %s (is_default=%s)",
                        payment_method_id,
                        org.id,
                        is_first_card,
                    )
            except Exception as exc:
                _logger.error(
                    "Failed to process setup_intent.succeeded for payment method %s, org %s: %s",
                    payment_method_id,
                    org.id,
                    exc,
                )
                # Return 200 to Stripe even on internal errors to prevent retries
                return {"status": "processed", "action": action, "org_id": str(org.id), "error": str(exc)}

    await db.commit()
    return {"status": "processed", "action": action, "org_id": str(org.id)}
