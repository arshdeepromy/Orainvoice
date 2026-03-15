"""Async email/SMS dispatch with retry.

Provides ``send_email_async``, ``send_sms_async``, and periodic reminder
processing functions. Called directly from the application layer.

Retry policy (Requirements 37.1, 37.2, 37.3):
- Up to 3 retries with exponential backoff: 60s → 300s → 900s
- After 3 retries (4 total attempts), mark as permanently failed and log
  the failure in the Global Admin error log.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Exponential backoff delays in seconds: 1min, 5min, 15min
RETRY_DELAYS = (60, 300, 900)
MAX_RETRIES = 3


def _get_retry_delay(retry_number: int) -> int:
    """Return the backoff delay for the given retry attempt (0-indexed)."""
    if retry_number < len(RETRY_DELAYS):
        return RETRY_DELAYS[retry_number]
    return RETRY_DELAYS[-1]


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
    template_id: str | None = None,
    variables: dict[str, str] | None = None,
) -> dict:
    """Execute the actual SMS send and update the notification log.

    If *template_id* and *variables* are provided, the template is loaded
    from the database, rendered with the supplied variables, and the
    rendered body is sent instead of the raw *body* parameter.

    Requirements: 15.1, 15.2
    """
    import json

    from app.core.database import async_session_factory
    from app.core.encryption import envelope_decrypt_str
    from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
    from app.integrations.sms_types import SmsMessage
    from app.modules.admin.models import SmsVerificationProvider
    from app.modules.notifications.service import update_log_status
    from sqlalchemy import select

    async with async_session_factory() as session:
        async with session.begin():
            # --- Template rendering (optional) ---
            effective_body = body
            if template_id and variables is not None:
                from app.modules.notifications.models import NotificationTemplate
                from app.modules.notifications.service import render_sms_body

                tpl_stmt = select(NotificationTemplate).where(
                    NotificationTemplate.id == uuid.UUID(template_id),
                    NotificationTemplate.channel == "sms",
                )
                tpl_result = await session.execute(tpl_stmt)
                tpl = tpl_result.scalar_one_or_none()
                if tpl is not None:
                    tpl_body_blocks = tpl.body_blocks or []
                    raw_body = ""
                    if tpl_body_blocks and isinstance(tpl_body_blocks, list) and len(tpl_body_blocks) > 0:
                        raw_body = tpl_body_blocks[0].get("content", "") if isinstance(tpl_body_blocks[0], dict) else ""
                    if raw_body:
                        effective_body = render_sms_body(raw_body, variables)

            # Resolve active Connexus provider
            stmt = select(SmsVerificationProvider).where(
                SmsVerificationProvider.provider_key == "connexus",
                SmsVerificationProvider.is_active == True,
            )
            result = await session.execute(stmt)
            provider = result.scalar_one_or_none()

            if provider is None or not provider.credentials_encrypted:
                return {"success": False, "error": "Connexus SMS provider not configured or active"}

            creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
            if provider.config and provider.config.get("token_refresh_interval_seconds"):
                creds["token_refresh_interval_seconds"] = provider.config["token_refresh_interval_seconds"]
            config = ConnexusConfig.from_dict(creds)
            client = ConnexusSmsClient(config)

            sms = SmsMessage(
                to_number=to_number,
                body=effective_body,
                from_number=org_sender_number,
            )
            send_result = await client.send(sms)

            if send_result.success:
                await update_log_status(
                    session,
                    log_id=uuid.UUID(log_id),
                    status="sent",
                    sent_at=datetime.now(timezone.utc),
                )
                return {"success": True, "message_sid": send_result.message_sid}

            return {"success": False, "error": send_result.error or "Unknown SMS send error"}




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


async def send_email_task(
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
    """Dispatch an email with logging. Called directly (no Celery).

    Requirements: 37.1, 37.2, 37.3
    """
    try:
        result = await _send_email_async(
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
        if result["success"]:
            return result

        error_msg = result.get("error", "Unknown error")
        await _mark_permanently_failed(
            log_id=log_id,
            org_id=org_id,
            channel="email",
            recipient=to_email,
            template_type=template_type,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}
    except Exception as exc:
        logger.exception("Email send failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def send_sms_task(
    org_id,
    log_id,
    to_number,
    body,
    org_sender_number=None,
    template_type="unknown",
    template_id=None,
    variables=None,
):
    """Dispatch an SMS with logging. Called directly (no Celery).

    When *template_id* and *variables* are provided, the template is loaded,
    rendered with the variables, and the rendered body is sent via Connexus.

    Requirements: 37.1, 37.2, 37.3, 15.1, 15.2
    """
    try:
        result = await _send_sms_async(
            org_id=org_id,
            log_id=log_id,
            to_number=to_number,
            body=body,
            org_sender_number=org_sender_number,
            template_id=template_id,
            variables=variables,
        )
        if result["success"]:
            return result

        error_msg = result.get("error", "Unknown error")
        await _mark_permanently_failed(
            log_id=log_id,
            org_id=org_id,
            channel="sms",
            recipient=to_number,
            template_type=template_type,
            error_message=error_msg,
        )
        return {"success": False, "error": error_msg, "permanently_failed": True}
    except Exception as exc:
        logger.exception("SMS send failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def process_overdue_reminders_task() -> dict:
    """Process overdue payment reminders. Requirements: 38.2, 38.3, 38.4"""
    from app.core.database import async_session_factory
    from app.modules.notifications.service import process_overdue_reminders

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await process_overdue_reminders(session)
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


async def process_wof_rego_reminders_task() -> dict:
    """Process WOF and registration expiry reminders. Requirements: 39.1–39.4"""
    from app.core.database import async_session_factory
    from app.modules.notifications.service import process_wof_rego_reminders

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await process_wof_rego_reminders(session)
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


async def process_customer_reminders_task() -> dict:
    """Process per-customer configured reminders (Service Due, WOF Expiry).

    Called daily by scheduled task. Checks each customer's reminder_config
    in custom_fields and sends notifications for upcoming vehicle expiry dates.
    """
    from app.core.database import async_session_factory
    from app.modules.notifications.service import process_customer_reminders

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await process_customer_reminders(session)
        logger.info(
            "Customer reminders processed: %d checked, %d sent, %d errors",
            result.get("customers_checked", 0),
            result.get("reminders_sent", 0),
            result.get("errors", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Failed to process customer reminders: %s", exc)
        return {"error": str(exc)}
