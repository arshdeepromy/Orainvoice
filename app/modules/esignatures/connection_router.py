"""Global-Admin per-organisation Documenso connection endpoints.

These endpoints let a **Global Admin** (platform-level admin, who has no active
org context) manage a *specific* organisation's Documenso connection by
carrying the target ``org_id`` in the path::

    GET  /api/v2/admin/organisations/{org_id}/esign/connection
    PUT  /api/v2/admin/organisations/{org_id}/esign/connection
    POST /api/v2/admin/organisations/{org_id}/esign/connection/test

Why the admin path (Task 14.2): a Global Admin has no active org context, so the
target org id must be in the path. ``/api/v2/admin/`` is already a
global-admin-only, tenant-context-exempt prefix (``_ADMIN_ONLY_PREFIXES`` in
``app/middleware/auth.py``) and sits OUTSIDE the ``/api/v2/esign``
``MODULE_ENDPOINT_MAP`` prefix, so these connection endpoints are intentionally
**not** module-gated — connection setup works regardless of whether the
``esignatures`` module is enabled. The org-USER endpoints
(``/api/v2/esign/envelopes...``) stay module-gated.

Authorisation: every route requires the ``global_admin`` role (mirroring the
admin router's ``dependencies=[require_role("global_admin")]`` pattern — there
is no ``require_global_admin`` helper).

Tenant context: because the admin prefix runs with the RLS context reset (a
global admin sees no tenant rows by default), each handler explicitly scopes the
session to the target org via ``set_config('app.current_org_id', ...)`` before
touching the org-scoped ``esign_org_connections`` row.

Secret handling: responses are **always masked** — ``service_token`` and
``webhook_signing_secret`` are surfaced only as an asterisk mask plus a
``*_last4`` projection, never plaintext (R1.4, R15.3). The asterisk mask is
shaped to match the connection service's ``_MASK_PATTERN`` so that a client
echoing it back on save **retains** the stored secret (R1.5).

Webhook surface (Task 14.7 / R18, R19.1): the GET response additionally carries
the org's opaque ``webhook_routing_id``, the fully-qualified ``webhook_url``
(``{public_base}/api/v2/esign/webhook/{routing_id}``) a Global Admin copies into
Documenso, and a ``webhook_subscription_status`` describing how far that org's
connection + webhook subscription have progressed (see ``_subscription_status``).

──────────────────────────────────────────────────────────────────────────────
MANUAL PER-ORGANISATION WEBHOOK REGISTRATION (R18.1) — operator procedure
──────────────────────────────────────────────────────────────────────────────
Documenso's public REST API exposes **no** endpoint to create a Team, mint a
team-scoped token, or register a Team webhook subscription. Those are therefore
a **one-time manual step** a Global Admin performs **per organisation** and
**per environment** (dev / prod each have their own Documenso instance/URL, so
each needs its own registration — R18.3). The optional auto-provisioning adapter
(Task 14.9 / R20) drives Documenso internals best-effort, but this manual path is
the **always-available supported fallback** (R20.4).

Steps a Global Admin follows for one organisation in one environment:

  1. In OraInvoice, open the org from the Global-Admin Organisations list and go
     to its E-Signature connection management view (Task 18.3). Enter that org's
     Documenso ``base_url``, ``documenso_team_id``, team-scoped ``service_token``
     and a ``webhook_signing_secret`` (any sufficiently random string), then save
     (PUT). Saving generates/keeps the org's ``webhook_routing_id`` and clears
     ``is_verified`` (R19.5).
  2. Copy the ``webhook_url`` shown on that view (this endpoint surfaces it).
  3. In the **Documenso** UI, signed in to **that org's Team**, open
     *Settings → Webhooks → Create webhook* and:
       • set the endpoint URL to the copied ``webhook_url``;
       • set the webhook **secret** to the **same** ``webhook_signing_secret``
         entered in step 1 (OraInvoice compares it verbatim — Documenso sends the
         secret as-is in ``X-Documenso-Secret``, it does NOT HMAC the body);
       • subscribe to the document lifecycle events (document opened/viewed,
         recipient completed/rejected, document completed/cancelled).
  4. Back in OraInvoice, run **Test connection** on the same view. A successful
     test sets ``is_verified = true`` (R19.2); only then can the org send for
     signature (R19.3/19.4). ``webhook_subscription_status`` becomes ``verified``.
  5. Trigger one signing event (or Documenso's "send test" on the webhook). When
     OraInvoice records the first inbound webhook on the org's routing URL,
     ``webhook_subscription_status`` advances to ``active`` — end-to-end proof the
     per-org subscription is live (R18.2).

Repeat the whole procedure independently for each organisation and for each
environment (dev/prod) — routing ids, secrets and Team tokens never cross orgs
or environments (R13.7, R18.3).

A copy of this procedure for operators lives in ``docs/esign-documenso-setup.md``.

Refs: requirements 1.1, 1.4, 1.5, 1.6, 1.7, 1.10, 18.1, 18.2, 18.3, 19.1, 19.2,
19.5; design §"Per-org connection config and lifecycle".
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.request_utils import extract_request_base_url
from app.config import settings
from app.integrations.documenso import DocumensoNotConfiguredError
from app.modules.auth.rbac import require_role
from app.modules.esignatures.connection_service import (
    _load_row,
    _masked_connection,
    auto_provision_connection,
    save_connection,
    test_connection,
)
from app.modules.esignatures.errors import humanize_esign_error, status_for_code

logger = logging.getLogger(__name__)

# Mounted under the admin prefix (``/api/v2/admin``) in app/main.py.
router = APIRouter()

# The asterisk mask returned for a *set* secret. It is intentionally shaped to
# match the connection service's ``_MASK_PATTERN`` (``^\*+$``) so that a client
# echoing it back on PUT is detected as a masked placeholder and the stored
# secret is retained (R1.5).
_SECRET_MASK = "********"

# Public path template for an org's inbound Documenso webhook (Task 12.1).
_WEBHOOK_PATH = "/api/v2/esign/webhook/{routing_id}"


# ---------------------------------------------------------------------------
# Schemas (masked — never carry plaintext secrets)
# ---------------------------------------------------------------------------


class ConnectionResponse(BaseModel):
    """Masked projection of an organisation's Documenso connection (R1.4).

    ``service_token`` / ``webhook_signing_secret`` are surfaced only as an
    asterisk mask (``********`` when a secret is stored, ``""`` when not) plus a
    ``*_last4`` projection. Plaintext secrets are never returned (R15.3).
    """

    configured: bool
    org_id: uuid.UUID
    base_url: str | None = None
    documenso_team_id: str | None = None
    is_verified: bool = False
    # Masked secret echoes (round-trip retains stored value on save, R1.5).
    service_token: str = ""
    service_token_last4: str = ""
    webhook_signing_secret: str = ""
    webhook_secret_last4: str = ""
    # Per-org webhook routing surface (Task 14.7 / R18, R19.1).
    webhook_routing_id: str | None = None
    webhook_url: str | None = None
    webhook_subscription_status: str = "not_configured"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectionSaveRequest(BaseModel):
    """Create/update payload for an organisation's Documenso connection.

    Secrets may be sent as plaintext (to set/replace) or as the masked echo
    (``********``) returned by GET (to retain the stored value, R1.5). The
    opaque ``webhook_routing_id`` is generated server-side and is never accepted
    from the client.
    """

    base_url: str | None = Field(default=None)
    documenso_team_id: str | None = Field(default=None)
    service_token: str | None = Field(default=None)
    webhook_signing_secret: str | None = Field(default=None)


class ConnectionTestResponse(BaseModel):
    """Result of testing an organisation's Documenso connection (R1.6/R19.2)."""

    is_verified: bool
    valid: bool


