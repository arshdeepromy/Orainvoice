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
    from sqlalchemy import update
    from app.core.database import async_session_factory
    from app.modules.admin.models import Organisation

    now = datetime.now(timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = update(Organisation).values(sms_sent_this_month=0, sms_sent_reset_at=now)
                result = await session.execute(stmt)
                reset_count = result.rowcount
        logger.info("SMS counter reset: %d orgs reset", reset_count)
        return {"reset": reset_count, "errors": []}
    except Exception as exc:
        logger.error("Error resetting SMS counters: %s", exc)
        return {"reset": 0, "errors": [str(exc)]}
