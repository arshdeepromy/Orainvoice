"""Write-ahead + completion audit writer for backup/restore (Req 1.5, 1.6, 17).

``AuditWriter`` records every backup, restore, configuration, and provider
connect/disconnect action into the existing append-only ``audit_log`` table
(``app/modules/admin/models.py::AuditLog``) — no new table is introduced
(design: "audit_log is reused as-is"). It implements the durable write-ahead
pattern required by Requirement 17:

* :meth:`write_ahead` — durably records a *start* entry (actor, action type,
  target id, UTC start timestamp) **before** the operation applies any change.
  If the durable write fails it raises :class:`AuditWriteAheadError` so the
  caller aborts before any change (Req 17.6, 17.7).
* :meth:`write_completion` — records the *completion* entry after the operation
  finishes. A completion-write failure NEVER undoes the completed operation;
  instead the record is queued for asynchronous retry and the operation is
  flagged for reconciliation (Req 17.8). This method never raises.
* :meth:`audit_rejected_attempt` — records a rejected authorisation attempt with
  the requesting user id, or an unauthenticated indicator when no valid token is
  present (Req 1.6). Never raises (a rejected request must still return its
  403/401 even if the audit write fails).

Secrets — OAuth/S3/NAS credentials, tokens, passphrases, API keys — are excluded
from every audit field, including ``before_value`` / ``after_value`` (Req 17.5,
2.8): :func:`scrub_secrets` redacts any secret-looking key before it is written.

Durability approach
-------------------
The request-scoped session yielded by ``get_db_session`` runs inside a single
``session.begin()`` block that auto-commits only when the request ends, and
services are required to use ``flush()`` (never ``commit()``) inside that block.
A write-ahead row flushed into that same transaction is **not** durable: if the
backup/restore operation later fails and the request transaction rolls back, the
write-ahead row would roll back with it — losing the very record that proves the
operation was attempted. That defeats Req 17.6/17.7.

So a durable audit write is performed in its **own short-lived session** obtained
from ``async_session_factory`` and committed immediately, independently of the
caller's transaction. The ``audit_log`` table is a platform/global table (nullable
``org_id``, no RLS), so this independent session writes it directly. The
independent commit means the write-ahead entry survives even if the operation it
guards is subsequently rolled back, and the completion entry is equally durable.
The project "use flush() not commit()" rule governs the *request* session; an
independent session committing its own transaction does not violate it.

Requirements: 1.5, 1.6, 17.5, 17.6, 17.7, 17.8
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import _set_rls_org_id, async_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action / phase constants (Req 17.1-17.4)
# ---------------------------------------------------------------------------
#: Backup lifecycle.
ACTION_BACKUP_CREATED = "backup.created"
ACTION_BACKUP_DELETED = "backup.deleted"
#: Restore lifecycle — triggered and completed are separate entries (Req 17.4).
ACTION_RESTORE_TRIGGERED = "restore.triggered"
ACTION_RESTORE_COMPLETED = "restore.completed"
#: Provider connect / disconnect (Req 17.1).
ACTION_PROVIDER_CONNECTED = "cloud_provider.connected"
ACTION_PROVIDER_DISCONNECTED = "cloud_provider.disconnected"
#: Configuration change (Req 17.2).
ACTION_BACKUP_CONFIG_CHANGED = "backup_config.changed"
ACTION_RESTORE_CONFIG_CHANGED = "restore_config.changed"

#: Pipeline ``audit_hook`` phase values (see :meth:`AuditWriter.audit_hook`).
PHASE_WRITE_AHEAD = "write_ahead"
PHASE_COMPLETION = "completion"

#: Stored in ``user_id`` for an unauthenticated rejected attempt — the column is
#: a nullable UUID, so the human-readable indicator lives in ``after_value``.
UNAUTHENTICATED_INDICATOR = "unauthenticated"

# A clock is any zero-arg callable returning a timezone-aware UTC datetime.
Clock = Callable[[], datetime]
#: A factory yielding a fresh, independent ``AsyncSession`` (an async context
#: manager). Defaults to ``async_session_factory``; injectable for tests.
SessionFactory = Callable[[], Any]
#: Enqueue hook for completion records that failed to persist (Req 17.8).
RetryEnqueue = Callable[["PendingCompletionAudit"], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# Secret scrubbing (Req 17.5, 2.8)
# ---------------------------------------------------------------------------
#: Substrings that mark a field name as carrying a secret. Matched
#: case-insensitively against each key in a before/after value dict.
_SECRET_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "passphrase",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "access_key",
    "secret_key",
    "private_key",
    "client_secret",
    "refresh_token",
    "access_token",
    "session_token",
    "recovery_kit",
    "wrapped_bmk",
    "wrapped_bdk",
    "kcv",
    "salt",
    # "authorization" (e.g. an Authorization header value) — deliberately NOT a
    # bare "auth" so legitimate non-secret fields like "auth_status"/"author"
    # are not clobbered. OAuth tokens are already caught by *_token patterns.
    "authorization",
)

_SECRET_KEY_RE = re.compile("|".join(re.escape(p) for p in _SECRET_KEY_PATTERNS), re.IGNORECASE)

#: Placeholder written in place of a redacted secret value.
REDACTED = "***REDACTED***"


def _is_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key))


def scrub_secrets(value: Any) -> Any:
    """Recursively redact secret-looking fields from an audit value (Req 17.5).

    Any mapping key whose name matches a secret pattern (token, secret,
    password, passphrase, credential, api key, …) has its value replaced with
    :data:`REDACTED`. Nested dicts and lists are scrubbed recursively so a
    secret buried inside an ``after_value`` cannot leak into the audit trail.
    Non-mapping scalars pass through unchanged.
    """
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                scrubbed[key] = REDACTED
            else:
                scrubbed[key] = scrub_secrets(item)
        return scrubbed
    if isinstance(value, (list, tuple)):
        return [scrub_secrets(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Errors and queued-retry record
# ---------------------------------------------------------------------------

class AuditWriteAheadError(Exception):
    """Raised when the durable write-ahead audit entry cannot be recorded.

    The caller MUST abort the operation before applying any change and return an
    error indicating the operation could not be audited (Req 17.7).
    """

    def __init__(self, action: str, cause: Exception) -> None:
        self.action = action
        self.cause = cause
        super().__init__(
            f"write-ahead audit entry for {action!r} could not be durably recorded: {cause}"
        )


@dataclass
class PendingCompletionAudit:
    """A completion audit entry that failed to persist and awaits retry (Req 17.8)."""

    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    user_id: uuid.UUID | None
    before_value: dict[str, Any] | None
    after_value: dict[str, Any] | None
    queued_at: datetime
    attempts: int = 1
    last_error: str | None = None


@dataclass
class _RetryQueue:
    """In-process queue of completion records pending reconciliation (Req 17.8).

    The writer flags a failed completion here and logs at ERROR so an operator /
    the reconciliation sweep can replay it. Held process-wide so a single
    deployment surfaces every unreconciled completion regardless of which writer
    instance failed.
    """

    pending: list[PendingCompletionAudit] = field(default_factory=list)

    def enqueue(self, record: PendingCompletionAudit) -> None:
        self.pending.append(record)

    def drain(self) -> list[PendingCompletionAudit]:
        items = list(self.pending)
        self.pending.clear()
        return items


#: Process-wide retry queue for failed completion audits (Req 17.8).
COMPLETION_RETRY_QUEUE = _RetryQueue()


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _entity_type_for(action: str, override: str | None) -> str:
    """Derive the audit ``entity_type`` from the action (e.g. ``backup.created``
    → ``backup``), unless an explicit override is supplied.

    The dotted action prefixes map exactly to the entity types mandated by
    Req 17.1-17.4: ``cloud_provider``, ``backup_config``, ``restore_config``,
    ``backup``, ``restore``.
    """
    if override:
        return override
    return action.split(".", 1)[0] if "." in action else action


class AuditWriter:
    """Durable write-ahead / completion audit writer over ``audit_log`` (Req 17).

    Every durable write runs in its own short-lived session (see the module
    docstring "Durability approach") so the entry persists independently of the
    caller's request transaction. The session factory and clock are injectable
    so the durability and timestamp behaviour are testable without real I/O.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        clock: Clock | None = None,
        retry_enqueue: RetryEnqueue | None = None,
    ) -> None:
        self._session_factory = session_factory or async_session_factory
        self._clock = clock or _default_clock
        self._retry_enqueue = retry_enqueue or self._default_retry_enqueue

    # ------------------------------------------------------------------
    # Durable write-ahead (Req 17.6, 17.7)
    # ------------------------------------------------------------------
    async def write_ahead(
        self,
        *,
        action: str,
        actor_id: uuid.UUID | str | None,
        target_id: uuid.UUID | str | None = None,
        entity_type: str | None = None,
        before_value: dict[str, Any] | None = None,
        after_value: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Durably record the write-ahead (start) audit entry (Req 17.6).

        Captures the actor, action type, target id, and a UTC start timestamp,
        and commits in an independent transaction so the record survives a later
        rollback of the guarded operation. Returns the new audit entry id.

        Raises:
            AuditWriteAheadError: the entry could not be durably recorded — the
                caller MUST abort before applying any change (Req 17.7).
        """
        payload = dict(after_value or {})
        payload.setdefault("phase", PHASE_WRITE_AHEAD)
        payload.setdefault("started_at", self._clock().isoformat())
        try:
            return await self._write_durable(
                action=action,
                entity_type=_entity_type_for(action, entity_type),
                entity_id=_coerce_uuid(target_id),
                user_id=_coerce_uuid(actor_id),
                before_value=before_value,
                after_value=payload,
            )
        except Exception as exc:  # noqa: BLE001 - any failure must abort the op
            logger.error(
                "write-ahead audit for %s (target=%s) failed; aborting operation: %s",
                action,
                target_id,
                exc,
            )
            raise AuditWriteAheadError(action, exc) from exc

    # ------------------------------------------------------------------
    # Durable completion (Req 17.8)
    # ------------------------------------------------------------------
    async def write_completion(
        self,
        *,
        action: str,
        actor_id: uuid.UUID | str | None,
        target_id: uuid.UUID | str | None = None,
        entity_type: str | None = None,
        outcome: str | None = None,
        before_value: dict[str, Any] | None = None,
        after_value: dict[str, Any] | None = None,
    ) -> uuid.UUID | None:
        """Record the completion audit entry (Req 17.6); never undo on failure.

        On success returns the new audit entry id. If the durable write fails,
        the completed operation is **not** rolled back: the record is queued for
        asynchronous retry and flagged for reconciliation, and ``None`` is
        returned (Req 17.8). This method never raises.
        """
        payload = dict(after_value or {})
        payload.setdefault("phase", PHASE_COMPLETION)
        payload.setdefault("completed_at", self._clock().isoformat())
        if outcome is not None:
            payload.setdefault("outcome", outcome)

        resolved_entity = _entity_type_for(action, entity_type)
        resolved_user = _coerce_uuid(actor_id)
        resolved_target = _coerce_uuid(target_id)
        scrubbed_before = scrub_secrets(before_value) if before_value is not None else None
        scrubbed_after = scrub_secrets(payload)
        try:
            return await self._write_durable(
                action=action,
                entity_type=resolved_entity,
                entity_id=resolved_target,
                user_id=resolved_user,
                before_value=before_value,
                after_value=payload,
            )
        except Exception as exc:  # noqa: BLE001 - never undo a completed op
            record = PendingCompletionAudit(
                action=action,
                entity_type=resolved_entity,
                entity_id=resolved_target,
                user_id=resolved_user,
                before_value=scrubbed_before,
                after_value=scrubbed_after,
                queued_at=self._clock(),
                last_error=str(exc),
            )
            logger.error(
                "completion audit for %s (target=%s) failed AFTER the operation "
                "completed; NOT undoing — queued for reconciliation: %s",
                action,
                target_id,
                exc,
            )
            await self._enqueue_retry(record)
            return None

    # ------------------------------------------------------------------
    # Rejected-attempt audit (Req 1.6)
    # ------------------------------------------------------------------
    async def audit_rejected_attempt(
        self,
        *,
        action: str,
        actor_id: uuid.UUID | str | None,
        entity_type: str | None = None,
        ip_address: str | None = None,
        device_info: str | None = None,
    ) -> uuid.UUID | None:
        """Record a rejected authorisation attempt (Req 1.6).

        Populates the requesting user id when a valid token is present, or marks
        the attempt as unauthenticated when no valid token was supplied
        (``actor_id is None``). Captures the attempted action type and a UTC
        timestamp. Never raises — a rejected request must still return its
        403/401 even if the audit write fails; a failure is logged.
        """
        resolved_user = _coerce_uuid(actor_id)
        after_value: dict[str, Any] = {
            "outcome": "rejected",
            "reason": "global_admin_authorisation_failed",
        }
        if resolved_user is None:
            after_value["auth_status"] = UNAUTHENTICATED_INDICATOR
        try:
            return await self._write_durable(
                action=action,
                entity_type=_entity_type_for(action, entity_type),
                entity_id=None,
                user_id=resolved_user,
                before_value=None,
                after_value=after_value,
                ip_address=ip_address,
                device_info=device_info,
            )
        except Exception as exc:  # noqa: BLE001 - rejection must still return
            logger.error(
                "rejected-attempt audit for %s failed (the request is still "
                "rejected): %s",
                action,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Pipeline audit_hook adapter
    # ------------------------------------------------------------------
    async def audit_hook(
        self,
        *,
        phase: str,
        action: str,
        target_id: uuid.UUID | str | None = None,
        actor_id: uuid.UUID | str | None = None,
        scope: str | None = None,
        outcome: str | None = None,
        entity_type: str | None = None,
        **extra: Any,
    ) -> None:
        """Adapter matching ``backup/pipeline.py``'s injectable ``audit_hook``.

        The pipeline calls this with ``phase="write_ahead"`` before any work and
        ``phase="completion"`` after success. The write-ahead phase propagates a
        failure as :class:`AuditWriteAheadError` so the pipeline aborts before
        any change (Req 17.7); the completion phase swallows failures and queues
        a retry (Req 17.8).
        """
        after: dict[str, Any] = {}
        if scope is not None:
            after["scope"] = scope
        # Fold any extra context (scrubbed) so provider details never leak.
        for key, val in extra.items():
            after[key] = val

        if phase == PHASE_WRITE_AHEAD:
            await self.write_ahead(
                action=action,
                actor_id=actor_id,
                target_id=target_id,
                entity_type=entity_type,
                after_value=after or None,
            )
        elif phase == PHASE_COMPLETION:
            await self.write_completion(
                action=action,
                actor_id=actor_id,
                target_id=target_id,
                entity_type=entity_type,
                outcome=outcome,
                after_value=after or None,
            )
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown audit phase: {phase!r}")

    # ------------------------------------------------------------------
    # Reconciliation (Req 17.8)
    # ------------------------------------------------------------------
    async def retry_pending(self) -> int:
        """Attempt to persist queued completion records; return the count retried.

        Records that still fail are re-queued with an incremented attempt count
        so a later sweep can try again. Intended to be driven by the scheduled
        reconciliation task.
        """
        drained = COMPLETION_RETRY_QUEUE.drain()
        retried = 0
        for record in drained:
            try:
                await self._write_durable(
                    action=record.action,
                    entity_type=record.entity_type,
                    entity_id=record.entity_id,
                    user_id=record.user_id,
                    before_value=record.before_value,
                    after_value=record.after_value,
                )
                retried += 1
            except Exception as exc:  # noqa: BLE001 - keep flagged for next sweep
                record.attempts += 1
                record.last_error = str(exc)
                COMPLETION_RETRY_QUEUE.enqueue(record)
                logger.error(
                    "completion-audit reconciliation retry %d for %s still failing: %s",
                    record.attempts,
                    record.action,
                    exc,
                )
        return retried

    # ------------------------------------------------------------------
    # Internal durable write
    # ------------------------------------------------------------------
    async def _write_durable(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        before_value: dict[str, Any] | None,
        after_value: dict[str, Any] | None,
        ip_address: str | None = None,
        device_info: str | None = None,
    ) -> uuid.UUID:
        """Insert one audit row in an independent, immediately-committed session.

        Secrets are scrubbed from ``before_value`` / ``after_value`` immediately
        before the write (Req 17.5). The independent commit is what makes the
        entry durable regardless of the caller's transaction outcome.
        """
        scrubbed_before = scrub_secrets(before_value) if before_value is not None else None
        scrubbed_after = scrub_secrets(after_value) if after_value is not None else None

        async with self._session_factory() as session:  # type: AsyncSession
            async with session.begin():
                # audit_log is a global table (nullable org_id, no RLS); reset the
                # GUC so the independent session writes it as a global-admin action.
                await _set_rls_org_id(session, None)
                entry_id = await write_audit_log(
                    session=session,
                    action=action,
                    entity_type=entity_type,
                    org_id=None,
                    user_id=user_id,
                    entity_id=entity_id,
                    before_value=scrubbed_before,
                    after_value=scrubbed_after,
                    ip_address=ip_address,
                    device_info=device_info,
                )
        return entry_id

    async def _enqueue_retry(self, record: PendingCompletionAudit) -> None:
        result = self._retry_enqueue(record)
        if isinstance(result, Awaitable):
            await result

    @staticmethod
    def _default_retry_enqueue(record: PendingCompletionAudit) -> None:
        COMPLETION_RETRY_QUEUE.enqueue(record)
