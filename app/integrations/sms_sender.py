"""Thin wrapper for sending SMS via the active SMS verification provider.

Mirrors the shape of :mod:`app.integrations.email_sender` so any feature
that needs to send transactional SMS (Phase 1 staff roster broadcast,
future kiosk codes, etc.) can do so without depending on the
``auth.mfa`` module — that module owns the ``SmsVerificationProvider``
rows but should not be the canonical send entry point.

Public API:

- :class:`SmsSendResult` — result value object returned by
  :func:`send_sms`. Distinct from
  :class:`app.integrations.sms_types.SmsSendResult` (which is the
  provider-internal Connexus result) so callers can rely on a stable
  ``(ok, message_id, provider_key, reason)`` shape regardless of which
  provider eventually delivers the message.
- :func:`send_sms` — top-level orchestrator. Loads the active SMS
  provider, instantiates :class:`ConnexusSmsClient`, dispatches the
  message, and (on failure with ``dlq_task_name`` set) stores a
  dead-letter row so ops can replay later.

Caller responsibilities:

- Own the DB session — ``send_sms`` never commits.
- Persist any per-message logging (notification_log, audit_log) at the
  call site — this module only returns the result.

**Validates: Requirement R9 prerequisite — Staff Phase 1 task C4.**
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str
from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
from app.integrations.sms_types import SmsMessage
from app.modules.admin.models import SmsVerificationProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SmsSendResult:
    """Aggregate result of a :func:`send_sms` call.

    ``ok`` is ``True`` when the active provider accepted the message;
    in that case ``message_id`` and ``provider_key`` reflect the
    delivering provider. When ``ok`` is ``False``, ``reason`` carries a
    short machine-readable code (e.g. ``"no_active_provider"``,
    ``"missing_credentials"``, ``"provider_error"``) and the operational
    detail is in the structured log line.
    """

    ok: bool
    message_id: str | None = None
    provider_key: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Provider loader
# ---------------------------------------------------------------------------


async def _load_active_provider(
    db: AsyncSession,
) -> SmsVerificationProvider | None:
    """Return the highest-priority active SMS provider, or ``None``.

    Mirrors the lookup in :mod:`app.modules.notifications.service` and
    :mod:`app.modules.notifications.reminder_queue_service`: active
    providers ordered by ``is_default DESC`` first (so the admin-
    designated default wins) then ``priority`` ASC. This keeps the
    selection rule consistent across the app.
    """
    stmt = (
        select(SmsVerificationProvider)
        .where(SmsVerificationProvider.is_active.is_(True))
        .order_by(
            SmsVerificationProvider.is_default.desc(),
            SmsVerificationProvider.priority,
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def send_sms(
    db: AsyncSession,
    *,
    to_phone: str,
    body: str,
    dlq_task_name: str | None = None,
    dlq_task_args: dict | None = None,
    org_id=None,
) -> SmsSendResult:
    """Send an SMS through the active provider; DLQ on failure.

    Args:
        db: Active SQLAlchemy session. Used for the provider lookup and
            (on failure) the dead-letter insert. Never committed.
        to_phone: Destination phone number — passed through to the
            provider as-is, the provider does its own E.164 validation.
        body: SMS text. Encoding (GSM-7 vs UCS-2) and segmentation are
            the provider's responsibility — see Phase 1 R9 for how the
            staff-roster path handles Māori macrons.
        dlq_task_name: When set, a failure inserts a dead-letter row
            with this task name so the failed send can be replayed.
            Leave ``None`` for one-shot ops where retry is not desired
            (e.g. MFA codes that the user can re-request).
        dlq_task_args: Extra context to store on the DLQ row alongside
            ``to_phone`` and ``body``. Caller-provided keys take
            precedence over the defaults injected here.
        org_id: Optional org UUID to scope the DLQ row.

    Returns:
        :class:`SmsSendResult` with the outcome. Never raises — provider
        and credential errors are caught and surfaced via ``reason``.
    """
    # 1. Load active provider.
    provider = await _load_active_provider(db)
    if provider is None:
        logger.error(
            "send_sms: no active SMS provider configured (to=%s)",
            _mask_phone(to_phone),
        )
        return SmsSendResult(ok=False, reason="no_active_provider")

    if not provider.credentials_encrypted:
        logger.error(
            "send_sms: provider %s has no credentials configured",
            provider.provider_key,
        )
        await _maybe_store_dlq(
            dlq_task_name=dlq_task_name,
            dlq_task_args=dlq_task_args,
            to_phone=to_phone,
            body=body,
            error_message=f"missing_credentials: {provider.provider_key}",
            org_id=org_id,
        )
        return SmsSendResult(
            ok=False,
            provider_key=provider.provider_key,
            reason="missing_credentials",
        )

    # 2. Instantiate the Connexus client. Phase 1 only ships Connexus —
    #    when other providers land, branch on ``provider.provider_key``
    #    here.
    try:
        creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
        # Carry through the provider-config refresh interval if set
        # (matches the pattern in :mod:`app.modules.sms_chat.service`).
        if provider.config and provider.config.get("token_refresh_interval_seconds"):
            creds["token_refresh_interval_seconds"] = provider.config[
                "token_refresh_interval_seconds"
            ]
        config = ConnexusConfig.from_dict(creds)
    except Exception as exc:  # noqa: BLE001 - surface every config error as one reason
        logger.exception(
            "send_sms: failed to load credentials for provider %s",
            provider.provider_key,
        )
        await _maybe_store_dlq(
            dlq_task_name=dlq_task_name,
            dlq_task_args=dlq_task_args,
            to_phone=to_phone,
            body=body,
            error_message=f"credentials_error: {exc}",
            org_id=org_id,
        )
        return SmsSendResult(
            ok=False,
            provider_key=provider.provider_key,
            reason="credentials_error",
        )

    client = ConnexusSmsClient(config)

    # 3. Dispatch.
    try:
        result = await client.send(SmsMessage(to_number=to_phone, body=body))
    except Exception as exc:  # noqa: BLE001 - any transport-level error is a soft failure
        logger.exception(
            "send_sms: provider %s raised on send (to=%s)",
            provider.provider_key,
            _mask_phone(to_phone),
        )
        await _maybe_store_dlq(
            dlq_task_name=dlq_task_name,
            dlq_task_args=dlq_task_args,
            to_phone=to_phone,
            body=body,
            error_message=f"provider_exception: {exc}",
            org_id=org_id,
        )
        return SmsSendResult(
            ok=False,
            provider_key=provider.provider_key,
            reason="provider_error",
        )
    finally:
        # Release the underlying httpx.AsyncClient so we don't leak
        # connections across many sends in the same process.
        try:
            await client.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.debug(
                "send_sms: ignored error while closing Connexus client",
                exc_info=True,
            )

    if result.success:
        return SmsSendResult(
            ok=True,
            message_id=result.message_sid,
            provider_key=provider.provider_key,
        )

    # Provider returned a structured failure (e.g. 4xx from Connexus).
    logger.warning(
        "send_sms: provider %s rejected message: %s",
        provider.provider_key,
        result.error,
    )
    await _maybe_store_dlq(
        dlq_task_name=dlq_task_name,
        dlq_task_args=dlq_task_args,
        to_phone=to_phone,
        body=body,
        error_message=f"provider_rejected: {result.error}",
        org_id=org_id,
    )
    return SmsSendResult(
        ok=False,
        provider_key=provider.provider_key,
        reason="provider_error",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _maybe_store_dlq(
    *,
    dlq_task_name: str | None,
    dlq_task_args: dict | None,
    to_phone: str,
    body: str,
    error_message: str,
    org_id,
) -> None:
    """Best-effort DLQ insert. Mirrors the email_sender pattern."""
    if not dlq_task_name:
        return
    try:
        # Late import to avoid a circular dependency at module load time.
        from app.core.dead_letter import DeadLetterService

        args: dict = {
            "to_phone": to_phone,
            "body": body,
        }
        if dlq_task_args:
            args.update(dlq_task_args)
        await DeadLetterService().store_failed_task(
            task_name=dlq_task_name,
            task_args=args,
            error_message=error_message,
            org_id=org_id,
        )
    except Exception:  # noqa: BLE001 - never let DLQ failure mask the original send error
        logger.exception("send_sms: failed to write SMS failure to dead-letter queue")


def _mask_phone(phone: str | None) -> str:
    """Return a logged-friendly phone number ``*****1234`` form."""
    if not phone:
        return "<empty>"
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]
