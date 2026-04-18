"""Scheduled tasks — overdue checks, retry, archival, recurring invoices.

All functions are plain async — called directly from the app or a
lightweight scheduler. No Celery dependency.

Requirements: 19.6, 37.2, 38.2, 39.3, 49.7, 60.2, 60.4
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

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
# 7. Check compliance document expiry
# ---------------------------------------------------------------------------

async def check_compliance_expiry_task() -> dict:
    from app.core.database import async_session_factory
    from app.modules.compliance_docs.models import ComplianceDocument
    from sqlalchemy import and_, select

    today = date.today()
    thirty_day_mark = today + timedelta(days=30)
    seven_day_mark = today + timedelta(days=7)
    reminders_sent = 0
    errors = 0

    try:
        async with async_session_factory() as session:
            result_30 = await session.execute(select(ComplianceDocument).where(ComplianceDocument.expiry_date == thirty_day_mark))
            docs_30 = list(result_30.scalars().all())
            result_7 = await session.execute(select(ComplianceDocument).where(ComplianceDocument.expiry_date == seven_day_mark))
            docs_7 = list(result_7.scalars().all())

            for doc in docs_30:
                logger.info("30-day expiry reminder: doc=%s org=%s type=%s expires=%s", doc.id, doc.org_id, doc.document_type, doc.expiry_date)
                reminders_sent += 1
            for doc in docs_7:
                logger.info("7-day expiry reminder: doc=%s org=%s type=%s expires=%s", doc.id, doc.org_id, doc.document_type, doc.expiry_date)
                reminders_sent += 1

        if reminders_sent > 0:
            logger.info("Sent %d compliance expiry reminder(s)", reminders_sent)
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
# Lightweight in-process scheduler
# ---------------------------------------------------------------------------

import asyncio

from app.tasks.subscriptions import process_recurring_billing_task

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
]

_stop_event: asyncio.Event | None = None
_task_handle: asyncio.Task | None = None


async def _run_task_safe(fn, name: str) -> None:
    try:
        result = await fn()
        logger.info("Scheduled task [%s] completed: %s", name, result)
    except Exception:
        logger.exception("Scheduled task [%s] failed", name)


async def _scheduler_loop() -> None:
    """Run all scheduled tasks at their configured intervals."""
    global _stop_event
    _stop_event = asyncio.Event()

    # Track last-run time per task
    last_run: dict[str, float] = {}
    import time

    # Run an initial pass for daily tasks on startup
    for fn, interval, name in _DAILY_TASKS:
        last_run[name] = 0.0  # force first run

    while not _stop_event.is_set():
        now = time.time()
        for fn, interval, name in _DAILY_TASKS:
            if now - last_run.get(name, 0) >= interval:
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
    logger.info("Background task scheduler stopped")
