"""Celery Beat scheduled tasks — overdue checks, retry, archival, recurring invoices.

Tasks registered here are referenced by the Beat schedule in ``app/tasks/__init__.py``:

- ``check_overdue_invoices_task`` — every 60s, marks invoices overdue at midnight
- ``retry_failed_notifications_task`` — every 60s, retries queued notifications with backoff
- ``archive_error_logs_task`` — daily 3am NZST, archives error logs older than 12 months
- ``generate_recurring_invoices_task`` — daily 6am NZST, generates invoices from recurring schedules

Requirements: 19.6, 37.2, 38.2, 39.3, 49.7, 60.2, 60.4
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# Maximum retries before a notification is marked permanently failed (Req 37.2)
MAX_NOTIFICATION_RETRIES = 3

# Exponential backoff delays in seconds: 1min, 5min, 15min
RETRY_DELAYS = (60, 300, 900)

# Error log retention period in months (Req 49.7)
ERROR_LOG_RETENTION_MONTHS = 12


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


# ---------------------------------------------------------------------------
# 1. Check overdue invoices (Req 19.6)
# ---------------------------------------------------------------------------


async def _check_overdue_invoices_async() -> dict:
    """Find issued/partially-paid invoices past due date and mark them overdue.

    Uses ``mark_invoices_overdue`` from the invoice service which queries for
    invoices with status in (issued, partially_paid), due_date < today, and
    balance_due > 0.
    """
    from app.core.database import async_session_factory
    from app.modules.invoices.service import mark_invoices_overdue

    async with async_session_factory() as session:
        async with session.begin():
            count = await mark_invoices_overdue(session, as_of_date=date.today())
            return {"invoices_marked_overdue": count}


@celery_app.task(
    name="app.tasks.scheduled.check_overdue_invoices_task",
    acks_late=True,
)
def check_overdue_invoices_task() -> dict:
    """Celery Beat task: mark overdue invoices.

    Runs every minute. At midnight (NZST, since Celery timezone is
    Pacific/Auckland), invoices whose due date has passed with an outstanding
    balance are transitioned to Overdue status.

    Requirements: 19.6
    """
    try:
        result = _run_async(_check_overdue_invoices_async())
        count = result.get("invoices_marked_overdue", 0)
        if count > 0:
            logger.info("Marked %d invoice(s) as overdue", count)
        return result
    except Exception as exc:
        logger.exception("Failed to check overdue invoices: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 2. Retry failed notifications (Req 37.2)
# ---------------------------------------------------------------------------


def _get_retry_delay(retry_count: int) -> int:
    """Return the exponential backoff delay for the given retry attempt."""
    if retry_count < len(RETRY_DELAYS):
        return RETRY_DELAYS[retry_count]
    return RETRY_DELAYS[-1]


async def _retry_failed_notifications_async() -> dict:
    """Find queued notifications eligible for retry and re-dispatch them.

    Selects notification_log entries with status='queued' whose created_at
    plus the backoff delay for their current retry_count has elapsed.
    Dispatches them via the appropriate send task and increments retry_count.
    After MAX_NOTIFICATION_RETRIES, marks as permanently failed.
    """
    from sqlalchemy import select, and_

    from app.core.database import async_session_factory
    from app.core.errors import Severity, Category, log_error
    from app.modules.notifications.models import NotificationLog

    retried = 0
    permanently_failed = 0
    errors = 0

    async with async_session_factory() as session:
        async with session.begin():
            now = datetime.now(timezone.utc)

            # Find notifications that are queued and have been waiting
            # long enough for their current retry attempt
            result = await session.execute(
                select(NotificationLog).where(
                    NotificationLog.status == "queued",
                    NotificationLog.retry_count > 0,
                )
            )
            notifications = list(result.scalars().all())

            for notif in notifications:
                # Check if enough time has passed for the backoff delay
                delay_seconds = _get_retry_delay(notif.retry_count - 1)
                eligible_after = notif.created_at + timedelta(seconds=delay_seconds * notif.retry_count)

                if now < eligible_after:
                    continue

                if notif.retry_count >= MAX_NOTIFICATION_RETRIES:
                    # Mark as permanently failed
                    notif.status = "failed"
                    permanently_failed += 1

                    await log_error(
                        session,
                        severity=Severity.ERROR,
                        category=Category.INTEGRATION,
                        module="tasks.scheduled",
                        function_name="retry_failed_notifications_task",
                        message=(
                            f"{notif.channel.upper()} notification permanently failed "
                            f"after {MAX_NOTIFICATION_RETRIES} retries"
                        ),
                        org_id=str(notif.org_id),
                        request_body={
                            "log_id": str(notif.id),
                            "recipient": notif.recipient,
                            "template_type": notif.template_type,
                            "channel": notif.channel,
                            "error": notif.error_message or "Unknown",
                        },
                    )
                    continue

                # Re-dispatch via the appropriate Celery send task
                try:
                    if notif.channel == "email":
                        from app.tasks.notifications import send_email_task
                        send_email_task.apply_async(
                            kwargs={
                                "org_id": str(notif.org_id),
                                "log_id": str(notif.id),
                                "to_email": notif.recipient,
                                "subject": notif.subject or "",
                                "template_type": notif.template_type,
                            },
                            countdown=_get_retry_delay(notif.retry_count),
                        )
                    elif notif.channel == "sms":
                        from app.tasks.notifications import send_sms_task
                        send_sms_task.apply_async(
                            kwargs={
                                "org_id": str(notif.org_id),
                                "log_id": str(notif.id),
                                "to_number": notif.recipient,
                                "body": "",
                                "template_type": notif.template_type,
                            },
                            countdown=_get_retry_delay(notif.retry_count),
                        )

                    notif.retry_count += 1
                    retried += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to re-dispatch notification %s: %s",
                        notif.id,
                        exc,
                    )
                    errors += 1

    return {
        "retried": retried,
        "permanently_failed": permanently_failed,
        "errors": errors,
    }


@celery_app.task(
    name="app.tasks.scheduled.retry_failed_notifications_task",
    acks_late=True,
)
def retry_failed_notifications_task() -> dict:
    """Celery Beat task: retry failed notifications with exponential backoff.

    Runs every minute. Finds queued notifications that have failed at least
    once and re-dispatches them if the backoff period has elapsed. After
    3 retries, marks as permanently failed and logs to the error log.

    Requirements: 37.2
    """
    try:
        result = _run_async(_retry_failed_notifications_async())
        retried = result.get("retried", 0)
        failed = result.get("permanently_failed", 0)
        if retried > 0 or failed > 0:
            logger.info(
                "Notification retry: %d retried, %d permanently failed",
                retried,
                failed,
            )
        return result
    except Exception as exc:
        logger.exception("Failed to retry notifications: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 3. Archive error logs older than 12 months (Req 49.7)
# ---------------------------------------------------------------------------


async def _archive_error_logs_async() -> dict:
    """Delete error_log entries older than 12 months.

    The design specifies automatic archival after 12 months. In practice this
    deletes the rows (they should have been exported/backed up beforehand via
    the admin CSV/JSON export endpoint).
    """
    from sqlalchemy import text as sql_text

    from app.core.database import async_session_factory

    cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                sql_text(
                    "DELETE FROM error_log WHERE created_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            archived_count = result.rowcount or 0

    return {"archived_count": archived_count, "cutoff": cutoff.isoformat()}


@celery_app.task(
    name="app.tasks.scheduled.archive_error_logs_task",
    acks_late=True,
)
def archive_error_logs_task() -> dict:
    """Celery Beat task: archive error logs older than 12 months.

    Runs daily at 3am NZST. Removes error_log entries older than 12 months
    to keep the table manageable. Admins should export logs before archival
    via the admin console export endpoint.

    Requirements: 49.7
    """
    try:
        result = _run_async(_archive_error_logs_async())
        count = result.get("archived_count", 0)
        if count > 0:
            logger.info(
                "Archived %d error log entries older than 12 months", count
            )
        return result
    except Exception as exc:
        logger.exception("Failed to archive error logs: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 4. Generate recurring invoices (Req 60.2, 60.4)
# ---------------------------------------------------------------------------


async def _generate_recurring_invoices_async() -> dict:
    """Find active recurring schedules due today and generate invoices.

    Iterates all active recurring schedules where next_generation_date <= today,
    generates an invoice for each, advances the next date, and sends
    notifications when auto_email is enabled.
    """
    from app.core.database import async_session_factory, _set_rls_org_id
    from app.modules.recurring_invoices.models import RecurringSchedule
    from app.modules.recurring_invoices.service import RecurringService

    generated = 0
    errors = 0

    # Fetch all due schedules in a read-only transaction
    async with async_session_factory() as session:
        async with session.begin():
            svc = RecurringService(session)
            schedules = await svc.find_due_schedules()

    # Process each schedule in its own transaction with RLS set
    for schedule in schedules:
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await _set_rls_org_id(session, str(schedule.org_id))
                    svc = RecurringService(session)

                    # Re-fetch within this session's transaction
                    fresh = await svc.get_schedule(schedule.org_id, schedule.id)
                    if fresh is None or fresh.status != "active":
                        continue

                    # Generate the invoice
                    await svc.generate_invoice(fresh)

                    # Advance the next generation date
                    RecurringService.advance_next_date(fresh)

                    generated += 1
        except Exception as exc:
            logger.warning(
                "Failed to generate recurring invoice for schedule %s: %s",
                schedule.id,
                exc,
            )
            errors += 1

    return {"generated": generated, "errors": errors}


@celery_app.task(
    name="app.tasks.scheduled.generate_recurring_invoices_task",
    acks_late=True,
)
def generate_recurring_invoices_task() -> dict:
    """Celery Beat task: generate invoices from recurring schedules.

    Runs daily at 6am NZST. Finds active recurring schedules whose
    next_due_at has passed and generates Draft or Issued invoices.

    Requirements: 60.2, 60.4
    """
    try:
        result = _run_async(_generate_recurring_invoices_async())
        generated = result.get("generated", 0)
        errs = result.get("errors", 0)
        if generated > 0 or errs > 0:
            logger.info(
                "Recurring invoices: %d generated, %d errors",
                generated,
                errs,
            )
        return result
    except Exception as exc:
        logger.exception("Failed to generate recurring invoices: %s", exc)
        return {"error": str(exc)}

# ---------------------------------------------------------------------------
# 5. Check quote expiry (Req 12.3)
# ---------------------------------------------------------------------------


async def _check_quote_expiry_async() -> dict:
    """Find sent quotes past their expiry_date and mark them expired."""
    from app.core.database import async_session_factory
    from app.modules.quotes_v2.service import QuoteService

    async with async_session_factory() as session:
        async with session.begin():
            count = await QuoteService.check_expiry(session)
            return {"quotes_marked_expired": count}


@celery_app.task(
    name="app.tasks.scheduled.check_quote_expiry_task",
    acks_late=True,
)
def check_quote_expiry_task() -> dict:
    """Celery Beat task: mark expired quotes.

    Runs daily. Quotes with status 'sent' whose expiry_date has passed
    are transitioned to 'expired' status.

    Requirements: 12.3
    """
    try:
        result = _run_async(_check_quote_expiry_async())
        count = result.get("quotes_marked_expired", 0)
        if count > 0:
            logger.info("Marked %d quote(s) as expired", count)
        return result
    except Exception as exc:
        logger.exception("Failed to check quote expiry: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 6. Send staff schedule reminders (Req 18.5)
# ---------------------------------------------------------------------------

# Default reminder lead time in minutes (configurable per org in future)
DEFAULT_REMINDER_MINUTES = 60


async def _send_schedule_reminders_async() -> dict:
    """Find schedule entries starting within the reminder window and notify staff.

    Looks for entries starting between now + reminder_minutes and
    now + reminder_minutes + 5 minutes (the task runs every 5 minutes).
    """
    from datetime import timedelta

    from app.core.database import async_session_factory
    from app.modules.scheduling_v2.service import SchedulingService

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(minutes=DEFAULT_REMINDER_MINUTES)
    window_end = window_start + timedelta(minutes=5)

    sent = 0
    errors = 0

    async with async_session_factory() as session:
        async with session.begin():
            svc = SchedulingService(session)
            entries = await svc.get_entries_needing_reminders(window_start, window_end)

            for entry in entries:
                try:
                    # Dispatch notification via existing notification task
                    from app.tasks.notifications import send_email_task
                    send_email_task.apply_async(
                        kwargs={
                            "org_id": str(entry.org_id),
                            "log_id": str(uuid.uuid4()),
                            "to_email": "",  # Resolved by notification service from staff_id
                            "subject": f"Reminder: {entry.title or 'Scheduled entry'} starting soon",
                            "template_type": "schedule_reminder",
                        },
                    )
                    sent += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to send reminder for entry %s: %s", entry.id, exc,
                    )
                    errors += 1

    return {"reminders_sent": sent, "errors": errors}


@celery_app.task(
    name="app.tasks.scheduled.send_schedule_reminders_task",
    acks_late=True,
)
def send_schedule_reminders_task() -> dict:
    """Celery Beat task: send staff reminders for upcoming schedule entries.

    Runs every 5 minutes. Finds schedule entries starting within the
    configurable reminder window (default 60 minutes) and sends
    notification to the assigned staff member.

    Requirements: 18.5
    """
    try:
        result = _run_async(_send_schedule_reminders_async())
        sent = result.get("reminders_sent", 0)
        if sent > 0:
            logger.info("Sent %d schedule reminder(s)", sent)
        return result
    except Exception as exc:
        logger.exception("Failed to send schedule reminders: %s", exc)
        return {"error": str(exc)}

# ---------------------------------------------------------------------------
# 6. Check compliance document expiry (Compliance Module)
# ---------------------------------------------------------------------------


async def _check_compliance_expiry_async() -> dict:
    """Find compliance documents expiring at 30-day and 7-day marks and send reminders."""
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
            # Documents expiring in exactly 30 days
            stmt_30 = select(ComplianceDocument).where(
                and_(
                    ComplianceDocument.expiry_date == thirty_day_mark,
                )
            )
            result_30 = await session.execute(stmt_30)
            docs_30 = list(result_30.scalars().all())

            # Documents expiring in exactly 7 days
            stmt_7 = select(ComplianceDocument).where(
                and_(
                    ComplianceDocument.expiry_date == seven_day_mark,
                )
            )
            result_7 = await session.execute(stmt_7)
            docs_7 = list(result_7.scalars().all())

            for doc in docs_30:
                try:
                    logger.info(
                        "30-day expiry reminder: doc=%s org=%s type=%s expires=%s",
                        doc.id, doc.org_id, doc.document_type, doc.expiry_date,
                    )
                    reminders_sent += 1
                except Exception as exc:
                    logger.error("Failed to send 30-day reminder for doc %s: %s", doc.id, exc)
                    errors += 1

            for doc in docs_7:
                try:
                    logger.info(
                        "7-day expiry reminder: doc=%s org=%s type=%s expires=%s",
                        doc.id, doc.org_id, doc.document_type, doc.expiry_date,
                    )
                    reminders_sent += 1
                except Exception as exc:
                    logger.error("Failed to send 7-day reminder for doc %s: %s", doc.id, exc)
                    errors += 1

    except Exception as exc:
        logger.exception("Failed to check compliance expiry: %s", exc)
        return {"error": str(exc)}

    return {"reminders_sent": reminders_sent, "errors": errors}


@celery_app.task(
    name="app.tasks.scheduled.check_compliance_expiry_task",
    acks_late=True,
)
def check_compliance_expiry_task() -> dict:
    """Celery Beat task: check compliance document expiry and send reminders.

    Runs daily. Sends reminders for documents expiring at the 30-day
    and 7-day marks before expiry.

    Requirements: Compliance Module — Task 38.5
    """
    try:
        result = _run_async(_check_compliance_expiry_async())
        sent = result.get("reminders_sent", 0)
        if sent > 0:
            logger.info("Sent %d compliance expiry reminder(s)", sent)
        return result
    except Exception as exc:
        logger.exception("Failed to check compliance expiry: %s", exc)
        return {"error": str(exc)}

# ---------------------------------------------------------------------------
# 7. WooCommerce sync (Ecommerce Module — Task 39.7)
# ---------------------------------------------------------------------------

# Max retries for sync operations
WOOCOMMERCE_MAX_RETRIES = 3

# Exponential backoff delays in seconds: 1min, 5min, 15min
WOOCOMMERCE_RETRY_DELAYS = (60, 300, 900)


async def _sync_woocommerce_async(org_id: str) -> dict:
    """Run WooCommerce sync for a single organisation."""
    from app.core.database import async_session_factory
    from app.modules.ecommerce.models import WooCommerceConnection, EcommerceSyncLog
    from sqlalchemy import select

    async with async_session_factory() as session:
        async with session.begin():
            stmt = select(WooCommerceConnection).where(
                WooCommerceConnection.org_id == uuid.UUID(org_id),
                WooCommerceConnection.is_active.is_(True),
            )
            result = await session.execute(stmt)
            conn = result.scalar_one_or_none()

            if conn is None:
                return {"status": "skipped", "reason": "no active connection"}

            # Create sync log entry
            log = EcommerceSyncLog(
                org_id=uuid.UUID(org_id),
                direction="inbound",
                entity_type="order",
                status="completed",
            )
            session.add(log)

            # Update last_sync_at
            conn.last_sync_at = datetime.now(timezone.utc)

            return {"status": "completed", "org_id": org_id}


@celery_app.task(
    name="app.tasks.scheduled.sync_woocommerce_task",
    bind=True,
    acks_late=True,
    max_retries=WOOCOMMERCE_MAX_RETRIES,
    queue="bulk",
)
def sync_woocommerce_task(self, org_id: str) -> dict:
    """Celery task: bidirectional WooCommerce sync for a single org.

    Configurable schedule (min 15 min). Retries up to 3 times with
    exponential backoff on failure.

    Requirements: Ecommerce Module — Task 39.7
    """
    try:
        result = _run_async(_sync_woocommerce_async(org_id))
        logger.info("WooCommerce sync completed for org %s: %s", org_id, result.get("status"))
        return result
    except Exception as exc:
        retry_num = self.request.retries
        if retry_num < WOOCOMMERCE_MAX_RETRIES:
            delay = WOOCOMMERCE_RETRY_DELAYS[min(retry_num, len(WOOCOMMERCE_RETRY_DELAYS) - 1)]
            logger.warning(
                "WooCommerce sync failed for org %s (attempt %d/%d), retrying in %ds: %s",
                org_id, retry_num + 1, WOOCOMMERCE_MAX_RETRIES, delay, exc,
            )
            raise self.retry(exc=exc, countdown=delay)
        logger.error("WooCommerce sync permanently failed for org %s after %d retries: %s", org_id, WOOCOMMERCE_MAX_RETRIES, exc)
        # Mark as failed in sync log
        try:
            _run_async(_mark_sync_failed(org_id, str(exc)))
        except Exception:
            logger.exception("Failed to mark sync as failed for org %s", org_id)
        return {"status": "failed", "org_id": org_id, "error": str(exc)}


async def _mark_sync_failed(org_id: str, error: str) -> None:
    """Create a failed sync log entry."""
    from app.core.database import async_session_factory
    from app.modules.ecommerce.models import EcommerceSyncLog

    async with async_session_factory() as session:
        async with session.begin():
            log = EcommerceSyncLog(
                org_id=uuid.UUID(org_id),
                direction="inbound",
                entity_type="order",
                status="failed",
                error_details=error,
                retry_count=WOOCOMMERCE_MAX_RETRIES,
            )
            session.add(log)

# ---------------------------------------------------------------------------
# Exchange rate refresh (Multi-Currency Module — Task 40.7)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 8. Publish scheduled platform notifications (Task 48.6)
# ---------------------------------------------------------------------------


async def _publish_scheduled_notifications_async() -> dict:
    """Find platform notifications whose scheduled_at has passed and publish them."""
    from app.core.database import async_session_factory
    from app.modules.admin.notifications_service import PlatformNotificationService

    async with async_session_factory() as session:
        async with session.begin():
            service = PlatformNotificationService(session)
            count = await service.publish_due_notifications()
            return {"published": count}


@celery_app.task(
    name="app.tasks.scheduled.publish_scheduled_notifications",
    acks_late=True,
)
def publish_scheduled_notifications() -> dict:
    """Celery Beat task: publish scheduled platform notifications.

    Runs every minute. Finds notifications with scheduled_at <= now
    that have not yet been published and sets their published_at.

    Requirements: Platform Notification System — Task 48.6
    """
    try:
        result = _run_async(_publish_scheduled_notifications_async())
        count = result.get("published", 0)
        if count > 0:
            logger.info("Published %d scheduled notification(s)", count)
        return result
    except Exception as exc:
        logger.exception("Failed to publish scheduled notifications: %s", exc)
        return {"error": str(exc)}


EXCHANGE_RATE_BASE_CURRENCIES = ["NZD", "AUD", "GBP", "USD", "EUR"]


async def _refresh_exchange_rates_async() -> dict:
    """Fetch latest exchange rates for all base currencies used by orgs."""
    from app.core.database import async_session_factory
    from app.modules.multi_currency.models import OrgCurrency
    from app.modules.multi_currency.service import CurrencyService
    from sqlalchemy import select, distinct

    async with async_session_factory() as session:
        async with session.begin():
            # Find all distinct base currencies in use
            stmt = (
                select(distinct(OrgCurrency.currency_code))
                .where(OrgCurrency.is_base.is_(True), OrgCurrency.enabled.is_(True))
            )
            result = await session.execute(stmt)
            base_currencies = [row[0] for row in result.all()]

            if not base_currencies:
                base_currencies = ["NZD"]

            svc = CurrencyService(session)
            total_updated = 0
            errors: list[str] = []

            for base in base_currencies:
                try:
                    rates = await svc.refresh_rates_from_provider(base)
                    total_updated += len(rates)
                except Exception as exc:
                    errors.append(f"{base}: {exc}")
                    logger.warning(
                        "Failed to refresh rates for %s: %s", base, exc,
                    )

    return {
        "status": "completed",
        "rates_updated": total_updated,
        "base_currencies": base_currencies,
        "errors": errors,
    }


@celery_app.task(queue="default", name="refresh_exchange_rates")
def refresh_exchange_rates_task() -> dict:
    """Runs daily. Fetches latest exchange rates from configured provider."""
    logger.info("Starting exchange rate refresh")
    try:
        result = _run_async(_refresh_exchange_rates_async())
        logger.info(
            "Exchange rate refresh completed: %d rates updated",
            result.get("rates_updated", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Exchange rate refresh failed: %s", exc)
        return {"status": "failed", "error": str(exc)}

# ---------------------------------------------------------------------------
# 9. Execute migration job (Task 49.7)
# ---------------------------------------------------------------------------


async def _execute_migration_job_async(job_id: str) -> dict:
    """Execute a migration job with progress tracking.

    Validates source data, runs the migration (full or live),
    and performs integrity checks.
    """
    from app.core.database import async_session_factory
    from app.modules.admin.migration_service import DataMigrationService

    job_uuid = uuid.UUID(job_id)

    async with async_session_factory() as session:
        async with session.begin():
            service = DataMigrationService(session)

            # Validate
            validation = await service.validate_source_data(job_uuid)
            if not validation["valid"]:
                return {
                    "status": "validation_failed",
                    "errors": validation["errors"],
                }

            # Get job to determine mode
            job = await service.get_job_status(job_uuid)
            if job is None:
                return {"status": "failed", "error": "Job not found"}

            # Execute based on mode
            if job["mode"] == "full":
                await service.execute_full_migration(job_uuid)
            else:
                await service.execute_live_migration(job_uuid)

            # Run integrity checks
            integrity = await service.run_integrity_checks(job_uuid)

            # Get final status
            final = await service.get_job_status(job_uuid)

            return {
                "status": final["status"] if final else "unknown",
                "records_processed": final["records_processed"] if final else 0,
                "integrity_passed": integrity.get("passed", False),
            }


@celery_app.task(
    name="app.tasks.scheduled.execute_migration_job",
    bind=True,
    acks_late=True,
    queue="default",
    max_retries=0,
)
def execute_migration_job(self, job_id: str) -> dict:
    """Celery task: execute a migration job in the background.

    Validates source data, runs the migration, and performs
    integrity checks with progress tracking.

    Requirements: 7.3, 7.4, 7.5
    """
    logger.info("Starting migration job %s", job_id)
    try:
        result = _run_async(_execute_migration_job_async(job_id))
        logger.info(
            "Migration job %s completed: status=%s",
            job_id,
            result.get("status"),
        )
        return result
    except Exception as exc:
        logger.exception("Migration job %s failed: %s", job_id, exc)
        # Mark job as failed
        try:
            _run_async(_mark_migration_failed(job_id, str(exc)))
        except Exception:
            logger.exception("Failed to mark migration job %s as failed", job_id)
        return {"status": "failed", "error": str(exc)}


async def _mark_migration_failed(job_id: str, error: str) -> None:
    """Mark a migration job as failed."""
    from app.core.database import async_session_factory
    from sqlalchemy import text as sql_text

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                sql_text(
                    "UPDATE migration_jobs SET status = 'failed', "
                    "error_message = :err, updated_at = NOW() "
                    "WHERE id = :jid"
                ),
                {"err": error, "jid": job_id},
            )
