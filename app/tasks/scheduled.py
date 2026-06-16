"""Scheduled tasks — overdue checks, retry, archival, recurring invoices.

All functions are plain async — called directly from the app or a
lightweight scheduler. No Celery dependency.

Requirements: 19.6, 37.2, 38.2, 39.3, 49.7, 60.2, 60.4
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Surface this module's INFO logs in dev. Uvicorn's default logging config
# does not attach a handler to `app.tasks.scheduled`, so without this the
# scheduler-lock acquire/renew/yield messages would be silently dropped.
# In production this is harmless — the root logger is configured separately.
if os.environ.get("SCHEDULER_DEBUG_PROBE") == "1":
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s: %(message)s"))
        logger.addHandler(_h)
        logger.propagate = False

MAX_NOTIFICATION_RETRIES = 3
RETRY_DELAYS = (60, 300, 900)
ERROR_LOG_RETENTION_MONTHS = 12


def _get_retry_delay(retry_count: int) -> int:
    if retry_count < len(RETRY_DELAYS):
        return RETRY_DELAYS[retry_count]
    return RETRY_DELAYS[-1]


# ---------------------------------------------------------------------------
# 1. Check overdue invoices (Req 19.6)
# ---------------------------------------------------------------------------

async def check_overdue_invoices_task() -> dict:
    from app.core.database import async_session_factory
    from app.modules.invoices.service import mark_invoices_overdue
    try:
        async with async_session_factory() as session:
            async with session.begin():
                count = await mark_invoices_overdue(session, as_of_date=date.today())
        if count > 0:
            logger.info("Marked %d invoice(s) as overdue", count)
        return {"invoices_marked_overdue": count}
    except Exception as exc:
        logger.exception("Failed to check overdue invoices: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 2. Retry failed notifications (Req 37.2)
# ---------------------------------------------------------------------------

async def retry_failed_notifications_task() -> dict:
    from sqlalchemy import select
    from app.core.database import async_session_factory
    from app.core.errors import Severity, Category, log_error
    from app.modules.notifications.models import NotificationLog

    retried = 0
    permanently_failed = 0
    errors = 0

    try:
        async with async_session_factory() as session:
            async with session.begin():
                now = datetime.now(timezone.utc)
                result = await session.execute(
                    select(NotificationLog).where(
                        NotificationLog.status == "queued",
                        NotificationLog.retry_count > 0,
                    )
                )
                notifications = list(result.scalars().all())

                for notif in notifications:
                    delay_seconds = _get_retry_delay(notif.retry_count - 1)
                    eligible_after = notif.created_at + timedelta(seconds=delay_seconds * notif.retry_count)
                    if now < eligible_after:
                        continue

                    if notif.retry_count >= MAX_NOTIFICATION_RETRIES:
                        notif.status = "failed"
                        permanently_failed += 1
                        await log_error(
                            session,
                            severity=Severity.ERROR,
                            category=Category.INTEGRATION,
                            module="tasks.scheduled",
                            function_name="retry_failed_notifications_task",
                            message=f"{notif.channel.upper()} notification permanently failed after {MAX_NOTIFICATION_RETRIES} retries",
                            org_id=str(notif.org_id),
                            request_body={"log_id": str(notif.id), "recipient": notif.recipient, "template_type": notif.template_type, "channel": notif.channel, "error": notif.error_message or "Unknown"},
                        )
                        continue

                    try:
                        from app.tasks.notifications import send_email_task, send_sms_task
                        if notif.channel == "email":
                            await send_email_task(org_id=str(notif.org_id), log_id=str(notif.id), to_email=notif.recipient, subject=notif.subject or "", template_type=notif.template_type)
                        elif notif.channel == "sms":
                            await send_sms_task(org_id=str(notif.org_id), log_id=str(notif.id), to_number=notif.recipient, body="", template_type=notif.template_type)
                        notif.retry_count += 1
                        retried += 1
                    except Exception as exc:
                        logger.warning("Failed to re-dispatch notification %s: %s", notif.id, exc)
                        errors += 1

        if retried > 0 or permanently_failed > 0:
            logger.info("Notification retry: %d retried, %d permanently failed", retried, permanently_failed)
        return {"retried": retried, "permanently_failed": permanently_failed, "errors": errors}
    except Exception as exc:
        logger.exception("Failed to retry notifications: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 3. Archive error logs older than 12 months (Req 49.7)
# ---------------------------------------------------------------------------

async def archive_error_logs_task() -> dict:
    from sqlalchemy import text as sql_text
    from app.core.database import async_session_factory
    cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(sql_text("DELETE FROM error_log WHERE created_at < :cutoff"), {"cutoff": cutoff})
                archived_count = result.rowcount or 0
        if archived_count > 0:
            logger.info("Archived %d error log entries older than 12 months", archived_count)
        return {"archived_count": archived_count, "cutoff": cutoff.isoformat()}
    except Exception as exc:
        logger.exception("Failed to archive error logs: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 3a. Clean up expired bounce-blocklist rows (Req 12.6 — Phase 8c)
# ---------------------------------------------------------------------------

async def cleanup_expired_bounce_rows_task() -> dict:
    """Delete soft-bounce rows from ``bounced_addresses`` whose
    ``expires_at`` is in the past.

    Phase 8c (task 9.10) of the email-provider-unification spec. Hard
    bounces leave ``expires_at NULL`` and are never pruned by this
    task — admins clear them manually via the Delivery Health UI. The
    partial index ``ix_bounced_addresses_expires`` (created in
    migration 0197) keeps this query cheap.

    Scheduled hourly via the existing scheduled-tasks framework — the
    spec calls for daily but hourly cleanup keeps the table small with
    no downside, matches the existing 1h cadence used by
    ``cleanup_stale_sessions_task``, and means a soft bounce expires
    promptly rather than hanging around for up to a day past its
    seven-day window.
    """
    from sqlalchemy import text as sql_text
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    sql_text(
                        "DELETE FROM bounced_addresses "
                        "WHERE expires_at IS NOT NULL "
                        "  AND expires_at < now()"
                    )
                )
                deleted = result.rowcount or 0
        if deleted > 0:
            logger.info(
                "cleanup_expired_bounce_rows: removed %d expired soft "
                "bounces",
                deleted,
            )
        return {"deleted_rows": deleted}
    except Exception as exc:
        logger.exception(
            "cleanup_expired_bounce_rows_task failed: %s", exc
        )
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 4. Generate recurring invoices (Req 60.2, 60.4)
# ---------------------------------------------------------------------------

async def generate_recurring_invoices_task() -> dict:
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.recurring_invoices.models import RecurringSchedule
    from app.modules.recurring_invoices.service import RecurringService

    generated = 0
    errors = 0
    try:
        async with async_session_factory() as session:
            async with session.begin():
                svc = RecurringService(session)
                schedules = await svc.find_due_schedules()

        for schedule in schedules:
            try:
                async with async_session_factory() as session:
                    async with session.begin():
                        await _set_rls_org_id(session, str(schedule.org_id))
                        svc = RecurringService(session)
                        fresh = await svc.get_schedule(schedule.org_id, schedule.id)
                        if fresh is None or fresh.status != "active":
                            continue
                        await svc.generate_invoice(fresh)
                        RecurringService.advance_next_date(fresh)
                        generated += 1
            except Exception as exc:
                logger.warning("Failed to generate recurring invoice for schedule %s: %s", schedule.id, exc)
                errors += 1
                # Record in DLQ so failed schedules don't silently get
                # skipped on every cycle. PERFORMANCE_AUDIT.md §I-H3 / §1
                # quick win #10.
                try:
                    from app.core.dead_letter import DeadLetterService
                    await DeadLetterService().store_failed_task(
                        task_name="generate_recurring_invoice",
                        task_args={
                            "schedule_id": str(schedule.id),
                            "org_id": str(schedule.org_id),
                        },
                        error_message=str(exc),
                        org_id=schedule.org_id,
                    )
                except Exception:
                    logger.exception("Failed to write recurring-invoice failure to DLQ")

        if generated > 0 or errors > 0:
            logger.info("Recurring invoices: %d generated, %d errors", generated, errors)
        return {"generated": generated, "errors": errors}
    except Exception as exc:
        logger.exception("Failed to generate recurring invoices: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 5. Check quote expiry (Req 12.3)
# ---------------------------------------------------------------------------

async def check_quote_expiry_task() -> dict:
    from app.core.database import async_session_factory
    from app.modules.quotes_v2.service import QuoteService
    try:
        async with async_session_factory() as session:
            async with session.begin():
                count = await QuoteService.check_expiry(session)
        if count > 0:
            logger.info("Marked %d quote(s) as expired", count)
        return {"quotes_marked_expired": count}
    except Exception as exc:
        logger.exception("Failed to check quote expiry: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 6. Send staff schedule reminders (Req 18.5)
# ---------------------------------------------------------------------------

DEFAULT_REMINDER_MINUTES = 60

async def send_schedule_reminders_task() -> dict:
    from app.core.database import async_session_factory
    from app.modules.scheduling_v2.service import SchedulingService
    from app.tasks.notifications import send_email_task

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=DEFAULT_REMINDER_MINUTES)
    window_end = window_start + timedelta(minutes=5)
    sent = 0
    errors = 0

    try:
        async with async_session_factory() as session:
            async with session.begin():
                svc = SchedulingService(session)
                entries = await svc.get_entries_needing_reminders(window_start, window_end)
                for entry in entries:
                    try:
                        await send_email_task(
                            org_id=str(entry.org_id),
                            log_id=str(uuid.uuid4()),
                            to_email="",
                            subject=f"Reminder: {entry.title or 'Scheduled entry'} starting soon",
                            template_type="schedule_reminder",
                        )
                        sent += 1
                    except Exception as exc:
                        logger.warning("Failed to send reminder for entry %s: %s", entry.id, exc)
                        errors += 1
        if sent > 0:
            logger.info("Sent %d schedule reminder(s)", sent)
        return {"reminders_sent": sent, "errors": errors}
    except Exception as exc:
        logger.exception("Failed to send schedule reminders: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 7. Check compliance document expiry (Req 7.7)
# ---------------------------------------------------------------------------

async def check_compliance_expiry_task() -> dict:
    """Daily task: send expiry notifications for compliance documents.

    Checks three thresholds — 30-day, 7-day, and day-of — using the
    ComplianceNotificationService which handles deduplication, email
    dispatch, and per-document error isolation.

    Requirements: 7.1, 7.2, 7.3, 7.7
    """
    from app.core.database import async_session_factory
    from app.modules.compliance_docs.notification_service import (
        ComplianceNotificationService,
    )

    reminders_sent = 0
    errors = 0
    dashboard_url = "/compliance"

    try:
        for threshold_days in (30, 7, 0):
            async with async_session_factory() as session:
                async with session.begin():
                    svc = ComplianceNotificationService(session)
                    result = await svc.send_expiry_notifications(
                        threshold_days=threshold_days,
                        dashboard_url=dashboard_url,
                    )
            reminders_sent += result.get("sent", 0)
            errors += result.get("errors", 0)

        if reminders_sent > 0 or errors > 0:
            logger.info(
                "Compliance expiry check: %d notified, %d errors",
                reminders_sent,
                errors,
            )
        return {"reminders_sent": reminders_sent, "errors": errors}
    except Exception as exc:
        logger.exception("Failed to check compliance expiry: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 8. WooCommerce sync
# ---------------------------------------------------------------------------

WOOCOMMERCE_MAX_RETRIES = 3

async def sync_woocommerce_task(org_id: str) -> dict:
    from app.core.database import async_session_factory
    from app.modules.ecommerce.models import WooCommerceConnection, EcommerceSyncLog
    from sqlalchemy import select

    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(WooCommerceConnection).where(WooCommerceConnection.org_id == uuid.UUID(org_id), WooCommerceConnection.is_active.is_(True))
                result = await session.execute(stmt)
                conn = result.scalar_one_or_none()
                if conn is None:
                    return {"status": "skipped", "reason": "no active connection"}
                log = EcommerceSyncLog(org_id=uuid.UUID(org_id), direction="inbound", entity_type="order", status="completed")
                session.add(log)
                conn.last_sync_at = datetime.now(timezone.utc)
        return {"status": "completed", "org_id": org_id}
    except Exception as exc:
        logger.exception("WooCommerce sync failed for org %s: %s", org_id, exc)
        return {"status": "failed", "org_id": org_id, "error": str(exc)}


# ---------------------------------------------------------------------------
# 9. Publish scheduled platform notifications
# ---------------------------------------------------------------------------

async def publish_scheduled_notifications() -> dict:
    from app.core.database import async_session_factory
    from app.modules.admin.notifications_service import PlatformNotificationService
    try:
        async with async_session_factory() as session:
            async with session.begin():
                service = PlatformNotificationService(session)
                count = await service.publish_due_notifications()
        if count > 0:
            logger.info("Published %d scheduled notification(s)", count)
        return {"published": count}
    except Exception as exc:
        logger.exception("Failed to publish scheduled notifications: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 10. Exchange rate refresh
# ---------------------------------------------------------------------------

async def refresh_exchange_rates_task() -> dict:
    from app.core.database import async_session_factory
    from app.modules.multi_currency.models import OrgCurrency
    from app.modules.multi_currency.service import CurrencyService
    from sqlalchemy import select, distinct

    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(distinct(OrgCurrency.currency_code)).where(OrgCurrency.is_base.is_(True), OrgCurrency.enabled.is_(True))
                result = await session.execute(stmt)
                base_currencies = [row[0] for row in result.all()]
                if not base_currencies:
                    base_currencies = ["NZD"]
                svc = CurrencyService(session)
                total_updated = 0
                errs = []
                for base in base_currencies:
                    try:
                        rates = await svc.refresh_rates_from_provider(base)
                        total_updated += len(rates)
                    except Exception as exc:
                        errs.append(f"{base}: {exc}")
        logger.info("Exchange rate refresh completed: %d rates updated", total_updated)
        return {"status": "completed", "rates_updated": total_updated, "base_currencies": base_currencies, "errors": errs}
    except Exception as exc:
        logger.exception("Exchange rate refresh failed: %s", exc)
        return {"status": "failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# 11. Execute migration job
# ---------------------------------------------------------------------------

async def execute_migration_job(job_id: str) -> dict:
    from app.core.database import async_session_factory
    from app.modules.admin.migration_service import DataMigrationService
    from sqlalchemy import text as sql_text

    try:
        job_uuid = uuid.UUID(job_id)
        async with async_session_factory() as session:
            async with session.begin():
                service = DataMigrationService(session)
                validation = await service.validate_source_data(job_uuid)
                if not validation["valid"]:
                    return {"status": "validation_failed", "errors": validation["errors"]}
                job = await service.get_job_status(job_uuid)
                if job is None:
                    return {"status": "failed", "error": "Job not found"}
                if job["mode"] == "full":
                    await service.execute_full_migration(job_uuid)
                else:
                    await service.execute_live_migration(job_uuid)
                integrity = await service.run_integrity_checks(job_uuid)
                final = await service.get_job_status(job_uuid)
        return {"status": final["status"] if final else "unknown", "records_processed": final["records_processed"] if final else 0, "integrity_passed": integrity.get("passed", False)}
    except Exception as exc:
        logger.exception("Migration job %s failed: %s", job_id, exc)
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await session.execute(sql_text("UPDATE migration_jobs SET status = 'failed', error_message = :err, updated_at = NOW() WHERE id = :jid"), {"err": str(exc), "jid": job_id})
        except Exception:
            pass
        return {"status": "failed", "error": str(exc)}


# ---------------------------------------------------------------------------
# 12. Monthly SMS counter reset (Req 2.5)
# ---------------------------------------------------------------------------

async def reset_sms_counters_task() -> dict:
    from sqlalchemy import update, select as sa_select
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation

    now = datetime.now(timezone.utc)

    # Only reset if we're in a new month since the last reset.
    # This prevents container restarts from zeroing out counters mid-month.
    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Check the most recent reset timestamp across all orgs
                result = await session.execute(
                    sa_select(Organisation.sms_sent_reset_at)
                    .where(Organisation.sms_sent_reset_at.is_not(None))
                    .order_by(Organisation.sms_sent_reset_at.desc())
                    .limit(1)
                )
                last_reset = result.scalar_one_or_none()

                if last_reset is not None:
                    # If the last reset was in the current month, skip
                    if last_reset.year == now.year and last_reset.month == now.month:
                        logger.debug(
                            "SMS counter reset skipped — already reset this month (%s)",
                            last_reset.isoformat(),
                        )
                        return {"reset": 0, "skipped": True, "reason": "already_reset_this_month"}

                stmt = update(Organisation).values(sms_sent_this_month=0, sms_sent_reset_at=now)
                result = await session.execute(stmt)
                reset_count = result.rowcount
        logger.info("SMS counter reset: %d orgs reset", reset_count)
        return {"reset": reset_count, "errors": []}
    except Exception as exc:
        logger.error("Error resetting SMS counters: %s", exc)
        return {"reset": 0, "errors": [str(exc)]}


async def process_customer_reminders_scheduled() -> dict:
    """Daily task: enqueue per-customer configured reminders.

    Phase 1: Scans customers with reminder_config, checks vehicle expiry
    dates, and inserts pending items into the reminder_queue table.
    """
    from app.core.database import async_session_factory
    from app.modules.notifications.reminder_queue_service import enqueue_customer_reminders

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await enqueue_customer_reminders(session)
        logger.info(
            "Customer reminders enqueued: %d scanned, %d enqueued, %d errors",
            result.get("customers_scanned", 0),
            result.get("reminders_enqueued", 0),
            result.get("errors", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Failed to enqueue customer reminders: %s", exc)
        return {"error": str(exc)}


async def process_reminder_queue_scheduled() -> dict:
    """Worker task: process pending reminder queue items in batches.

    Phase 2: Picks up batches of pending reminders, sends them with
    rate limiting and concurrency control, marks sent/failed.
    Runs every 60 seconds.
    """
    from app.core.database import async_session_factory
    from app.modules.notifications.reminder_queue_service import process_reminder_queue

    try:
        async with async_session_factory() as session:
            result = await process_reminder_queue(session)
        if result.get("sent", 0) > 0 or result.get("failed", 0) > 0:
            logger.info(
                "Reminder queue processed: %d sent, %d failed, %d retried, %d batches",
                result.get("sent", 0),
                result.get("failed", 0),
                result.get("retried", 0),
                result.get("batches_processed", 0),
            )
        return result
    except Exception as exc:
        logger.exception("Failed to process reminder queue: %s", exc)
        return {"error": str(exc)}


async def sync_public_holidays_task() -> dict:
    """Sync public holidays for NZ and AU for the next 12 months.

    Syncs both the current year and next year to ensure full coverage.
    Runs every 6 months to keep holiday data fresh.

    Checks DB synced_at to avoid redundant syncs on app restart / hot-reload.
    """
    from sqlalchemy import select, func as sa_func
    from app.core.database import async_session_factory
    from app.modules.admin.service import sync_public_holidays
    from app.modules.admin.models import PublicHoliday

    current_year = date.today().year
    next_year = current_year + 1
    total = 0
    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Check if holidays were synced in the last 24 hours — skip if so
                cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                result = await session.execute(
                    select(sa_func.max(PublicHoliday.synced_at))
                )
                last_synced = result.scalar_one_or_none()
                if last_synced is not None and last_synced >= cutoff:
                    logger.debug(
                        "Public holidays already synced at %s — skipping",
                        last_synced,
                    )
                    return {"skipped": True, "last_synced": str(last_synced)}

                for country in ("NZ", "AU"):
                    for year in (current_year, next_year):
                        res = await sync_public_holidays(session, country, year)
                        total += res.get("synced", 0)
        return {"synced": total, "years": [current_year, next_year], "countries": ["NZ", "AU"]}
    except Exception as exc:
        logger.error("Public holiday sync failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 13. Check card expiry and send notifications (Req 9.1–9.6)
# ---------------------------------------------------------------------------

async def check_card_expiry_task() -> dict:
    """Daily task: notify org admins about cards expiring within 2 months.

    Selects only default cards or sole cards for their org.
    Skips cards where expiry_notified_at is already set.
    Wraps each org's processing in try/except for isolation.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
    """
    from sqlalchemy import select, func as sa_func, update as sa_update
    from app.core.database import async_session_factory
    from app.modules.billing.models import OrgPaymentMethod
    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent

    notified = 0
    errors = 0

    try:
        now = datetime.now(timezone.utc)
        current_year = now.year
        current_month = now.month

        # Compute the 2-month-ahead boundary (month/year)
        boundary_month = current_month + 2
        boundary_year = current_year
        if boundary_month > 12:
            boundary_month -= 12
            boundary_year += 1

        async with async_session_factory() as session:
            # Query cards expiring within 2 months that haven't been notified yet.
            # A card expiring in month M/year Y expires at end of that month.
            # We want cards where (exp_year, exp_month) <= (boundary_year, boundary_month)
            # AND the card hasn't already expired (exp_year, exp_month) >= (current_year, current_month).
            result = await session.execute(
                select(OrgPaymentMethod).where(
                    OrgPaymentMethod.expiry_notified_at.is_(None),
                    # Card hasn't already expired
                    (
                        (OrgPaymentMethod.exp_year > current_year)
                        | (
                            (OrgPaymentMethod.exp_year == current_year)
                            & (OrgPaymentMethod.exp_month >= current_month)
                        )
                    ),
                    # Card expires within 2 months
                    (
                        (OrgPaymentMethod.exp_year < boundary_year)
                        | (
                            (OrgPaymentMethod.exp_year == boundary_year)
                            & (OrgPaymentMethod.exp_month <= boundary_month)
                        )
                    ),
                )
            )
            candidates = list(result.scalars().all())

        # Group candidates by org_id for sole-card check
        org_cards: dict[uuid.UUID, list] = {}
        for card in candidates:
            org_cards.setdefault(card.org_id, []).append(card)

        # Get total card counts per org to determine sole cards
        org_total_counts: dict[uuid.UUID, int] = {}
        if org_cards:
            async with async_session_factory() as session:
                for oid in org_cards:
                    count_result = await session.execute(
                        select(sa_func.count(OrgPaymentMethod.id)).where(
                            OrgPaymentMethod.org_id == oid
                        )
                    )
                    org_total_counts[oid] = count_result.scalar() or 0

        for org_id, cards in org_cards.items():
            try:
                total_cards = org_total_counts.get(org_id, 0)
                is_sole_org = total_cards == 1

                for card in cards:
                    # Only notify for default cards or sole cards
                    if not card.is_default and not is_sole_org:
                        continue

                    # Find an org admin to notify
                    async with async_session_factory() as session:
                        admin_result = await session.execute(
                            select(User).where(
                                User.org_id == org_id,
                                User.role == "org_admin",
                                User.is_active.is_(True),
                            ).limit(1)
                        )
                        admin_user = admin_result.scalar_one_or_none()

                    if admin_user is None or not admin_user.email:
                        logger.warning(
                            "No active org admin for org %s — skipping card expiry notification",
                            org_id,
                        )
                        continue

                    # Build notification content (Req 9.3)
                    exp_display = f"{card.exp_month:02d}/{card.exp_year}"
                    brand_display = card.brand.capitalize() if card.brand else "Card"
                    subject = (
                        f"Your {brand_display} ending in {card.last4} expires {exp_display}"
                    )
                    billing_link = "/settings/billing"
                    html_body = (
                        f"<p>Your {brand_display} card ending in {card.last4} "
                        f"expires {exp_display}.</p>"
                        f'<p>Please <a href="{billing_link}">update your payment method</a> '
                        f"to avoid any interruption to your subscription.</p>"
                    )
                    text_body = (
                        f"Your {brand_display} card ending in {card.last4} "
                        f"expires {exp_display}. "
                        f"Please visit {billing_link} to update your payment method."
                    )

                    # Log and send notification
                    async with async_session_factory() as session:
                        async with session.begin():
                            log_entry = await log_email_sent(
                                session,
                                org_id=org_id,
                                recipient=admin_user.email,
                                template_type="card_expiry_warning",
                                subject=subject,
                                status="queued",
                                channel="email",
                            )

                    from app.tasks.notifications import send_email_task
                    send_result = await send_email_task(
                        str(org_id),
                        log_entry["id"],
                        admin_user.email,
                        "",
                        subject,
                        html_body,
                        text_body,
                        None,
                        None,
                        "card_expiry_warning",
                    )

                    if send_result.get("success"):
                        # Mark as notified so we don't re-send (Req 9.4)
                        async with async_session_factory() as session:
                            async with session.begin():
                                await session.execute(
                                    sa_update(OrgPaymentMethod)
                                    .where(OrgPaymentMethod.id == card.id)
                                    .values(expiry_notified_at=datetime.now(timezone.utc))
                                )
                        notified += 1
                    else:
                        logger.warning(
                            "Failed to send card expiry notification for card %s org %s: %s",
                            card.id, org_id, send_result.get("error", "unknown"),
                        )
                        errors += 1

            except Exception as exc:
                logger.exception(
                    "Error processing card expiry for org %s: %s", org_id, exc
                )
                errors += 1

        if notified > 0 or errors > 0:
            logger.info("Card expiry check: %d notified, %d errors", notified, errors)
        return {"notified": notified, "errors": errors}
    except Exception as exc:
        logger.exception("Failed to check card expiry: %s", exc)
        return {"error": str(exc)}


async def cleanup_stale_sessions_task() -> dict:
    """Delete revoked and expired sessions to keep the table lean.

    At scale, token rotation creates one new row per refresh and revokes the
    old one.  Without cleanup the table grows unbounded.  This task runs
    every hour and removes sessions that are either revoked or past their
    expiry, keeping only active sessions.
    """
    from app.core.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(text(
            "DELETE FROM sessions WHERE is_revoked = true OR expires_at < now()"
        ))
        await session.commit()
        return {"deleted": result.rowcount}


# ---------------------------------------------------------------------------
# 14. Weekly roster broadcast — Staff Management Phase 1 task D1 (R10)
# ---------------------------------------------------------------------------

async def weekly_roster_broadcast(_now_utc: datetime | None = None) -> dict:
    """Friday 16:00-16:29 broadcast — sends next-week's roster to every
    opted-in staff member, in each org's local timezone.

    Runs every 30 minutes (the existing scheduler tick); the body
    short-circuits for any org whose local time is not currently
    inside the Friday 16:00-16:29 window. Per-staff sends are wrapped
    in ``db.begin_nested()`` SAVEPOINTs so a single failure does not
    poison the batch (per ``performance-and-resilience`` steering and
    R10.3). The cluster-wide Redis SETNX scheduler lock (``ISSUE-164``)
    keeps duplicate broadcasts from firing across multiple gunicorn
    workers — there is no extra coordination needed here (R10.4).

    Logs each per-staff outcome with ``org_id`` + ``staff_id`` so admins
    can grep production logs for failures (R10.5):

    - ``weekly_roster_broadcast: org=<id> staff=<id> email=ok message_id=...``
    - ``weekly_roster_broadcast: org=<id> staff=<id> email=skipped reason=...``
    - ``weekly_roster_broadcast: org=<id> staff=<id> email=failed error=...``
    - ``weekly_roster_broadcast: org=<id> staff=<id> sms=ok ...`` (same triplet)

    The optional ``_now_utc`` parameter is for unit tests only — it
    short-circuits the ``datetime.now(timezone.utc)`` call so the
    Friday-16:05 logic can be exercised deterministically without
    freezing the system clock.

    **Validates: Requirement R10** (Phase 1 task D1).
    """
    from zoneinfo import ZoneInfo

    from sqlalchemy import or_, select

    from app.config import settings as app_settings
    from app.core.database import _set_rls_org_id, async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.module_management.models import OrgModule
    from app.modules.staff.models import StaffMember

    now_utc = _now_utc or datetime.now(timezone.utc)

    summary: dict = {
        "orgs_in_window": 0,
        "staff_processed": 0,
        "email_sent": 0,
        "email_failed": 0,
        "sms_sent": 0,
        "sms_failed": 0,
    }

    # ------------------------------------------------------------------
    # Step 1 — enumerate orgs that have ``staff_management`` enabled.
    # The ``Organisation`` and ``org_modules`` tables have no RLS gate,
    # so a plain cross-tenant query is fine here (mirrors the pattern
    # used by ``process_recurring_billing_task``).
    # ------------------------------------------------------------------
    async with async_session_factory() as session:
        async with session.begin():
            stmt = (
                select(Organisation.id, Organisation.timezone)
                .join(OrgModule, OrgModule.org_id == Organisation.id)
                .where(
                    OrgModule.module_slug == "staff_management",
                    OrgModule.is_enabled.is_(True),
                )
            )
            result = await session.execute(stmt)
            enabled_orgs = result.all()

    if not enabled_orgs:
        return summary

    viewer_base_url = (
        f"{(app_settings.frontend_base_url or 'http://localhost').rstrip('/')}"
        f"/public/staff-roster"
    )

    # ------------------------------------------------------------------
    # Step 2 — for each enabled org, check whether the org-local time
    # is currently inside the Friday 16:00-16:29 window. If yes,
    # broadcast to every active staff with at least one opt-in.
    # ------------------------------------------------------------------
    for org_id, org_tz_name in enabled_orgs:
        try:
            tz = ZoneInfo(org_tz_name or "UTC")
        except (KeyError, ValueError):
            tz = ZoneInfo("UTC")
        local_now = now_utc.astimezone(tz)

        # Short-circuit unless we're inside Friday 16:00-16:29 local.
        # ``weekday()`` returns 0=Mon .. 4=Fri .. 6=Sun.
        if local_now.weekday() != 4:
            continue
        if local_now.hour != 16:
            continue
        if local_now.minute >= 30:
            continue

        summary["orgs_in_window"] += 1

        # Compute the week_start (next Monday in local time). The
        # Friday broadcast covers NEXT week's roster, so:
        #   - Friday  → +3 days = next Monday
        #   - Anything else → (7 - weekday) % 7 days, with Monday
        #     special-cased to +7 (rare path — short-circuit above
        #     guarantees Friday-only).
        local_today = local_now.date()
        days_until_monday = (7 - local_today.weekday()) % 7 or 7
        week_start = local_today + timedelta(days=days_until_monday)

        try:
            async with async_session_factory() as session:
                async with session.begin():
                    # Set RLS so the staff query only sees this org's
                    # rows (``staff_members`` has a ``tenant_isolation``
                    # policy keyed on ``app.current_org_id``).
                    await _set_rls_org_id(session, str(org_id))
                    stmt_staff = select(StaffMember).where(
                        StaffMember.org_id == org_id,
                        StaffMember.is_active.is_(True),
                        or_(
                            StaffMember.weekly_roster_email_enabled.is_(True),
                            StaffMember.weekly_roster_sms_enabled.is_(True),
                        ),
                    )
                    result_staff = await session.execute(stmt_staff)
                    staff_list = list(result_staff.scalars().all())

                    for staff in staff_list:
                        summary["staff_processed"] += 1

                        # Email leg ----------------------------------
                        if (
                            staff.weekly_roster_email_enabled
                            and staff.email
                            and staff.email.strip()
                        ):
                            await _broadcast_one_email(
                                session,
                                org_id=org_id,
                                staff=staff,
                                week_start=week_start,
                                summary=summary,
                            )

                        # SMS leg ------------------------------------
                        if (
                            staff.weekly_roster_sms_enabled
                            and staff.phone
                            and staff.phone.strip()
                        ):
                            await _broadcast_one_sms(
                                session,
                                org_id=org_id,
                                staff=staff,
                                week_start=week_start,
                                viewer_base_url=viewer_base_url,
                                summary=summary,
                            )
        except Exception:
            # The whole-org work-unit failed (DB connect, RLS set, ...).
            # Log and move on so one bad org doesn't poison the batch.
            logger.exception(
                "weekly_roster_broadcast: org=%s broadcast batch failed",
                org_id,
            )

    return summary


async def _broadcast_one_email(
    session,
    *,
    org_id,
    staff,
    week_start: date,
    summary: dict,
) -> None:
    """Email-leg helper for :func:`weekly_roster_broadcast`.

    Wrapped in a SAVEPOINT (``begin_nested``) so a per-staff failure
    rolls back only that staff's writes (e.g. ``notification_log``,
    ``audit_log`` partial inserts), letting the rest of the org's
    batch keep flowing (R10.3).
    """
    from app.modules.staff.roster_delivery import send_roster_email

    try:
        savepoint = await session.begin_nested()
    except Exception:
        # Couldn't even open a SAVEPOINT — DB session is sick. Bail
        # this leg so we don't crash the per-org transaction.
        logger.warning(
            "weekly_roster_broadcast: org=%s staff=%s email=failed "
            "error=savepoint_open_failed",
            org_id, staff.id,
        )
        summary["email_failed"] += 1
        return

    try:
        result = await send_roster_email(
            session, org_id=org_id, staff=staff, week_start=week_start,
        )
    except Exception as exc:
        await savepoint.rollback()
        summary["email_failed"] += 1
        logger.warning(
            "weekly_roster_broadcast: org=%s staff=%s email=failed error=%s",
            org_id, staff.id, exc,
        )
        return

    if result.ok:
        summary["email_sent"] += 1
        logger.info(
            "weekly_roster_broadcast: org=%s staff=%s email=ok message_id=%s",
            org_id, staff.id, result.message_id,
        )
    else:
        # Refusal cases (no shifts in week, opt-out flipped during the
        # tick) are NOT failures — they're skips. Roll back the
        # SAVEPOINT so any side-effect rows the helper might have
        # written (none today, but defence-in-depth) don't persist.
        await savepoint.rollback()
        summary["email_failed"] += 1
        logger.info(
            "weekly_roster_broadcast: org=%s staff=%s email=skipped reason=%s",
            org_id, staff.id, result.reason,
        )


async def _broadcast_one_sms(
    session,
    *,
    org_id,
    staff,
    week_start: date,
    viewer_base_url: str,
    summary: dict,
) -> None:
    """SMS-leg helper for :func:`weekly_roster_broadcast`.

    Mirrors :func:`_broadcast_one_email` but for the SMS provider
    chain. The viewer-token mint inside ``send_roster_sms`` is
    idempotent per ``(staff_id, week_start)`` so re-running this on
    the next Friday-16:05 tick (e.g. after a worker restart) reuses
    the same public viewer URL.
    """
    from app.modules.staff.roster_delivery import send_roster_sms

    try:
        savepoint = await session.begin_nested()
    except Exception:
        logger.warning(
            "weekly_roster_broadcast: org=%s staff=%s sms=failed "
            "error=savepoint_open_failed",
            org_id, staff.id,
        )
        summary["sms_failed"] += 1
        return

    try:
        result = await send_roster_sms(
            session,
            org_id=org_id,
            staff=staff,
            week_start=week_start,
            viewer_base_url=viewer_base_url,
        )
    except Exception as exc:
        await savepoint.rollback()
        summary["sms_failed"] += 1
        logger.warning(
            "weekly_roster_broadcast: org=%s staff=%s sms=failed error=%s",
            org_id, staff.id, exc,
        )
        return

    if result.ok:
        summary["sms_sent"] += 1
        logger.info(
            "weekly_roster_broadcast: org=%s staff=%s sms=ok message_id=%s",
            org_id, staff.id, result.message_id,
        )
    else:
        await savepoint.rollback()
        summary["sms_failed"] += 1
        logger.info(
            "weekly_roster_broadcast: org=%s staff=%s sms=skipped reason=%s",
            org_id, staff.id, result.reason,
        )




# ---------------------------------------------------------------------------
# 15. Accrue leave (Staff Management Phase 2 task C1) — daily UTC
# ---------------------------------------------------------------------------

async def accrue_leave() -> dict:
    """Daily leave-accrual sweep for every active staff in every org
    with the ``staff_management`` module enabled.

    Iterates orgs → iterates active staff → calls
    :func:`app.modules.leave.accrual.accrue_for_staff`. Each per-staff
    call is wrapped in a SAVEPOINT (``begin_nested``) so a single
    failure doesn't poison the per-org batch (mirrors the pattern used
    by :func:`weekly_roster_broadcast`). The accrual helper is itself
    idempotent — its existing-row guard keyed on
    ``(staff_id, leave_type_id, reason='accrual', occurred_at)``
    makes a same-day re-run a no-op (e.g. after a crash + restart).

    Per-org RLS is set via :func:`app.core.database._set_rls_org_id` so
    the staff query only sees the current tenant's rows. Cross-org work
    happens in separate sessions to keep RLS bounded.

    **Validates: Requirements R5, R6, R7 — Staff Management Phase 2 task C1**
    """
    from sqlalchemy import select

    from app.core.database import _set_rls_org_id, async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.leave.accrual import accrue_for_staff
    from app.modules.module_management.models import OrgModule
    from app.modules.staff.models import StaffMember

    today = date.today()
    summary = {"orgs_processed": 0, "staff_processed": 0, "errors": 0}

    # Step 1 — list orgs with staff_management enabled.
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(Organisation.id)
                    .join(OrgModule, OrgModule.org_id == Organisation.id)
                    .where(
                        OrgModule.module_slug == "staff_management",
                        OrgModule.is_enabled.is_(True),
                    )
                )
                result = await session.execute(stmt)
                org_ids = [row[0] for row in result.all()]
    except Exception as exc:
        logger.exception("accrue_leave: failed to load orgs: %s", exc)
        return {"error": str(exc)}

    if not org_ids:
        return summary

    # Step 2 — per-org work in its own session so RLS is bounded.
    for org_id in org_ids:
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await _set_rls_org_id(session, str(org_id))
                    stmt_staff = select(StaffMember).where(
                        StaffMember.org_id == org_id,
                        StaffMember.is_active.is_(True),
                    )
                    staff_result = await session.execute(stmt_staff)
                    staff_list = list(staff_result.scalars().all())

                    for staff in staff_list:
                        summary["staff_processed"] += 1
                        try:
                            savepoint = await session.begin_nested()
                        except Exception:
                            logger.warning(
                                "accrue_leave: org=%s staff=%s "
                                "error=savepoint_open_failed",
                                org_id, staff.id,
                            )
                            summary["errors"] += 1
                            continue
                        try:
                            await accrue_for_staff(session, staff, today)
                        except Exception as exc:
                            await savepoint.rollback()
                            summary["errors"] += 1
                            logger.warning(
                                "accrue_leave: org=%s staff=%s error=%s",
                                org_id, staff.id, exc,
                            )
            summary["orgs_processed"] += 1
        except Exception:
            # Whole-org work-unit failed (DB connect, RLS set, ...).
            # Log + move on so a single bad org doesn't poison the batch.
            logger.exception(
                "accrue_leave: org=%s batch failed", org_id,
            )
            summary["errors"] += 1

    logger.info(
        "accrue_leave: orgs=%d staff=%d errors=%d",
        summary["orgs_processed"],
        summary["staff_processed"],
        summary["errors"],
    )
    return summary


# ---------------------------------------------------------------------------
# 16. Process public holidays (Staff Management Phase 2 task C2) — daily UTC
# ---------------------------------------------------------------------------

async def process_public_holidays() -> dict:
    """For every org with ``staff_management`` enabled, walk public
    holidays in the next 14 days for the org's ``country_code`` (default
    NZ when unset) and call
    :func:`app.modules.leave.public_holidays.process_holiday_for_org`
    for each. Each per-holiday call is wrapped in a SAVEPOINT so a
    single failure doesn't poison the per-org batch.

    The downstream helper is itself idempotent — the alt-day grant is
    keyed on ``(staff_id, leave_type_id, reason='public_holiday_extension',
    occurred_at)`` so re-running the task is a no-op for already-granted
    days. Time-and-a-half schedule-entry markers are also idempotent
    (the helper checks for the existing marker substring).

    **Validates: Requirement R8 — Staff Management Phase 2 task C2**
    """
    from sqlalchemy import select

    from app.core.database import _set_rls_org_id, async_session_factory
    from app.modules.admin.models import Organisation, PublicHoliday
    from app.modules.leave.public_holidays import process_holiday_for_org
    from app.modules.module_management.models import OrgModule

    today = date.today()
    horizon = today + timedelta(days=14)
    summary = {
        "orgs_processed": 0,
        "holidays_processed": 0,
        "alt_days_granted": 0,
        "entries_marked": 0,
        "errors": 0,
    }

    # Step 1 — list orgs with staff_management enabled (+ their country).
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(Organisation.id, Organisation.country_code)
                    .join(OrgModule, OrgModule.org_id == Organisation.id)
                    .where(
                        OrgModule.module_slug == "staff_management",
                        OrgModule.is_enabled.is_(True),
                    )
                )
                result = await session.execute(stmt)
                org_rows = list(result.all())
    except Exception as exc:
        logger.exception("process_public_holidays: failed to load orgs: %s", exc)
        return {"error": str(exc)}

    if not org_rows:
        return summary

    # Step 2 — per-org work in its own session.
    for org_id, country_code in org_rows:
        cc = (country_code or "NZ").upper()
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await _set_rls_org_id(session, str(org_id))
                    ph_stmt = (
                        select(PublicHoliday.holiday_date)
                        .where(
                            PublicHoliday.country_code == cc,
                            PublicHoliday.holiday_date >= today,
                            PublicHoliday.holiday_date <= horizon,
                        )
                        .order_by(PublicHoliday.holiday_date)
                    )
                    ph_result = await session.execute(ph_stmt)
                    holiday_dates = [row[0] for row in ph_result.all()]

                    for holiday_date in holiday_dates:
                        summary["holidays_processed"] += 1
                        try:
                            savepoint = await session.begin_nested()
                        except Exception:
                            logger.warning(
                                "process_public_holidays: org=%s date=%s "
                                "error=savepoint_open_failed",
                                org_id, holiday_date,
                            )
                            summary["errors"] += 1
                            continue
                        try:
                            sub = await process_holiday_for_org(
                                session, org_id, holiday_date,
                            )
                            summary["alt_days_granted"] += sub.get(
                                "alt_days_granted", 0,
                            )
                            summary["entries_marked"] += sub.get(
                                "entries_marked", 0,
                            )
                        except Exception as exc:
                            await savepoint.rollback()
                            summary["errors"] += 1
                            logger.warning(
                                "process_public_holidays: org=%s date=%s "
                                "error=%s",
                                org_id, holiday_date, exc,
                            )
            summary["orgs_processed"] += 1
        except Exception:
            logger.exception(
                "process_public_holidays: org=%s batch failed", org_id,
            )
            summary["errors"] += 1

    logger.info(
        "process_public_holidays: orgs=%d holidays=%d alt_days=%d "
        "entries_marked=%d errors=%d",
        summary["orgs_processed"],
        summary["holidays_processed"],
        summary["alt_days_granted"],
        summary["entries_marked"],
        summary["errors"],
    )
    return summary


# ---------------------------------------------------------------------------
# 17. Update ADP snapshots (Staff Management Phase 2 task C3) — daily UTC
# ---------------------------------------------------------------------------

# Phase 4 (R13) divisor — NZ standard 260 working days/year (52 × 5).
# Used when a staff member has finalised payslips covering the last 52
# weeks; the Phase 2 fallback below uses the per-week schedule.
_ADP_PAYSLIP_WORKING_DAYS_PER_YEAR = 260


def _compute_phase2_adp(staff) -> "Decimal | None":  # noqa: F821 — Decimal imported lazily
    """Phase-2 placeholder ADP formula — unchanged from the original
    ``update_adp_snapshots`` body. Returns ``None`` when the staff
    record is missing the inputs required to compute a value.

    Formula (per design §1 / R9.1):

        daily_rate = (hourly_rate × standard_hours_per_week)
                      / weekday_count_in_schedule

    where ``weekday_count_in_schedule`` is the number of Mon-Fri keys
    flagged in ``staff.availability_schedule`` (fallback 5 when zero
    or missing).
    """
    from decimal import Decimal

    if (
        staff.hourly_rate is None
        or staff.standard_hours_per_week is None
    ):
        return None

    weekday_keys = ("monday", "tuesday", "wednesday", "thursday", "friday")
    schedule = staff.availability_schedule or {}
    weekday_count = 0
    for key in weekday_keys:
        entry = schedule.get(key)
        if isinstance(entry, dict):
            if entry.get("start") or entry.get("enabled"):
                weekday_count += 1
        elif isinstance(entry, bool):
            if entry:
                weekday_count += 1
        elif isinstance(entry, str):
            if entry.strip():
                weekday_count += 1
    if weekday_count == 0:
        weekday_count = 5

    weekly_pay = (
        Decimal(staff.hourly_rate)
        * Decimal(staff.standard_hours_per_week)
    )
    return (weekly_pay / Decimal(weekday_count)).quantize(Decimal("0.01"))


async def _compute_payslip_adp(
    session, staff_id, *, as_of: date,
) -> "Decimal | None":  # noqa: F821 — Decimal imported lazily
    """Phase-4 (R13) ADP from finalised payslips.

    Sums ``payslips.gross_pay`` for the staff over the last 365 days
    (joined to ``pay_periods.pay_date`` so we use the actual money-out
    date, not the period boundary) and divides by the NZ-standard 260
    working days/year. Only ``status='finalised'`` payslips count —
    drafts and voided rows are excluded.

    Returns ``None`` when no finalised payslips fall in the window or
    the sum is zero / NULL — the caller falls back to Phase 2.
    """
    from decimal import Decimal

    from sqlalchemy import text as sql_text

    window_end = as_of
    window_start = as_of - timedelta(days=365)

    result = await session.execute(
        sql_text(
            "SELECT COALESCE(SUM(p.gross_pay), 0) "
            "FROM payslips p "
            "JOIN pay_periods pp ON pp.id = p.pay_period_id "
            "WHERE p.staff_id = :staff_id "
            "  AND p.status = 'finalised' "
            "  AND pp.pay_date BETWEEN :start AND :end"
        ),
        {
            "staff_id": str(staff_id),
            "start": window_start,
            "end": window_end,
        },
    )
    total = result.scalar_one_or_none() or 0
    total_d = Decimal(total)
    if total_d <= 0:
        return None
    return (
        total_d / Decimal(_ADP_PAYSLIP_WORKING_DAYS_PER_YEAR)
    ).quantize(Decimal("0.01"))


async def update_adp_snapshots() -> dict:
    """Compute + persist ``average_daily_pay`` snapshot for every
    active staff member.

    Phase 4 (R13) — primary path uses real finalised payslip data:

        adp = sum(payslips.gross_pay over last 365 days, finalised)
              / 260 working days

    Falls back to the Phase 2 placeholder formula
    (:func:`_compute_phase2_adp`) when a staff member has no finalised
    payslips in the 52-week window — typical for new hires or orgs
    that haven't run their first pay run yet.

    Terminated staff are skipped (``is_active=false``) — consistent
    with the Phase 2 behaviour. Staff with neither finalised payslips
    nor the Phase 2 inputs (``hourly_rate`` + ``standard_hours_per_week``)
    are also skipped.

    Each successful update writes a redacted ``staff.adp_snapshot_updated``
    audit row with ``after_value = {staff_id, adp, source}`` only —
    no PII, no breakdown JSON.

    Idempotent — re-running overwrites the same value, so a crash +
    restart loop won't double-up.

    The ``average_daily_pay_snapshot`` column is added by alembic 0205
    but isn't on the ``StaffMember`` ORM yet, so we issue a raw
    parameterised UPDATE keyed on ``id``.

    **Validates: Requirement R13 — Staff Management Phase 4 task C2**
    """
    from sqlalchemy import select, text as sql_text

    from app.core.audit import write_audit_log
    from app.core.database import async_session_factory
    from app.modules.staff.models import StaffMember

    today = date.today()
    summary = {
        "staff_updated": 0,
        "skipped": 0,
        "errors": 0,
        "from_payslips": 0,
        "from_phase2": 0,
    }

    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = select(StaffMember).where(
                    StaffMember.is_active.is_(True),
                )
                result = await session.execute(stmt)
                staff_list = list(result.scalars().all())

                for staff in staff_list:
                    try:
                        # Try real-payslip path first (R13.1).
                        daily_rate = await _compute_payslip_adp(
                            session, staff.id, as_of=today,
                        )
                        source = "payslips"
                        if daily_rate is None:
                            # Fall back to Phase 2 placeholder (R13.2).
                            daily_rate = _compute_phase2_adp(staff)
                            source = "phase2"

                        if daily_rate is None:
                            # No payslips and Phase 2 inputs missing —
                            # nothing to compute.
                            summary["skipped"] += 1
                            continue

                        await session.execute(
                            sql_text(
                                "UPDATE staff_members "
                                "SET average_daily_pay_snapshot = :v "
                                "WHERE id = :id"
                            ),
                            {"v": daily_rate, "id": staff.id},
                        )
                        # Redacted audit per task spec — staff_id, adp,
                        # source only. NO breakdown JSON, NO PII.
                        await write_audit_log(
                            session=session,
                            org_id=staff.org_id,
                            user_id=None,
                            action="staff.adp_snapshot_updated",
                            entity_type="staff_member",
                            entity_id=staff.id,
                            after_value={
                                "staff_id": str(staff.id),
                                "adp": str(daily_rate),
                                "source": source,
                            },
                        )
                        summary["staff_updated"] += 1
                        if source == "payslips":
                            summary["from_payslips"] += 1
                        else:
                            summary["from_phase2"] += 1
                    except Exception as exc:
                        summary["errors"] += 1
                        logger.warning(
                            "update_adp_snapshots: staff=%s error=%s",
                            staff.id, exc,
                        )
    except Exception as exc:
        logger.exception("update_adp_snapshots failed: %s", exc)
        return {"error": str(exc)}

    logger.info(
        "update_adp_snapshots: updated=%d (payslips=%d phase2=%d) "
        "skipped=%d errors=%d",
        summary["staff_updated"],
        summary["from_payslips"],
        summary["from_phase2"],
        summary["skipped"],
        summary["errors"],
    )
    return summary


# ---------------------------------------------------------------------------
# 17. Late-arrival + missed-clock-out alerts — Staff Management Phase 3 C1/C2
# ---------------------------------------------------------------------------


async def check_late_arrivals_task() -> dict:
    """Every 5 min: find scheduled shifts that started 15+ minutes ago
    where the staff hasn't clocked in yet, and SMS the manager (R14).

    Per-shift dedupe via Redis key ``late:{shift_id}`` (8h TTL). Honours
    the snooze set by the running-late upward report (R14b / G3) — if
    the key already exists (set by the staff's "I'm running late"
    POST), this task skips the shift.

    The whole task is wrapped in try/except so a transient SMS failure
    or DB hiccup doesn't take the scheduler down.

    **Validates: Requirement R14 (G3 snooze) — Phase 3 task C1.**
    """
    from sqlalchemy import and_, select

    from app.core.database import async_session_factory
    from app.core.redis import redis_pool
    from app.integrations.sms_sender import send_sms
    from app.modules.scheduling_v2.models import ScheduleEntry
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry

    summary = {"shifts_checked": 0, "sms_sent": 0, "skipped": 0, "errors": 0}

    try:
        now_utc = datetime.now(timezone.utc)
        # Shifts that started 15-60 minutes ago — narrow window so
        # we only nag once per shift; the dedupe key prevents repeated
        # SMS for the same shift.
        window_start = now_utc - timedelta(minutes=60)
        window_end = now_utc - timedelta(minutes=15)

        async with async_session_factory() as session:
            async with session.begin():
                # Find candidate shifts.
                stmt = (
                    select(ScheduleEntry)
                    .where(
                        and_(
                            ScheduleEntry.status.in_(["scheduled"]),
                            ScheduleEntry.staff_id.is_not(None),
                            ScheduleEntry.start_time >= window_start,
                            ScheduleEntry.start_time <= window_end,
                            ScheduleEntry.entry_type.in_(
                                ["job", "booking", "other"],
                            ),
                        ),
                    )
                )
                shifts = (await session.execute(stmt)).scalars().all()

                for shift in shifts:
                    summary["shifts_checked"] += 1

                    # Honour the running-late snooze (G3).
                    redis_key = f"late:{shift.id}"
                    try:
                        existing = await redis_pool.get(redis_key)
                        if existing:
                            summary["skipped"] += 1
                            continue
                    except Exception:
                        # Redis down — proceed; skipping is best-effort.
                        existing = None

                    # Check if the staff has clocked in for this shift.
                    open_or_matched = (
                        await session.execute(
                            select(TimeClockEntry.id).where(
                                and_(
                                    TimeClockEntry.staff_id == shift.staff_id,
                                    TimeClockEntry.clock_in_at >= shift.start_time - timedelta(hours=1),
                                    TimeClockEntry.clock_in_at <= now_utc,
                                ),
                            ).limit(1)
                        )
                    ).scalar_one_or_none()
                    if open_or_matched is not None:
                        summary["skipped"] += 1
                        continue

                    # Resolve manager via reporting_to chain.
                    staff = await session.get(StaffMember, shift.staff_id)
                    if staff is None:
                        summary["skipped"] += 1
                        continue
                    manager = None
                    cursor = staff
                    seen: set = set()
                    while (
                        cursor.reporting_to
                        and cursor.reporting_to not in seen
                    ):
                        seen.add(cursor.id)
                        m = await session.get(StaffMember, cursor.reporting_to)
                        if m is None:
                            break
                        if m.phone:
                            manager = m
                            break
                        cursor = m

                    if manager is None or not manager.phone:
                        summary["skipped"] += 1
                        # Still set the dedupe key so we don't re-check
                        # this shift every 5 minutes.
                        try:
                            await redis_pool.set(redis_key, "1", ex=28800)
                        except Exception:
                            pass
                        continue

                    body = (
                        f"Late: {staff.first_name or staff.name} hasn't "
                        f"clocked in for shift starting "
                        f"{shift.start_time.strftime('%H:%M')}."
                    )
                    try:
                        await send_sms(
                            session,
                            to_phone=manager.phone,
                            body=body,
                            dlq_task_name="late_arrival_alert",
                            dlq_task_args={
                                "schedule_entry_id": str(shift.id),
                                "staff_id": str(staff.id),
                            },
                            org_id=shift.org_id,
                        )
                        summary["sms_sent"] += 1
                    except Exception as exc:
                        summary["errors"] += 1
                        logger.warning(
                            "check_late_arrivals: shift=%s sms_failed=%s",
                            shift.id, exc,
                        )

                    # Dedupe so we don't SMS the manager again for this shift.
                    try:
                        await redis_pool.set(redis_key, "1", ex=28800)  # 8h
                    except Exception:
                        pass
    except Exception as exc:
        logger.exception("check_late_arrivals failed: %s", exc)
        return {"error": str(exc)}

    logger.info(
        "check_late_arrivals: shifts=%d sms=%d skipped=%d errors=%d",
        summary["shifts_checked"],
        summary["sms_sent"],
        summary["skipped"],
        summary["errors"],
    )
    return summary


async def check_missed_clock_outs_task() -> dict:
    """Hourly: find ``time_clock_entries`` with ``clock_out_at IS NULL
    AND clock_in_at < now() - 12h`` and send the staff a "Did you
    forget to clock out?" SMS, plus notify the manager.

    Per-entry dedupe via Redis key ``missed_clockout:{entry_id}``
    (24h TTL).

    **Validates: Requirement R14.2 — Phase 3 task C2.**
    """
    from sqlalchemy import and_, select

    from app.core.database import async_session_factory
    from app.core.redis import redis_pool
    from app.integrations.sms_sender import send_sms
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry

    summary = {"entries_checked": 0, "sms_sent": 0, "skipped": 0, "errors": 0}

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)

        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(TimeClockEntry)
                    .where(
                        and_(
                            TimeClockEntry.clock_out_at.is_(None),
                            TimeClockEntry.clock_in_at < cutoff,
                        ),
                    )
                )
                entries = (await session.execute(stmt)).scalars().all()

                for entry in entries:
                    summary["entries_checked"] += 1
                    redis_key = f"missed_clockout:{entry.id}"
                    try:
                        existing = await redis_pool.get(redis_key)
                        if existing:
                            summary["skipped"] += 1
                            continue
                    except Exception:
                        pass

                    staff = await session.get(StaffMember, entry.staff_id)
                    if staff is None or not staff.phone:
                        summary["skipped"] += 1
                        try:
                            await redis_pool.set(
                                redis_key, "1", ex=86400,
                            )
                        except Exception:
                            pass
                        continue

                    body = (
                        "Did you forget to clock out? Your shift from "
                        f"{entry.clock_in_at.strftime('%H:%M')} is still open. "
                        "Open the app to close it."
                    )
                    try:
                        await send_sms(
                            session,
                            to_phone=staff.phone,
                            body=body,
                            dlq_task_name="missed_clockout_alert",
                            dlq_task_args={
                                "time_clock_entry_id": str(entry.id),
                            },
                            org_id=entry.org_id,
                        )
                        summary["sms_sent"] += 1
                    except Exception as exc:
                        summary["errors"] += 1
                        logger.warning(
                            "check_missed_clock_outs: entry=%s sms_failed=%s",
                            entry.id, exc,
                        )

                    try:
                        await redis_pool.set(redis_key, "1", ex=86400)
                    except Exception:
                        pass
    except Exception as exc:
        logger.exception("check_missed_clock_outs failed: %s", exc)
        return {"error": str(exc)}

    logger.info(
        "check_missed_clock_outs: entries=%d sms=%d skipped=%d errors=%d",
        summary["entries_checked"],
        summary["sms_sent"],
        summary["skipped"],
        summary["errors"],
    )
    return summary


# ---------------------------------------------------------------------------
# 18. Roll pay periods — Staff Management Phase 4 task C1
# ---------------------------------------------------------------------------


async def roll_pay_periods_task() -> dict:
    """Daily roll-forward of pay periods for every org with the
    ``payroll`` module enabled.

    For each such org, ensures the next four pay periods exist.
    Uses :func:`app.modules.payslips.period_rolling.compute_next_period_dates`
    with the org's stored ``pay_period_cadence`` / ``pay_period_anchor_day``
    / ``pay_date_offset_days`` columns and the latest existing
    ``pay_periods.end_date`` watermark.

    Idempotent — every INSERT uses ``ON CONFLICT (org_id, start_date)
    DO NOTHING`` against the unique index ``uq_pay_periods_org_start``,
    so a re-run is a silent no-op.

    G14 — non-retroactive cadence change: the algorithm reads cadence
    from ``organisations`` at call time and rolls forward from
    ``latest_end+1`` only. Existing finalised/paid periods are never
    rewritten.

    Per-org work runs in its own session + ``begin()`` transaction so
    a single org failure doesn't poison the batch (mirrors the
    pattern used by :func:`accrue_leave`).

    **Validates: Requirements R1.5, R1.6 (G5 + G14) — Staff Management
    Phase 4 task C1.**
    """
    from sqlalchemy import select, text as sql_text

    from app.core.audit import write_audit_log
    from app.core.database import _set_rls_org_id, async_session_factory
    from app.modules.payslips.models import PayPeriod
    from app.modules.payslips.period_rolling import compute_next_period_dates

    summary = {
        "orgs_processed": 0,
        "periods_created": 0,
        "periods_skipped": 0,
        "errors": 0,
    }

    # Step 1 — list orgs with payroll enabled.
    # The pay_period_* columns are physically present on
    # ``organisations`` (added by alembic 0209) but not yet mapped on
    # the ``Organisation`` ORM, so we use a raw SELECT.
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = sql_text(
                    "SELECT o.id, o.pay_period_cadence, "
                    "       o.pay_period_anchor_day, "
                    "       o.pay_date_offset_days "
                    "FROM organisations o "
                    "JOIN org_modules m ON m.org_id = o.id "
                    "WHERE m.module_slug = 'payroll' "
                    "  AND m.is_enabled = true"
                )
                result = await session.execute(stmt)
                org_rows = list(result.all())
    except Exception as exc:
        logger.exception("roll_pay_periods: failed to load orgs: %s", exc)
        return {"error": str(exc)}

    if not org_rows:
        return summary

    today = date.today()

    # Step 2 — per-org work in its own session so RLS is bounded.
    for org_id, cadence, anchor_day, offset_days in org_rows:
        cadence = (cadence or "fortnightly")
        anchor_day = int(anchor_day or 1)
        offset_days = int(offset_days if offset_days is not None else 3)

        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await _set_rls_org_id(session, str(org_id))

                    latest_end = (
                        await session.execute(
                            select(PayPeriod.end_date)
                            .where(PayPeriod.org_id == org_id)
                            .order_by(PayPeriod.end_date.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()

                    # Roll forward up to 4 periods, ON CONFLICT DO
                    # NOTHING for idempotency. We carry our own
                    # latest_end forward across the loop iterations
                    # so the next compute call chains end-to-start
                    # even when the prior INSERT silently no-op'd.
                    for _ in range(4):
                        try:
                            start, end, pay_dt = compute_next_period_dates(
                                cadence=cadence,
                                anchor_day=anchor_day,
                                pay_date_offset_days=offset_days,
                                latest_end=latest_end,
                                today=today,
                            )
                        except ValueError as exc:
                            logger.warning(
                                "roll_pay_periods: org=%s "
                                "compute_failed=%s",
                                org_id, exc,
                            )
                            summary["errors"] += 1
                            break

                        new_id = uuid.uuid4()
                        result = await session.execute(
                            sql_text(
                                "INSERT INTO pay_periods "
                                "(id, org_id, start_date, end_date, "
                                " pay_date, status) "
                                "VALUES (:id, :org_id, :start, :end, "
                                "        :pay, 'open') "
                                "ON CONFLICT (org_id, start_date) "
                                "DO NOTHING "
                                "RETURNING id"
                            ),
                            {
                                "id": str(new_id),
                                "org_id": str(org_id),
                                "start": start,
                                "end": end,
                                "pay": pay_dt,
                            },
                        )
                        inserted_id = result.scalar_one_or_none()
                        if inserted_id is not None:
                            summary["periods_created"] += 1
                            # G12-compliant audit: dates only, no PII /
                            # money. ``pay_period.created_by_roll`` is
                            # a system-initiated event so user_id=None.
                            await write_audit_log(
                                session=session,
                                org_id=org_id,
                                user_id=None,
                                action="pay_period.created_by_roll",
                                entity_type="pay_period",
                                entity_id=new_id,
                                after_value={
                                    "pay_period_id": str(new_id),
                                    "start_date": start.isoformat(),
                                    "end_date": end.isoformat(),
                                    "pay_date": pay_dt.isoformat(),
                                    "cadence": cadence,
                                },
                            )
                        else:
                            summary["periods_skipped"] += 1

                        # Carry the watermark forward so the next
                        # iteration computes against this end_date,
                        # whether we INSERTed or hit ON CONFLICT.
                        latest_end = end

            summary["orgs_processed"] += 1
        except Exception:
            # Whole-org work-unit failed — log + move on so a single
            # bad org doesn't poison the batch.
            logger.exception(
                "roll_pay_periods: org=%s batch failed", org_id,
            )
            summary["errors"] += 1

    logger.info(
        "roll_pay_periods: orgs=%d created=%d skipped=%d errors=%d",
        summary["orgs_processed"],
        summary["periods_created"],
        summary["periods_skipped"],
        summary["errors"],
    )
    return summary


# ---------------------------------------------------------------------------
# Lightweight in-process scheduler
# ---------------------------------------------------------------------------

import asyncio

from app.modules.ha.middleware import get_node_role
from app.tasks.subscriptions import (
    check_grace_period_task,
    check_suspension_retention_task,
    check_trial_expiry_task,
    process_recurring_billing_task,
)
# Cloud Backup & Restore scheduled-task entry points (cloud-backup-restore
# spec, task 15.2). Defined in the backup_restore service facade; registered in
# _DAILY_TASKS + WRITE_TASKS below so they run on the primary node only.
from app.modules.backup_restore.service import (
    run_blob_gc_task,
    run_rehearsal_task,
    run_scheduled_backup_task,
)

# Tasks that write to the database and must be skipped on standby nodes.
# ALL tasks that INSERT, UPDATE, or DELETE rows must be listed here.
# If a task writes to the DB and runs on both nodes, the standby will
# have the data locally AND receive it via replication → duplicate key
# errors that permanently block replication.  See ISSUE-147.
#
# NOTE on promotion: when a standby is promoted to primary, the middleware
# role cache is updated immediately by set_node_role(). The next scheduler
# cycle will read "primary" from get_node_role() and execute all tasks
# normally — no additional logic is needed here.
WRITE_TASKS: set[str] = {
    "recurring_billing",           # process_recurring_billing_task — charges orgs
    "overdue_invoices",            # check_overdue_invoices_task — marks invoices overdue
    "retry_notifications",         # retry_failed_notifications_task — re-sends notifications
    "archive_error_logs",          # archive_error_logs_task — deletes old error logs
    "recurring_invoices",          # generate_recurring_invoices_task — creates invoices
    "schedule_reminders",          # send_schedule_reminders_task — sends reminder emails
    "publish_notifications",       # publish_scheduled_notifications — publishes notifications
    "reset_sms_counters",         # reset_sms_counters_task — resets monthly SMS counters
    "customer_reminders",          # process_customer_reminders_scheduled — enqueues reminders
    "reminder_queue_worker",       # process_reminder_queue_scheduled — sends queued reminders
    "check_card_expiry",           # check_card_expiry_task — sends expiry notifications
    "cleanup_sessions",            # cleanup_stale_sessions_task — deletes stale sessions
    "check_trial_expiry",          # check_trial_expiry_task — status transitions, audit logs, email logs
    "check_grace_period",          # check_grace_period_task — status transitions, audit logs, email sends
    "check_suspension_retention",  # check_suspension_retention_task — status transitions, audit logs, settings updates, email sends
    "compliance_expiry",           # check_compliance_expiry_task — sends expiry emails, writes notification log
    "sync_public_holidays",        # sync_public_holidays_task — DELETE + INSERT holidays + audit log (ISSUE-147)
    "quote_expiry",                # check_quote_expiry_task — UPDATE quotes to expired status
    "cleanup_bounce_rows",         # cleanup_expired_bounce_rows_task — deletes expired soft bounces (Phase 8c)
    "weekly_roster_broadcast",     # weekly_roster_broadcast — sends roster email/SMS, writes audit_log + notification_log (Staff Phase 1, R10)
    "accrue_leave",                # accrue_leave — writes leave_ledger + leave_balance updates (Staff Phase 2, C1)
    "process_public_holidays",     # process_public_holidays — writes leave_ledger + schedule_entries notes (Staff Phase 2, C2)
    "update_adp_snapshots",        # update_adp_snapshots — UPDATEs staff_members.average_daily_pay_snapshot + writes staff.adp_snapshot_updated audit row (Staff Phase 2 C3 → Phase 4 C2 swapped in real payslip data per R13)
    "check_late_arrivals",         # check_late_arrivals_task — sends late-arrival SMS, sets Redis dedupe (Staff Phase 3, C1)
    "check_missed_clock_outs",     # check_missed_clock_outs_task — sends missed-clock-out SMS (Staff Phase 3, C2)
    "roll_pay_periods",            # roll_pay_periods_task — INSERTs next 4 pay_periods rows + audit_log (Staff Phase 4, C1)
    # Cloud Backup & Restore (cloud-backup-restore spec, task 15.2 / Req 8.8).
    # All three write platform/global rows (backups, blobs, jobs, rehearsals,
    # audit_log) on the PRIMARY only — the standby receives them via logical
    # replication, so running them on the standby would double-write (ISSUE-147).
    "backup_scheduled",            # run_scheduled_backup_task — creates Backup_Jobs + backups + blobs
    "backup_blob_gc",              # run_blob_gc_task — prunes/deletes backups + blobs (retention + orphan GC)
    "backup_rehearsal",            # run_rehearsal_task — writes restore_rehearsals rows
}

# (task_fn, interval_seconds, name)
_DAILY_TASKS: list[tuple] = [
    (check_overdue_invoices_task, 3600, "overdue_invoices"),
    (retry_failed_notifications_task, 300, "retry_notifications"),
    (archive_error_logs_task, 86400, "archive_error_logs"),
    (generate_recurring_invoices_task, 3600, "recurring_invoices"),
    (check_quote_expiry_task, 3600, "quote_expiry"),
    (send_schedule_reminders_task, 300, "schedule_reminders"),
    (check_compliance_expiry_task, 86400, "compliance_expiry"),
    (publish_scheduled_notifications, 60, "publish_notifications"),
    (reset_sms_counters_task, 86400, "reset_sms_counters"),
    (process_customer_reminders_scheduled, 86400, "customer_reminders"),
    (process_reminder_queue_scheduled, 60, "reminder_queue_worker"),
    (sync_public_holidays_task, 15552000, "sync_public_holidays"),  # every ~6 months
    (cleanup_stale_sessions_task, 3600, "cleanup_sessions"),  # every hour
    (check_card_expiry_task, 86400, "check_card_expiry"),  # daily
    (process_recurring_billing_task, 900, "recurring_billing"),  # every 15 minutes
    (check_trial_expiry_task, 86400, "check_trial_expiry"),  # daily
    (check_grace_period_task, 900, "check_grace_period"),  # every 15 minutes (matches billing cadence)
    (check_suspension_retention_task, 86400, "check_suspension_retention"),  # daily
    (cleanup_expired_bounce_rows_task, 3600, "cleanup_bounce_rows"),  # hourly (Phase 8c)
    # Staff Phase 1 D1 — runs every 30 minutes; the body short-circuits
    # unless the org-local time is currently inside Friday 16:00-16:29
    # (R10). The 30-min interval lines up with the spec so every timezone
    # in our customer base hits exactly one tick inside the window.
    (weekly_roster_broadcast, 1800, "weekly_roster_broadcast"),
    # Staff Phase 2 C1/C2/C3 — run once per UTC day. The 86400s interval
    # combined with the scheduler-lock first-acquire (last_run=0.0) means
    # they fire on the first tick after each app start; the per-task
    # idempotency guards (existing-ledger-row SELECTs in the accrual +
    # public-holiday helpers; same-key UPDATE for ADP) make a same-day
    # re-run a no-op (e.g. after a crash + restart).
    (accrue_leave, 86400, "accrue_leave"),
    (process_public_holidays, 86400, "process_public_holidays"),
    (update_adp_snapshots, 86400, "update_adp_snapshots"),
    # Staff Phase 3 C1/C2 — operational alerts. The scheduler-lock +
    # WRITE_TASKS guards skip these on standby HA nodes so the same
    # alert isn't sent twice. Both honour per-shift / per-entry Redis
    # dedupe so an immediate re-run after a worker restart is a no-op.
    (check_late_arrivals_task, 300, "check_late_arrivals"),
    (check_missed_clock_outs_task, 3600, "check_missed_clock_outs"),
    # Staff Phase 4 C1 — daily roll of pay_periods for orgs with the
    # payroll module enabled. Idempotent via UNIQUE(org_id, start_date)
    # + ON CONFLICT DO NOTHING; a same-day re-run is a no-op.
    (roll_pay_periods_task, 86400, "roll_pay_periods"),
    # Cloud Backup & Restore (cloud-backup-restore spec, task 15.2). Each task
    # ticks every 60s; the body short-circuits internally:
    #   - run_scheduled_backup_task honours the configured NZ-tz cron +
    #     Backup_Window (fires only inside the matching minute/window), with an
    #     in-process per-minute dedupe so a double-tick never starts two backups.
    #   - run_blob_gc_task runs retention prune + orphan GC under the
    #     per-destination prune/GC lock (no-ops when no primary is configured).
    #   - run_rehearsal_task honours the configured rehearsal_cron.
    # All three are WRITE_TASKS so the scheduler skips them on standby nodes.
    (run_scheduled_backup_task, 60, "backup_scheduled"),
    (run_blob_gc_task, 3600, "backup_blob_gc"),
    (run_rehearsal_task, 60, "backup_rehearsal"),
]

_stop_event: asyncio.Event | None = None
_task_handle: asyncio.Task | None = None

# --- Single-worker scheduler lock (Redis SETNX with TTL renewal) ---
#
# Without this lock, every gunicorn worker would run the scheduler
# independently. With --workers 2 (Pi) or --workers 4 (Docker default)
# that means each daily task fires 2-4× simultaneously, multiplying:
#
#   - DB queries (e.g. `find_due_schedules`)
#   - Outbound email/SMS sends (each worker re-sends the same notifications)
#   - Stripe API calls (mitigated by idempotency_key on the billing path,
#     but still wasteful)
#
# The HA heartbeat in app/main.py uses the same SETNX pattern; we follow it
# verbatim. The lock is renewed every loop tick (30s) with a 60s TTL so a
# crashed worker's lock self-expires and another worker takes over within
# one tick. PERFORMANCE_AUDIT.md §B-H3 / §1 quick win #7.
_SCHED_LOCK_KEY = "scheduler:loop_lock"
_SCHED_LOCK_TTL = 60  # seconds — must exceed the 30s loop tick


async def _try_acquire_scheduler_lock() -> bool:
    """Try to claim the cluster-wide scheduler lock for this worker.

    Returns True if the lock was acquired (or successfully renewed by a
    previous owner — see ``_renew_scheduler_lock``). Returns False if
    another worker already holds the lock.

    On Redis errors, returns True with a warning logged: failing safe by
    running the scheduler is preferable to silently skipping all tasks
    when Redis is briefly unavailable. This matches the HA heartbeat
    behaviour (see app/main.py).
    """
    try:
        from app.core.redis import redis_pool
        worker_id = str(os.getpid())
        # Atomic SET with NX + EX. Returns truthy only when the key didn't
        # exist before. Subsequent calls within the TTL window return None.
        was_new = await redis_pool.set(
            _SCHED_LOCK_KEY, worker_id, nx=True, ex=_SCHED_LOCK_TTL,
        )
        return bool(was_new)
    except Exception as exc:
        logger.warning(
            "Redis unavailable for scheduler lock — running scheduler in PID %s: %s",
            os.getpid(), exc,
        )
        return True


async def _renew_scheduler_lock() -> bool:
    """Renew the lock TTL if this worker still owns it.

    Uses a get-then-expire to confirm ownership rather than a blind
    EXPIRE. If we don't own the key (e.g. our entry expired and another
    worker took over), returns False and the loop should stop running
    tasks until it re-acquires.

    On Redis errors, returns True (fail-safe) for the same reason as
    ``_try_acquire_scheduler_lock``.
    """
    try:
        from app.core.redis import redis_pool
        worker_id = str(os.getpid())
        current = await redis_pool.get(_SCHED_LOCK_KEY)
        if current is None:
            # Lock expired between our last tick and now. Re-acquire.
            return bool(await redis_pool.set(
                _SCHED_LOCK_KEY, worker_id, nx=True, ex=_SCHED_LOCK_TTL,
            ))
        if current != worker_id:
            # Another worker owns it. We must stop running tasks.
            return False
        # We own it. Bump the TTL.
        await redis_pool.expire(_SCHED_LOCK_KEY, _SCHED_LOCK_TTL)
        return True
    except Exception as exc:
        logger.warning(
            "Redis unavailable during scheduler lock renewal in PID %s: %s",
            os.getpid(), exc,
        )
        return True


async def _release_scheduler_lock() -> None:
    """Best-effort lock release on graceful shutdown.

    Only deletes the key if we still own it (avoids stealing a successor's
    lock during a stagger restart). Errors are swallowed — at worst the
    lock self-expires within 60s.
    """
    try:
        from app.core.redis import redis_pool
        worker_id = str(os.getpid())
        current = await redis_pool.get(_SCHED_LOCK_KEY)
        if current == worker_id:
            await redis_pool.delete(_SCHED_LOCK_KEY)
    except Exception:
        pass


async def _run_task_safe(fn, name: str) -> None:
    try:
        result = await fn()
        logger.info("Scheduled task [%s] completed: %s", name, result)
    except Exception:
        logger.exception("Scheduled task [%s] failed", name)


# ---------------------------------------------------------------------------
# Dummy probe task — only enabled when SCHEDULER_DEBUG_PROBE=1.
#
# Used to monitor the scheduler-lock behaviour (ISSUE-164) on dev: it runs
# every 10 seconds, leaves a clearly-prefixed log line, and writes nothing
# to the database so it's safe to leave on. Should be off in prod.
# ---------------------------------------------------------------------------

async def _scheduler_probe_task() -> dict:
    # Use print() not logger.info() so output is visible regardless of
    # uvicorn's logging config (the `app.tasks.scheduled` logger has no
    # handler attached in dev, so INFO messages are silently dropped).
    msg = f"[scheduler-probe] tick from PID {os.getpid()} at {datetime.now(timezone.utc).isoformat()}"
    print(msg, flush=True)
    return {"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat()}


if os.environ.get("SCHEDULER_DEBUG_PROBE") == "1":
    _DAILY_TASKS.append((_scheduler_probe_task, 10, "scheduler_probe"))
    # Probe is read-only — must NOT be added to WRITE_TASKS so it runs on
    # standby too, demonstrating that the standby node still ticks.


async def _scheduler_loop() -> None:
    """Run all scheduled tasks at their configured intervals.

    Acquires a Redis SETNX lock so only one worker (across all gunicorn
    forks) runs tasks at any given moment. Re-attempts acquisition every
    tick if we don't currently hold it — this handles the case where the
    lock-holder crashed and its TTL expired, or where the holder's process
    is being restarted by gunicorn's --max-requests recycling.
    """
    global _stop_event
    _stop_event = asyncio.Event()

    # Track last-run time per task
    last_run: dict[str, float] = {}
    import time

    holds_lock = await _try_acquire_scheduler_lock()
    if holds_lock:
        logger.info("Scheduler lock acquired by PID %s — running tasks", os.getpid())
        # First-acquire: force every task to run at its first eligible tick.
        for _fn, _interval, name in _DAILY_TASKS:
            last_run[name] = 0.0
    else:
        logger.info(
            "Scheduler lock held by another worker — PID %s standing by", os.getpid(),
        )
        # We're standing by. Pretend tasks ran "now" so that if we later
        # take over, we wait a full interval before firing — preventing
        # duplicate runs when the original holder did its job and then
        # got recycled by gunicorn's --max-requests.
        _t0 = time.time()
        for _fn, _interval, name in _DAILY_TASKS:
            last_run[name] = _t0

    while not _stop_event.is_set():
        # Renew or re-acquire the lock each tick. If neither succeeds,
        # skip the task pass entirely (another worker is running them).
        if holds_lock:
            holds_lock = await _renew_scheduler_lock()
            if not holds_lock:
                logger.info(
                    "Scheduler lock taken over by another worker — PID %s yielding",
                    os.getpid(),
                )
        else:
            holds_lock = await _try_acquire_scheduler_lock()
            if holds_lock:
                logger.info(
                    "Scheduler lock acquired by PID %s after takeover", os.getpid(),
                )
                # Reset last_run to "now" on takeover so we don't fire
                # tasks that the predecessor likely just ran. They will
                # still fire on their next configured interval.
                _t = time.time()
                for _fn, _interval, name in _DAILY_TASKS:
                    last_run[name] = _t

        if holds_lock:
            now = time.time()
            role = get_node_role()
            for fn, interval, name in _DAILY_TASKS:
                if now - last_run.get(name, 0) >= interval:
                    if role == "standby" and name in WRITE_TASKS:
                        logger.debug("Skipping task %s on standby node", name)
                        continue
                    last_run[name] = now
                    asyncio.create_task(_run_task_safe(fn, name))

        # Check every 30 seconds
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


async def start_scheduler() -> None:
    """Start the background scheduler (called from app startup)."""
    global _task_handle
    if _task_handle is not None and not _task_handle.done():
        return
    _task_handle = asyncio.create_task(_scheduler_loop(), name="task-scheduler")
    logger.info("Background task scheduler started")


async def stop_scheduler() -> None:
    """Stop the background scheduler (called from app shutdown)."""
    global _task_handle, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task_handle is not None:
        try:
            await asyncio.wait_for(_task_handle, timeout=10)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task_handle.cancel()
        _task_handle = None
    # Best-effort lock release so a successor worker can pick up immediately
    # (rather than waiting for the 60s TTL).
    await _release_scheduler_lock()
    logger.info("Background task scheduler stopped")
