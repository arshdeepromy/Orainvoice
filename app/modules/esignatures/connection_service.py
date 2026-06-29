"""Per-organisation Documenso connection service.

This is the service layer for the per-organisation ``esign_org_connections``
record (one row per org). It mirrors the app's existing **per-org
accounting/Xero connection** storage pattern — **not** the single global
``integration_configs`` row — and is intentionally a *fresh* module: it does
**NOT** extend ``app/modules/admin/service.py``'s ``valid_names`` /
``_SAFE_FIELDS`` / ``_MASKED_FIELDS`` (those applied only to the removed single
global ``integration_configs[documenso]`` row and no longer apply under the
per-org Documenso Teams model).

Responsibilities (R1, R19):

* :func:`save_connection` — upsert an org's Documenso connection. ``base_url``
  and ``documenso_team_id`` are stored as-is; ``service_token`` and
  ``webhook_signing_secret`` are **envelope-encrypted** (writes use
  ``envelope_encrypt``; reads use ``envelope_decrypt_str`` — note
  ``envelope_encrypt_str`` does **not** exist). OraInvoice **generates** the
  opaque ``webhook_routing_id`` on first create (it is never entered by the
  admin). Saving back a value that matches the masked representation
  (``_MASK_PATTERN``) **retains** the previously stored secret rather than
  overwriting it with the mask (R1.4, R1.5). Any save **clears** ``is_verified``
  until a subsequent connection test succeeds (R19.5). The per-org connection
  cache is invalidated on every save, and a credential-free Audit_Log entry is
  written (R1.7).
* :func:`test_connection` — perform an authenticated request against the org's
  own Documenso Team using its team-scoped token, set ``is_verified`` from the
  result (R1.6, R19.2), and return a humanized "configure first" error when the
  org has no connection row (R1.10).

Secrets are **never** returned in plaintext (R15.3); responses carry only
``*_last4`` masked projections.

Refs: requirements 1.1, 1.2, 1.3, 1.5, 1.7, 1.8, 15.1, 19.2, 19.5;
design §"Per-org connection config and lifecycle".
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import write_audit_log
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.integrations.documenso import (
    DocumensoApiError,
    DocumensoClient,
    DocumensoConnection,
    DocumensoNotConfiguredError,
    invalidate_documenso_connection_cache,
)
from app.integrations.documenso_provisioning import (
    ProvisioningError,
    _load_platform_secret,
    get_provisioning_adapter,
)
from app.modules.admin.models import Organisation
from app.modules.esignatures.errors import (
    CODE_AUTO_PROVISION_FAILED,
    CODE_AUTO_PROVISION_UNAVAILABLE,
    esign_error,
    humanize_esign_error,
)
from app.modules.esignatures.models import EsignOrgConnection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Masking — the GUI surfaces secrets as masked strings (e.g. ``****`` or
# ``ab****``). If the client echoes a masked value back on save, we must NOT
# overwrite the real stored secret with the mask. This is the same heuristic
# used by ``save_carjam_config`` in ``app/modules/admin/service.py`` (kept here
# as a fresh, per-org copy rather than reaching into the admin service).
# ---------------------------------------------------------------------------

_MASK_PATTERN = re.compile(r"^\*+$|^.{0,4}\*{4,}$")

#: Number of trailing characters surfaced in a ``*_last4`` masked projection.
_LAST4 = 4


def _is_masked(value: str) -> bool:
    """Return ``True`` when ``value`` looks like a masked placeholder echo."""
    return bool(_MASK_PATTERN.match(value))


def _last4(value: str | None) -> str:
    """Return the last 4 characters of a secret for a masked projection.

    Never returns the full plaintext (R15.3). Short values (< 4 chars) are
    returned verbatim, matching the existing CarJam/Stripe ``*_last4`` contract.
    """
    if not value:
        return ""
    return value[-_LAST4:] if len(value) >= _LAST4 else value


def _last4_from_blob(blob: bytes | None) -> str:
    """Decrypt an envelope-encrypted secret column and return its last 4 chars.

    Decryption happens only to compute the masked ``*_last4`` projection; the
    full plaintext is never returned to the caller.
    """
    if not blob:
        return ""
    try:
        return _last4(envelope_decrypt_str(blob))
    except Exception:  # noqa: BLE001 - never leak/raise on a masking helper
        return ""


def _generate_routing_id() -> str:
    """Generate an opaque, URL-safe, unique per-org webhook routing identifier.

    Embedded in the org's registered Documenso callback URL
    (``/api/v2/esign/webhook/{routing_id}``). It is not a secret by itself; it
    only attributes inbound webhooks to the right org before the per-org
    webhook secret is verified.
    """
    return secrets.token_urlsafe(32)


def _masked_connection(row: EsignOrgConnection) -> dict[str, Any]:
    """Build the masked, plaintext-free projection of a connection row.

    Secrets are surfaced only as ``service_token_last4`` / ``webhook_secret_last4``
    (R1.4, R15.3). ``base_url``, ``documenso_team_id``, ``webhook_routing_id`` and
    ``is_verified`` are non-secret and returned as-is.
    """
    return {
        "id": row.id,
        "org_id": row.org_id,
        "base_url": row.base_url,
        "documenso_team_id": row.documenso_team_id,
        "webhook_routing_id": row.webhook_routing_id,
        "is_verified": row.is_verified,
        "service_token_last4": _last4_from_blob(row.service_token_encrypted),
        "webhook_secret_last4": _last4_from_blob(row.webhook_secret_encrypted),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _load_row(
    db: AsyncSession, org_id: uuid.UUID | str
) -> EsignOrgConnection | None:
    """Load the org's ``esign_org_connections`` row (org-scoped under RLS)."""
    key = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))
    result = await db.execute(
        select(EsignOrgConnection).where(EsignOrgConnection.org_id == key)
    )
    return result.scalar_one_or_none()


