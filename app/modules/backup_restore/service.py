"""Service facade for Cloud Backup & Restore (Req 8, 18, 2.6).

This module is the seam between the scheduler / Global-Admin API and the
already-built backup/restore building blocks. It composes:

* :class:`~app.modules.backup_restore.keys.key_service.BackupKeyService` — the
  escrowed BMK/BDK hierarchy used to encrypt/decrypt artifacts.
* :func:`~app.modules.backup_restore.backup.pipeline.run_backup` — the
  content-addressed backup pipeline.
* :func:`~app.modules.backup_restore.backup.prune.run_retention_prune` /
  :func:`~app.modules.backup_restore.backup.prune.run_orphan_gc` — retention +
  orphan garbage collection.
* :class:`~app.modules.backup_restore.restore.rehearsal.RehearsalService` — the
  scheduled restore rehearsal.
* :class:`~app.modules.backup_restore.config_service.BackupConfigService` —
  schedule / retention / notification config + recipient resolution.
* :class:`~app.modules.backup_restore.audit.AuditWriter` — durable write-ahead
  + completion audit.

It exposes the three **scheduled-task entry points** the in-process scheduler
calls — :func:`run_scheduled_backup_task`, :func:`run_blob_gc_task`,
:func:`run_rehearsal_task` — which are registered in ``_DAILY_TASKS`` and added
to ``WRITE_TASKS`` in ``app/tasks/scheduled.py`` so they run **only on the
primary node** (the standby skips every ``WRITE_TASK`` — Req 8.8, ISSUE-147).
The scheduled-backup task honours the configured cron + ``Backup_Window``
internally (it short-circuits outside the window) following the
``weekly_roster_broadcast`` precedent.

Outcome **notifications** are dispatched by :class:`BackupNotifier` over email
(via :mod:`app.tasks.notifications` / the unified email sender), Connexus SMS,
and webhook, using the new template types ``backup_failed`` /
``backup_succeeded`` / ``restore_failed`` / ``restore_succeeded`` /
``rehearsal_failed``. Recipients are resolved through
:meth:`BackupConfigService.resolve_notification_recipients` (explicit lists →
``global_admin`` email fallback → per-channel delivery-failure record, Req
18.11). A revoked OAuth token flips the adapter to ``disconnected`` and invokes
the facade's :meth:`BackupNotifier.make_on_disconnected` callback, dispatching
exactly one failure notification per disconnection (Req 2.6).
:meth:`BackupNotifier.send_test` dispatches a test message on each enabled
channel and reports per-channel ``{ok, detail}`` **without touching any
backup/restore/config/job state** (Req 18.12).

Per the project ``get_db_session`` ``session.begin()`` auto-commit pattern the
request-scoped logic uses ``flush()`` / ``await db.refresh()`` (never
``commit()``); the scheduled-task entry points open their own short-lived
``async_session_factory`` sessions and let the surrounding ``session.begin()``
block commit.

Requirements: 8.1, 8.2, 8.3, 8.8, 2.6, 18.11, 18.12
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory
from app.modules.backup_restore.audit import (
    ACTION_PROVIDER_DISCONNECTED,
    AuditWriter,
)
from app.modules.backup_restore.backup.cas import DEFAULT_BLOB_PREFIX
from app.modules.backup_restore.backup.pipeline import (
    BackupPipelineError,
    BackupScopeError,
    run_backup,
)
from app.modules.backup_restore.backup.prune import (
    parse_cron,
    run_orphan_gc,
    run_retention_prune,
)
from app.modules.backup_restore.config_service import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CHANNEL_WEBHOOK,
    BackupConfigService,
)
from app.modules.backup_restore.models import (
    BackupConfig,
    BackupDestination,
    BackupJob,
)
from app.modules.backup_restore.storage.registry import resolve_adapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timezone, scheduling, and retry constants
# ---------------------------------------------------------------------------
#: The schedule cron is expressed in NZ local time (Req 8.1). DST is handled by
#: ``zoneinfo``; the scheduler ticks frequently enough that the minute-resolution
#: cron match below fires inside each eligible minute.
NZ_TIMEZONE = "Pacific/Auckland"

#: Per-channel dispatch retry budget (Req 18.9 — up to 3 attempts per channel).
MAX_CHANNEL_ATTEMPTS = 3

#: Per-attempt webhook HTTP timeout (Req 19.6/19.7 — 10 s per attempt).
WEBHOOK_TIMEOUT_SECONDS = 10.0

# ---------------------------------------------------------------------------
# Notification event vocabulary + new template types (design "Notifications")
# ---------------------------------------------------------------------------
#: New notification template types added by this feature (design Where-it-plugs-in).
TEMPLATE_BACKUP_FAILED = "backup_failed"
TEMPLATE_BACKUP_SUCCEEDED = "backup_succeeded"
TEMPLATE_RESTORE_FAILED = "restore_failed"
TEMPLATE_RESTORE_SUCCEEDED = "restore_succeeded"
TEMPLATE_REHEARSAL_FAILED = "rehearsal_failed"

TEMPLATE_TYPES: tuple[str, ...] = (
    TEMPLATE_BACKUP_FAILED,
    TEMPLATE_BACKUP_SUCCEEDED,
    TEMPLATE_RESTORE_FAILED,
    TEMPLATE_RESTORE_SUCCEEDED,
    TEMPLATE_REHEARSAL_FAILED,
)

#: Notification event names dispatched by the pipeline / restore / rehearsal /
#: adapter, mapped to the template type each resolves to.
EVENT_BACKUP_SUCCESS = "backup.success"
EVENT_BACKUP_FAILURE = "backup.failure"
EVENT_BACKUP_COPY_FAILED = "backup.copy_failed"
EVENT_RESTORE_SUCCESS = "restore.success"
EVENT_RESTORE_FAILURE = "restore.failure"
EVENT_REHEARSAL_FAILED = "rehearsal.failed"
EVENT_REHEARSAL_RTO_UNMET = "rehearsal.rto_unmet"
EVENT_REHEARSAL_TEARDOWN_FAILED = "rehearsal.teardown_failed"
EVENT_PROVIDER_DISCONNECTED = "provider.disconnected"
EVENT_TEST = "notification.test"

_TEMPLATE_TYPE_BY_EVENT: dict[str, str] = {
    EVENT_BACKUP_SUCCESS: TEMPLATE_BACKUP_SUCCEEDED,
    EVENT_BACKUP_FAILURE: TEMPLATE_BACKUP_FAILED,
    EVENT_BACKUP_COPY_FAILED: TEMPLATE_BACKUP_FAILED,
    EVENT_RESTORE_SUCCESS: TEMPLATE_RESTORE_SUCCEEDED,
    EVENT_RESTORE_FAILURE: TEMPLATE_RESTORE_FAILED,
    EVENT_REHEARSAL_FAILED: TEMPLATE_REHEARSAL_FAILED,
    EVENT_REHEARSAL_RTO_UNMET: TEMPLATE_REHEARSAL_FAILED,
    EVENT_REHEARSAL_TEARDOWN_FAILED: TEMPLATE_REHEARSAL_FAILED,
    EVENT_PROVIDER_DISCONNECTED: TEMPLATE_BACKUP_FAILED,
    EVENT_TEST: TEMPLATE_BACKUP_SUCCEEDED,
}

#: Webhook ``status`` enum (Req 19.1): started | succeeded | failed.
_WEBHOOK_STATUS_STARTED = "started"
_WEBHOOK_STATUS_SUCCEEDED = "succeeded"
_WEBHOOK_STATUS_FAILED = "failed"

#: Human-readable email subjects per template type.
_SUBJECT_BY_TEMPLATE: dict[str, str] = {
    TEMPLATE_BACKUP_SUCCEEDED: "OraInvoice backup succeeded",
    TEMPLATE_BACKUP_FAILED: "OraInvoice backup FAILED",
    TEMPLATE_RESTORE_SUCCEEDED: "OraInvoice restore succeeded",
    TEMPLATE_RESTORE_FAILED: "OraInvoice restore FAILED",
    TEMPLATE_REHEARSAL_FAILED: "OraInvoice restore rehearsal FAILED",
}

# Channel-sender callable signatures (injectable for tests).
EmailSender = Callable[[Sequence[str], str, str], Awaitable[tuple[bool, str]]]
SmsSender = Callable[[Sequence[str], str], Awaitable[tuple[bool, str]]]
WebhookSender = Callable[[str, dict[str, Any]], Awaitable[tuple[bool, str]]]


@dataclass
class ChannelDispatchResult:
    """Per-channel outcome of a notification dispatch (Req 18.9/18.11/18.12)."""

    channel: str
    ok: bool
    detail: str
    delivery_failure: bool = False
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Shape the ``/config/notifications/test`` per-channel result (Req 18.12)."""
        return {"channel": self.channel, "ok": self.ok, "detail": self.detail}