class AutoProvisionResponse(BaseModel):
    """Result of the optional best-effort auto-provision run (R19.6, R20).

    Carries the same **masked** connection projection as the connection ``GET``
    (``*_last4``, never plaintext — R1.4/R15.3) plus a ``status`` describing the
    outcome and, on a non-success, a humanized ``error`` + machine ``code`` and a
    pointer to complete the connection manually:

      - ``provisioned`` — the org's Team, token, and webhook were all created and
        the verifying connection test ran; ``connection`` reflects the verified
        row (HTTP 200).
      - ``partial`` — auto-provisioning failed at some step; whatever artefacts
        were created are persisted and **manually completable** on the same row
        (``error``/``code`` humanized; HTTP 502 per the error table).
      - ``unavailable`` — auto-provisioning is turned off in this environment
        (``ESIGN_PROVISIONING_MODE=off``); the manual path is unaffected
        (``error``/``code`` humanized; HTTP 200 per the error table).
    """

    status: str
    connection: ConnectionResponse
    error: str | None = None
    code: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_response(exc: Any) -> JSONResponse:
    """Render a humanized ``{ message, code }`` error with its HTTP status."""
    err = humanize_esign_error(exc)
    return JSONResponse(
        status_code=status_for_code(err.code),
        content={"detail": {"message": err.message, "code": err.code}},
    )


