"""Migrate legacy ``integration_configs[smtp]`` row into ``email_providers``.

Phase 8b of the email-provider-unification spec (task 8.1). Carries the
admin's existing SMTP/Brevo/SendGrid configuration — captured by the
legacy "Admin → Integrations → SMTP" form before Phase 7 turned that
endpoint into HTTP 410 Gone — into the new multi-provider
``email_providers`` table that the unified sender
(``app/integrations/email_sender.py``) reads at runtime.

Provider mapping (matches the runtime mirror in
``import_integration_settings`` and Phase 8b runbook)::

    legacy ``provider`` field  →  ``email_providers.provider_key``
    ──────────────────────────    ─────────────────────────────────
    "brevo"                    →  "brevo"
    "sendgrid"                 →  "sendgrid"
    "smtp"                     →  "custom_smtp"

Credential shape per provider_key (matches the unified sender's
expectations in ``app/integrations/email_sender.py::_dispatch_*``)::

    REST providers (brevo, sendgrid):  {"api_key": "<key>"}
    SMTP providers (custom_smtp):      {"username": "...", "password": "..."}

Concurrency
-----------

This migration touches the same ``email_providers.credentials_encrypted``
column that ``app/cli/rotate_keys.py`` re-encrypts during a master-key
rotation. Both processes acquire the same PG advisory lock,
``pg_advisory_lock(hashtext('email_provider_rotate'))``, so they
serialise. ``lock_timeout`` is set to 60 seconds before acquiring the
lock so a live ``rotate_keys.py`` run aborts the migration cleanly
rather than hanging the deploy. The lock is released in a ``finally``
block so a crash inside the migration body still frees it.

No-clobber rule
---------------

Only ``email_providers`` rows whose ``credentials_set=false`` are
updated. If the admin already saved credentials for a given provider
through the new UI, the legacy row's content is **not** copied over
that fresh configuration. This makes the migration safe to re-run and
safe to apply on environments where Phase 8b's GUI cutover has already
been used to populate one of the email_providers rows directly.

Failure handling
----------------

Decryption of the legacy ``config_encrypted`` blob can fail when the
master key has been rotated since the row was written and the rotation
missed the legacy table (rare, but possible). When that happens this
migration:

* logs the error with full context (revision id + provider_key context),
* leaves both ``integration_configs[smtp]`` and ``email_providers``
  unchanged,
* emits an operator advisory the deploy log will surface, and
* **CONTINUES** the broader Alembic upgrade — a corrupted legacy row
  must never block subsequent unrelated migrations from applying.

The 5-minute "recent write" guard is a hard abort: if someone wrote to
the legacy row inside the maintenance window we'd risk losing their
change, so we bail with a clear retry message.

HA replication
--------------

This migration only updates existing rows in two tables that are already
members of ``ora_publication`` (``integration_configs`` from migration
0001, ``email_providers`` from migration 0065). Logical replication
streams ``UPDATE`` events automatically, so no ``_HA_ADD_TPL`` snippet
is required.

Revision ID: 0198
Revises: 0197
Create Date: 2026-05-27
"""

from __future__ import annotations

import json
import logging
from typing import Any

from alembic import op
import sqlalchemy as sa

from app.core.encryption import envelope_decrypt_str, envelope_encrypt


revision: str = "0198"
down_revision: str = "0197"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


logger = logging.getLogger("alembic.runtime.migration.0198")


# Map legacy ``integration_configs[smtp].config['provider']`` value onto
# the matching ``email_providers.provider_key``. Mirrors the same map in
# ``app/modules/admin/service.py::import_integration_settings``.
_LEGACY_PROVIDER_MAP: dict[str, str] = {
    "brevo": "brevo",
    "sendgrid": "sendgrid",
    "smtp": "custom_smtp",
}