# ---------------------------------------------------------------------------
# Default channel senders (real I/O; overridable in tests)
# ---------------------------------------------------------------------------
def _clip(text: str | None, limit: int) -> str:
    """Clip a human-readable message to ``limit`` chars (Req 19.3/19.4 bounds)."""
    value = (text or "").strip() or "(no detail)"
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


async def _default_email_send(
    recipients: Sequence[str], subject: str, body: str
) -> tuple[bool, str]:
    """Dispatch a platform-level outcome email to every resolved recipient (Req 18.2).

    Reuses the unified email sender (``app.integrations.email_sender.send_email``,
    the same pipeline as ``app/tasks/notifications.py``) inside an independent,
    immediately-committed session. These are platform alerts to Global_Admins, so
    no ``org_id`` and no per-org ``notification_log`` row is involved. Returns
    ``(ok, detail)`` where ``ok`` is ``True`` only when every recipient succeeded.
    """
    from app.integrations.email_sender import EmailMessage, send_email

    if not recipients:
        return False, "no recipient"

    text_body = body
    html_body = f"<pre>{body}</pre>"
    failures: list[str] = []
    async with async_session_factory() as session:
        async with session.begin():
            for recipient in recipients:
                message = EmailMessage(
                    to_email=recipient,
                    to_name="",
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    attachments=[],
                    org_id=None,
                )
                result = await send_email(session, message)
                if not result.success:
                    failures.append(f"{recipient}: {result.error or 'unknown error'}")

    if failures:
        return False, "; ".join(failures)
    return True, f"sent to {len(recipients)} recipient(s)"