async def save_connection(
    db: AsyncSession,
    org_id: uuid.UUID | str,
    *,
    base_url: str | None = None,
    documenso_team_id: str | None = None,
    service_token: str | None = None,
    webhook_signing_secret: str | None = None,
    updated_by: uuid.UUID | str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Upsert the organisation's Documenso connection.

    ``base_url`` and ``documenso_team_id`` are stored as-is. ``service_token``
    and ``webhook_signing_secret`` are envelope-encrypted; a value matching the
    masked representation (``_MASK_PATTERN``) is **skipped**, retaining the
    previously stored secret (R1.5). On first create the opaque
    ``webhook_routing_id`` is generated (R1.1). Any save clears ``is_verified``
    (R19.5), invalidates the per-org connection cache, and writes a
    credential-free audit entry (R1.7).

    Args:
        db: Async session whose RLS context is scoped to ``org_id``.
        org_id: Target organisation.
        base_url: Documenso base URL (required when creating a new connection).
        documenso_team_id: The org's Documenso Team id (R1.8).
        service_token: Team-scoped Documenso API token (plaintext or a masked
            echo to retain the stored value).
        webhook_signing_secret: Per-org webhook secret (plaintext or masked echo).
        updated_by: Acting Global Admin user id (audit attribution).
        ip_address: Client IP for the audit entry.

    Returns:
        The masked connection projection (never plaintext secrets).

    Raises:
        ValueError: When creating a new connection without a ``base_url``.
    """
    key = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))

    row = await _load_row(db, key)
    is_create = row is None

    if is_create:
        if not base_url:
            raise ValueError(
                "A Documenso base URL is required to create the connection."
            )
        row = EsignOrgConnection(
            org_id=key,
            base_url=base_url,
            webhook_routing_id=_generate_routing_id(),
            created_by=uuid.UUID(str(updated_by)) if updated_by else None,
        )
        db.add(row)

    # Non-secret fields are stored as-is when provided.
    if base_url is not None:
        row.base_url = base_url
    if documenso_team_id is not None:
        row.documenso_team_id = documenso_team_id

    # Secrets: skip a masked echo (retain stored value), else envelope-encrypt.
    if service_token is not None and not _is_masked(service_token):
        row.service_token_encrypted = envelope_encrypt(service_token)
    if webhook_signing_secret is not None and not _is_masked(webhook_signing_secret):
        row.webhook_secret_encrypted = envelope_encrypt(webhook_signing_secret)

    # Any create/update clears verification until a fresh test succeeds (R19.5).
    row.is_verified = False

    await db.flush()
    await db.refresh(row)

    # The org's decrypted connection may be cached — drop it so the next load
    # re-reads the freshly-saved row (R1.3).
    invalidate_documenso_connection_cache(key)

    # Audit WITHOUT plaintext credentials (R1.7) — only masked last-4 forms.
    await write_audit_log(
        session=db,
        org_id=key,
        user_id=uuid.UUID(str(updated_by)) if updated_by else None,
        action="esign.connection_updated",
        entity_type="esign_org_connection",
        entity_id=row.id,
        after_value={
            "base_url": row.base_url,
            "documenso_team_id": row.documenso_team_id,
            "webhook_routing_id": row.webhook_routing_id,
            "is_verified": row.is_verified,
            "service_token_last4": _last4_from_blob(row.service_token_encrypted),
            "webhook_secret_last4": _last4_from_blob(row.webhook_secret_encrypted),
            "created": is_create,
        },
        ip_address=ip_address,
    )

    return _masked_connection(row)


async def test_connection(
    db: AsyncSession,
    org_id: uuid.UUID | str,
    *,
    tested_by: uuid.UUID | str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Test the org's Documenso connection and set ``is_verified`` accordingly.

    Performs an authenticated request against **that org's** Documenso Team
    using its team-scoped token (R1.6) and sets ``is_verified`` from the result
    (R19.2). A definitive credential rejection (HTTP 401/403) or a server-side
    failure marks the connection unverified rather than raising, so the flag is
    always persisted to reflect the latest test.

    Args:
        db: Async session whose RLS context is scoped to ``org_id``.
        org_id: Target organisation.
        tested_by: Acting Global Admin user id (audit attribution).
        ip_address: Client IP for the audit entry.

    Returns:
        ``{"is_verified": bool, "valid": bool}`` reporting whether the org's
        credentials are valid.

    Raises:
        DocumensoNotConfiguredError: When the org has no connection row — the
            humanized "configure the connection first" error (R1.10).
    """
    row = await _load_row(db, org_id)
    if row is None:
        # R1.10 — reject the test before any Documenso call when unconfigured.
        raise DocumensoNotConfiguredError(
            "Configure this organisation's Documenso connection before testing it."
        )

    service_token = (
        envelope_decrypt_str(row.service_token_encrypted)
        if row.service_token_encrypted
        else ""
    )
    webhook_secret = (
        envelope_decrypt_str(row.webhook_secret_encrypted)
        if row.webhook_secret_encrypted
        else ""
    )
    conn = DocumensoConnection(
        base_url=row.base_url,
        service_token=service_token,
        webhook_secret=webhook_secret,
        documenso_team_id=row.documenso_team_id,
        webhook_routing_id=row.webhook_routing_id,
        is_verified=row.is_verified,
    )

    try:
        async with httpx.AsyncClient() as http:
            client = DocumensoClient.for_org(conn, http)
            valid = await client.test_connection()
    except DocumensoApiError:
        # A transient/server-side failure is not a successful verification.
        valid = False

    row.is_verified = valid
    await db.flush()
    await db.refresh(row)

    invalidate_documenso_connection_cache(org_id)

    await write_audit_log(
        session=db,
        org_id=row.org_id,
        user_id=uuid.UUID(str(tested_by)) if tested_by else None,
        action="esign.connection_tested",
        entity_type="esign_org_connection",
        entity_id=row.id,
        after_value={
            "documenso_team_id": row.documenso_team_id,
            "webhook_routing_id": row.webhook_routing_id,
            "is_verified": row.is_verified,
            "valid": valid,
        },
        ip_address=ip_address,
    )

    return {"is_verified": valid, "valid": valid}


# ---------------------------------------------------------------------------
# Optional best-effort auto-provisioning orchestration (R20)
# ---------------------------------------------------------------------------
#
# Base-URL choice (documented decision): the org's connection ``base_url`` is
# the shared self-hosted Documenso instance URL. There is no dedicated per-org
# REST base configured at provisioning time, so we derive it from the
# platform-level ``ESIGN_DOCUMENSO_ADMIN_URL`` (the same Documenso instance the
# tRPC adapter talks to), decrypted via the platform-secret loader. When that
# is not configured (e.g. ``db`` mode without an admin URL) the connection is
# still created with the artefacts that succeed and an empty ``base_url`` that a
# Global Admin completes manually — never a broken state (R20.3/R20.4).
#
# The webhook routing URL is ``{frontend_base_url}/api/v2/esign/webhook/{id}``;
# ``frontend_base_url`` is the public origin that fronts the API in each
# environment.


def _provision_base_url() -> str:
    """Resolve the shared Documenso instance base URL for the org connection.

    Derived from the platform-level ``esign_documenso_admin_url`` (decrypted if
    supplied envelope-encrypted). Returns ``""`` when not configured, in which
    case the connection is still created for manual completion of ``base_url``.
    """
    try:
        return (_load_platform_secret(settings.esign_documenso_admin_url) or "").rstrip(
            "/"
        )
    except Exception:  # noqa: BLE001 - never let secret resolution break provisioning
        return ""


def _webhook_url(routing_id: str) -> str:
    """Build the org's public Documenso webhook callback URL."""
    base = (settings.frontend_base_url or "").rstrip("/")
    return f"{base}/api/v2/esign/webhook/{routing_id}"


async def _load_org(db: AsyncSession, org_id: uuid.UUID) -> Organisation | None:
    """Load the Organisation row used to name the org's Documenso Team."""
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    return result.scalar_one_or_none()


async def _audit_auto_provision(
    db: AsyncSession,
    row: EsignOrgConnection,
    *,
    requested_by: uuid.UUID | str | None,
    ip_address: str | None,
    outcome: str,
) -> None:
    """Write a credential-free audit entry for an auto-provision run (R1.7)."""
    await write_audit_log(
        session=db,
        org_id=row.org_id,
        user_id=uuid.UUID(str(requested_by)) if requested_by else None,
        action="esign.connection_auto_provisioned",
        entity_type="esign_org_connection",
        entity_id=row.id,
        after_value={
            "outcome": outcome,
            "base_url": row.base_url,
            "documenso_team_id": row.documenso_team_id,
            "webhook_routing_id": row.webhook_routing_id,
            "is_verified": row.is_verified,
            "service_token_last4": _last4_from_blob(row.service_token_encrypted),
            "webhook_secret_last4": _last4_from_blob(row.webhook_secret_encrypted),
        },
        ip_address=ip_address,
    )


def _provision_result(
    *,
    status: str,
    row: EsignOrgConnection | None,
    webhook_url: str | None,
    error: str | None,
    code: str | None,
    is_verified: bool | None = None,
) -> dict[str, Any]:
    """Shape the auto-provision result (masked connection + status + error)."""
    return {
        "status": status,
        "connection": _masked_connection(row) if row is not None else None,
        "webhook_url": webhook_url,
        "is_verified": is_verified,
        "error": error,
        "code": code,
    }


async def auto_provision_connection(
    db: AsyncSession,
    org_id: uuid.UUID | str,
    *,
    requested_by: uuid.UUID | str | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Best-effort auto-provision an org's Documenso Team, token, and webhook.

    Orchestrates the optional :class:`ProvisioningAdapter` to create the org's
    Documenso Team, mint its team-scoped token, and register its webhook
    subscription, then persists the connection (token + webhook secret
    envelope-encrypted) and runs the connection test to set ``is_verified``
    (R20.1, R20.2).

    The flow is **idempotent / re-runnable** and persists progress at each step
    so a failure is always recoverable by manual completion: an existing
    ``documenso_team_id`` / ``webhook_routing_id`` / webhook secret is reused
    rather than duplicated, and every successfully-created artefact is persisted
    before the next step is attempted. **Any** failure (a
    :class:`ProvisioningError` or anything else) is caught and surfaced as a
    humanized result; partial progress is preserved and the manual per-org
    connection path is never corrupted or blocked (R20.3, R20.4). Raw adapter
    internals are never raised or returned.

    When auto-provisioning is disabled (``ESIGN_PROVISIONING_MODE=off`` →
    :func:`get_provisioning_adapter` returns ``None``) this returns a humanized
    "auto-provisioning unavailable" result and the manual path remains intact
    (R20.5).

    Args:
        db: Async session whose RLS context is scoped to ``org_id``.
        org_id: Target organisation.
        requested_by: Acting Global Admin user id (audit attribution).
        ip_address: Client IP for the audit entry.

    Returns:
        A dict ``{status, connection, webhook_url, is_verified, error, code}``
        where ``status`` is one of ``"provisioned"`` (all artefacts created),
        ``"partial"`` (some/none created — complete manually), or
        ``"unavailable"`` (auto-provisioning is turned off). ``connection`` is
        the masked, plaintext-free projection (or ``None`` when no row exists).
    """
    key = org_id if isinstance(org_id, uuid.UUID) else uuid.UUID(str(org_id))

    adapter = get_provisioning_adapter()
    if adapter is None:
        # R20.5 — auto-provisioning is unavailable; manual path is unaffected.
        existing = await _load_row(db, key)
        err = esign_error(CODE_AUTO_PROVISION_UNAVAILABLE)
        return _provision_result(
            status="unavailable",
            row=existing,
            webhook_url=(
                _webhook_url(existing.webhook_routing_id) if existing else None
            ),
            error=err.message,
            code=err.code,
        )

    org = await _load_org(db, key)
    if org is None:
        # No org to provision for — leave any existing connection untouched and
        # manually completable; never raise raw internals.
        existing = await _load_row(db, key)
        err = esign_error(CODE_AUTO_PROVISION_FAILED)
        return _provision_result(
            status="partial",
            row=existing,
            webhook_url=(
                _webhook_url(existing.webhook_routing_id) if existing else None
            ),
            error=err.message,
            code=err.code,
        )

    base_url = _provision_base_url()

    # Step 1 — ensure the OraInvoice-side identifiers exist first. Reuse an
    # existing row's routing id / secret (a prior partial run) rather than
    # generating duplicates.
    row = await _load_row(db, key)
    if row is None:
        row = EsignOrgConnection(
            org_id=key,
            base_url=base_url,
            webhook_routing_id=_generate_routing_id(),
            is_verified=False,
            created_by=uuid.UUID(str(requested_by)) if requested_by else None,
        )
        db.add(row)
        await db.flush()
    elif base_url and not row.base_url:
        row.base_url = base_url

    routing_url = _webhook_url(row.webhook_routing_id)

    # Reuse an already-stored webhook secret if present, else generate a fresh
    # one before touching Documenso so it can be registered in one pass.
    if row.webhook_secret_encrypted:
        try:
            secret = envelope_decrypt_str(row.webhook_secret_encrypted)
        except Exception:  # noqa: BLE001 - regenerate on any decrypt issue
            secret = secrets.token_urlsafe(32)
    else:
        secret = secrets.token_urlsafe(32)

    try:
        # Step 2 — create (or reuse) the org's Documenso Team.
        if not row.documenso_team_id:
            team = await adapter.create_team(org=org)
            row.documenso_team_id = team.team_id
            if base_url and not row.base_url:
                row.base_url = base_url
            row.is_verified = False
            await db.flush()
        team_id = row.documenso_team_id

        # Step 3 — mint the team-scoped token; persist it encrypted immediately.
        minted = await adapter.mint_team_token(team_id=team_id)
        row.service_token_encrypted = envelope_encrypt(minted.token)
        row.is_verified = False
        await db.flush()

        # Step 4 — create/confirm the Team's webhook; persist the secret.
        await adapter.ensure_webhook(
            team_id=team_id, routing_url=routing_url, secret=secret
        )
        row.webhook_secret_encrypted = envelope_encrypt(secret)
        row.is_verified = False
        await db.flush()
    except Exception as exc:  # noqa: BLE001 - isolate ALL failures (R20.3/R20.4)
        # Preserve whatever was already created (partial state is valid and
        # reusable) and surface a humanized error. Returning normally lets the
        # request transaction commit the partial progress.
        await db.flush()
        await db.refresh(row)
        invalidate_documenso_connection_cache(key)
        await _audit_auto_provision(
            db, row, requested_by=requested_by, ip_address=ip_address, outcome="partial"
        )
        if isinstance(exc, ProvisioningError):
            err = humanize_esign_error(exc)
        else:
            err = esign_error(CODE_AUTO_PROVISION_FAILED)
        return _provision_result(
            status="partial",
            row=row,
            webhook_url=routing_url,
            error=err.message,
            code=err.code,
        )

    await db.refresh(row)
    invalidate_documenso_connection_cache(key)

    # Step 5 — verify against the org's Team using the freshly-minted token and
    # set is_verified from the result (R20.2). A verification failure does not
    # undo the successfully-created artefacts.
    try:
        test_result = await test_connection(
            db, key, tested_by=requested_by, ip_address=ip_address
        )
        verified = bool(test_result.get("is_verified"))
    except Exception:  # noqa: BLE001 - never let a test failure break provisioning
        verified = False

    await db.refresh(row)
    await _audit_auto_provision(
        db, row, requested_by=requested_by, ip_address=ip_address, outcome="provisioned"
    )
    return _provision_result(
        status="provisioned",
        row=row,
        webhook_url=routing_url,
        error=None,
        code=None,
        is_verified=verified,
    )
