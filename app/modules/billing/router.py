"""Billing router — Stripe Connect OAuth, storage add-on, trial status, subscription invoices, webhook.

Provides:
- POST /api/v1/billing/stripe/connect — initiate Stripe Connect OAuth
- GET  /api/v1/billing/stripe/connect/callback — handle OAuth callback
- POST /api/v1/billing/storage/purchase — purchase storage add-on
- GET  /api/v1/billing/trial — trial countdown data
- GET  /api/v1/billing/invoices — list past subscription invoices
- POST /api/v1/billing/webhook — Stripe subscription webhook handler

Requirements: 25.1, 25.2, 30.1, 30.2, 30.3, 30.4, 41.3, 42.1, 42.2, 42.3, 42.4
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.audit import write_audit_log
from app.core.database import get_db_session
from app.integrations.stripe_billing import (
    get_subscription_details,
    get_subscription_invoices,
    handle_subscription_webhook,
    update_subscription_plan,
)
from app.integrations.stripe_connect import (
    generate_connect_url,
    handle_connect_callback,
)
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.auth.rbac import require_role
from app.modules.billing.schemas import (
    BillingDashboardResponse,
    PlanChangeRequest,
    PlanDowngradeResponse,
    PlanUpgradeResponse,
    SubscriptionInvoiceResponse,
    TrialStatusResponse,
)
from app.modules.payments.schemas import (
    StripeConnectCallbackResponse,
    StripeConnectInitResponse,
)
from app.modules.storage.schemas import (
    StoragePurchaseRequest,
    StoragePurchaseResponse,
)
from app.modules.storage.service import purchase_storage_addon

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

    # Next billing date from Stripe subscription
    next_billing_date = None
    if org.stripe_subscription_id:
        try:
            sub_details = await get_subscription_details(
                subscription_id=org.stripe_subscription_id,
            )
            period_end = sub_details.get("current_period_end")
            if period_end:
                next_billing_date = datetime.fromtimestamp(period_end, tz=timezone.utc)
        except Exception:
            logger.warning(
                "Could not fetch subscription details for org %s", org_uuid,
            )

    # Storage usage
    storage_used_gb = org.storage_used_bytes / (1024 ** 3)

    # Storage add-on charge: any extra GB beyond the plan's base quota
    storage_addon_gb = max(0, org.storage_quota_gb - (plan.storage_quota_gb if plan else 0))
    # Use tier pricing from plan if available, otherwise default $5/GB/month
    storage_price_per_gb = 5.0
    if plan and plan.storage_tier_pricing:
        storage_price_per_gb = plan.storage_tier_pricing.get("price_per_gb", 5.0)
    storage_addon_charge = storage_addon_gb * storage_price_per_gb

    # Carjam overage charge
    carjam_used = org.carjam_lookups_this_month
    carjam_overage = max(0, carjam_used - carjam_included)
    carjam_overage_charge = carjam_overage * _CARJAM_OVERAGE_RATE_NZD

    # Estimated next invoice
    estimated_total = plan_price + storage_addon_charge + carjam_overage_charge

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
        org_status=org.status,
        past_invoices=past_invoices,
    )


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
    organisation's plan, storage quota, and Stripe subscription with proration.

    Requirements: 43.1, 43.2
    """
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
        return JSONResponse(status_code=400, content={"detail": "Already on this plan"})

    # Load current plan to verify this is actually an upgrade (higher price)
    current_plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    current_plan = current_plan_result.scalar_one_or_none()
    if current_plan and float(new_plan.monthly_price_nzd) <= float(current_plan.monthly_price_nzd):
        return JSONResponse(
            status_code=400,
            content={"detail": "Target plan is not an upgrade. Use the downgrade endpoint instead."},
        )

    # Store before values for audit
    before_plan_id = org.plan_id
    before_storage = org.storage_quota_gb

    # Update org immediately
    org.plan_id = new_plan.id
    org.storage_quota_gb = max(org.storage_quota_gb, new_plan.storage_quota_gb)
    await db.flush()

    # Update Stripe subscription with proration
    prorated_charge_nzd = 0.0
    if org.stripe_subscription_id:
        try:
            stripe_result = await update_subscription_plan(
                subscription_id=org.stripe_subscription_id,
                new_monthly_amount_cents=int(float(new_plan.monthly_price_nzd) * 100),
                proration_behavior="create_prorations",
            )
            prorated_charge_nzd = stripe_result.get("prorated_amount_cents", 0) / 100.0
        except Exception:
            _logger = logging.getLogger(__name__)
            _logger.exception("Stripe subscription update failed for org %s", org_uuid)
            # Rollback org changes on Stripe failure
            org.plan_id = before_plan_id
            org.storage_quota_gb = before_storage
            await db.flush()
            return JSONResponse(
                status_code=502,
                content={"detail": "Failed to update subscription with Stripe. Plan not changed."},
            )

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
        },
        after_value={
            "plan_id": str(new_plan.id),
            "plan_name": new_plan.name,
            "storage_quota_gb": org.storage_quota_gb,
            "prorated_charge_nzd": prorated_charge_nzd,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return PlanUpgradeResponse(
        success=True,
        message=f"Upgraded to {new_plan.name}. Prorated charge of ${prorated_charge_nzd:.2f} NZD applied.",
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
    the downgrade. Returns warnings if the org exceeds the new plan's limits.

    Requirements: 43.1, 43.3, 43.4
    """
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
        return JSONResponse(status_code=400, content={"detail": "Already on this plan"})

    # Load current plan to verify this is actually a downgrade (lower price)
    current_plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    current_plan = current_plan_result.scalar_one_or_none()
    if current_plan and float(new_plan.monthly_price_nzd) >= float(current_plan.monthly_price_nzd):
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

    # Schedule downgrade at next billing period via Stripe
    effective_at = None
    if org.stripe_subscription_id:
        try:
            stripe_result = await update_subscription_plan(
                subscription_id=org.stripe_subscription_id,
                new_monthly_amount_cents=int(float(new_plan.monthly_price_nzd) * 100),
                proration_behavior="none",
            )
            # The change takes effect at the end of the current period
            period_end = stripe_result.get("current_period_end")
            if period_end:
                effective_at = datetime.fromtimestamp(period_end, tz=timezone.utc)
        except Exception:
            _logger = logging.getLogger(__name__)
            _logger.exception("Stripe subscription update failed for org %s", org_uuid)
            return JSONResponse(
                status_code=502,
                content={"detail": "Failed to schedule downgrade with Stripe."},
            )

    # Store the pending downgrade in org settings so it can be applied at period end
    org_settings = dict(org.settings) if org.settings else {}
    org_settings["pending_downgrade"] = {
        "new_plan_id": str(new_plan.id),
        "new_plan_name": new_plan.name,
        "new_storage_quota_gb": new_plan.storage_quota_gb,
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
        },
        after_value={
            "new_plan_id": str(new_plan.id),
            "new_plan_name": new_plan.name,
            "effective_at": effective_at.isoformat() if effective_at else None,
        },
        ip_address=ip_address,
    )
    await db.commit()

    return PlanDowngradeResponse(
        success=True,
        message=f"Downgrade to {new_plan.name} scheduled for the start of your next billing period.",
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

    # Verify webhook signature
    webhook_secret = settings.stripe_webhook_secret
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

    # Process via integration layer
    webhook_result = await handle_subscription_webhook(
        event_type=event_type,
        event_data=event_data,
    )

    if not webhook_result.get("processed"):
        return {"status": "ignored", "event_type": event_type}

    action = webhook_result.get("action")
    customer_id = webhook_result.get("customer_id")

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

            send_invoice_email_task.delay(
                org_id=str(org.id),
                invoice_pdf_url=invoice_pdf,
                amount_paid=webhook_result.get("amount_paid", 0),
            )

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

        send_dunning_email_task.delay(
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

    await db.commit()
    return {"status": "processed", "action": action, "org_id": str(org.id)}