async def _default_sms_send(
    recipients: Sequence[str], body: str
) -> tuple[bool, str]:
    """Dispatch a platform-level outcome SMS to every resolved number (Req 18.3).

    Sends through the Connexus SMS integration (the same client used by
    ``app/tasks/notifications.py``) in an independent session. SMS bodies are
    clipped to a conservative length. Returns ``(ok, detail)`` — ``ok`` only when
    every number succeeded.
    """
    import json as _json

    from app.core.encryption import envelope_decrypt_str
    from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
    from app.integrations.sms_types import SmsMessage
    from app.modules.admin.models import SmsVerificationProvider

    if not recipients:
        return False, "no recipient"

    sms_body = _clip(body, 480)
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(SmsVerificationProvider).where(
                    SmsVerificationProvider.provider_key == "connexus",
                    SmsVerificationProvider.is_active.is_(True),
                )
            )
            provider = result.scalar_one_or_none()
            if provider is None or not provider.credentials_encrypted:
                return False, "Connexus SMS provider not configured or active"

            creds = _json.loads(envelope_decrypt_str(provider.credentials_encrypted))
            if provider.config and provider.config.get("token_refresh_interval_seconds"):
                creds["token_refresh_interval_seconds"] = provider.config[
                    "token_refresh_interval_seconds"
                ]
            client = ConnexusSmsClient(ConnexusConfig.from_dict(creds))

            failures: list[str] = []
            for number in recipients:
                send_result = await client.send(
                    SmsMessage(to_number=number, body=sms_body, from_number=None)
                )
                if not send_result.success:
                    failures.append(
                        f"{number}: {send_result.error or 'unknown error'}"
                    )

    if failures:
        return False, "; ".join(failures)
    return True, f"sent to {len(recipients)} number(s)"