def _subscription_status(
    configured: bool,
    is_verified: bool,
    webhook_seen: bool = False,
) -> str:
    """Derive the org's webhook subscription status (Task 14.7 / R18.2).

    States, in lifecycle order:

      - ``not_configured``       — the org has no ``esign_org_connections`` row
        yet; nothing to register.
      - ``pending_verification`` — a connection is recorded but its credentials
        have not passed a connection test (``is_verified = false``); the org's
        e-signature features stay unusable (R19.3) and sends are blocked
        (R19.4).
      - ``verified``             — the connection test has passed
        (``is_verified = true``), but OraInvoice has not yet observed an inbound
        Documenso webhook for this org, so the **manual** Documenso-side webhook
        subscription registration (R18.1) is recorded-but-unconfirmed.
      - ``active``               — the connection is verified **and** at least
        one Documenso webhook has been received on this org's routing URL,
        proving the per-org webhook subscription is wired up and delivering
        end-to-end (R18.2).
    """
    if not configured:
        return "not_configured"
    if not is_verified:
        return "pending_verification"
    return "active" if webhook_seen else "verified"


def _build_response(
    masked: dict[str, Any] | None,
    request: Request,
    webhook_active: bool = False,
) -> ConnectionResponse:
    """Build the masked connection response from a service projection.

    ``masked`` is the dict returned by the connection service
    (``_masked_connection``) or ``None`` when the org has no connection row.
    ``webhook_active`` reflects whether OraInvoice has ever received a Documenso
    webhook for this org (proof the manual subscription is live, R18.2); callers
    that cannot cheaply determine this may leave it ``False`` (the status then
    tops out at ``verified``).
    """
    if masked is None:
        # Unconfigured — surface a stable "not configured" shape so the
        # Global-Admin settings view can render an empty form (200, not 404).
        return ConnectionResponse(
            configured=False,
            org_id=_org_id_from_request(request),
            webhook_subscription_status="not_configured",
        )

    routing_id = masked.get("webhook_routing_id")
    # Prefer the request origin (the public host the Global Admin is on) and
    # fall back to the configured ``frontend_base_url`` so the routing URL is
    # always copy-able even for callers without an Origin header (mirrors
    # connection_service._webhook_url). Documenso calls this public host, so it
    # must be the externally-reachable origin.
    base = (
        extract_request_base_url(request)
        or (getattr(settings, "frontend_base_url", "") or "").rstrip("/")
        or None
    )
    webhook_url = (
        f"{base}{_WEBHOOK_PATH.format(routing_id=routing_id)}"
        if base and routing_id
        else None
    )

    token_last4 = masked.get("service_token_last4") or ""
    secret_last4 = masked.get("webhook_secret_last4") or ""
    is_verified = bool(masked.get("is_verified"))

    return ConnectionResponse(
        configured=True,
        org_id=masked["org_id"],
        base_url=masked.get("base_url"),
        documenso_team_id=masked.get("documenso_team_id"),
        is_verified=is_verified,
        service_token=_SECRET_MASK if token_last4 else "",
        service_token_last4=token_last4,
        webhook_signing_secret=_SECRET_MASK if secret_last4 else "",
        webhook_secret_last4=secret_last4,
        webhook_routing_id=routing_id,
        webhook_url=webhook_url,
        webhook_subscription_status=_subscription_status(
            True, is_verified, webhook_active,
        ),
        created_at=masked.get("created_at"),
        updated_at=masked.get("updated_at"),
    )


def _org_id_from_request(request: Request) -> uuid.UUID:
    """Best-effort extraction of the path ``org_id`` for the unconfigured shape."""
    raw = request.path_params.get("org_id")
    try:
        return raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return uuid.uuid4()


