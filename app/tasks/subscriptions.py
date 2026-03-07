"""Celery tasks for subscription lifecycle — trial expiry and auto-charge.

Provides:
- ``check_trial_expiry_task``: Celery Beat task that runs every hour to:
  1. Send reminder email when 3 days remain in trial (Req 41.4)
  2. Auto-create Stripe subscription when trial ends (Req 41.5)

Requirements: 41.4, 41.5
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone

from app.tasks import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _check_trial_expiry_async() -> dict:
    """Core logic for trial expiry checking.

    Scans all organisations with status='trial' and:
    - Sends a reminder email if 3 days remain (and not already sent)
    - Transitions to 'active' and creates a Stripe subscription if trial ended

    Returns a summary dict with counts.
    """
    from sqlalchemy import func, select

    from app.core.database import async_session_factory
    from app.integrations.stripe_billing import create_subscription_from_trial
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.notifications.models import NotificationLog

    now = datetime.now(timezone.utc)
    reminders_sent = 0
    trials_converted = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            # Fetch all orgs currently on trial
            result = await session.execute(
                select(Organisation).where(Organisation.status == "trial")
            )
            trial_orgs = result.scalars().all()

            for org in trial_orgs:
                if not org.trial_ends_at:
                    continue

                delta = org.trial_ends_at - now
                days_remaining = delta.total_seconds() / 86400

                # --- Trial ended: auto-charge (Req 41.5) ---
                if days_remaining <= 0:
                    try:
                        await _convert_trial_to_active(
                            session, org, now
                        )
                        trials_converted += 1
                    except Exception as exc:
                        error_msg = f"Failed to convert trial for org {org.id}: {exc}"
                        logger.error(error_msg)
                        errors.append(error_msg)
                    continue

                # --- 3-day reminder (Req 41.4) ---
                if days_remaining <= 3:
                    # Dedup: check if we already sent a trial reminder for this org
                    dedup_subject = f"trial_reminder_{org.id}"
                    dedup_stmt = select(func.count(NotificationLog.id)).where(
                        NotificationLog.org_id == org.id,
                        NotificationLog.template_type == "trial_expiry_reminder",
                        NotificationLog.subject == dedup_subject,
                    )
                    dedup_count = (await session.execute(dedup_stmt)).scalar() or 0
                    if dedup_count == 0:
                        try:
                            await _send_trial_reminder(
                                session, org, math.ceil(days_remaining)
                            )
                            reminders_sent += 1
                        except Exception as exc:
                            error_msg = (
                                f"Failed to send trial reminder for org {org.id}: {exc}"
                            )
                            logger.error(error_msg)
                            errors.append(error_msg)

    return {
        "reminders_sent": reminders_sent,
        "trials_converted": trials_converted,
        "errors": errors,
        "total_trial_orgs": len(trial_orgs) if "trial_orgs" in dir() else 0,
    }


async def _send_trial_reminder(session, org, days_remaining: int) -> None:
    """Send a trial expiry reminder email to the Org_Admin.

    Requirements: 41.4
    """
    from sqlalchemy import select

    from app.modules.notifications.models import NotificationLog
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    # Find the org admin user
    from app.modules.auth.models import User

    admin_result = await session.execute(
        select(User).where(
            User.org_id == org.id,
            User.role == "org_admin",
            User.is_active.is_(True),
        )
    )
    admin_user = admin_result.scalars().first()
    if not admin_user:
        logger.warning("No active org_admin found for org %s", org.id)
        return

    subject = f"Your WorkshopPro NZ trial ends in {days_remaining} day{'s' if days_remaining != 1 else ''}"
    html_body = (
        f"<p>Hi {admin_user.email},</p>"
        f"<p>Your free trial for <strong>{org.name}</strong> ends in "
        f"<strong>{days_remaining} day{'s' if days_remaining != 1 else ''}</strong>.</p>"
        f"<p>After your trial ends, your saved payment method will be charged "
        f"automatically for your subscription plan.</p>"
        f"<p>If you have any questions, please contact our support team.</p>"
        f"<p>Thanks,<br>The WorkshopPro NZ Team</p>"
    )

    # Log the email
    log_entry = await log_email_sent(
        session,
        org_id=org.id,
        recipient=admin_user.email,
        template_type="trial_expiry_reminder",
        subject=f"trial_reminder_{org.id}",
        status="queued",
    )

    # Dispatch via Celery
    send_email_task.delay(
        org_id=str(org.id),
        log_id=str(log_entry["id"]),
        to_email=admin_user.email,
        subject=subject,
        html_body=html_body,
        template_type="trial_expiry_reminder",
    )


async def _convert_trial_to_active(session, org, now: datetime) -> None:
    """Transition an org from trial to active and create a Stripe subscription.

    Requirements: 41.5
    """
    from sqlalchemy import select

    from app.core.audit import write_audit_log
    from app.integrations.stripe_billing import create_subscription_from_trial
    from app.modules.admin.models import SubscriptionPlan

    # Load the plan to get the price
    plan_result = await session.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise ValueError(f"Plan {org.plan_id} not found for org {org.id}")

    if not org.stripe_customer_id:
        raise ValueError(f"No Stripe customer ID for org {org.id}")

    # Create Stripe subscription
    monthly_amount_cents = int(float(plan.monthly_price_nzd) * 100)
    sub_result = await create_subscription_from_trial(
        customer_id=org.stripe_customer_id,
        monthly_amount_cents=monthly_amount_cents,
        metadata={
            "org_id": str(org.id),
            "plan_id": str(plan.id),
            "plan_name": plan.name,
        },
    )

    # Update org status
    org.status = "active"
    org.stripe_subscription_id = sub_result["subscription_id"]
    await session.flush()

    # Audit log
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
            "stripe_subscription_id": sub_result["subscription_id"],
            "subscription_status": sub_result["status"],
        },
    )

    logger.info(
        "Converted org %s from trial to active (subscription=%s)",
        org.id,
        sub_result["subscription_id"],
    )


@celery_app.task(name="app.tasks.subscriptions.check_trial_expiry_task")
def check_trial_expiry_task():
    """Celery Beat task: check for expiring trials.

    Runs every hour. Sends 3-day reminder emails and auto-converts
    expired trials to active subscriptions.

    Requirements: 41.4, 41.5
    """
    result = _run_async(_check_trial_expiry_async())
    logger.info(
        "Trial expiry check complete: %d reminders sent, %d trials converted, %d errors",
        result["reminders_sent"],
        result["trials_converted"],
        len(result["errors"]),
    )
    return result


# ---------------------------------------------------------------------------
# Monthly billing lifecycle tasks — Requirements: 42.3, 42.4, 42.5, 42.6
# ---------------------------------------------------------------------------


async def _send_invoice_email_async(org_id: str, invoice_pdf_url: str, amount_paid: int) -> dict:
    """Send Stripe invoice PDF link to the Org_Admin.

    Requirements: 42.3
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}

            admin_result = await session.execute(
                select(User).where(
                    User.org_id == org.id,
                    User.role == "org_admin",
                    User.is_active.is_(True),
                )
            )
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            amount_nzd = amount_paid / 100
            subject = f"Your WorkshopPro NZ invoice — ${amount_nzd:.2f} NZD"
            html_body = (
                f"<p>Hi,</p>"
                f"<p>Your monthly subscription payment of <strong>${amount_nzd:.2f} NZD</strong> "
                f"for <strong>{org.name}</strong> has been processed successfully.</p>"
                f"<p><a href=\"{invoice_pdf_url}\">Download your invoice PDF</a></p>"
                f"<p>You can also view all past invoices from your Billing page.</p>"
                f"<p>Thanks,<br>The WorkshopPro NZ Team</p>"
            )

            log_entry = await log_email_sent(
                session,
                org_id=org.id,
                recipient=admin_user.email,
                template_type="subscription_invoice",
                subject=subject,
                status="queued",
            )

            send_email_task.delay(
                org_id=str(org.id),
                log_id=str(log_entry["id"]),
                to_email=admin_user.email,
                subject=subject,
                html_body=html_body,
                template_type="subscription_invoice",
            )

    return {"sent": True, "recipient": admin_user.email}