async def _default_webhook_send(
    url: str, payload: dict[str, Any]
) -> tuple[bool, str]:
    """POST a Webhook_Notification to the configured URL (Req 19.6).

    A single attempt: a non-2xx or transport error returns ``(False, detail)`` and
    the caller's retry loop handles the up-to-3 retries (Req 19.7). Secrets are
    never in ``payload`` (the caller builds it from non-secret fields only).
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as http:
            response = await http.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001 - normalise transport failures
        return False, f"webhook transport error: {exc}"

    if 200 <= response.status_code < 300:
        return True, f"HTTP {response.status_code}"
    return False, f"HTTP {response.status_code}"


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------
class BackupNotifier:
    """Dispatches backup/restore/rehearsal outcome notifications (Req 18, 2.6).

    Resolves recipients via :class:`BackupConfigService`, then dispatches on every
    enabled channel (email / SMS / webhook) independently, retrying a failed
    channel up to :data:`MAX_CHANNEL_ATTEMPTS` times and recording a per-channel
    delivery failure when a channel resolves to nobody or stays failed after the
    final retry (Req 18.9, 18.11). Channel senders are injectable so the dispatch
    logic is unit-testable without real email/SMS/HTTP I/O.

    The :meth:`notify_hook` adapter matches the ``notify_hook(**kwargs)`` contract
    the backup pipeline and the rehearsal service call; the facade wires it in so
    those components dispatch real notifications.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        config_service: BackupConfigService | None = None,
        audit_writer: AuditWriter | None = None,
        email_sender: EmailSender | None = None,
        sms_sender: SmsSender | None = None,
        webhook_sender: WebhookSender | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._config_service = config_service or BackupConfigService(db)
        self._audit = audit_writer or AuditWriter()
        self._email_send = email_sender or _default_email_send
        self._sms_send = sms_sender or _default_sms_send
        self._webhook_send = webhook_sender or _default_webhook_send
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Hook adapter for pipeline / rehearsal (notify_hook(**kwargs))
    # ------------------------------------------------------------------
    async def notify_hook(self, **kwargs: Any) -> list[ChannelDispatchResult]:
        """Adapter matching the pipeline / rehearsal ``notify_hook`` signature.

        The pipeline calls ``notify_hook(event=, success=, message=)`` and the
        rehearsal service calls ``notify_hook(event=, success=, backup_id=,
        detail=, ...)``. Both are normalised to :meth:`dispatch_event`.
        """
        event = str(kwargs.get("event") or EVENT_BACKUP_FAILURE)
        success = bool(kwargs.get("success", False))
        message = kwargs.get("message") or kwargs.get("detail")
        return await self.dispatch_event(
            event=event,
            success=success,
            message=message,
            job_id=kwargs.get("job_id") or kwargs.get("backup_id"),
            scope=kwargs.get("scope"),
        )

    # ------------------------------------------------------------------
    # Event dispatch (Req 18.5-18.8)
    # ------------------------------------------------------------------
    async def dispatch_event(
        self,
        *,
        event: str,
        success: bool,
        message: str | None = None,
        job_id: Any = None,
        scope: str | None = None,
        config: BackupConfig | None = None,
    ) -> list[ChannelDispatchResult]:
        """Dispatch ``event`` on every enabled channel independently (Req 18.5).

        Email is enabled by ``email_enabled``, SMS by ``sms_enabled``, and webhook
        whenever a ``webhook_url`` is configured. When no channel is enabled the
        method completes without dispatching and records that no channel was
        enabled (Req 18.10). Returns one :class:`ChannelDispatchResult` per channel
        attempted.
        """
        cfg = config or await self._config_service.get_config()
        template_type = _TEMPLATE_TYPE_BY_EVENT.get(event, TEMPLATE_BACKUP_FAILED)
        subject = _SUBJECT_BY_TEMPLATE.get(template_type, "OraInvoice backup alert")
        body = _clip(message or event, 500)

        results: list[ChannelDispatchResult] = []

        if cfg.email_enabled:
            results.append(
                await self._dispatch_recipient_channel(
                    CHANNEL_EMAIL, cfg, subject=subject, body=body
                )
            )
        if cfg.sms_enabled:
            results.append(
                await self._dispatch_recipient_channel(
                    CHANNEL_SMS, cfg, subject=subject, body=body
                )
            )
        if (cfg.webhook_url or "").strip():
            results.append(
                await self._dispatch_webhook(
                    cfg,
                    event=event,
                    success=success,
                    message=body,
                    job_id=job_id,
                    scope=scope,
                )
            )

        if not results:
            # Req 18.10 — nothing enabled; complete without dispatch, record it.
            logger.info(
                "backup notification %r: no notification channel is enabled; "
                "nothing dispatched",
                event,
            )
        return results

    # ------------------------------------------------------------------
    # Email / SMS channel dispatch with recipient resolution + retry
    # ------------------------------------------------------------------
    async def _dispatch_recipient_channel(
        self, channel: str, cfg: BackupConfig, *, subject: str, body: str
    ) -> ChannelDispatchResult:
        """Resolve recipients then dispatch on ``channel`` with retry (Req 18.9/18.11)."""
        resolution = await self._config_service.resolve_notification_recipients(
            channel, config=cfg
        )
        if resolution.delivery_failure:
            # No resolvable recipient — surface, do NOT report a success (Req 18.11).
            return ChannelDispatchResult(
                channel=channel,
                ok=False,
                detail=resolution.reason or "no recipient resolved",
                delivery_failure=True,
                source=resolution.source,
            )

        last_detail = ""
        for attempt in range(1, MAX_CHANNEL_ATTEMPTS + 1):
            try:
                if channel == CHANNEL_EMAIL:
                    ok, detail = await self._email_send(
                        resolution.recipients, subject, body
                    )
                else:
                    ok, detail = await self._sms_send(resolution.recipients, body)
            except Exception as exc:  # noqa: BLE001 - one channel's failure is isolated
                ok, detail = False, str(exc)
            if ok:
                return ChannelDispatchResult(
                    channel=channel, ok=True, detail=detail, source=resolution.source
                )
            last_detail = detail

        logger.warning(
            "backup notification channel %s failed after %d attempts: %s",
            channel,
            MAX_CHANNEL_ATTEMPTS,
            last_detail,
        )
        return ChannelDispatchResult(
            channel=channel,
            ok=False,
            detail=f"failed after {MAX_CHANNEL_ATTEMPTS} attempts: {last_detail}",
            delivery_failure=True,
            source=resolution.source,
        )

    # ------------------------------------------------------------------
    # Webhook dispatch with payload build + retry (Req 19)
    # ------------------------------------------------------------------
    async def _dispatch_webhook(
        self,
        cfg: BackupConfig,
        *,
        event: str,
        success: bool,
        message: str,
        job_id: Any = None,
        scope: str | None = None,
    ) -> ChannelDispatchResult:
        """Build the secret-free payload and POST it with retry (Req 19.6/19.7)."""
        url = (cfg.webhook_url or "").strip()
        payload = self._build_webhook_payload(
            event=event, success=success, message=message, job_id=job_id, scope=scope
        )

        last_detail = ""
        for attempt in range(1, MAX_CHANNEL_ATTEMPTS + 1):
            try:
                ok, detail = await self._webhook_send(url, payload)
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, str(exc)
            if ok:
                return ChannelDispatchResult(
                    channel=CHANNEL_WEBHOOK, ok=True, detail=detail, source="explicit"
                )
            last_detail = detail

        logger.warning(
            "backup webhook delivery failed after %d attempts: %s",
            MAX_CHANNEL_ATTEMPTS,
            last_detail,
        )
        return ChannelDispatchResult(
            channel=CHANNEL_WEBHOOK,
            ok=False,
            detail=f"failed after {MAX_CHANNEL_ATTEMPTS} attempts: {last_detail}",
            delivery_failure=True,
            source="explicit",
        )

    def _build_webhook_payload(
        self,
        *,
        event: str,
        success: bool,
        message: str,
        job_id: Any = None,
        scope: str | None = None,
    ) -> dict[str, Any]:
        """Build the Webhook_Notification JSON body (Req 19.1-19.5).

        Includes the event type, ISO-8601 UTC timestamp, job id, operation status
        (started|succeeded|failed), a 1-500 char message, and (on failure) a
        1-1000 char error description. The Backup_Scope is included for backup
        events. No secret/token/credential field is ever included (Req 19.5).
        """
        if event == EVENT_TEST:
            status = _WEBHOOK_STATUS_STARTED
        elif success:
            status = _WEBHOOK_STATUS_SUCCEEDED
        else:
            status = _WEBHOOK_STATUS_FAILED

        payload: dict[str, Any] = {
            "event_type": event,
            "timestamp": self._clock().astimezone(timezone.utc).isoformat(),
            "job_id": str(job_id) if job_id is not None else None,
            "status": status,
            "message": _clip(message, 500),
        }
        if scope is not None:
            payload["scope"] = scope
        if status == _WEBHOOK_STATUS_FAILED:
            payload["error"] = _clip(message, 1000)
        return payload

    # ------------------------------------------------------------------
    # Test dispatch (Req 18.12) — touches NO backup/restore/config/job state
    # ------------------------------------------------------------------
    async def send_test(self) -> list[dict[str, Any]]:
        """Dispatch a test message on each enabled channel; report per-channel ok.

        Resolves recipients exactly as a real event would (Req 18.11) and reports
        the per-channel success/failure so a Global_Admin can verify the alert
        path before relying on it (Req 18.12). This method only *reads* the config
        and sends — it creates no backup, restore, config, or job state.
        """
        cfg = await self._config_service.get_config()
        body = (
            "This is a test notification from OraInvoice Cloud Backup. "
            "If you received it, this alert channel is configured correctly."
        )
        subject = "OraInvoice backup notification test"
        results: list[ChannelDispatchResult] = []

        if cfg.email_enabled:
            results.append(
                await self._dispatch_recipient_channel(
                    CHANNEL_EMAIL, cfg, subject=subject, body=body
                )
            )
        if cfg.sms_enabled:
            results.append(
                await self._dispatch_recipient_channel(
                    CHANNEL_SMS, cfg, subject=subject, body=body
                )
            )
        if (cfg.webhook_url or "").strip():
            results.append(
                await self._dispatch_webhook(
                    cfg, event=EVENT_TEST, success=True, message=body
                )
            )

        return [r.to_dict() for r in results]

    # ------------------------------------------------------------------
    # Provider-disconnected wiring (Req 2.6)
    # ------------------------------------------------------------------
    def make_on_disconnected(
        self,
        *,
        provider_type: str,
        destination_id: uuid.UUID | str | None = None,
        display_name: str | None = None,
    ) -> Callable[[], Awaitable[None]]:
        """Build the adapter ``on_disconnected`` callback (Req 2.6).

        The storage adapter flips itself to ``disconnected`` and calls this
        callback **exactly once** per disconnection; the facade audits the
        disconnect and dispatches a single failure notification so scheduling can
        be halted for that provider.
        """

        async def _on_disconnected() -> None:
            label = display_name or provider_type
            logger.warning(
                "backup destination %s (%s) disconnected; dispatching failure "
                "notification (Req 2.6)",
                destination_id,
                provider_type,
            )
            await self._audit.write_completion(
                action=ACTION_PROVIDER_DISCONNECTED,
                actor_id=None,
                target_id=destination_id,
                entity_type="cloud_provider",
                outcome="disconnected",
                after_value={
                    "provider_type": provider_type,
                    "destination_id": str(destination_id)
                    if destination_id is not None
                    else None,
                },
            )
            await self.dispatch_event(
                event=EVENT_PROVIDER_DISCONNECTED,
                success=False,
                message=(
                    f"Backup storage provider {label!r} reported its credentials "
                    "were revoked and is now disconnected; backups to it are halted "
                    "until it is reconnected."
                ),
                job_id=destination_id,
            )

        return _on_disconnected