async def _scope_to_org(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Scope the (admin-context) session to ``org_id`` for RLS-protected reads.

    The ``/api/v2/admin`` prefix runs with ``app.current_org_id`` reset (global
    admins see no tenant rows by default), so ``esign_org_connections`` — which
    lives under RLS keyed on ``app.current_org_id`` — is invisible until we set
    the context to the target org. ``set_config(..., true)`` binds the value
    parametrically (no injection) and is local to the current transaction.
    """
    await db.execute(
        text("SELECT set_config('app.current_org_id', :oid, true)"),
        {"oid": str(org_id)},
    )


async def _org_exists(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Return ``True`` when the organisation exists (raw SQL, RLS-independent)."""
    result = await db.execute(
        text("SELECT 1 FROM organisations WHERE id = :oid"),
        {"oid": str(org_id)},
    )
    return result.first() is not None


async def _webhook_event_seen(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Return ``True`` when ≥1 Documenso webhook has been received for this org.

    A received webhook is the only programmatic proof OraInvoice has that the
    **manual** per-org Documenso webhook subscription (R18.1) is actually live —
    Documenso's REST API exposes no endpoint to query a Team's webhook
    subscriptions. The caller scopes the session to ``org_id`` first, so this
    read sees only this org's ``esign_webhook_events`` rows under RLS.

    Best-effort: any error degrades to ``False`` (status falls back to
    ``verified``) and never breaks the connection response.
    """
    try:
        result = await db.execute(
            text("SELECT 1 FROM esign_webhook_events WHERE org_id = :oid LIMIT 1"),
            {"oid": str(org_id)},
        )
        return result.first() is not None
    except Exception:  # noqa: BLE001 - subscription-status enrichment is best-effort
        logger.debug(
            "esign webhook-activity probe failed for org %s", org_id, exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/organisations/{org_id}/esign/connection",
    response_model=ConnectionResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="Get an organisation's Documenso connection (masked)",
    dependencies=[require_role("global_admin")],
)
async def get_org_connection(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the organisation's Documenso connection with secrets **masked**.

    Secrets are never returned in plaintext (R1.4, R15.3); the response carries
    an asterisk mask plus a ``*_last4`` projection, the org's webhook URL and
    its ``webhook_subscription_status`` (R18, R19.1). When the org has no
    connection yet, a stable "not configured" shape is returned (HTTP 200).

    Only Global_Admin users can access this endpoint.
    """
    if not await _org_exists(db, org_id):
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    await _scope_to_org(db, org_id)
    row = await _load_row(db, org_id)
    masked = _masked_connection(row) if row is not None else None
    # Probe webhook activity only when a connection exists — it promotes the
    # status from ``verified`` to ``active`` (R18.2). Best-effort; never fatal.
    webhook_active = await _webhook_event_seen(db, org_id) if masked is not None else False
    return _build_response(masked, request, webhook_active=webhook_active)


@router.put(
    "/organisations/{org_id}/esign/connection",
    response_model=ConnectionResponse,
    responses={
        400: {"description": "Validation error (e.g. missing base URL on create)"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="Create or update an organisation's Documenso connection",
    dependencies=[require_role("global_admin")],
)
async def save_org_connection(
    org_id: uuid.UUID,
    payload: ConnectionSaveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create or update the organisation's Documenso connection.

    ``base_url`` / ``documenso_team_id`` are stored as-is; ``service_token`` and
    ``webhook_signing_secret`` are envelope-encrypted by the service. A secret
    echoed back as the masked placeholder retains the stored value rather than
    overwriting it (R1.5). Any save clears ``is_verified`` until a fresh test
    succeeds (R19.5). The response is masked (R1.4).

    Only Global_Admin users can access this endpoint.
    """
    if not await _org_exists(db, org_id):
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    await _scope_to_org(db, org_id)

    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    try:
        masked = await save_connection(
            db,
            org_id,
            base_url=payload.base_url,
            documenso_team_id=payload.documenso_team_id,
            service_token=payload.service_token,
            webhook_signing_secret=payload.webhook_signing_secret,
            updated_by=user_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        # e.g. creating a new connection without a base_url — a 400 with a
        # human-readable message (the service raises a clean, leak-free string).
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - map to humanized error shape
        logger.exception("esign connection save failed for org %s", org_id)
        return _error_response(exc)

    return _build_response(masked, request)


@router.post(
    "/organisations/{org_id}/esign/connection/test",
    response_model=ConnectionTestResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
        503: {"description": "Connection not configured yet"},
    },
    summary="Test an organisation's Documenso connection",
    dependencies=[require_role("global_admin")],
)
async def test_org_connection(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test the organisation's Documenso connection and persist ``is_verified``.

    Performs an authenticated request against the org's own Documenso Team using
    its team-scoped token, sets ``is_verified`` from the result (R1.6, R19.2),
    and reports ``valid``. When the org has no connection row yet, a humanized
    "configure first" error is returned (R1.10).

    Only Global_Admin users can access this endpoint.
    """
    if not await _org_exists(db, org_id):
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    await _scope_to_org(db, org_id)

    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    try:
        result = await test_connection(
            db,
            org_id,
            tested_by=user_id,
            ip_address=ip_address,
        )
    except DocumensoNotConfiguredError as exc:
        # R1.10 — humanized "configure the connection first".
        return _error_response(exc)
    except Exception as exc:  # noqa: BLE001 - map to humanized error shape
        logger.exception("esign connection test failed for org %s", org_id)
        return _error_response(exc)

    return ConnectionTestResponse(
        is_verified=bool(result.get("is_verified")),
        valid=bool(result.get("valid")),
    )


@router.post(
    "/organisations/{org_id}/esign/auto-provision",
    response_model=AutoProvisionResponse,
    responses={
        200: {"description": "Provisioned, or auto-provisioning unavailable (manual path intact)"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
        502: {"description": "Auto-provisioning failed — partial state is manually completable"},
    },
    summary="Best-effort auto-provision an organisation's Documenso connection",
    dependencies=[require_role("global_admin")],
)
async def auto_provision_org_connection(
    org_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Run the OPTIONAL best-effort auto-provisioning for the target org (R19.6, R20).

    Triggers :func:`auto_provision_connection`, which creates the org's Documenso
    Team, mints its team-scoped token, registers its webhook subscription, and
    runs the verifying connection test — persisting progress at every step so a
    failure is always recoverable by the manual path (R20.3, R20.4). The response
    carries the **masked** connection (same shape as the connection ``GET`` —
    ``*_last4`` only, never plaintext — R1.4/R15.3) plus the outcome ``status``:

      - ``provisioned`` → HTTP 200 with the verified connection.
      - ``unavailable`` (``ESIGN_PROVISIONING_MODE=off``) → HTTP 200 with the
        humanized "configure manually" message + code (R20.5). The manual path
        is unaffected.
      - ``partial`` → HTTP 502 (per the error table) with the humanized error +
        code **and** the partially-populated, manually-completable connection
        so the Global Admin can finish setup on the same row (R20.1, R20.3).

    Only Global_Admin users can access this endpoint.
    """
    if not await _org_exists(db, org_id):
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    await _scope_to_org(db, org_id)

    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    try:
        result = await auto_provision_connection(
            db,
            org_id,
            requested_by=user_id,
            ip_address=ip_address,
        )
    except Exception as exc:  # noqa: BLE001 - map to humanized error shape
        # The service is designed to never raise (it catches all failures and
        # returns a humanized "partial" result), but stay defensive: surface a
        # humanized error rather than leaking raw internals (R15.5).
        logger.exception("esign auto-provision failed for org %s", org_id)
        return _error_response(exc)

    # The masked connection projection round-trips through the same builder as
    # the connection GET so the shape is identical (R1.4/R15.3). When no row
    # exists (e.g. unavailable on a never-configured org) this yields the stable
    # "not configured" shape.
    connection = _build_response(result.get("connection"), request)

    status_value = result.get("status")
    code = result.get("code")
    # Map the outcome to HTTP per the design's error table: provisioned → 200;
    # auto_provision_unavailable → 200 (manual path intact); auto_provision_failed
    # ("partial") → 502. status_for_code covers the latter two; provisioned has
    # no code so it is mapped explicitly.
    if status_value == "provisioned":
        http_status = 200
    else:
        http_status = status_for_code(code)

    body = AutoProvisionResponse(
        status=status_value,
        connection=connection,
        error=result.get("error"),
        code=code,
    )
    return JSONResponse(status_code=http_status, content=body.model_dump(mode="json"))
