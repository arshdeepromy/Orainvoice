"""Subscription lifecycle tasks — trial expiry, billing, grace period, suspension.

All functions are plain async — called directly from the app layer.

Requirements: 41.4, 41.5, 42.3, 42.4, 42.5, 42.6, 16.3, 4.1–4.5
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants for recurring billing retry / grace period
# ---------------------------------------------------------------------------
MAX_BILLING_RETRIES = 3
GRACE_PERIOD_DAYS = 7


# ---------------------------------------------------------------------------
# Recurring billing (Req 5.1–5.6)
# ---------------------------------------------------------------------------

async def process_recurring_billing_task() -> dict:
    """Find orgs due for billing and charge them.

    Query: status='active', next_billing_date IS NOT NULL,
           next_billing_date <= utcnow()

    For each org:
    1. Load plan + interval config → compute_effective_price
    2. Apply active coupon discount (if any)
    3. Get default OrgPaymentMethod
    4. Call charge_org_payment_method
    5. On success: advance next_billing_date by interval duration, reset retry count
    6. On failure: increment retry, transition to grace_period after MAX_BILLING_RETRIES

    Returns summary dict with charged, failed, skipped counts.
    """
    from decimal import Decimal

    from sqlalchemy import select

    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.integrations.stripe_billing import (
        PaymentActionRequiredError,
        PaymentFailedError,
        charge_org_payment_method,
    )
    from app.modules.admin.models import (
        Coupon,
        Organisation,
        OrganisationCoupon,
        SubscriptionPlan,
    )
    from app.modules.billing.interval_pricing import (
        apply_coupon_to_interval_price,
        compute_effective_price,
        compute_interval_duration,
    )
    from app.modules.billing.models import OrgPaymentMethod

    now = datetime.now(timezone.utc)
    charged = 0
    failed = 0
    skipped = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            # Query orgs due for billing (Req 5.1)
            stmt = (
                select(Organisation)
                .where(
                    Organisation.status == "active",
                    Organisation.next_billing_date.isnot(None),
                    Organisation.next_billing_date <= now,
                )
            )
            result = await session.execute(stmt)
            due_orgs = result.scalars().all()

            for org in due_orgs:
                try:
                    # 1. Load plan + interval config
                    plan_result = await session.execute(
                        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
                    )
                    plan = plan_result.scalar_one_or_none()
                    if not plan:
                        logger.warning("Plan %s not found for org %s, skipping", org.plan_id, org.id)
                        skipped += 1
                        continue

                    billing_interval = getattr(org, "billing_interval", "monthly") or "monthly"

                    # Find interval discount from plan config
                    discount_percent = Decimal("0")
                    interval_config = getattr(plan, "interval_config", None) or []
                    for item in interval_config:
                        if item.get("interval") == billing_interval and item.get("enabled", False):
                            discount_percent = Decimal(str(item.get("discount_percent", 0)))
                            break

                    # Compute effective price (Req 5.2)
                    base_price = Decimal(str(plan.monthly_price_nzd))
                    effective_price = compute_effective_price(base_price, billing_interval, discount_percent)

                    # 2. Apply active coupon discount (if any)
                    coupon_result = await session.execute(
                        select(OrganisationCoupon, Coupon)
                        .join(Coupon, OrganisationCoupon.coupon_id == Coupon.id)
                        .where(
                            OrganisationCoupon.org_id == org.id,
                            OrganisationCoupon.is_expired.is_(False),
                        )
                        .order_by(OrganisationCoupon.applied_at.desc())
                        .limit(1)
                    )
                    coupon_row = coupon_result.one_or_none()

                    if coupon_row:
                        org_coupon, coupon = coupon_row
                        effective_price = apply_coupon_to_interval_price(
                            effective_price,
                            coupon.discount_type,
                            Decimal(str(coupon.discount_value)),
                        )

                    amount_cents = int((effective_price * Decimal("100")).to_integral_value())

                    # 2b. Compute SMS overage charges (excl. GST)
                    sms_overage_cents = 0
                    sms_overage_count = 0
                    try:
                        from app.modules.admin.service import compute_sms_overage_for_billing
                        sms_data = await compute_sms_overage_for_billing(session, org.id)
                        sms_overage_count = sms_data.get("overage_count", 0)
                        if sms_overage_count > 0:
                            sms_overage_cents = round(sms_data["total_charge_nzd"] * 100)
                    except Exception as exc:
                        logger.warning("Failed to compute SMS overage for org %s: %s", org.id, exc)

                    # 2c. Compute Carjam overage charges (excl. GST)
                    carjam_overage_cents = 0
                    carjam_overage_count = 0
                    try:
                        from app.modules.admin.service import (
                            compute_carjam_overage,
                            get_carjam_per_lookup_cost,
                        )
                        carjam_overage_count = compute_carjam_overage(
                            org.carjam_lookups_this_month,
                            plan.carjam_lookups_included,
                        )
                        if carjam_overage_count > 0:
                            per_lookup_cost = await get_carjam_per_lookup_cost(session)
                            carjam_overage_cents = round(carjam_overage_count * per_lookup_cost * 100)
                    except Exception as exc:
                        logger.warning("Failed to compute Carjam overage for org %s: %s", org.id, exc)

                    # 2d. Compute storage add-on charge (excl. GST)
                    # This is ONLY for extra storage purchased by the user,
                    # NOT the storage included in the plan.
                    storage_addon_cents = 0
                    storage_addon_gb = 0
                    try:
                        from app.modules.admin.models import OrgStorageAddon
                        addon_result = await session.execute(
                            select(OrgStorageAddon).where(
                                OrgStorageAddon.org_id == org.id
                            )
                        )
                        addon = addon_result.scalar_one_or_none()
                        if addon and float(addon.price_nzd_per_month) > 0:
                            storage_addon_gb = addon.quantity_gb
                            storage_addon_cents = round(float(addon.price_nzd_per_month) * 100)
                    except Exception as exc:
                        logger.warning("Failed to compute storage addon for org %s: %s", org.id, exc)

                    # 2e. Total excl. GST = plan + SMS overage + Carjam overage + storage addon
                    total_excl_gst_cents = amount_cents + sms_overage_cents + carjam_overage_cents + storage_addon_cents

                    # Skip free plans with no overages
                    if total_excl_gst_cents <= 0:
                        # Advance billing date even for free plans
                        org.next_billing_date = org.next_billing_date + compute_interval_duration(billing_interval)
                        # Reset usage counters
                        if sms_overage_count > 0:
                            org.sms_sent_this_month = 0
                        if carjam_overage_count > 0:
                            org.carjam_lookups_this_month = 0
                        skipped += 1
                        continue

                    # 2e. Apply GST and Stripe processing fee on the combined total
                    from app.modules.organisations.service import (
                        _compute_billing_breakdown,
                        _load_signup_billing_config,
                    )
                    billing_config = await _load_signup_billing_config()
                    breakdown = _compute_billing_breakdown(total_excl_gst_cents, billing_config)
                    charge_amount_cents = breakdown["total_amount_cents"]

                    # 3. Get default OrgPaymentMethod (Req 5.3)
                    pm_result = await session.execute(
                        select(OrgPaymentMethod).where(
                            OrgPaymentMethod.org_id == org.id,
                            OrgPaymentMethod.is_default.is_(True),
                        )
                    )
                    default_pm = pm_result.scalar_one_or_none()

                    if not default_pm:
                        logger.warning(
                            "No default payment method for org %s, skipping billing",
                            org.id,
                        )
                        skipped += 1
                        continue

                    if not org.stripe_customer_id:
                        logger.warning(
                            "No Stripe customer ID for org %s, skipping billing",
                            org.id,
                        )
                        skipped += 1
                        continue

                    # 4. Charge (Req 5.3)
                    # Idempotency key prevents double-charges if the
                    # container restarts after Stripe succeeds but before
                    # next_billing_date is advanced in the DB.
                    idem_key = f"billing-{org.id}-{org.next_billing_date.isoformat()}"
                    charge_result = await charge_org_payment_method(
                        customer_id=org.stripe_customer_id,
                        payment_method_id=default_pm.stripe_payment_method_id,
                        amount_cents=charge_amount_cents,
                        currency="nzd",
                        metadata={
                            "org_id": str(org.id),
                            "plan_id": str(plan.id),
                            "plan_name": plan.name,
                            "billing_interval": billing_interval,
                            "plan_amount_cents": str(amount_cents),
                            "sms_overage_cents": str(sms_overage_cents),
                            "sms_overage_count": str(sms_overage_count),
                            "carjam_overage_cents": str(carjam_overage_cents),
                            "carjam_overage_count": str(carjam_overage_count),
                            "storage_addon_cents": str(storage_addon_cents),
                            "storage_addon_gb": str(storage_addon_gb),
                            "subtotal_excl_gst_cents": str(total_excl_gst_cents),
                            "gst_amount_cents": str(breakdown["gst_amount_cents"]),
                            "processing_fee_cents": str(breakdown["processing_fee_cents"]),
                        },
                        idempotency_key=idem_key,
                    )

                    # 5. On success: advance next_billing_date, reset retry count (Req 5.4)
                    org.next_billing_date = org.next_billing_date + compute_interval_duration(billing_interval)
                    org_settings = dict(org.settings) if org.settings else {}
                    org_settings["billing_retry_count"] = 0
                    org.settings = org_settings

                    # Reset usage counters after successful billing
                    if sms_overage_count > 0:
                        org.sms_sent_this_month = 0
                    if carjam_overage_count > 0:
                        org.carjam_lookups_this_month = 0

                    await session.flush()

                    # 5b. Create billing receipt record
                    from app.modules.billing.models import BillingReceipt
                    receipt = BillingReceipt(
                        org_id=org.id,
                        stripe_payment_intent_id=charge_result["payment_intent_id"],
                        billing_date=now,
                        billing_interval=billing_interval,
                        plan_amount_cents=amount_cents,
                        sms_overage_cents=sms_overage_cents,
                        carjam_overage_cents=carjam_overage_cents,
                        storage_addon_cents=storage_addon_cents,
                        subtotal_excl_gst_cents=total_excl_gst_cents,
                        gst_amount_cents=breakdown["gst_amount_cents"],
                        processing_fee_cents=breakdown["processing_fee_cents"],
                        total_amount_cents=charge_amount_cents,
                        plan_name=plan.name,
                        sms_overage_count=sms_overage_count,
                        carjam_overage_count=carjam_overage_count,
                        storage_addon_gb=storage_addon_gb,
                        currency="nzd",
                        status="paid",
                    )
                    session.add(receipt)
                    await session.flush()

                    # 5c. Send receipt email to org admin (async, non-blocking)
                    try:
                        await _send_billing_receipt_email(
                            session, org, receipt, breakdown,
                        )
                    except Exception as email_exc:
                        logger.warning(
                            "Failed to send billing receipt email for org %s: %s",
                            org.id, email_exc,
                        )

                    charged += 1
                    logger.info(
                        "Charged org %s: %d cents total "
                        "(plan=%d + sms_overage=%d + carjam_overage=%d + storage_addon=%d = %d excl GST, "
                        "+%d GST +%d fee, %s), next billing %s",
                        org.id,
                        charge_amount_cents,
                        amount_cents,
                        sms_overage_cents,
                        carjam_overage_cents,
                        storage_addon_cents,
                        total_excl_gst_cents,
                        breakdown["gst_amount_cents"],
                        breakdown["processing_fee_cents"],
                        billing_interval,
                        org.next_billing_date,
                    )

                except (PaymentFailedError, PaymentActionRequiredError) as exc:
                    # 6. On failure: increment retry, transition after MAX_BILLING_RETRIES (Req 5.5)
                    org_settings = dict(org.settings) if org.settings else {}
                    retry_count = org_settings.get("billing_retry_count", 0) + 1
                    org_settings["billing_retry_count"] = retry_count
                    org.settings = org_settings

                    logger.warning(
                        "Payment failed for org %s (attempt %d/%d): %s",
                        org.id,
                        retry_count,
                        MAX_BILLING_RETRIES,
                        exc,
                    )

                    if retry_count >= MAX_BILLING_RETRIES:
                        org.status = "grace_period"
                        org_settings["grace_period_started_at"] = now.isoformat()
                        org.settings = org_settings
                        await session.flush()

                        await write_audit_log(
                            session=session,
                            org_id=org.id,
                            user_id=None,
                            action="subscription.grace_period_entered",
                            entity_type="organisation",
                            entity_id=org.id,
                            before_value={"status": "active"},
                            after_value={
                                "status": "grace_period",
                                "billing_retry_count": retry_count,
                            },
                        )

                    await session.flush()
                    failed += 1
                    errors.append(f"org {org.id}: {exc}")

                except Exception as exc:
                    # Catch-all: log and continue to next org (Req 5.6)
                    logger.error(
                        "Unexpected error billing org %s: %s",
                        org.id,
                        exc,
                        exc_info=True,
                    )
                    failed += 1
                    errors.append(f"org {org.id}: {exc}")

    logger.info(
        "Recurring billing complete: %d charged, %d failed, %d skipped",
        charged,
        failed,
        skipped,
    )
    return {"charged": charged, "failed": failed, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Billing receipt email helper
# ---------------------------------------------------------------------------

async def _send_billing_receipt_email(session, org, receipt, breakdown) -> None:
    """Send a payment receipt email to the org admin.

    Uses the existing log_email_sent + send_email_task pattern.
    Non-blocking: the email is dispatched via the async task system.
    """
    from sqlalchemy import select
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    admin_result = await session.execute(
        select(User).where(
            User.org_id == org.id,
            User.role == "org_admin",
            User.is_active.is_(True),
        )
    )
    admin_user = admin_result.scalars().first()
    if not admin_user:
        return

    total_nzd = receipt.total_amount_cents / 100
    subtotal_nzd = receipt.subtotal_excl_gst_cents / 100
    gst_nzd = receipt.gst_amount_cents / 100
    processing_nzd = receipt.processing_fee_cents / 100
    plan_nzd = receipt.plan_amount_cents / 100

    # Build breakdown rows
    rows = [f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>Plan ({receipt.plan_name})</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>${plan_nzd:.2f}</td></tr>"]
    if receipt.sms_overage_cents > 0:
        sms_nzd = receipt.sms_overage_cents / 100
        rows.append(f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>SMS overage ({receipt.sms_overage_count} messages)</td>"
                     f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>${sms_nzd:.2f}</td></tr>")
    if receipt.carjam_overage_cents > 0:
        cj_nzd = receipt.carjam_overage_cents / 100
        rows.append(f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>Carjam overage ({receipt.carjam_overage_count} lookups)</td>"
                     f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>${cj_nzd:.2f}</td></tr>")
    if receipt.storage_addon_cents > 0:
        stor_nzd = receipt.storage_addon_cents / 100
        rows.append(f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>Storage add-on ({receipt.storage_addon_gb} GB)</td>"
                     f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>${stor_nzd:.2f}</td></tr>")

    breakdown_html = "\n".join(rows)

    subject = f"Your OraInvoice subscription payment receipt — ${total_nzd:.2f} NZD"
    html_body = f"""<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