# ---------------------------------------------------------------------------
# Service facade
# ---------------------------------------------------------------------------
class BackupService:
    """Facade composing keys / pipeline / restore / prune / config / audit.

    Holds the shared :class:`AuditWriter`, :class:`BackupConfigService`, and
    :class:`BackupNotifier`, and wires the durable audit hook + the notification
    hook into a backup run. Used by the Global-Admin router (task 15.3) and by
    the scheduled-task entry points below.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        audit_writer: AuditWriter | None = None,
        config_service: BackupConfigService | None = None,
        notifier: BackupNotifier | None = None,
    ) -> None:
        self.db = db
        self.audit = audit_writer or AuditWriter()
        self.config_service = config_service or BackupConfigService(
            db, audit_writer=self.audit
        )
        self.notifier = notifier or BackupNotifier(
            db, config_service=self.config_service, audit_writer=self.audit
        )

    async def run_backup(
        self,
        *,
        scope: str,
        triggered_by: str = "manual",
        actor_id: uuid.UUID | None = None,
        job: BackupJob | None = None,
    ):
        """Run one Full_Backup, wiring the durable audit + notification hooks.

        Delegates to :func:`run_backup`, injecting :meth:`AuditWriter.audit_hook`
        (durable write-ahead → abort on failure, completion → reconcile) and
        :meth:`BackupNotifier.notify_hook` so outcome notifications dispatch over
        every enabled channel.
        """
        return await run_backup(
            self.db,
            scope=scope,
            triggered_by=triggered_by,
            actor_id=actor_id,
            job=job,
            audit_hook=self.audit.audit_hook,
            notify_hook=self.notifier.notify_hook,
        )

    async def send_test_notification(self) -> list[dict[str, Any]]:
        """Dispatch a test notification on each enabled channel (Req 18.12).

        Returns a list of ``{channel, ok, detail}`` results. Alters no backup,
        restore, configuration, or job state.
        """
        return await self.notifier.send_test()


# ---------------------------------------------------------------------------
# Scheduling helpers
# ---------------------------------------------------------------------------
def _nz_now(now: datetime | None = None) -> datetime:
    """Current time in NZ local time (the timezone the schedule cron uses)."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base.astimezone(ZoneInfo(NZ_TIMEZONE))


