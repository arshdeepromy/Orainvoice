"""Schedule / retention / RPO-RTO / notification config + multi-destination management.

This module implements ``BackupConfigService`` — the Global-Admin-facing service
behind the backup *configuration* surface (design: ``config_service.py``). It
owns three concerns:

* **Single-row backup configuration (Req 8, 25).** A single ``backup_config``
  row (like ``ha_config``) holding the NZ-timezone cron schedule, the optional
  Backup_Window, the Retention_Policy (count + days), the Recovery_Point /
  Recovery_Time objectives, the notification toggles + channel enables, the
  webhook URL, and the explicit email / SMS recipient lists.
  :meth:`BackupConfigService.update_config` validates the supplied schedule and
  objectives and **attaches an RPO warning** (it does not refuse the save) when
  the inter-backup interval cannot satisfy the configured Recovery_Point_Objective
  (Req 8.13, 25.2) — reusing the already-implemented
  :func:`validate_schedule_against_rpo` from ``backup/prune.py``.

* **Multi-destination management with exactly-one-primary (Req 30).** Several
  :class:`BackupDestination` rows may be configured at once, of which **exactly
  one** is the primary and zero or more are copy destinations (Req 30.2).
  :meth:`create_destination` / :meth:`edit_destination` envelope-encrypt the
  provider credentials under ``ENCRYPTION_MASTER_KEY`` (operational secrets, NOT
  the Backup_Data_Key hierarchy), and detect a **masked-credential save** — a
  credential field submitted as its masked placeholder is left at its existing
  ciphertext rather than re-encrypted. :meth:`set_primary` clears the previous
  primary and sets the new one in **one atomic transaction** (a savepoint),
  enforcing exactly-one-primary so the change either fully applies or leaves the
  prior designation intact (Req 30.7).

* **Notification recipient resolution (Req 18.11).** :meth:`resolve_notification_recipients`
  resolves email / SMS recipients from the explicit configured lists; WHERE no
  explicit recipient is configured for an enabled **email** channel it falls back
  to the email addresses of all ``global_admin`` users; and IF an enabled channel
  still resolves to nobody it records a per-channel **delivery failure** rather
  than reporting a successful dispatch, so alerts that resolve to nobody are
  surfaced rather than silently lost.

Per the project ``get_db_session`` ``session.begin()`` auto-commit pattern this
service uses ``flush()`` / ``await db.refresh()`` (never ``commit()``). The
encryptor/decryptor and audit writer are injectable so the logic is testable
without real encryption keys or audit I/O.

Requirements: 8.1, 8.2, 8.3, 8.4, 18.11, 25.2, 30.2, 30.7
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.auth.models import User
from app.modules.auth.rbac import GLOBAL_ADMIN
from app.modules.backup_restore.audit import (
    ACTION_BACKUP_CONFIG_CHANGED,
    AuditWriter,
)
from app.modules.backup_restore.backup.prune import (
    RpoValidationResult,
    parse_cron,
    validate_schedule_against_rpo,
)
from app.modules.backup_restore.models import (
    BACKUP_SCOPES,
    RESIDENCY_VALUES,
    BackupConfig,
    BackupDestination,
)
from app.modules.backup_restore.residency import (
    DestinationNotFoundError,
    derive_residency,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Notification channels (Req 18)
# ---------------------------------------------------------------------------
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
CHANNEL_WEBHOOK = "webhook"

#: Recipient-resolution sources reported by :meth:`resolve_notification_recipients`.
SOURCE_EXPLICIT = "explicit"
SOURCE_GLOBAL_ADMIN_FALLBACK = "global_admin_fallback"
SOURCE_NONE = "none"

#: Audit action recorded for a destination create / edit / set-primary change.
ACTION_DESTINATION_CHANGED = "backup_config.destination_changed"

# ---------------------------------------------------------------------------
# Credential masking (security-hardening checklist; design "sk_****1234" pattern)
# ---------------------------------------------------------------------------
#: The sentinel embedded in every masked credential. A real secret never
#: contains it, so its presence in a submitted value unambiguously marks that
#: value as a masked placeholder that must NOT be re-encrypted (the existing
#: ciphertext is kept instead).
MASK_SENTINEL = "****"

#: Config keys that carry a provider secret. These are the fields masked in
#: responses and subject to masked-credential save detection on edit. Mirrors
#: the credential fields read by the storage adapters (``s3.py``, ``nas.py``,
#: ``google_drive.py``, ``onedrive.py``).
CREDENTIAL_FIELDS: frozenset[str] = frozenset(
    {
        # S3 / S3-compatible (Req 28.4)
        "access_key_id",
        "secret_access_key",
        "session_token",
        # NAS / SMB (Req 29.4)
        "username",
        "password",
        # OAuth cloud drives (Req 2.4)
        "refresh_token",
        "access_token",
        "client_secret",
        "client_id",
    }
)

#: Config keys an edit may update directly (non-secret provider settings). The
#: ``is_primary`` designation is deliberately excluded — it is changed only via
#: :meth:`set_primary` (Req 30.7).
EDITABLE_CONFIG_FIELDS: frozenset[str] = frozenset(
    {
        # S3
        "bucket",
        "region",
        "endpoint_url",
        "addressing_style",
        "verify_tls",
        "part_size",
        # NAS
        "share_path",
        "access_mode",
        "target_dir",
        # OAuth drives
        "folder_path",
        "chunk_size",
        # residency declaration (non-secret)
        "residency",
        "data_residency",
        "onshore",
        "country",
        "location",
    }
)

#: Single-row ``backup_config`` columns an update may set (Req 8, 18, 25).
_UPDATABLE_CONFIG_COLUMNS: frozenset[str] = frozenset(
    {
        "schedule_cron",
        "backup_window_start",
        "backup_window_end",
        "retention_count",
        "retention_days",
        "default_scope",
        "rpo_seconds",
        "rto_seconds",
        "notify_backup_failure",
        "notify_backup_success",
        "notify_restore_failure",
        "notify_restore_success",
        "webhook_url",
        "sms_enabled",
        "email_enabled",
        "notification_emails",
        "notification_sms_numbers",
        "orphan_gc_grace_hours",
        "perorg_export_size_cap_bytes",
        "rehearsal_cron",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ConfigValidationError(ValueError):
    """Raised when a configuration update is rejected as invalid.

    Distinct from an RPO *warning*, which never refuses the save (Req 25.2):
    this is a hard validation failure (e.g. a non-positive RPO/RTO, an invalid
    cron expression, or an unknown scope) that leaves the configuration
    unchanged.
    """


class PrimaryDestinationError(Exception):
    """Raised when a change would violate the exactly-one-primary invariant (Req 30.7).

    The atomic transaction is rolled back so the prior primary designation
    remains intact.
    """


# ---------------------------------------------------------------------------
# Injectable config encrypt/decrypt (operational secrets under ENCRYPTION_MASTER_KEY)
# ---------------------------------------------------------------------------
ConfigEncryptor = Callable[[Mapping[str, Any]], bytes]
ConfigDecryptor = Callable[[bytes | None], dict[str, Any]]


def _default_encrypt_config(config: Mapping[str, Any]) -> bytes:
    """Envelope-encrypt a destination config dict under ``ENCRYPTION_MASTER_KEY``.

    These are operational secrets that live on the running deployment (the same
    protection as OAuth tokens, Req 2.4 / 28.4 / 29.4) — deliberately NOT the
    escrowed Backup_Data_Key hierarchy used for backup artifacts.
    """
    return envelope_encrypt(json.dumps(dict(config), default=str))


def _default_decrypt_config(blob: bytes | None) -> dict[str, Any]:
    """Decrypt a destination's ``config_encrypted`` blob into a config dict."""
    if not blob:
        return {}
    try:
        decoded = json.loads(envelope_decrypt_str(blob))
    except (ValueError, TypeError) as exc:  # malformed / legacy config
        logger.warning("Could not decode destination config: %s", exc)
        return {}
    return decoded if isinstance(decoded, dict) else {}