<h2 style="color:#1a1a1a">Payment Receipt</h2>
<p>Hi,</p>
<p>Your subscription payment for <strong>{org.name}</strong> has been processed successfully.</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0">
<thead>
<tr style="background:#f9fafb">
<th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e5e7eb">Description</th>
<th style="padding:8px 12px;text-align:right;border-bottom:2px solid #e5e7eb">Amount (NZD)</th>
</tr>
</thead>
<tbody>
{breakdown_html}
</tbody>
<tfoot>
<tr><td style="padding:6px 12px;border-top:1px solid #ddd">Subtotal (excl. GST)</td>
<td style="padding:6px 12px;text-align:right;border-top:1px solid #ddd">${subtotal_nzd:.2f}</td></tr>
<tr><td style="padding:6px 12px">GST (15%)</td>
<td style="padding:6px 12px;text-align:right">${gst_nzd:.2f}</td></tr>
<tr><td style="padding:6px 12px">Processing fee</td>
<td style="padding:6px 12px;text-align:right">${processing_nzd:.2f}</td></tr>
<tr style="font-weight:bold;background:#f9fafb">
<td style="padding:8px 12px;border-top:2px solid #e5e7eb">Total</td>
<td style="padding:8px 12px;text-align:right;border-top:2px solid #e5e7eb">${total_nzd:.2f}</td></tr>
</tfoot>
</table>
<p style="color:#6b7280;font-size:14px">Billing interval: {receipt.billing_interval.capitalize()}</p>
<p style="color:#6b7280;font-size:14px">You can view all your receipts in the Billing section of your OraInvoice dashboard.</p>
</div>"""

    log_entry = await log_email_sent(
        session,
        org_id=org.id,
        recipient=admin_user.email,
        template_type="billing_receipt",
        subject=subject,
        status="queued",
    )
    await send_email_task(
        org_id=str(org.id),
        log_id=str(log_entry["id"]),
        to_email=admin_user.email,
        subject=subject,
        html_body=html_body,
        template_type="billing_receipt",
    )


# ---------------------------------------------------------------------------
# Trial expiry (Req 41.4, 41.5)
# ---------------------------------------------------------------------------

async def check_trial_expiry_task() -> dict:
    from sqlalchemy import func, select
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.notifications.models import NotificationLog

    now = datetime.now(timezone.utc)
    reminders_sent = 0
    trials_converted = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.status == "trial"))
            trial_orgs = result.scalars().all()

            for org in trial_orgs:
                if not org.trial_ends_at:
                    continue
                delta = org.trial_ends_at - now
                days_remaining = delta.total_seconds() / 86400

                if days_remaining <= 0:
                    try:
                        await _convert_trial_to_active(session, org, now)
                        trials_converted += 1
                    except Exception as exc:
                        errors.append(f"Failed to convert trial for org {org.id}: {exc}")
                    continue

                if days_remaining <= 3:
                    dedup_subject = f"trial_reminder_{org.id}"
                    dedup_stmt = select(func.count(NotificationLog.id)).where(
                        NotificationLog.org_id == org.id,
                        NotificationLog.template_type == "trial_expiry_reminder",
                        NotificationLog.subject == dedup_subject,
                    )
                    dedup_count = (await session.execute(dedup_stmt)).scalar() or 0
                    if dedup_count == 0:
                        try:
                            await _send_trial_reminder(session, org, math.ceil(days_remaining))
                            reminders_sent += 1
                        except Exception as exc:
                            errors.append(f"Failed to send trial reminder for org {org.id}: {exc}")

    logger.info("Trial expiry check: %d reminders, %d converted, %d errors", reminders_sent, trials_converted, len(errors))
    return {"reminders_sent": reminders_sent, "trials_converted": trials_converted, "errors": errors, "total_trial_orgs": len(trial_orgs) if "trial_orgs" in dir() else 0}


async def _send_trial_reminder(session, org, days_remaining: int) -> None:
    from sqlalchemy import select
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task
    from app.modules.auth.models import User

    admin_result = await session.execute(select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active.is_(True)))
    admin_user = admin_result.scalars().first()
    if not admin_user:
        return

    subject = f"Your WorkshopPro NZ trial ends in {days_remaining} day{'s' if days_remaining != 1 else ''}"
    html_body = f"<p>Hi {admin_user.email},</p><p>Your free trial for <strong>{org.name}</strong> ends in <strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong>.</p><p>After your trial ends, your saved payment method will be charged automatically.</p>"

    log_entry = await log_email_sent(session, org_id=org.id, recipient=admin_user.email, template_type="trial_expiry_reminder", subject=f"trial_reminder_{org.id}", status="queued")
    await send_email_task(org_id=str(org.id), log_id=str(log_entry["id"]), to_email=admin_user.email, subject=subject, html_body=html_body, template_type="trial_expiry_reminder")


async def _convert_trial_to_active(session, org, now: datetime) -> None:
    from decimal import Decimal
    from sqlalchemy import select
    from app.core.audit import write_audit_log
    from app.integrations.stripe_billing import (
        PaymentFailedError,
        PaymentActionRequiredError,
        charge_org_payment_method,
    )
    from app.modules.admin.models import (
        Coupon,
        OrganisationCoupon,
        SubscriptionPlan,
    )
    from app.modules.billing.interval_pricing import (
        apply_coupon_to_interval_price,
        compute_effective_price,
        compute_interval_duration,
    )
    from app.modules.billing.models import OrgPaymentMethod

    plan_result = await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"Plan {org.plan_id} not found for org {org.id}")
    if not org.stripe_customer_id:
        raise ValueError(f"No Stripe customer ID for org {org.id}")

    # Read org billing interval (default to monthly for legacy orgs)
    billing_interval = getattr(org, "billing_interval", "monthly") or "monthly"

    # Look up discount for the org's interval from plan's interval_config
    discount_percent = Decimal("0")
    interval_config = getattr(plan, "interval_config", None) or []
    for item in interval_config:
        if item.get("interval") == billing_interval and item.get("enabled", False):
            discount_percent = Decimal(str(item.get("discount_percent", 0)))
            break

    # Compute effective price for the selected interval
    base_price = Decimal(str(plan.monthly_price_nzd))
    effective_price = compute_effective_price(base_price, billing_interval, discount_percent)

    # Apply active coupon discount (if any)
    coupon_result = await session.execute(
        select(OrganisationCoupon, Coupon)
        .join(Coupon, OrganisationCoupon.coupon_id == Coupon.id)
        .where(
            OrganisationCoupon.org_id == org.id,
            OrganisationCoupon.is_expired.is_(False),
        )
        .order_by(OrganisationCoupon.applied_at.desc())
        .limit(1)
    )
    coupon_row = coupon_result.one_or_none()

    if coupon_row:
        org_coupon, coupon = coupon_row
        effective_price = apply_coupon_to_interval_price(
            effective_price,
            coupon.discount_type,
            Decimal(str(coupon.discount_value)),
        )

    amount_cents = int((effective_price * Decimal("100")).to_integral_value())

    # Get default payment method
    pm_result = await session.execute(
        select(OrgPaymentMethod).where(
            OrgPaymentMethod.org_id == org.id,
            OrgPaymentMethod.is_default.is_(True),
        )
    )
    default_pm = pm_result.scalar_one_or_none()

    if not default_pm:
        raise ValueError(f"No default payment method for org {org.id}")

    # Apply GST and Stripe processing fee (same formula as signup)
    charge_amount_cents = amount_cents
    breakdown = None
    if amount_cents > 0:
        from app.modules.organisations.service import (
            _compute_billing_breakdown,
            _load_signup_billing_config,
        )
        billing_config = await _load_signup_billing_config()
        breakdown = _compute_billing_breakdown(amount_cents, billing_config)
        charge_amount_cents = breakdown["total_amount_cents"]

    try:
        # Charge the saved payment method (Req 4.1)
        if charge_amount_cents > 0:
            await charge_org_payment_method(
                customer_id=org.stripe_customer_id,
                payment_method_id=default_pm.stripe_payment_method_id,
                amount_cents=charge_amount_cents,
                currency="nzd",
                metadata={
                    "org_id": str(org.id),
                    "plan_id": str(plan.id),
                    "plan_name": plan.name,
                    "billing_interval": billing_interval,
                    "type": "trial_conversion",
                    "plan_amount_cents": str(amount_cents),
                    "gst_amount_cents": str(breakdown["gst_amount_cents"]) if breakdown else "0",
                    "processing_fee_cents": str(breakdown["processing_fee_cents"]) if breakdown else "0",
                },
            )

        # On success: set status to active and set next_billing_date (Req 4.2)
        org.status = "active"
        org.next_billing_date = now + compute_interval_duration(billing_interval)
        await session.flush()

        await write_audit_log(
            session=session,
            org_id=org.id,
            user_id=None,
            action="subscription.trial_converted",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": "trial"},
            after_value={
                "status": "active",
                "next_billing_date": org.next_billing_date.isoformat(),
                "billing_interval": billing_interval,
                "amount_cents": amount_cents,
            },
        )

    except (PaymentFailedError, PaymentActionRequiredError) as exc:
        # On failure: set status to grace_period and log (Req 4.4)
        org.status = "grace_period"
        org_settings = dict(org.settings) if org.settings else {}
        org_settings["grace_period_started_at"] = now.isoformat()
        org_settings["billing_retry_count"] = 1
        org.settings = org_settings
        await session.flush()

        logger.warning(
            "Trial conversion payment failed for org %s: %s",
            org.id,
            exc,
        )

        await write_audit_log(
            session=session,
            org_id=org.id,
            user_id=None,
            action="subscription.trial_conversion_failed",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": "trial"},
            after_value={
                "status": "grace_period",
                "error": str(exc),
            },
        )



# ---------------------------------------------------------------------------
# Invoice email (Req 42.3)
# ---------------------------------------------------------------------------

async def send_invoice_email_task(org_id: str, invoice_pdf_url: str, amount_paid: int = 0) -> dict:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.id == org_id))
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}
            admin_result = await session.execute(select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active.is_(True)))
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            amount_nzd = amount_paid / 100
            subject = f"Your WorkshopPro NZ invoice — ${amount_nzd:.2f} NZD"
            html_body = f"<p>Hi,</p><p>Your monthly subscription payment of <strong>${amount_nzd:.2f} NZD</strong> for <strong>{org.name}</strong> has been processed.</p><p><a href=\"{invoice_pdf_url}\">Download your invoice PDF</a></p>"

            log_entry = await log_email_sent(session, org_id=org.id, recipient=admin_user.email, template_type="subscription_invoice", subject=subject, status="queued")
            await send_email_task(org_id=str(org.id), log_id=str(log_entry["id"]), to_email=admin_user.email, subject=subject, html_body=html_body, template_type="subscription_invoice")
    return {"sent": True, "recipient": admin_user.email}


# ---------------------------------------------------------------------------
# Dunning email (Req 42.4)
# ---------------------------------------------------------------------------

async def send_dunning_email_task(org_id: str, attempt_count: int = 1) -> dict:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.id == org_id))
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}
            admin_result = await session.execute(select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active.is_(True)))
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            retry_schedule = {1: "We will retry in 3 days.", 2: "We will retry in 7 days.", 3: "This was our final retry attempt. Your account will enter a grace period."}
            retry_msg = retry_schedule.get(attempt_count, "Please update your payment method.")
            subject = f"Payment failed for {org.name} — action required"
            html_body = f"<p>Hi,</p><p>We were unable to process your subscription payment for <strong>{org.name}</strong>.</p><p>{retry_msg}</p>"

            log_entry = await log_email_sent(session, org_id=org.id, recipient=admin_user.email, template_type="dunning_payment_failed", subject=subject, status="queued")
            await send_email_task(org_id=str(org.id), log_id=str(log_entry["id"]), to_email=admin_user.email, subject=subject, html_body=html_body, template_type="dunning_payment_failed")
    return {"sent": True, "attempt_count": attempt_count}


# ---------------------------------------------------------------------------
# Grace period check (Req 42.5, 42.6)
# ---------------------------------------------------------------------------

async def check_grace_period_task() -> dict:
    from sqlalchemy import select
    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation

    now = datetime.now(timezone.utc)
    transitioned = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.status == "grace_period"))
            grace_orgs = result.scalars().all()
            for org in grace_orgs:
                try:
                    org_settings = dict(org.settings) if org.settings else {}
                    grace_started = org_settings.get("grace_period_started_at")
                    if not grace_started:
                        continue
                    grace_start_dt = datetime.fromisoformat(grace_started)
                    if (now - grace_start_dt).total_seconds() / 86400 >= 7:
                        org.status = "suspended"
                        org_settings["suspended_at"] = now.isoformat()
                        org.settings = org_settings
                        await session.flush()
                        await write_audit_log(session=session, org_id=org.id, action="subscription.suspended", entity_type="organisation", entity_id=org.id, before_value={"status": "grace_period"}, after_value={"status": "suspended"})
                        transitioned += 1
                        await send_suspension_email_task(org_id=str(org.id), email_type="suspended")
                except Exception as exc:
                    errors.append(f"Error processing org {org.id}: {exc}")

    return {"transitioned": transitioned, "errors": errors}


# ---------------------------------------------------------------------------
# Suspension retention check (Req 42.6)
# ---------------------------------------------------------------------------

async def check_suspension_retention_task() -> dict:
    from sqlalchemy import select
    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation

    now = datetime.now(timezone.utc)
    warnings_sent = 0
    deleted = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.status == "suspended"))
            suspended_orgs = result.scalars().all()
            for org in suspended_orgs:
                try:
                    org_settings = dict(org.settings) if org.settings else {}
                    suspended_at = org_settings.get("suspended_at")
                    if not suspended_at:
                        continue
                    days_suspended = (now - datetime.fromisoformat(suspended_at)).total_seconds() / 86400
                    days_remaining = max(0, 90 - days_suspended)
                    warnings_already_sent = org_settings.get("retention_warnings_sent", [])

                    if days_remaining <= 30 and "30_day" not in warnings_already_sent:
                        await send_suspension_email_task(org_id=str(org.id), email_type="retention_30_day")
                        warnings_already_sent.append("30_day")
                        org_settings["retention_warnings_sent"] = warnings_already_sent
                        org.settings = org_settings
                        await session.flush()
                        warnings_sent += 1
                    elif days_remaining <= 7 and "7_day" not in warnings_already_sent:
                        await send_suspension_email_task(org_id=str(org.id), email_type="retention_7_day")
                        warnings_already_sent.append("7_day")
                        org_settings["retention_warnings_sent"] = warnings_already_sent
                        org.settings = org_settings
                        await session.flush()
                        warnings_sent += 1

                    if days_suspended >= 90:
                        org.status = "deleted"
                        org_settings["deleted_at"] = now.isoformat()
                        org.settings = org_settings
                        await session.flush()
                        await write_audit_log(session=session, org_id=org.id, action="subscription.data_deleted", entity_type="organisation", entity_id=org.id, before_value={"status": "suspended"}, after_value={"status": "deleted"})
                        deleted += 1
                except Exception as exc:
                    errors.append(f"Error processing org {org.id}: {exc}")

    return {"warnings_sent": warnings_sent, "deleted": deleted, "errors": errors}


# ---------------------------------------------------------------------------
# Suspension email (Req 42.5, 42.6)
# ---------------------------------------------------------------------------

async def send_suspension_email_task(org_id: str, email_type: str = "suspended") -> dict:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    subjects = {"suspended": "Your WorkshopPro NZ account has been suspended", "retention_30_day": "Your WorkshopPro NZ data will be deleted in 30 days", "retention_7_day": "URGENT: Your WorkshopPro NZ data will be deleted in 7 days"}
    bodies = {"suspended": "<p>Your account for <strong>{org_name}</strong> has been suspended due to non-payment.</p>", "retention_30_day": "<p>Your data will be permanently deleted in <strong>30 days</strong> unless payment is recovered.</p>", "retention_7_day": "<p>URGENT: Your data will be permanently deleted in <strong>7 days</strong>.</p>"}

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(select(Organisation).where(Organisation.id == org_id))
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}
            admin_result = await session.execute(select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active.is_(True)))
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            subject = subjects.get(email_type, "WorkshopPro NZ account notice")
            body_template = bodies.get(email_type, "<p>Please check your account.</p>")
            html_body = f"<p>Hi,</p>{body_template.format(org_name=org.name)}"

            log_entry = await log_email_sent(session, org_id=org.id, recipient=admin_user.email, template_type=f"suspension_{email_type}", subject=subject, status="queued")
            await send_email_task(org_id=str(org.id), log_id=str(log_entry["id"]), to_email=admin_user.email, subject=subject, html_body=html_body, template_type=f"suspension_{email_type}")
    return {"sent": True, "email_type": email_type}


# ---------------------------------------------------------------------------
# Carjam overage billing (Req 16.3)
# ---------------------------------------------------------------------------

async def report_carjam_overage_task() -> dict:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.integrations.stripe_billing import report_metered_usage
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.admin.service import compute_carjam_overage

    reported = 0
    skipped = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            stmt = select(Organisation, SubscriptionPlan).join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id).where(Organisation.status.in_(("active", "trial"))).where(Organisation.stripe_subscription_id.isnot(None))
            result = await session.execute(stmt)
            rows = result.all()
            for org, plan in rows:
                overage = compute_carjam_overage(org.carjam_lookups_this_month, plan.carjam_lookups_included)
                if overage <= 0:
                    skipped += 1
                    continue
                try:
                    usage_result = await report_metered_usage(subscription_id=org.stripe_subscription_id, quantity=overage, action="set")
                    if usage_result.get("reported"):
                        reported += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    errors.append(str(org.id))

    return {"reported": reported, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# SMS overage billing (Req 4.1–4.5)
# ---------------------------------------------------------------------------

async def report_sms_overage_task() -> dict:
    import math as _math
    from sqlalchemy import select
    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.integrations.stripe_billing import create_invoice_item
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.admin.service import compute_sms_overage_for_billing

    reported = 0
    skipped = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            stmt = select(Organisation, SubscriptionPlan).join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id).where(Organisation.status.in_(("active", "trial"))).where(Organisation.stripe_customer_id.isnot(None))
            result = await session.execute(stmt)
            rows = result.all()
            for org, plan in rows:
                overage_data = await compute_sms_overage_for_billing(session, org.id)
                overage_count = overage_data["overage_count"]
                per_sms_cost = overage_data["per_sms_cost_nzd"]
                total_charge = overage_data["total_charge_nzd"]
                if overage_count <= 0:
                    org.sms_sent_this_month = 0
                    skipped += 1
                    continue
                try:
                    unit_amount_cents = _math.ceil(per_sms_cost * 100)
                    description = f"SMS overage: {overage_count} messages × ${per_sms_cost:.4f}"
                    await create_invoice_item(customer_id=org.stripe_customer_id, description=description, quantity=overage_count, unit_amount_cents=unit_amount_cents, currency="nzd", metadata={"org_id": str(org.id), "type": "sms_overage"})
                    org.sms_sent_this_month = 0
                    await write_audit_log(session, action="sms_overage.billed", entity_type="organisation", org_id=org.id, entity_id=org.id, after_value={"overage_count": overage_count, "per_sms_cost_nzd": per_sms_cost, "total_charge_nzd": total_charge})
                    reported += 1
                except Exception as exc:
                    errors.append(str(org.id))

    return {"reported": reported, "skipped": skipped, "errors": errors}