def _within_backup_window(cfg: BackupConfig, local_now: datetime) -> bool:
    """Whether ``local_now`` falls inside the configured Backup_Window (Req 8.2/8.3).

    No window configured ⇒ always within. A window that does not wrap past
    midnight matches ``start <= t < end``; a wrapping window (e.g. 22:00→02:00)
    matches ``t >= start or t < end``.
    """
    start = cfg.backup_window_start
    end = cfg.backup_window_end
    if start is None or end is None:
        return True
    current = local_now.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _cron_fires_at(cron_expr: str | None, local_now: datetime) -> bool:
    """Whether the NZ-local-time cron fires in the current minute (Req 8.1).

    The cron expression is matched at minute resolution against ``local_now``;
    the in-process dedupe (see :func:`run_scheduled_backup_task`) prevents a
    double-fire when the scheduler ticks more than once inside the same minute.
    """
    spec = parse_cron(cron_expr)
    if spec is None:
        return False
    # ``_cron_matches`` lives in prune.py as a private helper; re-implement the
    # minute-resolution match here to avoid importing a private symbol.
    if local_now.minute not in spec.minutes:
        return False
    if local_now.hour not in spec.hours:
        return False
    if local_now.month not in spec.months:
        return False
    cron_dow = (local_now.weekday() + 1) % 7
    dom_ok = local_now.day in spec.doms
    dow_ok = cron_dow in spec.dows
    if spec.dom_restricted and spec.dow_restricted:
        return dom_ok or dow_ok
    if spec.dom_restricted:
        return dom_ok
    if spec.dow_restricted:
        return dow_ok
    return True


