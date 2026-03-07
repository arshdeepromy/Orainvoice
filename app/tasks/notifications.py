"""Celery tasks for async email/SMS dispatch with retry.

Provides ``send_email_task`` and ``send_sms_task`` which are enqueued by the
application layer and executed asynchronously by Celery notification workers.

Retry policy (Requirements 37.1, 37.2, 37.3):
- Up to 3 retries with exponential backoff: 60s → 300s → 900s
- After 3 retries (4 total attempts), mark as permanently failed and log
  the failure in the Global Admin error log.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# Exponential backoff delays in seconds: 1min, 5min, 15min
RETRY_DELAYS = (60, 300, 900)
MAX_RETRIES = 3


def _get_retry_delay(retry_number: int) -> int:
    """Return the backoff delay for the given retry attempt (0-indexed)."""
    if retry_number < len(RETRY_DELAYS):
        return RETRY_DELAYS[retry_number]
    return RETRY_DELAYS[-1]


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


async def _send_email_async(
    org_id: str,
    log_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    html_body: str,
    text_body: str,
    org_sender_name: str | None,
    org_reply_to: str | None,
) -> dict:
    """Execute the actual email send and update the notification log."""
    from app.core.database import async_session_factory
    from app.integrations.brevo import send_org_email
    from app.modules.notifications.service import update_log_status

    async with async_session_factory() as session:
        async with session.begin():
            result = await send_org_email(
                session,
                to_email=to_email,
                to_name=to_name,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                org_sender_name=org_sender_name,
                org_reply_to=org_reply_to,
            )

            if result.success:
                await update_log_status(
                    session,
                    log_id=uuid.UUID(log_id),
                    status="sent",
                    sent_at=datetime.now(timezone.utc),
                )
                return {"success": True, "message_id": result.message_id}

            return {"success": False, "error": result.error or "Unknown email send error"}


async def _send_sms_async(
    org_id: str,
    log_id: str,
    to_number: str,
    body: str,
    org_sender_number: str | None,
) -> dict:
    """Execute the actual SMS send and update the notification log."""
    from app.core.database import async_session_factory
    from app.integrations.twilio_sms import send_org_sms
    from app.modules.notifications.service import update_log_status

    async with async_session_factory() as session:
        async with session.begin():
            result = await send_org_sms(
                session,
                to_number=to_number,
                body=body,
                org_sender_number=org_sender_number,
            )

            if result.success:
                await update_log_status(
                    session,
                    log_id=uuid.UUID(log_id),
                    status="sent",
                    sent_at=datetime.now(timezone.utc),
                )
                return {"success": True, "message_sid": result.message_sid}

            return {"success": False, "error": result.error or "Unknown SMS send error"}


async def _mark_permanently_failed(
    log_id: str,
    org_id: str,
    channel: str,
    recipient: str,
    template_type: str,
    error_message: str,
) -> None:
    """Mark a notification as permanently failed and log to Global Admin error log."""
    from app.core.database import async_session_factory
    from app.core.errors import Severity, Category, log_error
    from app.modules.notifications.service import update_log_status

    async with async_session_factory() as session:
        async with session.begin():
            await update_log_status(
                session,
                log_id=uuid.UUID(log_id),
                status="failed",
                error_message=error_message,
            )

            await log_error(
                session,
                severity=Severity.ERROR,
                category=Category.INTEGRATION,
                module="tasks.notifications",
                function_name=f"send_{channel}_task",
                message=(
                    f"{channel.upper()} notification permanently failed after "
                    f"{MAX_RETRIES} retries: {error_message}"
                ),
                stack_trace=None,
                org_id=org_id,
                request_body={
                    "log_id": log_id,
                    "recipient": recipient,
                    "template_type": template_type,
                    "channel": channel,
                    "error": error_message,
                },
            )


@celery_app.task(
    bind=True,
    name="app.tasks.notifications.send_email_task",
    max_retries=MAX_RETRIES,
    acks_late=True,
)
def send_email_task(
    self,
    org_id,
    log_id,
    to_email,
    to_name="",
    subject="",
    html_body="",
    text_body="",
    org_sender_name=None,
    org_reply_to=None,
    template_type="unknown",
):
    """Celery task: dispatch an email asynchronously with retry.

    Requirements: 37.1, 37.2, 37.3
    """
    try:
        result = _run_async(
            _send_email_async(
                org_id=org_id,
                log_id=log_id,
                to_email=to_email,
                to_name=to_name,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                org_sender_name=org_sender_name,
                org_reply_to=org_reply_to,
            )
        )

        if result["success"]:
            return result

        error_msg = result.get("error", "Unknown error")
        retry_count = self.request.retries

        if retry_count < MAX_RETRIES:
            delay = _get_retry_delay(retry_count)
            logger.warning(
                "Email send failed (attempt %d/%d), retrying in %ds: %s",
                retry_count + 1,
                MAX_RETRIES + 1,
                delay,
                error_msg,
            )
            raise self.retry(countdown=delay, exc=Exception(error_msg))

        # Exhausted all retries — mark as permanently failed
        _run_async(
            _mark_permanently_failed(
                log_id=log_id,
                org_id=org_id,
                channel="email",
                recipient=to_email,
                template_type=template_type,
                error_message=error_msg,
            )
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}

    except self.MaxRetriesExceededError:
        error_msg = "Max retries exceeded"
        _run_async(
            _mark_permanently_failed(
                log_id=log_id,
                org_id=org_id,
                channel="email",
                recipient=to_email,
                template_type=template_type,
                error_message=error_msg,
            )
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}


@celery_app.task(
    bind=True,
    name="app.tasks.notifications.send_sms_task",
    max_retries=MAX_RETRIES,
    acks_late=True,
)
def send_sms_task(
    self,
    org_id,
    log_id,
    to_number,
    body,
    org_sender_number=None,
    template_type="unknown",
):
    """Celery task: dispatch an SMS asynchronously with retry.

    Requirements: 37.1, 37.2, 37.3
    """
    try:
        result = _run_async(
            _send_sms_async(
                org_id=org_id,
                log_id=log_id,
                to_number=to_number,
                body=body,
                org_sender_number=org_sender_number,
            )
        )

        if result["success"]:
            return result

        error_msg = result.get("error", "Unknown error")
        retry_count = self.request.retries

        if retry_count < MAX_RETRIES:
            delay = _get_retry_delay(retry_count)
            logger.warning(
                "SMS send failed (attempt %d/%d), retrying in %ds: %s",
                retry_count + 1,
                MAX_RETRIES + 1,
                delay,
                error_msg,
            )
            raise self.retry(countdown=delay, exc=Exception(error_msg))

        _run_async(
            _mark_permanently_failed(
                log_id=log_id,
                org_id=org_id,
                channel="sms",
                recipient=to_number,
                template_type=template_type,
                error_message=error_msg,
            )
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}

    except self.MaxRetriesExceededError:
        error_msg = "Max retries exceeded"
        _run_async(
            _mark_permanently_failed(
                log_id=log_id,
                org_id=org_id,
                channel="sms",
                recipient=to_number,
                template_type=template_type,
                error_message=error_msg,
            )
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}


# ---------------------------------------------------------------------------
# Celery Beat task: process overdue reminders (Req 38.2, 38.3, 38.4)
# ---------------------------------------------------------------------------


async def _process_overdue_reminders_async() -> dict:
    """Run the overdue reminder processing logic."""
    from app.core.database import async_session_factory
    from app.modules.notifications.service import process_overdue_reminders

    async with async_session_factory() as session:
        async with session.begin():
            return await process_overdue_reminders(session)


@celery_app.task(
    name="app.tasks.notifications.process_overdue_reminders_task",
    acks_late=True,
)
def process_overdue_reminders_task():
    """Celery Beat task: process overdue payment reminders.

    Runs every 5 minutes. Finds overdue invoices matching configured rules
    and sends email/SMS reminders. Skips voided/paid invoices.

    Requirements: 38.2, 38.3, 38.4
    """
    try:
        result = _run_async(_process_overdue_reminders_async())
        logger.info(
            "Overdue reminders processed: %d orgs, %d reminders sent, %d errors",
            result.get("orgs_processed", 0),
            result.get("reminders_sent", 0),
            result.get("errors", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Failed to process overdue reminders: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Celery Beat task: process WOF/rego expiry reminders (Req 39)
# ---------------------------------------------------------------------------


async def _process_wof_rego_reminders_async() -> dict:
    """Run the WOF/rego expiry reminder processing logic."""
    from app.core.database import async_session_factory
    from app.modules.notifications.service import process_wof_rego_reminders

    async with async_session_factory() as session:
        async with session.begin():
            return await process_wof_rego_reminders(session)


@celery_app.task(
    name="app.tasks.notifications.process_wof_rego_reminders_task",
    acks_late=True,
)
def process_wof_rego_reminders_task():
    """Celery Beat task: process WOF and registration expiry reminders.

    Runs daily at 2am NZST. Finds vehicles with WOF or registration
    expiring within the configured window and sends reminders to linked
    customers via the configured channel (email/SMS/both).

    Requirements: 39.1, 39.2, 39.3, 39.4
    """
    try:
        result = _run_async(_process_wof_rego_reminders_async())
        logger.info(
            "WOF/rego reminders processed: %d orgs, %d reminders sent, %d errors",
            result.get("orgs_processed", 0),
            result.get("reminders_sent", 0),
            result.get("errors", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Failed to process WOF/rego reminders: %s", exc)
        return {"error": str(exc)}