@celery_app.task(name="app.tasks.subscriptions.send_invoice_email_task")
def send_invoice_email_task(org_id: str, invoice_pdf_url: str, amount_paid: int = 0):
    """Send subscription invoice PDF email to Org_Admin.

    Requirements: 42.3
    """
    result = _run_async(_send_invoice_email_async(org_id, invoice_pdf_url, amount_paid))
    logger.info("Invoice email for org %s: %s", org_id, result)
    return result


async def _send_dunning_email_async(org_id: str, attempt_count: int) -> dict:
    """Send dunning email to Org_Admin on payment failure.

    Retry schedule: immediately (attempt 1), 3 days (attempt 2), 7 days (attempt 3).

    Requirements: 42.4
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}

            admin_result = await session.execute(
                select(User).where(
                    User.org_id == org.id,
                    User.role == "org_admin",
                    User.is_active.is_(True),
                )
            )
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            retry_schedule = {
                1: "We will retry in 3 days.",
                2: "We will retry in 7 days.",
                3: "This was our final retry attempt. Your account will enter a grace period.",
            }
            retry_msg = retry_schedule.get(
                attempt_count, "Please update your payment method."
            )

            subject = f"Payment failed for {org.name} — action required"
            html_body = (
                f"<p>Hi,</p>"
                f"<p>We were unable to process your subscription payment for "
                f"<strong>{org.name}</strong>.</p>"
                f"<p>{retry_msg}</p>"
                f"<p>Please update your payment method from the Billing page "
                f"to avoid any service interruption.</p>"
                f"<p>Thanks,<br>The WorkshopPro NZ Team</p>"
            )

            log_entry = await log_email_sent(
                session,
                org_id=org.id,
                recipient=admin_user.email,
                template_type="dunning_payment_failed",
                subject=subject,
                status="queued",
            )

            send_email_task.delay(
                org_id=str(org.id),
                log_id=str(log_entry["id"]),
                to_email=admin_user.email,
                subject=subject,
                html_body=html_body,
                template_type="dunning_payment_failed",
            )

    return {"sent": True, "attempt_count": attempt_count}


@celery_app.task(name="app.tasks.subscriptions.send_dunning_email_task")
def send_dunning_email_task(org_id: str, attempt_count: int = 1):
    """Send dunning email on payment failure.

    Requirements: 42.4
    """
    result = _run_async(_send_dunning_email_async(org_id, attempt_count))
    logger.info("Dunning email for org %s (attempt %d): %s", org_id, attempt_count, result)
    return result


async def _check_grace_period_async() -> dict:
    """Check orgs in grace_period and transition to suspended after 7 days.

    Requirements: 42.5, 42.6
    """
    from sqlalchemy import select

    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation

    now = datetime.now(timezone.utc)
    transitioned = 0
    errors = []

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Organisation).where(Organisation.status == "grace_period")
            )
            grace_orgs = result.scalars().all()

            for org in grace_orgs:
                try:
                    org_settings = dict(org.settings) if org.settings else {}
                    grace_started = org_settings.get("grace_period_started_at")
                    if not grace_started:
                        continue

                    grace_start_dt = datetime.fromisoformat(grace_started)
                    days_in_grace = (now - grace_start_dt).total_seconds() / 86400

                    if days_in_grace >= 7:
                        org.status = "suspended"
                        org_settings["suspended_at"] = now.isoformat()
                        org.settings = org_settings
                        await session.flush()

                        await write_audit_log(
                            session=session,
                            org_id=org.id,
                            action="subscription.suspended",
                            entity_type="organisation",
                            entity_id=org.id,
                            before_value={"status": "grace_period"},
                            after_value={"status": "suspended"},
                        )
                        transitioned += 1

                        # Send suspension notice email
                        send_suspension_email_task.delay(
                            org_id=str(org.id),
                            email_type="suspended",
                        )
                except Exception as exc:
                    errors.append(f"Error processing org {org.id}: {exc}")
                    logger.error("Grace period check error for org %s: %s", org.id, exc)

    return {"transitioned": transitioned, "errors": errors}


@celery_app.task(name="app.tasks.subscriptions.check_grace_period_task")
def check_grace_period_task():
    """Celery Beat task: check grace period orgs and suspend after 7 days.

    Requirements: 42.5, 42.6
    """
    result = _run_async(_check_grace_period_async())
    logger.info("Grace period check: %d transitioned, %d errors", result["transitioned"], len(result["errors"]))
    return result


async def _check_suspension_retention_async() -> dict:
    """Check suspended orgs for data retention warnings and deletion.

    - Warning email at 30 days remaining (60 days suspended)
    - Warning email at 7 days remaining (83 days suspended)
    - Delete after 90 days

    Requirements: 42.6
    """
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
            result = await session.execute(
                select(Organisation).where(Organisation.status == "suspended")
            )
            suspended_orgs = result.scalars().all()

            for org in suspended_orgs:
                try:
                    org_settings = dict(org.settings) if org.settings else {}
                    suspended_at = org_settings.get("suspended_at")
                    if not suspended_at:
                        continue

                    suspended_dt = datetime.fromisoformat(suspended_at)
                    days_suspended = (now - suspended_dt).total_seconds() / 86400
                    days_remaining = max(0, 90 - days_suspended)

                    warnings_already_sent = org_settings.get("retention_warnings_sent", [])

                    # 30 days remaining warning (60 days suspended)
                    if days_remaining <= 30 and "30_day" not in warnings_already_sent:
                        send_suspension_email_task.delay(
                            org_id=str(org.id),
                            email_type="retention_30_day",
                        )
                        warnings_already_sent.append("30_day")
                        org_settings["retention_warnings_sent"] = warnings_already_sent
                        org.settings = org_settings
                        await session.flush()
                        warnings_sent += 1

                    # 7 days remaining warning (83 days suspended)
                    elif days_remaining <= 7 and "7_day" not in warnings_already_sent:
                        send_suspension_email_task.delay(
                            org_id=str(org.id),
                            email_type="retention_7_day",
                        )
                        warnings_already_sent.append("7_day")
                        org_settings["retention_warnings_sent"] = warnings_already_sent
                        org.settings = org_settings
                        await session.flush()
                        warnings_sent += 1

                    # 90 days: mark as deleted
                    if days_suspended >= 90:
                        org.status = "deleted"
                        org_settings["deleted_at"] = now.isoformat()
                        org.settings = org_settings
                        await session.flush()

                        await write_audit_log(
                            session=session,
                            org_id=org.id,
                            action="subscription.data_deleted",
                            entity_type="organisation",
                            entity_id=org.id,
                            before_value={"status": "suspended"},
                            after_value={"status": "deleted"},
                        )
                        deleted += 1

                except Exception as exc:
                    errors.append(f"Error processing org {org.id}: {exc}")
                    logger.error("Suspension retention error for org %s: %s", org.id, exc)

    return {"warnings_sent": warnings_sent, "deleted": deleted, "errors": errors}


@celery_app.task(name="app.tasks.subscriptions.check_suspension_retention_task")
def check_suspension_retention_task():
    """Celery Beat task: check suspended orgs for retention warnings and deletion.

    Requirements: 42.6
    """
    result = _run_async(_check_suspension_retention_async())
    logger.info(
        "Suspension retention check: %d warnings, %d deleted, %d errors",
        result["warnings_sent"],
        result["deleted"],
        len(result["errors"]),
    )
    return result


async def _send_suspension_email_async(org_id: str, email_type: str) -> dict:
    """Send suspension-related emails to Org_Admin.

    email_type: 'suspended', 'retention_30_day', 'retention_7_day'

    Requirements: 42.5, 42.6
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    subjects = {
        "suspended": "Your WorkshopPro NZ account has been suspended",
        "retention_30_day": "Your WorkshopPro NZ data will be deleted in 30 days",
        "retention_7_day": "URGENT: Your WorkshopPro NZ data will be deleted in 7 days",
    }
    bodies = {
        "suspended": (
            "<p>Your account for <strong>{org_name}</strong> has been suspended "
            "due to non-payment.</p>"
            "<p>You can no longer access platform functionality, but your data "
            "will be retained for 90 days.</p>"
            "<p>To reactivate your account, please update your payment method "
            "from the Billing page.</p>"
        ),
        "retention_30_day": (
            "<p>Your account for <strong>{org_name}</strong> remains suspended.</p>"
            "<p>Your data will be permanently deleted in <strong>30 days</strong> "
            "unless payment is recovered.</p>"
            "<p>Please update your payment method to reactivate your account.</p>"
        ),
        "retention_7_day": (
            "<p>URGENT: Your account for <strong>{org_name}</strong> remains suspended.</p>"
            "<p>Your data will be permanently deleted in <strong>7 days</strong>.</p>"
            "<p>This is your final warning. Please update your payment method immediately.</p>"
        ),
    }

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = result.scalar_one_or_none()
            if not org:
                return {"sent": False, "reason": "org_not_found"}

            admin_result = await session.execute(
                select(User).where(
                    User.org_id == org.id,
                    User.role == "org_admin",
                    User.is_active.is_(True),
                )
            )
            admin_user = admin_result.scalars().first()
            if not admin_user:
                return {"sent": False, "reason": "no_admin"}

            subject = subjects.get(email_type, "WorkshopPro NZ account notice")
            body_template = bodies.get(email_type, "<p>Please check your account.</p>")
            html_body = (
                f"<p>Hi,</p>"
                f"{body_template.format(org_name=org.name)}"
                f"<p>Thanks,<br>The WorkshopPro NZ Team</p>"
            )

            log_entry = await log_email_sent(
                session,
                org_id=org.id,
                recipient=admin_user.email,
                template_type=f"suspension_{email_type}",
                subject=subject,
                status="queued",
            )

            send_email_task.delay(
                org_id=str(org.id),
                log_id=str(log_entry["id"]),
                to_email=admin_user.email,
                subject=subject,
                html_body=html_body,
                template_type=f"suspension_{email_type}",
            )

    return {"sent": True, "email_type": email_type}