async def _resolve_primary_storage(
    db: AsyncSession,
) -> tuple[BackupDestination | None, Any]:
    """Resolve the primary destination + its storage adapter for prune/GC.

    Returns ``(None, None)`` when no primary destination is configured. The
    destination config is decrypted under ``ENCRYPTION_MASTER_KEY`` and the
    adapter resolved through the provider registry.
    """
    from app.core.encryption import envelope_decrypt

    result = await db.execute(
        select(BackupDestination).where(BackupDestination.is_primary.is_(True))
    )
    primary = result.scalars().first()
    if primary is None:
        return None, None

    config: dict[str, Any] = {}
    if primary.config_encrypted:
        try:
            config = json.loads(envelope_decrypt(primary.config_encrypted).decode("utf-8"))
        except Exception:  # noqa: BLE001 - normalise to empty; resolve_adapter guards
            config = {}
    adapter = resolve_adapter(primary.provider_type, config)
    return primary, adapter


# In-process dedupe of the last NZ-local minute the scheduled backup fired in, so
# a scheduler tick landing twice inside one cron minute does not start two
# backups. Mirrors the ``last_run`` map in app/tasks/scheduled.py.
_LAST_SCHEDULED_BACKUP_MINUTE: str | None = None


# ---------------------------------------------------------------------------
# Scheduled-task entry points (registered in _DAILY_TASKS / WRITE_TASKS)
# ---------------------------------------------------------------------------
async def run_scheduled_backup_task(_now: datetime | None = None) -> dict:
    """Scheduler entry point: run a scheduled Full_Backup when due (Req 8.1/8.2/8.8).

    Registered in ``_DAILY_TASKS`` and listed in ``WRITE_TASKS`` so it runs **only
    on the primary node**. Ticking frequently, the body short-circuits unless the
    configured NZ-local cron fires in the current minute AND the current time is
    inside the Backup_Window (following the ``weekly_roster_broadcast``
    precedent). A minute-resolution in-process dedupe prevents a double-fire.

    The optional ``_now`` parameter is for tests only.
    """
    global _LAST_SCHEDULED_BACKUP_MINUTE

    try:
        async with async_session_factory() as session:
            async with session.begin():
                config_service = BackupConfigService(session)
                cfg = await config_service.get_config()

                if not (cfg.schedule_cron or "").strip():
                    return {"skipped": "no_schedule"}

                local_now = _nz_now(_now)

                if not _cron_fires_at(cfg.schedule_cron, local_now):
                    return {"skipped": "cron_no_match"}

                if not _within_backup_window(cfg, local_now):
                    return {"skipped": "outside_backup_window"}

                minute_key = local_now.strftime("%Y-%m-%dT%H:%M")
                if _LAST_SCHEDULED_BACKUP_MINUTE == minute_key:
                    return {"skipped": "already_fired_this_minute"}
                _LAST_SCHEDULED_BACKUP_MINUTE = minute_key

                scope = cfg.default_scope
                job = BackupJob(triggered_by="scheduled", scope=scope)
                session.add(job)
                await session.flush()
                await session.refresh(job)
                job_id = job.id

                service = BackupService(session)
                try:
                    result = await service.run_backup(
                        scope=scope, triggered_by="scheduled", job=job
                    )
                except (BackupScopeError, BackupPipelineError) as exc:
                    # The pipeline has already marked the job failed and dispatched
                    # a failure notification; surface a summary for the scheduler log.
                    logger.error("scheduled backup failed: %s", exc)
                    return {"status": "failed", "job_id": str(job_id), "error": str(exc)}

        logger.info(
            "scheduled backup completed: backup_id=%s scope=%s files=%s",
            result.backup_id,
            result.scope,
            result.file_count,
        )
        return {
            "status": "completed",
            "job_id": str(job_id),
            "backup_id": str(result.backup_id),
            "scope": result.scope,
            "file_count": result.file_count,
            "copies_failed": len(result.copy_failures),
        }
    except Exception as exc:  # noqa: BLE001 - never let a task crash the scheduler
        logger.exception("run_scheduled_backup_task failed: %s", exc)
        return {"error": str(exc)}