# ---------------------------------------------------------------------------
# Masking helpers
# ---------------------------------------------------------------------------
def mask_secret(value: Any) -> str:
    """Mask a single credential value (design ``sk_****1234`` pattern).

    Keeps a short head + the last four characters so a Global_Admin can
    recognise which credential is stored without exposing it; a short value is
    masked entirely. The result always contains :data:`MASK_SENTINEL`.
    """
    if value in (None, ""):
        return MASK_SENTINEL
    text = str(value)
    if len(text) <= 4:
        return MASK_SENTINEL
    return f"{text[:2]}{MASK_SENTINEL}{text[-4:]}"


def is_masked_value(value: Any) -> bool:
    """Return ``True`` when ``value`` is a masked placeholder, not a real secret.

    A real secret never contains :data:`MASK_SENTINEL`, so its presence
    unambiguously marks a submitted value as the masked credential round-tripped
    back from a response — which must be left unchanged on save.
    """
    return isinstance(value, str) and MASK_SENTINEL in value


def mask_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of a destination config with every credential field masked.

    Used to build responses so credentials are never returned in clear (the
    security-hardening checklist). Non-credential fields pass through unchanged.
    """
    masked: dict[str, Any] = {}
    for key, value in config.items():
        masked[key] = mask_secret(value) if key in CREDENTIAL_FIELDS else value
    return masked


# ---------------------------------------------------------------------------
# Result value objects
# ---------------------------------------------------------------------------
@dataclass
class ConfigUpdateResult:
    """Outcome of an :meth:`BackupConfigService.update_config` call (Req 25.2).

    ``rpo_validation`` carries the schedule-vs-RPO evaluation; ``warnings`` holds
    every human-readable warning to surface to the Global_Admin *after* the save
    (the RPO warning never blocks the save — Req 8.13 / 25.2).
    """

    config: BackupConfig
    rpo_validation: RpoValidationResult
    warnings: list[str] = field(default_factory=list)


@dataclass
class RecipientResolution:
    """Resolved recipients for one notification channel (Req 18.11).

    ``delivery_failure`` is ``True`` when an enabled channel resolved to no
    recipient — the caller records that per-channel delivery failure rather than
    reporting a successful dispatch.
    """

    channel: str
    recipients: list[str]
    source: str
    delivery_failure: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class BackupConfigService:
    """Backup configuration + multi-destination management (Req 8, 18, 25, 30)."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        encrypt_config: ConfigEncryptor | None = None,
        decrypt_config: ConfigDecryptor | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self._db = db
        self._encrypt_config = encrypt_config or _default_encrypt_config
        self._decrypt_config = decrypt_config or _default_decrypt_config
        self._audit = audit_writer or AuditWriter()

    # ==================================================================
    # Single-row backup configuration (Req 8, 25)
    # ==================================================================
    async def get_config(self) -> BackupConfig:
        """Return the single ``backup_config`` row, creating it with defaults if absent.

        The configuration is a single global row (like ``ha_config``); the column
        ``server_default``s supply the documented sensible defaults (24 h RPO,
        4 h RTO, etc. — Req 25.1) on first creation.
        """
        result = await self._db.execute(select(BackupConfig).limit(1))
        config = result.scalars().first()
        if config is not None:
            return config

        config = BackupConfig()
        self._db.add(config)
        await self._db.flush()
        await self._db.refresh(config)
        return config

    async def update_config(
        self,
        updates: Mapping[str, Any],
        *,
        actor_id: uuid.UUID | str | None = None,
        now: datetime | None = None,
    ) -> ConfigUpdateResult:
        """Apply a configuration update, validate it, and attach an RPO warning.

        Validates the cron schedule syntax, the scope, and that the
        Recovery_Point / Recovery_Time objectives are positive durations
        (:class:`ConfigValidationError` on failure, leaving the config
        unchanged). On success it persists the change, stamps
        ``rpo_rto_changed_at`` when either objective changed (Req 25.3), and
        evaluates the schedule against the RPO — attaching a warning when the
        inter-backup interval cannot meet it (Req 8.13 / 25.2) **without**
        refusing the save.
        """
        config = await self.get_config()

        applied = self._validate_updates(updates, config)

        objectives_changed = (
            "rpo_seconds" in applied
            and applied["rpo_seconds"] != config.rpo_seconds
        ) or (
            "rto_seconds" in applied
            and applied["rto_seconds"] != config.rto_seconds
        )

        for column, value in applied.items():
            setattr(config, column, value)

        if objectives_changed:
            config.rpo_rto_changed_at = now or datetime.now(timezone.utc)

        await self._db.flush()
        await self._db.refresh(config)

        # Evaluate the schedule against the RPO and surface (not block) a warning
        # (Req 8.13 / 25.2) — reuse the validator already implemented in prune.py.
        rpo_validation = validate_schedule_against_rpo(config, now=now)
        warnings: list[str] = []
        if rpo_validation.warning:
            warnings.append(rpo_validation.warning)

        await self._audit.write_completion(
            action=ACTION_BACKUP_CONFIG_CHANGED,
            actor_id=actor_id,
            target_id=config.id,
            entity_type="backup_config",
            outcome="updated",
            after_value={
                "changed_fields": sorted(applied.keys()),
                "rpo_satisfied": rpo_validation.satisfied,
            },
        )

        return ConfigUpdateResult(
            config=config, rpo_validation=rpo_validation, warnings=warnings
        )

    def _validate_updates(
        self, updates: Mapping[str, Any], config: BackupConfig
    ) -> dict[str, Any]:
        """Validate + coerce an update dict to the columns it may set.

        Raises :class:`ConfigValidationError` for an unknown scope, an invalid
        cron expression, a non-positive RPO/RTO, or negative retention values.
        Unknown keys are ignored so the caller can pass a wider payload.
        """
        applied: dict[str, Any] = {}
        for key, value in updates.items():
            if key not in _UPDATABLE_CONFIG_COLUMNS:
                continue
            applied[key] = value

        # Cron syntax (Req 8.1) — empty/None clears the schedule.
        for cron_key in ("schedule_cron", "rehearsal_cron"):
            if cron_key in applied:
                cron_value = applied[cron_key]
                if cron_value not in (None, "") and parse_cron(cron_value) is None:
                    raise ConfigValidationError(
                        f"{cron_key} is not a valid 5-field cron expression: "
                        f"{cron_value!r}"
                    )

        # Backup scope (Req 8 default_scope).
        if "default_scope" in applied and applied["default_scope"] not in BACKUP_SCOPES:
            raise ConfigValidationError(
                f"default_scope must be one of {sorted(BACKUP_SCOPES)}"
            )

        # RPO / RTO must be positive durations (Req 25.1 / 25.2).
        for objective in ("rpo_seconds", "rto_seconds"):
            if objective in applied:
                seconds = applied[objective]
                if not isinstance(seconds, int) or isinstance(seconds, bool):
                    raise ConfigValidationError(f"{objective} must be an integer")
                if seconds <= 0:
                    raise ConfigValidationError(
                        f"{objective} must be a positive number of seconds"
                    )

        # Retention values must be non-negative when set (Req 8.4).
        for retention in ("retention_count", "retention_days", "orphan_gc_grace_hours"):
            if retention in applied and applied[retention] is not None:
                count = applied[retention]
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ConfigValidationError(
                        f"{retention} must be a non-negative integer"
                    )

        # Recipient lists must be lists of strings (Req 18.11).
        for list_key in ("notification_emails", "notification_sms_numbers"):
            if list_key in applied:
                applied[list_key] = self._coerce_recipient_list(list_key, applied[list_key])

        # Backup window endpoints must both be present or both absent (Req 8.2/8.3).
        self._validate_backup_window(applied, config)

        return applied

    @staticmethod
    def _coerce_recipient_list(key: str, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            raise ConfigValidationError(f"{key} must be a list")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned

    @staticmethod
    def _validate_backup_window(
        applied: dict[str, Any], config: BackupConfig
    ) -> None:
        """A Backup_Window needs both a start and an end, or neither (Req 8.2/8.3)."""
        if "backup_window_start" not in applied and "backup_window_end" not in applied:
            return
        start = applied.get("backup_window_start", config.backup_window_start)
        end = applied.get("backup_window_end", config.backup_window_end)
        if (start is None) != (end is None):
            raise ConfigValidationError(
                "A backup window requires both a start and an end time (or neither)."
            )
        if isinstance(start, time) and isinstance(end, time) and start == end:
            raise ConfigValidationError(
                "Backup window start and end must differ."
            )

    # ==================================================================
    # Multi-destination management (Req 30)
    # ==================================================================
    async def list_destinations(self) -> list[BackupDestination]:
        """All configured destinations, primary first then by creation order."""
        result = await self._db.execute(
            select(BackupDestination).order_by(
                BackupDestination.is_primary.desc(),
                BackupDestination.created_at.asc(),
            )
        )
        return list(result.scalars().all())

    async def create_destination(
        self,
        *,
        provider_type: str,
        display_name: str,
        config: Mapping[str, Any] | None = None,
        residency: str | None = None,
        is_immutable_copy: bool = False,
        lock_window_days: int | None = None,
        actor_id: uuid.UUID | str | None = None,
    ) -> BackupDestination:
        """Create a destination, envelope-encrypting its credentials.

        The credential config is encrypted under ``ENCRYPTION_MASTER_KEY``
        (operational secrets — Req 2.4 / 28.4 / 29.4). The **first** destination
        configured is designated the primary so the exactly-one-primary invariant
        holds from the moment any destination exists (Req 30.2); subsequent
        destinations are copy destinations.
        """
        cfg = dict(config or {})
        resolved_residency = (residency or derive_residency(provider_type, cfg)).strip().lower()
        if resolved_residency not in RESIDENCY_VALUES:
            resolved_residency = "unknown"

        existing = await self.list_destinations()
        is_primary = len(existing) == 0

        destination = BackupDestination(
            provider_type=provider_type,
            display_name=display_name,
            is_primary=is_primary,
            is_immutable_copy=is_immutable_copy,
            residency=resolved_residency,
            lock_window_days=lock_window_days,
            config_encrypted=self._encrypt_config(cfg) if cfg else None,
            updated_by=_coerce_uuid(actor_id),
        )
        self._db.add(destination)
        await self._db.flush()
        await self._db.refresh(destination)

        await self._audit_destination(destination, actor_id, outcome="created")
        return destination

    async def edit_destination(
        self,
        destination_id: uuid.UUID | str,
        updates: Mapping[str, Any],
        *,
        actor_id: uuid.UUID | str | None = None,
    ) -> BackupDestination:
        """Edit a destination's config, preserving masked credentials.

        Updates the display name, the immutable-copy flag, and the non-secret
        provider settings (S3 endpoint/region/addressing, NAS path/mode, etc.).
        Credential fields are merged with **masked-credential detection**: a
        credential submitted as its masked placeholder (:func:`is_masked_value`)
        keeps the existing ciphertext rather than being re-encrypted, so saving a
        form that round-tripped a masked secret never destroys the stored
        credential. Never changes ``is_primary`` — that is :meth:`set_primary`'s
        job (Req 30.7).
        """
        destination = await self._get_destination(destination_id)

        if "display_name" in updates and updates["display_name"]:
            destination.display_name = str(updates["display_name"])
        if "is_immutable_copy" in updates:
            destination.is_immutable_copy = bool(updates["is_immutable_copy"])
        if "lock_window_days" in updates:
            destination.lock_window_days = updates["lock_window_days"]

        incoming_config = updates.get("config")
        if isinstance(incoming_config, Mapping):
            merged = self._merge_destination_config(destination, incoming_config)
            destination.config_encrypted = self._encrypt_config(merged)
            # Re-derive residency from the (non-secret) merged config unless the
            # operator pinned it explicitly in this edit.
            if "residency" not in incoming_config and "data_residency" not in incoming_config:
                destination.residency = derive_residency(
                    destination.provider_type, merged
                )

        destination.updated_by = _coerce_uuid(actor_id)
        await self._db.flush()
        await self._db.refresh(destination)

        await self._audit_destination(destination, actor_id, outcome="edited")
        return destination

    def _merge_destination_config(
        self, destination: BackupDestination, incoming: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Merge an incoming config over the stored one with masked-credential detection.

        Starts from the existing decrypted config so untouched fields are
        preserved. A credential field whose submitted value is a masked
        placeholder is dropped from the update (the existing ciphertext value is
        kept); a credential submitted with a real value replaces it. Non-secret
        editable fields are applied directly.
        """
        existing = self._decrypt_config(destination.config_encrypted)
        merged = dict(existing)

        for key, value in incoming.items():
            if key in CREDENTIAL_FIELDS:
                # Masked placeholder → keep the existing stored credential
                # (do not overwrite with the mask). A real value replaces it.
                if is_masked_value(value):
                    continue
                merged[key] = value
            elif key in EDITABLE_CONFIG_FIELDS:
                merged[key] = value
            # Unknown keys are ignored so a wider payload is tolerated.

        return merged

    async def set_primary(
        self,
        destination_id: uuid.UUID | str,
        *,
        actor_id: uuid.UUID | str | None = None,
    ) -> list[BackupDestination]:
        """Designate a destination as the primary, atomically (Req 30.2 / 30.7).

        Clears the previous primary and sets the new one in **one atomic
        transaction** (a savepoint): every destination's ``is_primary`` is set in
        a single flush, then the exactly-one-primary invariant is asserted. If the
        invariant does not hold (or anything raises), the savepoint rolls back so
        the prior designation is left intact — the change either fully applies or
        not at all. Returns the refreshed destination list with updated badges.
        """
        target = await self._get_destination(destination_id)

        # One atomic transaction: clear the prior primary and set the new one
        # together, enforcing exactly-one-primary (Req 30.7).
        async with self._db.begin_nested():
            destinations = await self.list_destinations()
            for dest in destinations:
                dest.is_primary = dest.id == target.id
                if dest.id == target.id:
                    dest.updated_by = _coerce_uuid(actor_id)
            await self._db.flush()

            primaries = [d for d in destinations if d.is_primary]
            if len(primaries) != 1 or primaries[0].id != target.id:
                # Rolls back the savepoint → prior designation intact.
                raise PrimaryDestinationError(
                    "Setting the primary destination must leave exactly one "
                    f"primary; found {len(primaries)}."
                )

        await self._db.refresh(target)
        await self._audit_destination(target, actor_id, outcome="set_primary")
        return await self.list_destinations()

    # ==================================================================
    # Notification recipient resolution (Req 18.11)
    # ==================================================================
    async def resolve_notification_recipients(
        self, channel: str, *, config: BackupConfig | None = None
    ) -> RecipientResolution:
        """Resolve recipients for a notification channel (Req 18.11).

        * **email** — the explicit ``notification_emails`` list; else fall back to
          the email addresses of all ``global_admin`` users; else a delivery
          failure.
        * **sms** — the explicit ``notification_sms_numbers`` list; else a
          delivery failure (SMS has no global-admin fallback).
        * **webhook** — the configured ``webhook_url``; else a delivery failure.

        An enabled channel resolving to nobody yields ``delivery_failure=True``
        (and is logged) so alerts that resolve to no recipient are surfaced rather
        than silently lost.
        """
        cfg = config or await self.get_config()
        normalised = channel.strip().lower()

        if normalised == CHANNEL_EMAIL:
            return await self._resolve_email_recipients(cfg)
        if normalised == CHANNEL_SMS:
            return self._resolve_sms_recipients(cfg)
        if normalised == CHANNEL_WEBHOOK:
            return self._resolve_webhook_recipients(cfg)

        raise ValueError(f"Unknown notification channel: {channel!r}")

    async def _resolve_email_recipients(
        self, cfg: BackupConfig
    ) -> RecipientResolution:
        explicit = [str(e).strip() for e in (cfg.notification_emails or []) if str(e).strip()]
        if explicit:
            return RecipientResolution(
                channel=CHANNEL_EMAIL,
                recipients=explicit,
                source=SOURCE_EXPLICIT,
                delivery_failure=False,
            )

        # Fall back to all global_admin user emails (Req 18.11).
        fallback = await self._global_admin_emails()
        if fallback:
            return RecipientResolution(
                channel=CHANNEL_EMAIL,
                recipients=fallback,
                source=SOURCE_GLOBAL_ADMIN_FALLBACK,
                delivery_failure=False,
            )

        return self._delivery_failure(
            CHANNEL_EMAIL,
            "No explicit notification email address is configured and no "
            "global_admin email could be resolved.",
        )

    def _resolve_sms_recipients(self, cfg: BackupConfig) -> RecipientResolution:
        explicit = [
            str(n).strip() for n in (cfg.notification_sms_numbers or []) if str(n).strip()
        ]
        if explicit:
            return RecipientResolution(
                channel=CHANNEL_SMS,
                recipients=explicit,
                source=SOURCE_EXPLICIT,
                delivery_failure=False,
            )
        return self._delivery_failure(
            CHANNEL_SMS,
            "No explicit notification SMS number is configured (SMS has no "
            "global_admin fallback).",
        )

    def _resolve_webhook_recipients(self, cfg: BackupConfig) -> RecipientResolution:
        url = (cfg.webhook_url or "").strip()
        if url:
            return RecipientResolution(
                channel=CHANNEL_WEBHOOK,
                recipients=[url],
                source=SOURCE_EXPLICIT,
                delivery_failure=False,
            )
        return self._delivery_failure(
            CHANNEL_WEBHOOK, "No webhook URL is configured."
        )

    def _delivery_failure(self, channel: str, reason: str) -> RecipientResolution:
        """Build (and log) a per-channel delivery-failure resolution (Req 18.11)."""
        logger.warning(
            "notification channel %s resolved to no recipient: %s", channel, reason
        )
        return RecipientResolution(
            channel=channel,
            recipients=[],
            source=SOURCE_NONE,
            delivery_failure=True,
            reason=reason,
        )

    async def _global_admin_emails(self) -> list[str]:
        """Email addresses of all ``global_admin`` users (Req 18.11 fallback)."""
        result = await self._db.execute(
            select(User.email).where(User.role == GLOBAL_ADMIN)
        )
        return [email for email in result.scalars().all() if email]

    # ==================================================================
    # Internal helpers
    # ==================================================================
    async def _get_destination(
        self, destination_id: uuid.UUID | str
    ) -> BackupDestination:
        result = await self._db.execute(
            select(BackupDestination).where(BackupDestination.id == destination_id)
        )
        destination = result.scalars().first()
        if destination is None:
            raise DestinationNotFoundError(destination_id)
        return destination

    async def _audit_destination(
        self,
        destination: BackupDestination,
        actor_id: uuid.UUID | str | None,
        *,
        outcome: str,
    ) -> None:
        """Write a completion audit entry for a destination change (no secrets)."""
        await self._audit.write_completion(
            action=ACTION_DESTINATION_CHANGED,
            actor_id=actor_id,
            target_id=destination.id,
            entity_type="backup_config",
            outcome=outcome,
            after_value={
                "destination_id": str(destination.id),
                "provider_type": destination.provider_type,
                "display_name": destination.display_name,
                "is_primary": destination.is_primary,
                "is_immutable_copy": destination.is_immutable_copy,
                "residency": destination.residency,
            },
        )


def _coerce_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    """Coerce a uuid-or-str into a ``uuid.UUID`` (``updated_by`` is typed UUID)."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