# Reverse mapping for the downgrade path. ``custom_smtp`` rolls back to
# the generic ``smtp`` legacy provider value.
_REVERSE_PROVIDER_MAP: dict[str, str] = {v: k for k, v in _LEGACY_PROVIDER_MAP.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acquire_advisory_lock(bind: Any) -> None:
    """Acquire the ``email_provider_rotate`` advisory lock.

    Sets ``lock_timeout`` to 60 seconds **before** the
    ``pg_advisory_lock`` call so the acquisition itself respects the
    timeout. On timeout PG raises ``LockNotAvailable`` (SQLSTATE 55P03);
    SQLAlchemy 2.0 + asyncpg surfaces that as a generic
    ``sa.exc.DBAPIError`` (not the narrower ``OperationalError`` the
    psycopg sync driver maps it to), so we catch the broader class and
    re-raise as a ``RuntimeError`` with the documented message from the
    design doc.
    """
    bind.execute(sa.text("SET LOCAL lock_timeout = '60s'"))
    try:
        bind.execute(sa.text("SELECT pg_advisory_lock(hashtext('email_provider_rotate'))"))
    except sa.exc.DBAPIError as exc:
        raise RuntimeError(
            "Could not acquire email_provider_rotate advisory lock. "
            "Is rotate_keys.py running? Wait for it to finish, then retry."
        ) from exc


def _release_advisory_lock(bind: Any) -> None:
    """Release the advisory lock. Safe to call even if acquisition failed.

    A failed ``pg_advisory_unlock`` (lock not held) returns ``false`` in
    PG rather than raising, so calling this in a ``finally`` block is
    safe regardless of acquisition state.
    """
    try:
        bind.execute(sa.text("SELECT pg_advisory_unlock(hashtext('email_provider_rotate'))"))
    except Exception:  # noqa: BLE001 — best-effort cleanup
        # Don't mask the real exception that may already be in flight.
        logger.warning("Failed to release email_provider_rotate advisory lock", exc_info=True)


def _build_credentials(provider_key: str, legacy_config: dict) -> dict | None:
    """Build the ``credentials_encrypted`` plaintext for a target provider_key.

    Returns ``None`` when the legacy row carries no usable credentials
    (e.g. partially-redacted backup); the caller should skip the migration
    in that case rather than store empty credentials.
    """
    if provider_key in ("brevo", "sendgrid"):
        api_key = legacy_config.get("api_key") or ""
        if not api_key:
            return None
        return {"api_key": api_key}

    # custom_smtp (and any future SMTP-only mapping)
    username = legacy_config.get("username") or ""
    password = legacy_config.get("password") or ""
    if not (username or password):
        return None
    return {"username": username, "password": password}


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()

    _acquire_advisory_lock(bind)
    try:
        # ── 1. Read the legacy SMTP row ──────────────────────────────────
        legacy_row = bind.execute(
            sa.text(
                "SELECT config_encrypted, updated_at "
                "FROM integration_configs WHERE name = 'smtp'"
            )
        ).first()

        if legacy_row is None:
            # Nothing to migrate — fresh environment or already cleaned up.
            logger.info(
                "0198: no integration_configs[smtp] row found; "
                "nothing to migrate, continuing"
            )
            return

        config_encrypted: bytes | None = legacy_row[0]
        legacy_updated_at = legacy_row[1]

        if not config_encrypted:
            logger.info(
                "0198: integration_configs[smtp] has empty config_encrypted; "
                "nothing to migrate"
            )
            return

        # ── 2. Recent-write guard ────────────────────────────────────────
        # If someone touched the legacy row inside the last 5 minutes, the
        # safest action is to abort: we'd risk overwriting an in-progress
        # admin change, or racing the very GUI flow we're trying to
        # supersede.
        recent_write = bind.execute(
            sa.text(
                "SELECT updated_at > now() - interval '5 minutes' "
                "FROM integration_configs WHERE name = 'smtp'"
            )
        ).scalar()
        if recent_write:
            raise RuntimeError(
                "Recent write to integration_configs[smtp] detected. "
                "Reschedule maintenance window."
            )

        # ── 3. Decrypt the legacy blob ──────────────────────────────────
        # Decryption failure is treated as a soft error: log + advise +
        # continue. A corrupted/un-decryptable legacy row must NOT block
        # the broader Alembic upgrade (other migrations downstream are
        # unrelated and need to apply cleanly).
        try:
            decrypted = envelope_decrypt_str(config_encrypted)
            legacy_config: dict = json.loads(decrypted)
        except Exception as exc:  # noqa: BLE001 — decryption may raise anything
            logger.error(
                "0198: failed to decrypt integration_configs[smtp].config_encrypted: %s. "
                "Leaving both integration_configs and email_providers unchanged. "
                "OPERATOR ADVISORY: rotate_keys.py may have left this row stale; "
                "re-encrypt it (or have the admin re-save SMTP credentials via the "
                "old UI before its 410 cutover) and re-run this migration. "
                "Continuing with the rest of the Alembic upgrade.",
                exc,
            )
            return

        if not isinstance(legacy_config, dict):
            logger.error(
                "0198: integration_configs[smtp] decrypted to a non-dict (%s); "
                "skipping migration and continuing.",
                type(legacy_config).__name__,
            )
            return

        legacy_provider = legacy_config.get("provider")
        target_provider_key = _LEGACY_PROVIDER_MAP.get(legacy_provider) if legacy_provider else None
        if not target_provider_key:
            logger.warning(
                "0198: integration_configs[smtp].config has unknown provider %r; "
                "expected one of %s. Skipping migration.",
                legacy_provider,
                sorted(_LEGACY_PROVIDER_MAP.keys()),
            )
            return

        # ── 4. Build credentials for the target provider_key ────────────
        credentials = _build_credentials(target_provider_key, legacy_config)
        if credentials is None:
            logger.warning(
                "0198: legacy SMTP row has no usable credentials for provider_key=%s; "
                "skipping migration (the row was likely redacted during a backup).",
                target_provider_key,
            )
            return

        # ── 5. Look up the target email_providers row ───────────────────
        target_row = bind.execute(
            sa.text(
                "SELECT id, credentials_set FROM email_providers "
                "WHERE provider_key = :pk"
            ),
            {"pk": target_provider_key},
        ).first()

        if target_row is None:
            logger.warning(
                "0198: email_providers row for provider_key=%s not found; "
                "the seed data in 0065 should have created it. Skipping migration.",
                target_provider_key,
            )
            return

        target_id, target_credentials_set = target_row
        if target_credentials_set:
            # No-clobber: admin already configured this provider through
            # the new UI. Leave their fresh configuration alone.
            logger.info(
                "0198: email_providers[%s] already has credentials_set=true; "
                "no-clobber rule applied, skipping legacy import.",
                target_provider_key,
            )
            return

        # ── 6. Re-encrypt and write into email_providers ────────────────
        encrypted_credentials = envelope_encrypt(json.dumps(credentials))

        new_config = {
            "from_email": legacy_config.get("from_email", "") or "",
            "from_name": legacy_config.get("from_name", "") or "",
            "reply_to": legacy_config.get("reply_to", "") or "",
        }

        # Preserve smtp_host / smtp_port / smtp_encryption when the legacy
        # row carried explicit values; otherwise leave the existing column
        # value (which for seed rows is the default-host table from 0065).
        # We only update fields the admin actually set in the legacy form
        # so we don't accidentally NULL a sensible default.
        update_kwargs: dict = {
            "id": target_id,
            "credentials_encrypted": encrypted_credentials,
            "config": json.dumps(new_config),
        }
        update_setters = [
            "credentials_encrypted = :credentials_encrypted",
            "credentials_set = true",
            "is_active = true",
            "priority = 1",
            "config = CAST(:config AS jsonb)",
            "updated_at = now()",
        ]
        if legacy_config.get("host"):
            update_setters.append("smtp_host = :smtp_host")
            update_kwargs["smtp_host"] = legacy_config["host"]
        if legacy_config.get("port"):
            update_setters.append("smtp_port = :smtp_port")
            update_kwargs["smtp_port"] = int(legacy_config["port"])
        if legacy_config.get("encryption"):
            update_setters.append("smtp_encryption = :smtp_encryption")
            update_kwargs["smtp_encryption"] = legacy_config["encryption"]

        bind.execute(
            sa.text(
                "UPDATE email_providers SET "
                + ", ".join(update_setters)
                + " WHERE id = :id"
            ),
            update_kwargs,
        )

        logger.info(
            "0198: migrated integration_configs[smtp] (provider=%s, last updated_at=%s) "
            "into email_providers[%s] (credentials_set=true, is_active=true, priority=1).",
            legacy_provider,
            legacy_updated_at,
            target_provider_key,
        )

    finally:
        _release_advisory_lock(bind)


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Re-encrypt ``email_providers.credentials_encrypted`` back into
    ``integration_configs[smtp].config_encrypted``.

    The reverse migration is best-effort: it picks the highest-priority
    active provider whose ``provider_key`` reverse-maps to a legacy
    value and rebuilds the legacy ``{provider, api_key | username,
    password, host, port, from_email, from_name, reply_to}`` shape from
    its decrypted credentials and config. If no such row exists the
    downgrade is a no-op (matching the upgrade's symmetric "nothing
    to migrate" path).

    A decryption failure during downgrade is logged and swallowed so a
    stale ``email_providers`` row does not block ``alembic downgrade``.
    """
    bind = op.get_bind()

    _acquire_advisory_lock(bind)
    try:
        # Pick the highest-priority active provider whose key reverse-maps.
        # Order matches the unified sender's failover chain
        # (priority ASC, then provider_key ASC for stable tiebreaks).
        active_rows = bind.execute(
            sa.text(
                "SELECT provider_key, credentials_encrypted, config, "
                "smtp_host, smtp_port, smtp_encryption "
                "FROM email_providers "
                "WHERE is_active = true AND credentials_set = true "
                "ORDER BY priority ASC, provider_key ASC"
            )
        ).all()

        chosen = None
        for row in active_rows:
            provider_key = row[0]
            if provider_key in _REVERSE_PROVIDER_MAP:
                chosen = row
                break

        if chosen is None:
            logger.info(
                "0198 downgrade: no active email_providers row maps back to a "
                "legacy provider; leaving integration_configs[smtp] unchanged."
            )
            return

        (
            provider_key,
            credentials_encrypted,
            config,
            smtp_host,
            smtp_port,
            smtp_encryption,
        ) = chosen

        try:
            credentials = json.loads(envelope_decrypt_str(credentials_encrypted))
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "0198 downgrade: failed to decrypt email_providers[%s].credentials_encrypted: %s. "
                "Leaving integration_configs[smtp] unchanged and continuing.",
                provider_key,
                exc,
            )
            return

        legacy_provider = _REVERSE_PROVIDER_MAP[provider_key]

        # Reconstruct the legacy config shape. Empty strings for missing
        # credential fields mirror the shape the legacy save_smtp_config
        # endpoint wrote (and that import_integration_settings's mirror
        # block reads) so a subsequent re-upgrade round-trips cleanly.
        legacy_config: dict = {
            "provider": legacy_provider,
            "api_key": credentials.get("api_key", "") if provider_key in ("brevo", "sendgrid") else "",
            "username": credentials.get("username", "") if provider_key == "custom_smtp" else "",
            "password": credentials.get("password", "") if provider_key == "custom_smtp" else "",
            "host": smtp_host or "",
            "port": smtp_port or 587,
            "from_email": (config or {}).get("from_email", "") if isinstance(config, dict) else "",
            "from_name": (config or {}).get("from_name", "") if isinstance(config, dict) else "",
            "reply_to": (config or {}).get("reply_to", "") if isinstance(config, dict) else "",
        }
        if smtp_encryption:
            legacy_config["encryption"] = smtp_encryption

        encrypted_blob = envelope_encrypt(json.dumps(legacy_config))

        # UPSERT into integration_configs[smtp]. ``name`` is uniquely
        # constrained so ON CONFLICT lets the downgrade work whether the
        # legacy row was deleted between upgrade and downgrade or kept.
        bind.execute(
            sa.text(
                "INSERT INTO integration_configs (name, config_encrypted, is_verified) "
                "VALUES ('smtp', :blob, false) "
                "ON CONFLICT (name) DO UPDATE SET "
                "config_encrypted = EXCLUDED.config_encrypted, "
                "updated_at = now()"
            ),
            {"blob": encrypted_blob},
        )

        logger.info(
            "0198 downgrade: re-encrypted email_providers[%s] back into "
            "integration_configs[smtp] (legacy provider=%s).",
            provider_key,
            legacy_provider,
        )

    finally:
        _release_advisory_lock(bind)