async def run_blob_gc_task() -> dict:
    """Scheduler entry point: retention prune + orphan GC on the primary (Req 8.5-8.10).

    Registered in ``_DAILY_TASKS`` and listed in ``WRITE_TASKS`` (primary-only).
    Runs the reference-counted retention prune then the mark-and-sweep orphan GC
    against the primary destination, both under the per-destination prune/GC lock
    that excludes an in-progress backup (Req 8.11).
    """
    try:
        async with async_session_factory() as session:
            async with session.begin():
                config_service = BackupConfigService(session)
                cfg = await config_service.get_config()

                primary, storage = await _resolve_primary_storage(session)
                if primary is None or storage is None:
                    return {"skipped": "no_primary_destination"}

                destination_key = str(primary.id)
                prune_outcome = await run_retention_prune(
                    session,
                    storage,
                    cfg,
                    blob_prefix=DEFAULT_BLOB_PREFIX,
                    destinations=destination_key,
                )
                orphan_outcome = await run_orphan_gc(
                    session,
                    storage,
                    cfg,
                    blob_prefix=DEFAULT_BLOB_PREFIX,
                    destinations=destination_key,
                )

        summary = {
            "status": "completed",
            "backups_pruned": len(prune_outcome.pruned_backup_ids),
            "blobs_deleted": len(prune_outcome.deleted_blob_hashes),
            "orphans_deleted": len(orphan_outcome.deleted_orphan_hashes),
        }
        logger.info("blob GC completed: %s", summary)
        return summary
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_blob_gc_task failed: %s", exc)
        return {"error": str(exc)}


async def run_rehearsal_task(_now: datetime | None = None) -> dict:
    """Scheduler entry point: run a scheduled Restore_Rehearsal when due (Req 25.4/26).

    Registered in ``_DAILY_TASKS`` and listed in ``WRITE_TASKS`` (primary-only).
    Short-circuits unless the configured NZ-local ``rehearsal_cron`` fires in the
    current minute, then restores a recent backup into an isolated scratch
    database, runs the validation checks, records the result, dispatches failure /
    RTO notifications via the notifier, and tears the scratch environment down.
    """
    from app.modules.backup_restore.keys.key_service import BackupKeyService
    from app.modules.backup_restore.models import Backup
    from app.modules.backup_restore.restore.per_org_restore import (
        StorageArtifactReader,
    )
    from app.modules.backup_restore.restore.rehearsal import (
        NoBackupAvailableError,
        PgScratchEnvironmentProvider,
        RehearsalService,
    )

    try:
        async with async_session_factory() as session:
            async with session.begin():
                config_service = BackupConfigService(session)
                cfg = await config_service.get_config()

                if not (cfg.rehearsal_cron or "").strip():
                    return {"skipped": "no_rehearsal_schedule"}

                local_now = _nz_now(_now)
                if not _cron_fires_at(cfg.rehearsal_cron, local_now):
                    return {"skipped": "cron_no_match"}

                primary, storage = await _resolve_primary_storage(session)
                if primary is None or storage is None:
                    return {"skipped": "no_primary_destination"}

                key_service = BackupKeyService(session)
                notifier = BackupNotifier(session, config_service=config_service)

                async def _reader_factory(backup: Backup):
                    if backup.key_version is not None:
                        bdk = await key_service.get_bdk(backup.key_version)
                    else:
                        _version, bdk = await key_service.get_active_bdk()
                    return StorageArtifactReader(
                        storage,
                        bdk,
                        session,
                        backup.id,
                        blob_prefix=DEFAULT_BLOB_PREFIX,
                    )

                scratch_provider = PgScratchEnvironmentProvider(settings.database_url)
                rehearsal = RehearsalService(
                    session,
                    scratch_provider=scratch_provider,
                    reader_factory=_reader_factory,
                    notify_hook=notifier.notify_hook,
                )

                try:
                    run_result = await rehearsal.run_rehearsal()
                except NoBackupAvailableError as exc:
                    return {"skipped": "no_backup_to_rehearse", "detail": str(exc)}

        logger.info(
            "restore rehearsal completed: result=%s backup_id=%s duration=%ss",
            run_result.result,
            run_result.backup_id,
            run_result.measured_duration_seconds,
        )
        return {"status": "completed", **run_result.to_dict()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_rehearsal_task failed: %s", exc)
        return {"error": str(exc)}
