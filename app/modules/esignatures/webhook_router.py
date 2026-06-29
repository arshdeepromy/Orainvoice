"""Public, per-org-routed, shared-secret-gated Documenso webhook ingestion.

Documenso delivers signing-event callbacks to a per-organisation URL of the
shape ``/api/v2/esign/webhook/{routing_id}``, where ``{routing_id}`` is the
opaque ``webhook_routing_id`` generated for that org's
``esign_org_connections`` row. Documenso cannot present an OraInvoice JWT, so
this route is mounted under a **public prefix** (``/api/v2/esign/webhook/`` —
see ``PUBLIC_PREFIXES`` in ``app/middleware/auth.py``) and bypasses JWT auth.
Because the request carries no org session, ``ModuleMiddleware`` skips it (it
only gates requests with a resolved ``org_id``), so the path is naturally
ungated despite living under the ``/api/v2/esign`` module-gate prefix.

Authentication is per-organisation and happens **before any body parse or DB
write** (R8.1, R8.2):

1. Open a fresh DB session and run it in **system context**
   (``RESET app.current_org_id``) so the connection lookup is *cross-org* — the
   inbound request is not yet attributed to any tenant, so RLS must not filter
   the ``esign_org_connections`` row out.
2. Resolve the organisation by ``webhook_routing_id`` (UNIQUE). An unknown
   routing id (maps to no org) → **HTTP 401**, nothing modified.
3. Decrypt **that org's** ``webhook_secret_encrypted`` and constant-time compare
   the verbatim secret string against the ``X-Documenso-Secret`` header value
   (Documenso sends the configured secret as-is; it does **not** HMAC the body).
   A mismatch → **HTTP 401**, nothing modified.

Only once the per-org secret is verified does the handler scope the session's
RLS context to the resolved org and hand off to the idempotent apply logic.

**This module (task 12.1) implements only the routing + per-org secret gate +
401 + registration.** The idempotent apply (synthesized dedupe key,
per-recipient status update, terminal-safe transition, signed-document
retrieval) is **task 12.2**; the explicit hand-off seam is marked below.

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.core.database import async_session_factory
from app.core.encryption import envelope_decrypt_str
from app.modules.esignatures import service
from app.modules.esignatures.models import EsignOrgConnection
from app.modules.esignatures.validation import secret_compare

logger = logging.getLogger(__name__)

# Mounted at its full path (the prefix carries the public marker recognised by
# ``PUBLIC_PREFIXES``); registered in ``app/main.py`` with no extra prefix —
# same pattern as the Xero / Connexus public webhook routers.
router = APIRouter(prefix="/api/v2/esign/webhook", tags=["v2-esign-webhook"])

def _unauthorized() -> JSONResponse:
    # A deliberately generic 401 body. We do NOT distinguish "unknown routing
    # id" from "secret mismatch" so the endpoint never confirms whether a given
    # routing id maps to a real organisation (no tenant-existence oracle). A
    # fresh instance is returned per call — a JSONResponse is single-use.
    return JSONResponse(
        status_code=401,
        content={"message": "Webhook authentication failed.", "code": "unauthorized"},
    )


@router.post("/{routing_id}")
async def documenso_webhook(routing_id: str, request: Request) -> JSONResponse:
    """Authenticate an inbound Documenso webhook by per-org routing + secret.

    Resolves the org from ``routing_id`` in **system DB context**, verifies the
    ``X-Documenso-Secret`` header against that org's stored webhook secret with a
    constant-time compare, and only then hands off to the (task 12.2) apply
    logic. An unknown routing id OR a secret mismatch returns 401 and modifies
    nothing (R8.2).
    """
    # Read the header BEFORE touching the body so a malformed/oversized body can
    # never short-circuit the auth gate. (Body parsing is task 12.2.)
    provided_secret = request.headers.get("X-Documenso-Secret", "")

    async with async_session_factory() as db:
        # --- System context: cross-org lookup (R8.1) -----------------------
        # The request is not yet attributed to any tenant, so reset the RLS GUC
        # to read the connection row across orgs. Nothing is written here, so a
        # rejected request modifies no state (R8.2).
        await db.execute(text("RESET app.current_org_id"))

        result = await db.execute(
            select(EsignOrgConnection).where(
                EsignOrgConnection.webhook_routing_id == routing_id
            )
        )
        conn = result.scalar_one_or_none()

        # Unknown routing id (maps to no org) → 401, modify nothing (R8.2).
        if conn is None or not conn.webhook_secret_encrypted:
            logger.warning(
                "Esign webhook rejected: routing id resolved to no configured "
                "org connection"
            )
            return _unauthorized()

        # Decrypt THIS org's webhook secret and constant-time compare the
        # verbatim secret string (Documenso does NOT HMAC the body) BEFORE any
        # parse/DB write (R8.1).
        try:
            expected_secret = envelope_decrypt_str(conn.webhook_secret_encrypted)
        except Exception:
            # A decrypt failure must not leak detail or 500 — treat as auth
            # failure, modify nothing.
            logger.exception("Esign webhook: failed to decrypt stored webhook secret")
            return _unauthorized()

        if not secret_compare(expected_secret, provided_secret):
            logger.warning("Esign webhook rejected: X-Documenso-Secret mismatch")
            return _unauthorized()

        # --- Authenticated: scope to the resolved org for apply ------------
        org_id = conn.org_id
        await db.execute(
            text("SELECT set_config('app.current_org_id', :oid, true)"),
            {"oid": str(org_id)},
        )

        # === TASK 12.2: idempotent apply + per-recipient update ============
        # The org is resolved and its per-org secret verified; the session is
        # now scoped to ``org_id`` under RLS. Read the raw body and hand off to
        # the apply logic, which synthesizes the SHA-256 dedupe key, records it
        # idempotently in ``esign_webhook_events`` (acknowledging duplicates and
        # unmapped documents without modification), applies the terminal-safe
        # status transition + per-recipient update for the matching envelope,
        # writes audit + notification on a transition, owns the transaction
        # (commit), and triggers signed-document retrieval on completion.
        #
        # ``apply_webhook`` never raises: a verified webhook is ALWAYS
        # acknowledged 200; failures degrade to a logged no-op so Documenso is
        # not prompted into an endless retry storm. The specific outcome
        # (duplicate / unmapped / applied / no-op) is for logging/tests only.
        # ===================================================================
        raw_body = await request.body()
        try:
            result = await service.apply_webhook(
                db, org_id=org_id, raw_body=raw_body
            )
            logger.info("Esign webhook applied: outcome=%s", result.outcome)
        except Exception:  # pragma: no cover - apply is itself best-effort
            # Defence in depth: apply_webhook is designed not to raise, but if
            # it ever did we still acknowledge (verification already passed) so
            # the per-org gate's "verified ⇒ 200" contract holds.
            logger.exception("Esign webhook apply failed after verification")

    return JSONResponse(status_code=200, content={"status": "ok"})