@celery_app.task(name="app.tasks.subscriptions.send_suspension_email_task")
def send_suspension_email_task(org_id: str, email_type: str = "suspended"):
    """Send suspension/retention warning email.

    Requirements: 42.5, 42.6
    """
    result = _run_async(_send_suspension_email_async(org_id, email_type))
    logger.info("Suspension email for org %s (%s): %s", org_id, email_type, result)
    return result


# ---------------------------------------------------------------------------
# Carjam overage billing (Req 16.3)
# ---------------------------------------------------------------------------


async def _report_carjam_overage_async() -> dict:
    """Check all active orgs for Carjam overage and report to Stripe.

    For each org whose ``carjam_lookups_this_month`` exceeds the plan's
    ``carjam_lookups_included``, report the overage quantity to Stripe via
    metered billing so it appears on the next monthly invoice.

    Requirements: 16.3
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.integrations.stripe_billing import report_metered_usage
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.admin.service import compute_carjam_overage

    reported = 0
    skipped = 0
    errors: list[str] = []

    async with async_session_factory() as session:
        async with session.begin():
            stmt = (
                select(Organisation, SubscriptionPlan)
                .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
                .where(Organisation.status.in_(("active", "trial")))
                .where(Organisation.stripe_subscription_id.isnot(None))
            )
            result = await session.execute(stmt)
            rows = result.all()

            for org, plan in rows:
                overage = compute_carjam_overage(
                    org.carjam_lookups_this_month,
                    plan.carjam_lookups_included,
                )
                if overage <= 0:
                    skipped += 1
                    continue

                try:
                    usage_result = await report_metered_usage(
                        subscription_id=org.stripe_subscription_id,
                        quantity=overage,
                        action="set",
                    )
                    if usage_result.get("reported"):
                        reported += 1
                        logger.info(
                            "Reported %d Carjam overage for org %s",
                            overage,
                            org.id,
                        )
                    else:
                        skipped += 1
                        logger.warning(
                            "Could not report Carjam overage for org %s: %s",
                            org.id,
                            usage_result.get("reason"),
                        )
                except Exception as exc:
                    errors.append(str(org.id))
                    logger.error(
                        "Error reporting Carjam overage for org %s: %s",
                        org.id,
                        exc,
                    )

    return {"reported": reported, "skipped": skipped, "errors": errors}


@celery_app.task(name="app.tasks.subscriptions.report_carjam_overage_task")
def report_carjam_overage_task():
    """Celery Beat task: report Carjam overage to Stripe for all active orgs.

    Runs daily to ensure overage charges are reflected on the next invoice.

    Requirements: 16.3
    """
    result = _run_async(_report_carjam_overage_async())
    logger.info(
        "Carjam overage billing: %d reported, %d skipped, %d errors",
        result["reported"],
        result["skipped"],
        len(result["errors"]),
    )
    return result
