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
    from sqlalchemy import select
    from app.core.audit import write_audit_log
    from app.integrations.stripe_billing import create_subscription_from_trial
    from app.modules.admin.models import SubscriptionPlan

    plan_result = await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"Plan {org.plan_id} not found for org {org.id}")
    if not org.stripe_customer_id:
        raise ValueError(f"No Stripe customer ID for org {org.id}")

    monthly_amount_cents = int(float(plan.monthly_price_nzd) * 100)
    sub_result = await create_subscription_from_trial(customer_id=org.stripe_customer_id, monthly_amount_cents=monthly_amount_cents, metadata={"org_id": str(org.id), "plan_id": str(plan.id), "plan_name": plan.name})

    org.status = "active"
    org.stripe_subscription_id = sub_result["subscription_id"]
    await session.flush()
    await write_audit_log(session=session, org_id=org.id, user_id=None, action="subscription.trial_converted", entity_type="organisation", entity_id=org.id, before_value={"status": "trial"}, after_value={"status": "active", "stripe_subscription_id": sub_result["subscription_id"], "subscription_status": sub_result["status"]})


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
