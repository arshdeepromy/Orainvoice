"""Service orchestration for the e-signature (``esignatures``) module.

This module owns the **send / void / list / detail** orchestration that sits
between the ``/api/v2/esign`` router and the per-organisation
:class:`~app.integrations.documenso.DocumensoClient`. The router applies the
authentication, RBAC (``require_esign_sender``) and module-gate dependencies;
the service receives the resolved ``org_id`` plus the calling user context and
is responsible for the business flow only.

Currently implemented:

* :func:`create_and_send_envelope` — the create-and-send flow (task 8.1).

Error signalling
----------------
The service raises :class:`fastapi.HTTPException` directly, with the body shaped
as the module's canonical humanized envelope
(``detail = { "message": ..., "code": ... }``) built from
:mod:`app.modules.esignatures.errors`. This mirrors the established pattern in
this codebase (e.g. ``app/modules/staff/public_router.py`` raises
``HTTPException(detail={"message": ..., "code": ...})``) and keeps the HTTP
status code aligned with the design's Error Handling table via
:func:`~app.modules.esignatures.errors.status_for_code`. Raw DB/exception text
is never leaked (R15.5).

Refs: requirements 3.1, 3.2, 3.4, 3.5, 3.6, 4.4, 10.3, 10.4, 12.1, 13.7,
19.3, 19.4; design §"Send → sign → store sequence", §"Create/send flow".
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, get_args
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.audit import write_audit_log
from app.core.database import _set_rls_org_id, async_session_factory
from app.integrations.documenso import (
    DocumensoApiError,
    DocumensoClient,
    DocumensoConnection,
    DocumensoCreateResult,
    DocumensoError,
    DocumensoFieldSpec,
    DocumensoNotConfiguredError,
    RecipientSpec,
    get_documenso_connection,
)
from app.modules.esignatures.dependency_graph import validate_dependencies
from app.modules.esignatures.errors import (
    CODE_DOCUMENSO_ERROR,
    CODE_FILTER_UNAVAILABLE,
    CODE_INTEGRATION_NOT_CONFIGURED,
    CODE_NO_RECIPIENTS,
    CODE_NO_SIGNERS,
    CODE_NOT_EDITABLE,
    CODE_NOT_FOUND,
    CODE_NOT_PDF,
    CODE_NOT_VOIDABLE,
    CODE_SERVER_ERROR,
    CODE_SIGNATURE_FIELD_FAILED,
    esign_error,
    status_for_code,
)
from app.modules.esignatures.field_mapping import (
    FIELD_TYPE_MAP,
    build_field_meta,
    map_field_type,
)
from app.modules.esignatures.field_validation import editable_state, validate_field_set
from app.modules.esignatures.models import EsignEnvelope, EsignRecipient, EsignWebhookEvent
from app.modules.esignatures.schemas import (
    EnvelopeCreate,
    EnvelopeFieldsOut,
    EnvelopeListResponse,
    EnvelopeOut,
    EsignError,
    FieldOut,
    FieldSetReplace,
    RecipientOut,
)
from app.modules.esignatures.status import (
    EnvelopeStatus,
    TERMINAL_STATUSES,
    RecipientState,
    next_status,
)
from app.modules.esignatures.validation import is_pdf, pdf_page_count, validate_recipients
from app.modules.in_app_notifications.service import create_in_app_notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default MVP signature-field placement (R17)
# ---------------------------------------------------------------------------
# Every signer recipient must carry at least one SIGNATURE field before the
# document is sent, otherwise Documenso would collect no signature. The MVP
# places a single SIGNATURE field per signer on the document's **last page** at
# the documented default coordinates (a signature box in the lower-right of the
# final page; normalised page units, origin top-left).
#
# Last-page resolution: Documenso's create-document response does NOT carry a
# page count, so the last page is derived **best-effort** from the source PDF
# bytes via :func:`pdf_page_count`. When the count cannot be determined (e.g. a
# PDF whose page objects live in compressed object streams) we fall back to the
# FIRST page rather than guessing an out-of-range page number — an out-of-range
# page would make Documenso reject the field and, under the R17 guard below,
# needlessly block an otherwise-valid send. The coordinates are fixed per the
# design MVP and refined later by drag-and-drop placement / per-type templates.
_FALLBACK_FIELD_PAGE_NUMBER = 1
_DEFAULT_FIELD_PAGE_X = 65.0
_DEFAULT_FIELD_PAGE_Y = 85.0
_DEFAULT_FIELD_PAGE_WIDTH = 25.0
_DEFAULT_FIELD_PAGE_HEIGHT = 8.0

# Documenso roles that actually sign and therefore require a SIGNATURE field.
_SIGNING_ROLES = frozenset({"SIGNER", "APPROVER"})


def _last_page_number(pdf_bytes: bytes) -> int:
    """Resolve the page number for the MVP signature field (R17).

    Returns the document's **last** page when the page count can be derived
    from the PDF bytes, else falls back to the **first** page so a bad page
    guess can never block an otherwise-valid send.
    """
    count = pdf_page_count(pdf_bytes)
    if count and count > 0:
        return count
    return _FALLBACK_FIELD_PAGE_NUMBER

# ---------------------------------------------------------------------------
# Dashboard list/detail (R11) constants
# ---------------------------------------------------------------------------
# The set of *applyable* ``?status=`` filter values — exactly the 8 envelope
# statuses pinned by the migration CHECK constraint and the status reducer
# (derived from the ``EnvelopeStatus`` Literal so the two never drift). Any
# value outside this set is an UNAPPLYABLE filter and triggers the fail-closed
# path in :func:`list_envelopes` (empty items + ``filter_unavailable``, R11.6).
_VALID_STATUSES: frozenset[str] = frozenset(get_args(EnvelopeStatus))

# Relative URL of the org-checked signed-document download endpoint
# (``GET /api/v2/esign/envelopes/{id}/signed-document``). The service builds a
# RELATIVE link here (rather than deferring URL construction to the router) so
# the "link present iff a signed doc is stored" rule (R11.5, Property 21) is
# self-contained and directly testable without a request context. The router
# (task 10.1) serves this same path.
_SIGNED_DOCUMENT_URL_TEMPLATE = "/api/v2/esign/envelopes/{envelope_id}/signed-document"

# ---------------------------------------------------------------------------
# Audit + in-app notification side-effects (R3.7, R3.8, R14.3)
# ---------------------------------------------------------------------------
# Audit and notification are **best-effort relative to the envelope row**
# (R14.3): a failure to write either MUST be logged and MUST NOT roll back the
# envelope (or its status). ``create_in_app_notification`` is self-guarding
# (never raises), but ``write_audit_log`` (``app/core/audit.py``) does NOT
# swallow exceptions — so wrapping it so an audit failure cannot poison/roll
# back the envelope transaction is MANDATORY. We isolate **every** side-effect
# in its own SAVEPOINT (``db.begin_nested()``) — the established pattern in this
# codebase for best-effort writes (see ``weekly_roster_broadcast`` /
# ``dashboard_service._safe_call``) — so the side-effect's own partial writes
# roll back on failure while the surrounding envelope transaction is preserved.

# In-app notification category for the Agreements (esign) module.
_NOTIFICATION_CATEGORY = "esignature"
# Roles that may send/void agreements (mirrors ``require_esign_sender``).
_NOTIFICATION_AUDIENCE = ["org_admin", "branch_admin", "location_manager"]
# Audit actions for the create/send flow.
_AUDIT_ACTION_SENT = "esign.envelope.sent"
_AUDIT_ACTION_SEND_FAILED = "esign.envelope.send_failed"
# Audit action for the void flow (R7.4).
_AUDIT_ACTION_VOIDED = "esign.envelope.voided"
# Audit action for a webhook-driven status transition (R6.8, R14.1).
_AUDIT_ACTION_TRANSITION = "esign.envelope.transition"
# Audit action for an edit-after-send Field_Set replace (R13.7).
_AUDIT_ACTION_FIELDS_EDITED = "esign.envelope.fields_edited"
_AUDIT_ENTITY_TYPE = "esign_envelope"


async def _run_best_effort(db, what: str, coro) -> None:
    """Run a best-effort DB side-effect inside a SAVEPOINT.

    The side-effect ``coro`` is awaited inside a nested transaction
    (``begin_nested()``). On **any** failure — whether the coroutine raises
    (e.g. ``write_audit_log``) or the nested commit fails because a
    self-guarding helper already poisoned the savepoint (e.g.
    ``create_in_app_notification`` swallowed its own error) — the SAVEPOINT is
    rolled back and the failure logged. The surrounding (envelope) transaction
    is never rolled back. This is the MANDATORY wrapping for ``write_audit_log``
    (R14.3) and is applied to the notification too for defence in depth.
    """
    try:
        savepoint = await db.begin_nested()
    except Exception:  # pragma: no cover - DB session already unusable
        logger.warning(
            "esign: could not open SAVEPOINT for %s; side-effect skipped", what
        )
        return
    try:
        await coro
        await savepoint.commit()
    except Exception:
        logger.warning(
            "esign: %s failed (best-effort; envelope not rolled back)",
            what,
            exc_info=True,
        )
        try:
            await savepoint.rollback()
        except Exception:  # pragma: no cover - defensive
            logger.warning("esign: SAVEPOINT rollback for %s failed", what)


async def _audit_and_notify_send(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope: EsignEnvelope,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Write the audit log entry + in-app notification for a send attempt.

    Records the successful send (R3.7) or the failed-send attempt (R3.8) on the
    given session. Each side-effect runs in its own SAVEPOINT so a failure is
    logged and never rolls back the envelope row (R14.3). No plaintext
    credentials or signed-document contents are included (R14.4) — only the
    envelope's own non-secret metadata and the already-humanized error message.
    """
    agreement_type = envelope.agreement_type
    after_value: dict[str, object] = {
        "status": envelope.status,
        "agreement_type": agreement_type,
        "originating_entity_type": envelope.originating_entity_type,
        "originating_entity_id": str(envelope.originating_entity_id),
    }
    if envelope.documenso_document_id:
        after_value["documenso_document_id"] = envelope.documenso_document_id
    if not success and error_message:
        after_value["last_error"] = error_message

    await _run_best_effort(
        db,
        "audit_log",
        write_audit_log(
            db,
            org_id=org_id,
            user_id=user_id,
            action=_AUDIT_ACTION_SENT if success else _AUDIT_ACTION_SEND_FAILED,
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            after_value=after_value,
        ),
    )

    if success:
        title = f"Agreement sent for signature ({agreement_type})"
        severity = "success"
        body: str | None = None
    else:
        title = f"Failed to send agreement for signature ({agreement_type})"
        severity = "error"
        body = (error_message or "")[:1500] or None

    await _run_best_effort(
        db,
        "in_app_notification",
        create_in_app_notification(
            db,
            org_id=org_id,
            category=_NOTIFICATION_CATEGORY,
            severity=severity,
            title=title,
            body=body,
            link_url="/agreements",
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            audience_roles=_NOTIFICATION_AUDIENCE,
        ),
    )

async def _audit_and_notify_void(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope: EsignEnvelope,
) -> None:
    """Write the audit log entry + in-app notification for a void (R7.4).

    Records that the envelope was voided on the given session. Each side-effect
    runs in its own SAVEPOINT so a failure is logged and never rolls back the
    voided envelope row (R14.3). No plaintext credentials or signed-document
    contents are included (R14.4) — only the envelope's own non-secret
    metadata.
    """
    agreement_type = envelope.agreement_type
    after_value: dict[str, object] = {
        "status": envelope.status,
        "agreement_type": agreement_type,
        "originating_entity_type": envelope.originating_entity_type,
        "originating_entity_id": str(envelope.originating_entity_id),
    }
    if envelope.documenso_document_id:
        after_value["documenso_document_id"] = envelope.documenso_document_id

    await _run_best_effort(
        db,
        "audit_log",
        write_audit_log(
            db,
            org_id=org_id,
            user_id=user_id,
            action=_AUDIT_ACTION_VOIDED,
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            after_value=after_value,
        ),
    )

    await _run_best_effort(
        db,
        "in_app_notification",
        create_in_app_notification(
            db,
            org_id=org_id,
            category=_NOTIFICATION_CATEGORY,
            severity="info",
            title=f"Agreement voided ({agreement_type})",
            body=None,
            link_url="/agreements",
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            audience_roles=_NOTIFICATION_AUDIENCE,
        ),
    )


# A client factory takes a per-org connection and returns a ready DocumensoClient.
ClientFactory = Callable[[DocumensoConnection], DocumensoClient]


def _esign_http_error(code: str, *, message: str | None = None) -> HTTPException:
    """Build an :class:`HTTPException` carrying the humanized ``{message, code}``.

    The HTTP status code is derived from the design's Error Handling table via
    :func:`status_for_code`, and the body matches the module's canonical error
    shape (``detail = { "message", "code" }``). Raw exception text is never
    embedded (R15.5).
    """
    err = esign_error(code, message=message)
    return HTTPException(
        status_code=status_for_code(err.code),
        detail=err.model_dump(),
    )


async def _record_error_envelope(
    *,
    org_id: UUID,
    payload: EnvelopeCreate,
    user_id: UUID | None,
    documenso_document_id: str | None,
    last_error: str,
) -> None:
    """Persist an ``error``-status envelope on a fresh, independently-committed
    session (R3.5).

    The create-and-send flow runs inside the request's ``session.begin()``
    transaction, which is rolled back when the service raises the 502
    ``HTTPException``. To guarantee the failed attempt is still recorded, the
    error envelope is written on a **fresh** session obtained from
    :data:`async_session_factory` with the org's RLS context set, and committed
    independently of the request transaction. This is the same
    "fresh-session-for-must-survive-writes" pattern used elsewhere in the
    codebase. Persistence is itself best-effort: a failure here is logged and
    swallowed so the caller can still surface the humanized 502.
    """
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await _set_rls_org_id(session, str(org_id))
                envelope = EsignEnvelope(
                    org_id=org_id,
                    agreement_type=payload.agreement_type,
                    originating_entity_type=payload.originating_entity_type,
                    originating_entity_id=payload.originating_entity_id,
                    documenso_document_id=documenso_document_id,
                    status="error",
                    last_error=last_error,
                    created_by=user_id,
                )
                session.add(envelope)
                # Flush so the row has an id for the audit/notification refs.
                # This runs on the fresh, independently-committed session, so
                # the failed attempt + its audit/notification survive the 502
                # rollback of the request transaction (R3.8).
                await session.flush()
                await _audit_and_notify_send(
                    session,
                    org_id=org_id,
                    user_id=user_id,
                    envelope=envelope,
                    success=False,
                    error_message=last_error,
                )
    except Exception:  # pragma: no cover - defensive, never blocks the 502
        logger.exception(
            "Failed to persist error envelope for org_id=%s (originating %s:%s)",
            org_id,
            payload.originating_entity_type,
            payload.originating_entity_id,
        )


def _require_effect_dependents(dependencies: list[Any] | None) -> set[str]:
    """Collect the ``client_id`` of every field that is the dependent of a
    ``require``-effect advisory dependency (R14.8).

    Documenso has no cross-field conditional primitive, so conditional
    dependencies are **advisory** only. Per R14.8 a ``require``-effect advisory
    dependency must degrade its dependent field to OPTIONAL at signing time, so
    that an unmet advisory condition can never block a recipient. The dependent
    field is identified by :attr:`DependencyIn.dependent_client_id` (matched
    against :attr:`FieldIn.client_id`); only dependencies whose ``effect`` is
    ``require`` contribute (a ``show`` effect places no requirement and so needs
    no degrade).

    Pure (no I/O); tolerant of mappings or attribute objects, never raises.
    """
    dependents: set[str] = set()
    for dep in dependencies or ():
        if isinstance(dep, Mapping):
            effect = dep.get("effect")
            dependent = dep.get("dependent_client_id")
        else:
            effect = getattr(dep, "effect", None)
            dependent = getattr(dep, "dependent_client_id", None)
        if effect == "require" and isinstance(dependent, str) and dependent:
            dependents.add(dependent)
    return dependents


def _to_graph_dependencies(dependencies: list[Any] | None) -> list[dict[str, str]]:
    """Adapt wire ``DependencyIn`` items to the pure dependency-graph shape.

    The pure :func:`validate_dependencies` / ``dependency_graph`` operate over a
    field-name-agnostic edge value keyed on ``dependent_field`` /
    ``trigger_field``, while the wire schema (:class:`DependencyIn`) and the
    editor key fields by ``dependent_client_id`` / ``trigger_client_id``. This
    maps the latter onto the former so the cycle/self-loop check sees the real
    edges (without this, both endpoints coerce to ``""`` and every dependency
    is misread as a self-loop). Tolerant of mappings or attribute objects.
    """
    out: list[dict[str, str]] = []
    for dep in dependencies or ():
        if isinstance(dep, Mapping):
            dependent = dep.get("dependent_client_id")
            trigger = dep.get("trigger_client_id")
            condition = dep.get("condition")
            effect = dep.get("effect")
        else:
            dependent = getattr(dep, "dependent_client_id", None)
            trigger = getattr(dep, "trigger_client_id", None)
            condition = getattr(dep, "condition", None)
            effect = getattr(dep, "effect", None)
        out.append(
            {
                "dependent_field": dependent if isinstance(dependent, str) else "",
                "trigger_field": trigger if isinstance(trigger, str) else "",
                "condition": condition if isinstance(condition, str) else "",
                "effect": effect if isinstance(effect, str) else "",
            }
        )
    return out


def _build_documenso_field_specs(
    *,
    fields: list[Any],
    recipients: list[Any],
    created_recipients: list[Any],
    force_optional_client_ids: set[str] | None = None,
) -> list[DocumensoFieldSpec]:
    """Reconcile a sender-defined Field_Set against the created Documenso
    recipients and build the wire-ready :class:`DocumensoFieldSpec` list
    (R8.1, R8.2).

    Each placed field references a recipient by ``recipient_index`` (an index
    into the send's recipient list). That recipient is reconciled to the
    Documenso ``recipientId`` by **email** against ``created_recipients`` (the
    same ``created_by_*_email`` mapping the auto-placement path already uses),
    then the field's lowercase type is mapped to its UPPERCASE Documenso type
    via :func:`map_field_type` and its ``fieldMeta`` is built via
    :func:`build_field_meta`.

    ``force_optional_client_ids`` is the set of field ``client_id`` values that
    are the dependent of a ``require``-effect advisory dependency (R14.8). For
    each such field, ``fieldMeta`` is built with ``force_optional=True`` so its
    ``required`` is degraded to ``False`` at signing time — an unmet advisory
    condition can never block a recipient. (The degrade is applied to the built
    ``fieldMeta`` regardless of whether ``fieldMeta`` is ultimately sent on the
    wire, since ``fieldMeta`` is itself capability-gated.)

    The Field_Set has already passed :func:`validate_field_set` server-side, so
    every ``recipient_index`` is in range and every type is supported. The only
    residual failure mode is Documenso not returning a recipient matching a
    placed field's email — treated as a Documenso failure so the caller blocks
    distribute, records an ``error`` envelope, and surfaces a humanized 502
    (R8.4).

    Pure (no I/O); raises :class:`DocumensoApiError` on a reconciliation miss.
    """
    force_optional = force_optional_client_ids or set()
    created_by_email = {
        (cr.email or "").strip().lower(): cr for cr in created_recipients
    }
    specs: list[DocumensoFieldSpec] = []
    for field_in in fields:
        recipient = recipients[field_in.recipient_index]
        created = created_by_email.get(str(recipient.email).strip().lower())
        if created is None or not created.recipient_id:
            raise DocumensoApiError(
                "Documenso did not return a recipient matching a placed field."
            )
        client_id = getattr(field_in, "client_id", None)
        degrade = bool(client_id) and client_id in force_optional
        specs.append(
            DocumensoFieldSpec(
                recipient_id=int(created.recipient_id),
                type=map_field_type(field_in.type),
                page_number=field_in.page,
                page_x=field_in.position_x,
                page_y=field_in.position_y,
                width=field_in.width,
                height=field_in.height,
                field_meta=build_field_meta(field_in, force_optional=degrade),
            )
        )
    return specs


async def create_and_send_envelope(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    payload: EnvelopeCreate,
    pdf_bytes: bytes,
    title: str | None = None,
    http: httpx.AsyncClient | None = None,
    client: DocumensoClient | None = None,
    client_factory: ClientFactory | None = None,
) -> EsignEnvelope:
    """Create a Documenso document and send it for signature, persisting an
    :class:`~app.modules.esignatures.models.EsignEnvelope`.

    The router has already authorized the caller's role (``require_esign_sender``)
    and module enablement; this function performs the business flow:

    0. **Connection gate (R19.3, R19.4).** Load the org's Documenso connection.
       If the org has no connection row, or its connection is not verified,
       block the send with a humanized **503** (``integration_not_configured``)
       and make **no** Documenso call.
    1. **Pure validation (no Documenso call on failure).** Reject a non-PDF
       source (R3.4), a recipient list that is empty or contains any
       syntactically invalid email (R3.3, R4.2, R4.3, R4.6) — atomic
       all-or-nothing — and a send with **zero signer recipients** (R17), since
       a document with nothing to sign cannot be sent.
    2. **Multi-step Documenso flow** using *this org's* team-scoped client
       (R13.7): ``create_document`` (PDF uploaded inline) →
       ``place_signature_field`` (one SIGNATURE field per signer, on the last
       page) → ``send_document`` (distribute). **Before** ``send_document`` is
       requested, every signer recipient must carry ≥1 SIGNATURE field; if any
       signer would have no field, the send is **blocked** (no ``send_document``
       call), an ``error`` envelope is recorded, and a humanized validation
       error naming that signer is raised (R17.1, R17.2).
    3. On success, insert the envelope (status ``sent``) plus one
       recipient row per recipient (status ``pending``, capturing each
       recipient's ``signingUrl``); ``flush()`` then ``await db.refresh()``
       before returning for serialisation (R3.2, R4.4, R10.3, R10.4).
    4. On any Documenso error, record an ``error``-status envelope (R3.5) and
       raise a humanized **502** (``documenso_error``).

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        user_id: The initiating user (stored as ``created_by``); may be ``None``.
        payload: The validated create payload (agreement type, originating
            entity, recipients).
        pdf_bytes: The raw source PDF bytes.
        title: Optional document title; defaults to a name derived from the
            agreement type.
        http: Optional injected :class:`httpx.AsyncClient`. When omitted (and no
            ``client``/``client_factory`` is supplied) a client is created per
            call and closed before returning (managed lifecycle).
        client: Optional pre-built :class:`DocumensoClient` (used by tests to
            inject a spy/mock); bypasses ``http``/``client_factory``.
        client_factory: Optional callable ``conn -> DocumensoClient`` (used by
            tests to inject a spy while still exercising the real connection
            gate against the database).

    Returns:
        The persisted, refreshed :class:`EsignEnvelope` (status ``sent``) with
        its recipients populated.

    Raises:
        HTTPException: ``503`` when the org's connection is missing/unverified;
            ``422`` on validation failure; ``502`` on a Documenso API failure.
    """
    # --- Step 0: connection gate (R19.3, R19.4) ---------------------------
    try:
        conn = await get_documenso_connection(db, org_id)
    except DocumensoNotConfiguredError:
        raise _esign_http_error(CODE_INTEGRATION_NOT_CONFIGURED) from None

    if not conn.is_verified:
        # A present-but-unverified connection blocks the send just like a
        # missing one — no Documenso call is made (Property 27).
        raise _esign_http_error(CODE_INTEGRATION_NOT_CONFIGURED)

    # --- Step 1: pure validation (no Documenso call on failure) -----------
    if not is_pdf(pdf_bytes):
        raise _esign_http_error(CODE_NOT_PDF)

    recipient_result = validate_recipients(payload.recipients)
    if not recipient_result.ok:
        # validate_recipients identifies the offending recipient and supplies a
        # humanized, leak-free message; honour both its code and message.
        raise _esign_http_error(
            recipient_result.code or CODE_NO_RECIPIENTS,
            message=recipient_result.message,
        )

    document_title = title or f"{payload.agreement_type} agreement"
    # Thread each recipient's optional 1-based ``order`` onto the RecipientSpec
    # (R15.3, R15.6). The DocumensoClient applies the capability gate — when
    # ``esign_signing_order_supported`` is False the per-recipient position is
    # accepted/stored but omitted from the wire (sequential degrades to
    # parallel), so the service just threads the value through unchanged.
    recipient_specs = [
        RecipientSpec(
            name=r.name,
            email=str(r.email),
            role=r.signing_role,
            signing_order=r.order,
        )
        for r in payload.recipients
    ]

    # Determine the signer set (R17): recipients whose Documenso role signs
    # (``SIGNER`` / ``APPROVER``). Viewers never receive a signature field. A
    # send with ZERO signers has nothing to sign and is a validation error,
    # rejected HERE — before any Documenso call is made.
    signer_indices = [
        idx
        for idx, spec in enumerate(recipient_specs)
        if _documenso_role(spec.role) in _SIGNING_ROLES
    ]
    if not signer_indices:
        raise _esign_http_error(CODE_NO_SIGNERS)

    # --- Step 1b: server-side Field_Set re-validation (R6.6) --------------
    # When the send carries a sender-defined Field_Set, re-validate it on the
    # server BEFORE any Documenso call so a crafted payload can never bypass the
    # client rules. On failure we reject with the validation code's humanized
    # 422 and create nothing (no document, no recipient, no field). The codes
    # (field_unassigned / field_out_of_bounds / invalid_field_type /
    # signature_field_missing) are registered in the central error tables
    # (errors.py), so ``status_for_code`` resolves them to 422 and the result's
    # humanized, leak-free message is surfaced verbatim.
    has_field_set = bool(payload.fields)
    if has_field_set:
        field_result = validate_field_set(
            payload.fields, payload.recipients, signer_indices
        )
        if not field_result.ok:
            raise _esign_http_error(
                field_result.code or CODE_SERVER_ERROR,
                message=field_result.message,
            )

        # Advisory conditional dependencies (R14.4): re-check the submitted
        # ``dependencies[]`` for self-loops / cycles server-side BEFORE any
        # Documenso call so a crafted payload can never bypass the client check
        # (defence in depth, mirroring the Field_Set re-validation above). A
        # failure is a humanized 422 (dependency_self / dependency_cycle) and
        # creates nothing. A valid set is advisory only — the require→optional
        # degrade is applied when building each field's fieldMeta below (R14.8).
        dependency_result = validate_dependencies(
            _to_graph_dependencies(payload.dependencies)
        )
        if not dependency_result.ok:
            raise _esign_http_error(
                dependency_result.code or CODE_SERVER_ERROR,
                message=dependency_result.message,
            )

    # --- Step 2: build this org's client + run the Documenso flow ---------
    created_http: httpx.AsyncClient | None = None
    documenso_document_id: str | None = None
    try:
        active_client = client
        if active_client is None:
            if client_factory is not None:
                active_client = client_factory(conn)
            elif http is not None:
                active_client = DocumensoClient.for_org(conn, http)
            else:
                created_http = httpx.AsyncClient(
                    timeout=httpx.Timeout(DocumensoClient.DEFAULT_TIMEOUT)
                )
                active_client = DocumensoClient.for_org(conn, created_http)

        try:
            create_result: DocumensoCreateResult = await active_client.create_document(
                title=document_title,
                recipients=recipient_specs,
                pdf_bytes=pdf_bytes,
            )
            documenso_document_id = create_result.document_id

            if has_field_set:
                # --- Field_Set path (R8.1, R8.2, R8.3) ---------------------
                # Reconcile each placed field's recipient_index to its Documenso
                # recipientId (by email) and create the FULL sender-defined
                # Field_Set via ``field/create-many`` BEFORE distribute. The
                # legacy single auto-placement is SKIPPED for sends that carry a
                # Field_Set (R8.3). A ``field/create-many`` failure (or a
                # reconciliation miss) raises ``DocumensoError`` and is handled
                # by the ``except DocumensoError`` below: no distribute, an
                # ``error`` envelope is recorded, and a humanized 502 is raised
                # (R8.4).
                field_specs = _build_documenso_field_specs(
                    fields=payload.fields,
                    recipients=payload.recipients,
                    created_recipients=create_result.recipients,
                    force_optional_client_ids=_require_effect_dependents(
                        payload.dependencies
                    ),
                )
                await active_client.create_fields(
                    documenso_document_id, field_specs
                )
            else:
                # --- R17: guarantee EVERY signer has ≥1 SIGNATURE field ----
                # (Backward-compat fallback path — no Field_Set supplied.)
                # Place one SIGNATURE field per signer on the document's last
                # page. Match each signer (by email) to the recipient Documenso
                # created so the field is bound to the right Documenso recipient
                # id, then track any signer for whom a field could NOT be placed
                # — because Documenso returned no matching recipient, the
                # recipient carried no id, or the placement call itself failed.
                # If ANY signer would end up with no field, BLOCK the send: do
                # NOT call ``send_document``, record an ``error``-status envelope
                # (the failed-send path, so the attempt is audited), and raise a
                # humanized validation error naming that signer (R17.1, R17.2).
                # Viewer recipients are skipped — only signers need a field.
                page_number = _last_page_number(pdf_bytes)
                created_by_recipient_email = {
                    (cr.email or "").strip().lower(): cr
                    for cr in create_result.recipients
                }
                signers_without_field: list[str] = []
                for idx in signer_indices:
                    spec = recipient_specs[idx]
                    created = created_by_recipient_email.get(spec.email.strip().lower())
                    if created is None or not created.recipient_id:
                        signers_without_field.append(spec.name or spec.email)
                        continue
                    try:
                        await active_client.place_signature_field(
                            documenso_document_id,
                            recipient_id=created.recipient_id,
                            page_number=page_number,
                            page_x=_DEFAULT_FIELD_PAGE_X,
                            page_y=_DEFAULT_FIELD_PAGE_Y,
                            page_width=_DEFAULT_FIELD_PAGE_WIDTH,
                            page_height=_DEFAULT_FIELD_PAGE_HEIGHT,
                        )
                    except DocumensoError:
                        # A placement failure means this signer would have no
                        # field; don't let it bubble as a generic 502 — it is
                        # handled below as a "signer without a field" so the
                        # signer is named.
                        signers_without_field.append(spec.name or spec.email)

                if signers_without_field:
                    names = ", ".join(f"'{n}'" for n in signers_without_field)
                    message = (
                        "We couldn't add a signature field for "
                        f"{names}, so the agreement wasn't sent. Please try again."
                    )
                    logger.warning(
                        "esign: blocking send for org_id=%s document_id=%s — "
                        "%d signer(s) had no signature field",
                        org_id,
                        documenso_document_id,
                        len(signers_without_field),
                    )
                    # Record the blocked attempt as an error envelope (failed-send
                    # path) on a fresh committed session so it survives the
                    # rollback of the request transaction when we raise below
                    # (R3.5, R17.2).
                    await _record_error_envelope(
                        org_id=org_id,
                        payload=payload,
                        user_id=user_id,
                        documenso_document_id=documenso_document_id,
                        last_error=message,
                    )
                    # HTTPException is NOT a DocumensoError, so it propagates
                    # past the surrounding ``except DocumensoError`` and out to
                    # the router — no ``send_document`` call is made.
                    raise _esign_http_error(
                        CODE_SIGNATURE_FIELD_FAILED, message=message
                    )

            await active_client.send_document(
                documenso_document_id,
                signing_order_mode=payload.signing_order_mode,
            )
        finally:
            if created_http is not None:
                await created_http.aclose()
    except DocumensoError as exc:
        # R3.5 — record the failed attempt with status=error (on a fresh
        # committed session so it survives the 502 rollback), then surface a
        # humanized 502. The upstream status, if any, is for logging only.
        humanized = esign_error(CODE_DOCUMENSO_ERROR)
        logger.warning(
            "Documenso send failed for org_id=%s document_id=%s: %s",
            org_id,
            documenso_document_id,
            type(exc).__name__,
        )
        await _record_error_envelope(
            org_id=org_id,
            payload=payload,
            user_id=user_id,
            documenso_document_id=documenso_document_id,
            last_error=humanized.message,
        )
        raise _esign_http_error(CODE_DOCUMENSO_ERROR) from exc

    # --- Step 3: persist the successful envelope + recipients -------------
    # Index the created recipients by email so each persisted recipient row can
    # capture its one-time signing URL + Documenso recipient id (R5.1).
    created_by_email = {
        (cr.email or "").strip().lower(): cr for cr in create_result.recipients
    }

    envelope = EsignEnvelope(
        org_id=org_id,
        agreement_type=payload.agreement_type,
        originating_entity_type=payload.originating_entity_type,
        originating_entity_id=payload.originating_entity_id,
        documenso_document_id=documenso_document_id,
        status="sent",
        created_by=user_id,
    )

    for spec, r_in in zip(recipient_specs, payload.recipients):
        created = created_by_email.get(spec.email.strip().lower())
        envelope.recipients.append(
            EsignRecipient(
                name=r_in.name,
                email=spec.email,
                # Persist the UPPERCASE Documenso role (matches the client map).
                signing_role=(created.role or "").upper()
                if created and created.role
                else _documenso_role(r_in.signing_role),
                recipient_status="pending",
                signing_url=created.signing_url if created else None,
                documenso_recipient_id=created.recipient_id if created else None,
            )
        )

    db.add(envelope)
    await db.flush()
    await db.refresh(envelope)

    # Best-effort audit + in-app notification for the successful send (R3.7).
    # Both run in their own SAVEPOINT so a failure is logged and never rolls
    # back the just-persisted envelope (R14.3).
    await _audit_and_notify_send(
        db,
        org_id=org_id,
        user_id=user_id,
        envelope=envelope,
        success=True,
    )
    return envelope


def _documenso_role(api_role: str) -> str:
    """Map an OraInvoice API role (lowercase) to its UPPERCASE Documenso role.

    Falls back through the shared client mapping; defaults to ``SIGNER`` for an
    unrecognised value so a recipient is never persisted with an empty role.
    """
    from app.integrations.documenso import map_recipient_role

    try:
        return map_recipient_role(api_role)
    except DocumensoError:
        return "SIGNER"


async def _load_envelope_for_org(
    db, *, org_id: UUID, envelope_id: UUID
) -> EsignEnvelope | None:
    """Load an envelope under the org's RLS context, ownership-checked.

    The request session's RLS context is already scoped to ``org_id`` so a
    cross-org row is invisible; the explicit ``org_id`` predicate is a
    belt-and-braces ownership check (R13.4). Returns ``None`` when the envelope
    does not exist for this organisation — the caller maps that to a 404 that
    never confirms the envelope exists elsewhere (R13.5).
    """
    result = await db.execute(
        select(EsignEnvelope).where(
            EsignEnvelope.id == envelope_id,
            EsignEnvelope.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def void_envelope(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope_id: UUID,
    http: httpx.AsyncClient | None = None,
    client: DocumensoClient | None = None,
    client_factory: ClientFactory | None = None,
) -> EsignEnvelope:
    """Void a non-terminal envelope, cancelling it in Documenso (R7).

    The router has already authorized the caller's role
    (``require_esign_sender``, R12.3) and module enablement; this function
    performs the business flow:

    1. **Org-scoped load (R13.4, R13.5).** Load the envelope under the org's RLS
       context. A cross-org or missing envelope yields a humanized **404**
       (``not_found``) that never confirms the envelope exists for another org.
    2. **Terminal guard (R7.1, R7.3).** Void is allowed *only* while the
       envelope is non-terminal. A terminal envelope (``completed`` /
       ``declined`` / ``voided``) is rejected with a humanized **409**
       (``not_voidable``) and makes **no** Documenso call.
    3. **Cancel in Documenso (R7.2).** For a non-terminal envelope, build *this
       org's* team-scoped client (R13.7) and call
       :meth:`DocumensoClient.cancel_document` (issues ``DOCUMENT_CANCELLED``).
       An envelope with no mapped Documenso document id (e.g. a failed-send
       ``error`` envelope) is voided locally without a Documenso call.
    4. Set ``status=voided``, ``flush()`` then ``await db.refresh()``, and write
       a best-effort audit log + in-app notification (R7.4, R14.3).

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        user_id: The initiating user (recorded on the audit entry); may be
            ``None``.
        envelope_id: The envelope to void.
        http: Optional injected :class:`httpx.AsyncClient`. When omitted (and no
            ``client``/``client_factory`` is supplied) a client is created per
            call and closed before returning (managed lifecycle).
        client: Optional pre-built :class:`DocumensoClient` (used by tests to
            inject a spy/mock); bypasses the connection load.
        client_factory: Optional callable ``conn -> DocumensoClient`` (used by
            tests to inject a spy while still exercising the real connection
            gate against the database).

    Returns:
        The persisted, refreshed :class:`EsignEnvelope` with status ``voided``.

    Raises:
        HTTPException: ``404`` when the envelope is missing/cross-org; ``409``
            when the envelope is already terminal; ``503`` when the org's
            connection is missing; ``502`` on a Documenso API failure.
    """
    # --- Step 1: org-scoped load (R13.4, R13.5) ---------------------------
    envelope = await _load_envelope_for_org(db, org_id=org_id, envelope_id=envelope_id)
    if envelope is None:
        raise _esign_http_error(CODE_NOT_FOUND)

    # --- Step 2: terminal guard — no Documenso call on a terminal envelope -
    if envelope.status in TERMINAL_STATUSES:
        raise _esign_http_error(CODE_NOT_VOIDABLE)

    # --- Step 3: cancel in Documenso on this org's own client (R7.2, R13.7) -
    created_http: httpx.AsyncClient | None = None
    try:
        active_client = client
        if active_client is None:
            try:
                conn = await get_documenso_connection(db, org_id)
            except DocumensoNotConfiguredError:
                raise _esign_http_error(CODE_INTEGRATION_NOT_CONFIGURED) from None
            if client_factory is not None:
                active_client = client_factory(conn)
            elif http is not None:
                active_client = DocumensoClient.for_org(conn, http)
            else:
                created_http = httpx.AsyncClient(
                    timeout=httpx.Timeout(DocumensoClient.DEFAULT_TIMEOUT)
                )
                active_client = DocumensoClient.for_org(conn, created_http)

        try:
            if envelope.documenso_document_id:
                await active_client.cancel_document(envelope.documenso_document_id)
        finally:
            if created_http is not None:
                await created_http.aclose()
    except DocumensoError as exc:
        logger.warning(
            "Documenso cancel failed for org_id=%s envelope_id=%s document_id=%s: %s",
            org_id,
            envelope_id,
            envelope.documenso_document_id,
            type(exc).__name__,
        )
        raise _esign_http_error(CODE_DOCUMENSO_ERROR) from exc

    # --- Step 4: persist the voided status + best-effort audit/notify ------
    envelope.status = "voided"
    db.add(envelope)
    await db.flush()
    await db.refresh(envelope)

    await _audit_and_notify_void(
        db,
        org_id=org_id,
        user_id=user_id,
        envelope=envelope,
    )
    return envelope


# ---------------------------------------------------------------------------
# Dashboard list + detail (R11, R13.3/13.4/13.5)
# ---------------------------------------------------------------------------


def _signed_document_url(envelope: EsignEnvelope) -> str | None:
    """Return the org-checked signed-document link, or ``None``.

    The link is present **iff** a signed document has actually been stored for
    the envelope — i.e. ``signed_doc_status == 'stored'`` **and** a
    ``signed_doc_file_key`` is recorded (R11.5, Property 21). For every other
    ``signed_doc_status`` (``none`` / ``pending_retrieval``) there is nothing to
    download, so the link is ``None`` and no URL is fabricated.
    """
    if envelope.signed_doc_status == "stored" and envelope.signed_doc_file_key:
        return _SIGNED_DOCUMENT_URL_TEMPLATE.format(envelope_id=envelope.id)
    return None


def _envelope_to_out(envelope: EsignEnvelope) -> EnvelopeOut:
    """Serialise an :class:`EsignEnvelope` (with its recipients) to
    :class:`EnvelopeOut`, attaching the signed-document link only when stored.

    Recipients are eagerly loaded (``lazy="selectin"`` on the relationship), so
    ``model_validate`` can read them without a further await. ``EnvelopeOut``
    has no ``signed_document_url`` ORM attribute, so it defaults to ``None`` on
    validation and is then set explicitly from :func:`_signed_document_url`.
    """
    out = EnvelopeOut.model_validate(envelope)
    out.signed_document_url = _signed_document_url(envelope)
    return out


async def list_envelopes(
    db,
    *,
    org_id: UUID,
    status: str | None = None,
) -> tuple[EnvelopeListResponse, EsignError | None]:
    """List the calling organisation's envelopes, newest-updated first (R11).

    Returns a ``(response, error)`` tuple — a clean, request-context-free
    contract the router (task 10.1) folds into the final HTTP response and that
    Property 21 can assert directly:

    * **Success:** ``(EnvelopeListResponse(items=..., total=...), None)`` — the
      org's envelopes (optionally filtered by ``status``) ordered by
      ``updated_at DESC`` (R11.4), each carrying its recipients and current
      status (R11.1, R11.2). Org-scoping is enforced by RLS *and* an explicit
      ``org_id`` predicate, so another organisation's envelopes are never
      returned and an org with none gets an empty list (R11.1, R13.3).
    * **Unapplyable filter (fail-closed, R11.6):** when ``status`` is provided
      but is **not** one of the 8 valid envelope statuses, returns
      ``(EnvelopeListResponse(items=[], total=0), EsignError(filter_unavailable))``
      — **no** envelopes (never an unfiltered list) plus a humanized indication
      that the filter could not be applied. The DB is not queried in this case.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        status: Optional ``?status=`` filter. ``None`` / empty means "no
            filter" (return all of the org's envelopes). A non-empty value
            outside the valid status set is unapplyable (fail-closed).

    Returns:
        ``(EnvelopeListResponse, EsignError | None)`` — the error is non-``None``
        only on the fail-closed unapplyable-filter path.
    """
    # Normalise the incoming filter: treat None / blank as "no filter".
    normalized = status.strip() if isinstance(status, str) else status
    filter_status = normalized or None

    # Fail-closed: an unknown/unapplyable status returns NO envelopes plus a
    # humanized indication — never an unfiltered list (R11.6).
    if filter_status is not None and filter_status not in _VALID_STATUSES:
        return (
            EnvelopeListResponse(items=[], total=0),
            esign_error(CODE_FILTER_UNAVAILABLE),
        )

    stmt = select(EsignEnvelope).where(EsignEnvelope.org_id == org_id)
    if filter_status is not None:
        stmt = stmt.where(EsignEnvelope.status == filter_status)
    # Most-recently-updated first (R11.4); tie-break on id for a deterministic
    # order when two envelopes share an ``updated_at``.
    stmt = stmt.order_by(EsignEnvelope.updated_at.desc(), EsignEnvelope.id.desc())

    result = await db.execute(stmt)
    envelopes = result.scalars().all()
    items = [_envelope_to_out(e) for e in envelopes]
    return EnvelopeListResponse(items=items, total=len(items)), None


async def get_envelope_detail(
    db,
    *,
    org_id: UUID,
    envelope_id: UUID,
) -> EnvelopeOut:
    """Return one envelope's detail: per-recipient status + signed-doc link (R11.5).

    Loads the envelope under the org's RLS context with an explicit ``org_id``
    ownership predicate (R13.4). A missing or cross-org envelope yields a
    humanized **404** (``not_found``) that never confirms the envelope exists
    for another organisation (R13.5). The returned :class:`EnvelopeOut` carries
    every recipient's per-recipient signing status and a
    ``signed_document_url`` **only** when a signed document has been stored
    (R11.5) — see :func:`_signed_document_url`.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        envelope_id: The envelope to read.

    Returns:
        The :class:`EnvelopeOut` for the requested envelope.

    Raises:
        HTTPException: ``404`` when the envelope is missing or belongs to
            another organisation.
    """
    envelope = await _load_envelope_for_org(db, org_id=org_id, envelope_id=envelope_id)
    if envelope is None:
        raise _esign_http_error(CODE_NOT_FOUND)
    return _envelope_to_out(envelope)


# ---------------------------------------------------------------------------
# Edit fields after send (R13) — GET seed + atomic PUT replace
# ---------------------------------------------------------------------------

# Documenso (UPPERCASE) field type -> OraInvoice (lowercase) type, the exact
# inverse of ``field_mapping.FIELD_TYPE_MAP``. Used to map the live Documenso
# field set read back via ``GET /document/{id}`` onto the lowercase ``FieldOut``
# schema so the editor can be seeded from the current set (R13.1).
_DOCUMENSO_TYPE_TO_FIELD_TYPE: dict[str, str] = {v: k for k, v in FIELD_TYPE_MAP.items()}


def _signer_indices_for_recipients(recipients: list[Any]) -> list[int]:
    """Indices of the signer recipients (Documenso ``SIGNER`` / ``APPROVER``).

    Recipients are persisted with their UPPERCASE Documenso role; viewers are
    excluded. These are the recipients that must each carry at least one
    signature field (R6.1), reused when re-validating an edited Field_Set.
    """
    return [
        idx
        for idx, r in enumerate(recipients)
        if str(getattr(r, "signing_role", "") or "").upper() in _SIGNING_ROLES
    ]


def _field_out_list_from_documenso(
    doc: dict[str, Any], envelope: EsignEnvelope
) -> list[FieldOut]:
    """Map a Documenso document's live ``fields[...]`` array onto ``FieldOut``.

    Each Documenso field carries a numeric ``recipientId``; it is reconciled to
    the field's ``recipient_index`` (an index into the envelope's recipient
    list) **by email**: the document's ``recipients[...]`` array maps
    ``recipientId -> email`` and the persisted ``esign_recipients`` rows map
    ``email -> index`` (their stored order mirrors the original send's recipient
    order). A field whose type is unknown, or whose recipient cannot be
    reconciled, is skipped rather than guessed. Coordinates round-trip the wire
    keys (``pageNumber`` / ``pageX`` / ``pageY`` / ``width`` / ``height``) and any
    ``fieldMeta`` (``required`` / ``label`` / ``placeholder``) is read back when
    present. Pure (no I/O); never raises.
    """
    # Documenso recipientId -> email (from the live document recipients).
    email_by_recipient_id: dict[str, str] = {}
    for rr in doc.get("recipients") or []:
        if not isinstance(rr, dict):
            continue
        rid = rr.get("id") or rr.get("recipientId")
        email = rr.get("email")
        if rid is not None and isinstance(email, str) and email.strip():
            email_by_recipient_id[str(rid)] = email.strip().lower()

    # email -> recipient_index (the persisted order mirrors the send order).
    index_by_email: dict[str, int] = {}
    for idx, r in enumerate(envelope.recipients):
        if r.email:
            index_by_email[r.email.strip().lower()] = idx

    fields_out: list[FieldOut] = []
    for ff in doc.get("fields") or []:
        if not isinstance(ff, dict):
            continue
        documenso_type = str(ff.get("type") or "").upper()
        field_type = _DOCUMENSO_TYPE_TO_FIELD_TYPE.get(documenso_type)
        if field_type is None:
            # An unsupported/unknown Documenso type cannot be represented.
            continue

        rid = ff.get("recipientId") or ff.get("recipient_id")
        recipient_index: int | None = None
        if rid is not None:
            email = email_by_recipient_id.get(str(rid))
            if email is not None:
                recipient_index = index_by_email.get(email)
        if recipient_index is None:
            # Could not reconcile this field to a recipient — skip it.
            continue

        field_meta = ff.get("fieldMeta")
        field_meta = field_meta if isinstance(field_meta, dict) else {}
        required = field_meta.get("required")
        label = field_meta.get("label")
        placeholder = field_meta.get("placeholder")

        try:
            fields_out.append(
                FieldOut(
                    type=field_type,
                    page=int(ff.get("pageNumber") or ff.get("page") or 1),
                    recipient_index=recipient_index,
                    position_x=float(ff.get("pageX") or ff.get("position_x") or 0.0),
                    position_y=float(ff.get("pageY") or ff.get("position_y") or 0.0),
                    width=float(ff.get("width") or 0.0),
                    height=float(ff.get("height") or 0.0),
                    required=bool(required) if required is not None else True,
                    label=label if isinstance(label, str) else None,
                    placeholder=placeholder if isinstance(placeholder, str) else None,
                )
            )
        except (TypeError, ValueError):
            # Malformed coordinates — skip rather than fail the whole read.
            continue

    return fields_out


async def _read_documenso_document(
    db,
    *,
    org_id: UUID,
    document_id: str,
    http: httpx.AsyncClient | None,
    client: DocumensoClient | None,
    client_factory: ClientFactory | None,
) -> dict[str, Any]:
    """Read a Documenso document (recipients + fields) on this org's client.

    Mirrors the per-org client construction used by :func:`void_envelope`
    (connection gate → ``for_org`` with raw token + explicit timeout, or an
    injected ``client`` / ``client_factory`` for tests). Raises
    :class:`DocumensoError` on any read failure so the caller surfaces a
    humanized 502.
    """
    created_http: httpx.AsyncClient | None = None
    active_client = client
    if active_client is None:
        try:
            conn = await get_documenso_connection(db, org_id)
        except DocumensoNotConfiguredError:
            raise _esign_http_error(CODE_INTEGRATION_NOT_CONFIGURED) from None
        if client_factory is not None:
            active_client = client_factory(conn)
        elif http is not None:
            active_client = DocumensoClient.for_org(conn, http)
        else:
            created_http = httpx.AsyncClient(
                timeout=httpx.Timeout(DocumensoClient.DEFAULT_TIMEOUT)
            )
            active_client = DocumensoClient.for_org(conn, created_http)
    try:
        return await active_client._get_document(document_id)
    finally:
        if created_http is not None:
            await created_http.aclose()


async def get_envelope_fields(
    db,
    *,
    org_id: UUID,
    envelope_id: UUID,
    http: httpx.AsyncClient | None = None,
    client: DocumensoClient | None = None,
    client_factory: ClientFactory | None = None,
) -> EnvelopeFieldsOut:
    """Seed the field-placement editor for a sent envelope (R13.1).

    Loads the org-scoped envelope (a missing or cross-org envelope yields a
    humanized **404** that never confirms it exists elsewhere — R13.4/R13.5),
    computes the pure ``editable`` gate (``status == "sent"`` AND no recipient
    has signed), reads the document's **current** Documenso field set, and maps
    it onto :class:`EnvelopeFieldsOut` (``fields[]`` + ``recipients[]`` +
    ``editable``). When the envelope is **not** editable the response still
    carries the current fields + recipients with ``editable = false`` so the
    editor can render the Non_Editable_State banner and offer Void_And_Recreate
    (R13.4). An envelope with no mapped Documenso document id returns an empty
    field set.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        envelope_id: The envelope to read fields for.
        http / client / client_factory: Optional Documenso client injection
            (used by tests); mirrors :func:`void_envelope`.

    Returns:
        The :class:`EnvelopeFieldsOut` seeding the editor.

    Raises:
        HTTPException: ``404`` when the envelope is missing/cross-org; ``503``
            when the org's connection is missing; ``502`` on a Documenso read
            failure.
    """
    envelope = await _load_envelope_for_org(db, org_id=org_id, envelope_id=envelope_id)
    if envelope is None:
        raise _esign_http_error(CODE_NOT_FOUND)

    editable = editable_state(envelope.status, envelope.recipients)

    fields_out: list[FieldOut] = []
    if envelope.documenso_document_id:
        try:
            doc = await _read_documenso_document(
                db,
                org_id=org_id,
                document_id=envelope.documenso_document_id,
                http=http,
                client=client,
                client_factory=client_factory,
            )
        except DocumensoError as exc:
            logger.warning(
                "esign: failed to read fields for org_id=%s envelope_id=%s "
                "document_id=%s: %s",
                org_id,
                envelope_id,
                envelope.documenso_document_id,
                type(exc).__name__,
            )
            raise _esign_http_error(CODE_DOCUMENSO_ERROR) from exc
        fields_out = _field_out_list_from_documenso(doc, envelope)

    recipients_out = [RecipientOut.model_validate(r) for r in envelope.recipients]
    return EnvelopeFieldsOut(
        fields=fields_out, recipients=recipients_out, editable=editable
    )


async def _audit_fields_edited(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope: EsignEnvelope,
    field_count: int,
) -> None:
    """Write the best-effort ``esign.envelope.fields_edited`` audit entry (R13.7).

    Runs in its own SAVEPOINT via :func:`_run_best_effort` so a failure is
    logged and never rolls back the (already-applied) Documenso field replace.
    Only the envelope's own non-secret metadata is recorded — no plaintext
    credentials or document contents (R14.4).
    """
    after_value: dict[str, object] = {
        "status": envelope.status,
        "agreement_type": envelope.agreement_type,
        "originating_entity_type": envelope.originating_entity_type,
        "originating_entity_id": str(envelope.originating_entity_id),
        "field_count": field_count,
    }
    if envelope.documenso_document_id:
        after_value["documenso_document_id"] = envelope.documenso_document_id

    await _run_best_effort(
        db,
        "audit_log",
        write_audit_log(
            db,
            org_id=org_id,
            user_id=user_id,
            action=_AUDIT_ACTION_FIELDS_EDITED,
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            after_value=after_value,
        ),
    )


async def replace_envelope_fields(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope_id: UUID,
    body: FieldSetReplace,
    http: httpx.AsyncClient | None = None,
    client: DocumensoClient | None = None,
    client_factory: ClientFactory | None = None,
) -> EnvelopeFieldsOut:
    """Atomically replace a sent envelope's Field_Set in place (R13.3, R13.8).

    The router has already authorized the caller's role
    (``require_esign_sender``) and module enablement; this function performs the
    business flow:

    1. **Org-scoped load (R13.4, R13.5).** A missing or cross-org envelope
       yields a humanized **404**.
    2. **Editable_State race guard (R13.4, R13.6).** Re-check the pure
       ``editable_state`` gate (someone may have signed since the editor was
       opened). A Non_Editable_State is rejected with a humanized **422**
       (``not_editable``) that offers Void_And_Recreate, and makes **no**
       Documenso field mutation.
    3. **Server re-validation (R13.3).** Re-validate the edited Field_Set with
       the same :func:`validate_field_set` rules as a fresh send, then re-check
       the dependencies for cycles/self-loops. Either failure is a humanized
       **422** with no mutation.
    4. **Atomic Documenso replace.** Reconcile each field's ``recipient_index``
       to its Documenso ``recipientId`` by email (reusing
       :func:`_build_documenso_field_specs`) and call
       :meth:`DocumensoClient.replace_fields` (delete + ``field/create-many`` so
       only the edited set remains). On any replace failure — including the
       capability-gated "in-place replace unsupported" degrade — the prior field
       set is left in effect and a humanized **502** is returned with **no**
       partial apply (R13.8).
    5. **Audit (R13.7).** On success write a best-effort
       ``esign.envelope.fields_edited`` audit entry and return the new field set.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        user_id: The initiating user (recorded on the audit entry); may be
            ``None``.
        envelope_id: The envelope whose fields are being replaced.
        body: The validated :class:`FieldSetReplace` (≥1 field + optional
            dependencies).
        http / client / client_factory: Optional Documenso client injection
            (used by tests); mirrors :func:`void_envelope`.

    Returns:
        The :class:`EnvelopeFieldsOut` reflecting the newly-applied field set.

    Raises:
        HTTPException: ``404`` when the envelope is missing/cross-org; ``422``
            when not editable or the Field_Set / dependencies are invalid;
            ``503`` when the org's connection is missing; ``502`` on a Documenso
            replace failure.
    """
    # --- Step 1: org-scoped load (R13.4, R13.5) ---------------------------
    envelope = await _load_envelope_for_org(db, org_id=org_id, envelope_id=envelope_id)
    if envelope is None:
        raise _esign_http_error(CODE_NOT_FOUND)

    # --- Step 2: Editable_State race guard (R13.4, R13.6) -----------------
    # No Documenso mutation happens unless the envelope is still editable.
    if not editable_state(envelope.status, envelope.recipients):
        raise _esign_http_error(CODE_NOT_EDITABLE)

    # --- Step 3: server re-validation (R13.3) -----------------------------
    signer_indices = _signer_indices_for_recipients(list(envelope.recipients))
    field_result = validate_field_set(
        body.fields, envelope.recipients, signer_indices
    )
    if not field_result.ok:
        raise _esign_http_error(
            field_result.code or CODE_SERVER_ERROR, message=field_result.message
        )

    dependency_result = validate_dependencies(
        _to_graph_dependencies(body.dependencies)
    )
    if not dependency_result.ok:
        raise _esign_http_error(
            dependency_result.code or CODE_SERVER_ERROR,
            message=dependency_result.message,
        )

    # --- Step 4: atomic Documenso replace (R13.8) -------------------------
    created_http: httpx.AsyncClient | None = None
    try:
        active_client = client
        if active_client is None:
            try:
                conn = await get_documenso_connection(db, org_id)
            except DocumensoNotConfiguredError:
                raise _esign_http_error(CODE_INTEGRATION_NOT_CONFIGURED) from None
            if client_factory is not None:
                active_client = client_factory(conn)
            elif http is not None:
                active_client = DocumensoClient.for_org(conn, http)
            else:
                created_http = httpx.AsyncClient(
                    timeout=httpx.Timeout(DocumensoClient.DEFAULT_TIMEOUT)
                )
                active_client = DocumensoClient.for_org(conn, created_http)

        try:
            # Reconcile recipient_index -> Documenso recipientId by email
            # against the live document recipients (R13.3, R8.2).
            doc = await active_client._get_document(envelope.documenso_document_id)
            created_recipients = active_client._recipients_from_document(doc)
            specs = _build_documenso_field_specs(
                fields=body.fields,
                recipients=list(envelope.recipients),
                created_recipients=created_recipients,
                force_optional_client_ids=_require_effect_dependents(
                    body.dependencies
                ),
            )
            await active_client.replace_fields(
                envelope.documenso_document_id, specs
            )
        finally:
            if created_http is not None:
                await created_http.aclose()
    except DocumensoError as exc:
        # Replace failed (or in-place replace is unsupported and degrades to
        # Void_And_Recreate): the prior field set is left intact, no partial
        # apply, humanized 502 (R13.8).
        logger.warning(
            "esign: field replace failed for org_id=%s envelope_id=%s "
            "document_id=%s: %s",
            org_id,
            envelope_id,
            envelope.documenso_document_id,
            type(exc).__name__,
        )
        raise _esign_http_error(CODE_DOCUMENSO_ERROR) from exc

    # --- Step 5: best-effort audit + return the new field set (R13.7) -----
    await _audit_fields_edited(
        db,
        org_id=org_id,
        user_id=user_id,
        envelope=envelope,
        field_count=len(body.fields),
    )

    fields_out = [FieldOut.model_validate(f.model_dump()) for f in body.fields]
    recipients_out = [RecipientOut.model_validate(r) for r in envelope.recipients]
    return EnvelopeFieldsOut(
        fields=fields_out,
        recipients=recipients_out,
        editable=editable_state(envelope.status, envelope.recipients),
    )


# ---------------------------------------------------------------------------
# Webhook apply (R6, R8.3/8.4/8.5, R4.5, R13.6, R14) — invoked from the 12.1
# seam in ``webhook_router.py`` AFTER the org has been resolved by routing id,
# its per-org secret verified, and the session's RLS context scoped to the
# resolved ``org_id``.
# ---------------------------------------------------------------------------

# Human-readable notification titles per applied envelope status (R14.2). Kept
# leak-free: only the envelope's own non-secret status/agreement metadata is
# surfaced (R14.4).
_TRANSITION_NOTIFICATION = {
    "viewed": ("Agreement viewed", "info"),
    "partially_signed": ("Agreement partially signed", "info"),
    "completed": ("Agreement completed", "success"),
    "declined": ("Agreement declined", "warning"),
    "voided": ("Agreement voided", "info"),
    "sent": ("Agreement sent for signature", "info"),
}

# Documenso per-recipient ``signingStatus`` / ``readStatus`` values, mapped to
# the OraInvoice per-recipient status persisted on ``esign_recipients`` (R4.5).
_RECIPIENT_SIGNED_VALUES = frozenset({"SIGNED", "COMPLETED"})
_RECIPIENT_REJECTED_VALUES = frozenset({"REJECTED", "DECLINED"})
_RECIPIENT_OPENED_VALUES = frozenset({"OPENED"})


@dataclass(frozen=True)
class WebhookApplyResult:
    """Outcome of :func:`apply_webhook` — a small, request-context-free value
    the webhook router can act on and tests can assert against directly.

    ``outcome`` is one of:

    * ``"ignored"`` — the body could not be parsed / carried no usable event;
      nothing was recorded or modified (the handler still acknowledges 200).
    * ``"duplicate"`` — the synthesized ``dedupe_key`` was already recorded, so
      the event is acknowledged without re-applying any state change (R8.4).
    * ``"unmapped"`` — no envelope maps to the payload's document id within the
      resolved org, so nothing is modified (R8.5).
    * ``"no_transition"`` — the event mapped to no envelope-status change
      (terminal-safe / non-transitioning event); per-recipient status may still
      have been updated (R4.5).
    * ``"applied"`` — an envelope-status transition was applied (R6) plus any
      per-recipient updates; audit + notification were recorded (R14).

    ``reached_completed`` is ``True`` only when the applied transition moved the
    envelope into ``completed`` (the trigger for signed-document retrieval, R9).
    """

    outcome: str
    envelope_id: UUID | None = None
    new_status: str | None = None
    reached_completed: bool = False


def _synthesize_dedupe_key(
    *,
    event_type: str,
    documenso_document_id: str,
    recipients: list[dict[str, Any]],
    created_at: str,
) -> str:
    """Synthesize the idempotency ``dedupe_key`` for an inbound webhook (R8.3).

    The Documenso payload carries **no native event id**, so the key is a
    SHA-256 over the stable payload fields:
    ``event_type + documenso_document_id + recipient identifier/status +
    createdAt``. The recipient component is a deterministic, order-independent
    digest of each recipient's identifier paired with its signing status, so
    that two genuinely different recipient-state snapshots produce different
    keys while an identical replay produces the same key (exactly-once under
    retries/duplicates, R8.4).
    """
    recipient_parts = sorted(
        "{}:{}".format(
            str(r.get("id") or r.get("recipientId") or r.get("email") or ""),
            str(r.get("signingStatus") or r.get("status") or r.get("readStatus") or ""),
        )
        for r in recipients
    )
    recipient_repr = ";".join(recipient_parts)
    raw = "|".join(
        [event_type, documenso_document_id, recipient_repr, created_at]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _recipient_status_from_payload(rec: dict[str, Any]) -> str:
    """Map a Documenso webhook recipient entry to the persisted per-recipient
    status (R4.5).

    Documenso recipients carry ``signingStatus`` (e.g. ``NOT_SIGNED`` /
    ``SIGNED`` / ``REJECTED``) and ``readStatus`` (``NOT_OPENED`` / ``OPENED``).
    A signed recipient wins over a merely-opened one; a rejection maps to
    ``declined``; an opened-but-unsigned recipient maps to ``viewed``; anything
    else stays ``pending``.
    """
    signing = str(rec.get("signingStatus") or rec.get("status") or "").upper()
    read = str(rec.get("readStatus") or "").upper()
    if signing in _RECIPIENT_SIGNED_VALUES:
        return "signed"
    if signing in _RECIPIENT_REJECTED_VALUES:
        return "declined"
    if read in _RECIPIENT_OPENED_VALUES:
        return "viewed"
    return "pending"


def _apply_recipient_updates(
    envelope: EsignEnvelope,
    recipients_payload: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[RecipientState]:
    """Update each persisted recipient's status from the payload (R4.5) and
    return the ``RecipientState`` list the reducer consumes.

    Each payload recipient is matched to a persisted :class:`EsignRecipient`
    by Documenso recipient id first, then by case-insensitive email. A matched
    recipient's ``recipient_status`` is updated (bumping ``updated_at`` only
    when it actually changes). The returned ``RecipientState`` list reflects the
    payload's view of every recipient (``signed`` iff its mapped status is
    ``signed``), which is what ``next_status`` uses to distinguish
    ``partially_signed`` from ``completed``.
    """
    by_recipient_id: dict[str, EsignRecipient] = {}
    by_email: dict[str, EsignRecipient] = {}
    for r in envelope.recipients:
        if r.documenso_recipient_id:
            by_recipient_id[str(r.documenso_recipient_id)] = r
        if r.email:
            by_email[r.email.strip().lower()] = r

    states: list[RecipientState] = []
    for rec in recipients_payload:
        mapped_status = _recipient_status_from_payload(rec)
        states.append(RecipientState(signed=(mapped_status == "signed")))

        rec_id = rec.get("id") or rec.get("recipientId")
        target: EsignRecipient | None = None
        if rec_id is not None:
            target = by_recipient_id.get(str(rec_id))
        if target is None:
            email = str(rec.get("email") or "").strip().lower()
            if email:
                target = by_email.get(email)
        if target is not None and target.recipient_status != mapped_status:
            target.recipient_status = mapped_status
            target.updated_at = now

    return states


async def _audit_and_notify_transition(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    envelope: EsignEnvelope,
    from_status: str,
    to_status: str,
) -> None:
    """Write the audit log entry + in-app notification for a webhook-driven
    envelope-status transition (R6.8, R14.1, R14.2).

    Each side-effect runs in its own SAVEPOINT via :func:`_run_best_effort`, so
    a failure is logged and never rolls back the applied transition (R14.3).
    Only the envelope's own non-secret metadata is recorded — no plaintext
    credentials or signed-document contents (R14.4).
    """
    agreement_type = envelope.agreement_type
    after_value: dict[str, object] = {
        "status": to_status,
        "from_status": from_status,
        "agreement_type": agreement_type,
        "originating_entity_type": envelope.originating_entity_type,
        "originating_entity_id": str(envelope.originating_entity_id),
    }
    if envelope.documenso_document_id:
        after_value["documenso_document_id"] = envelope.documenso_document_id

    await _run_best_effort(
        db,
        "audit_log",
        write_audit_log(
            db,
            org_id=org_id,
            user_id=user_id,
            action=_AUDIT_ACTION_TRANSITION,
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            before_value={"status": from_status},
            after_value=after_value,
        ),
    )

    title, severity = _TRANSITION_NOTIFICATION.get(
        to_status, (f"Agreement status: {to_status}", "info")
    )
    await _run_best_effort(
        db,
        "in_app_notification",
        create_in_app_notification(
            db,
            org_id=org_id,
            category=_NOTIFICATION_CATEGORY,
            severity=severity,
            title=f"{title} ({agreement_type})",
            body=None,
            link_url="/agreements",
            entity_type=_AUDIT_ENTITY_TYPE,
            entity_id=envelope.id,
            audience_roles=_NOTIFICATION_AUDIENCE,
        ),
    )


async def _trigger_signed_document_retrieval(
    *, org_id: UUID, envelope_id: UUID
) -> None:
    """Trigger signed-document retrieval after an envelope reaches ``completed``
    (R9.1) — best-effort, on a FRESH session post-commit.

    === TASK 13.1 SEAM ==================================================
    The retrieve-and-store-signed-document implementation lives in
    ``app/modules/esignatures/signed_document.py`` (task 13.1), which may be
    implemented after / concurrently with this task. To avoid a hard import
    failure while 13.1 is in flight, the module is imported **lazily** here and
    its entrypoint is resolved defensively:

        from app.modules.esignatures import signed_document
        await signed_document.retrieve_and_store_signed_document(
            org_id=org_id, envelope_id=envelope_id
        )

    Contract expected of task 13.1: an awaitable
    ``retrieve_and_store_signed_document(*, org_id: UUID, envelope_id: UUID)``
    that opens its OWN fresh session (the webhook transaction has already
    committed and closed — ISSUE-005/048 fresh-session pattern), sets the RLS
    context to ``org_id``, downloads + encrypted-pipeline-stores the signed PDF,
    and stamps ``signed_doc_status`` on the envelope.

    If the module or entrypoint is not present yet, this is a no-op: the
    envelope stays ``completed`` with ``signed_doc_status='none'`` and the
    scheduled retry sweep (task 13.3) picks it up. Any retrieval error is
    swallowed here (logged) so it never turns a successful 200 webhook ack into
    a failure — retrieval is independently retried by the sweep (R9.5).
    =====================================================================
    """
    try:
        from app.modules.esignatures import signed_document  # noqa: WPS433
    except ImportError:
        logger.info(
            "esign: signed-document retrieval module not available yet "
            "(task 13.1); scheduled sweep will retrieve for envelope_id=%s",
            envelope_id,
        )
        return

    entrypoint = getattr(
        signed_document, "retrieve_and_store_signed_document", None
    )
    if entrypoint is None:
        logger.info(
            "esign: signed-document retrieval entrypoint not available yet "
            "(task 13.1); scheduled sweep will retrieve for envelope_id=%s",
            envelope_id,
        )
        return

    try:
        await entrypoint(org_id=org_id, envelope_id=envelope_id)
    except Exception:  # pragma: no cover - retrieval is independently retried
        logger.warning(
            "esign: signed-document retrieval failed for envelope_id=%s "
            "(best-effort; scheduled sweep will retry)",
            envelope_id,
            exc_info=True,
        )


async def apply_webhook(
    db,
    *,
    org_id: UUID,
    raw_body: bytes,
    user_id: UUID | None = None,
) -> WebhookApplyResult:
    """Apply a verified Documenso webhook to the resolved org's state (R8/R6/R4.5).

    Invoked from the 12.1 seam in ``webhook_router.py`` **after** the org has
    been resolved by ``routing_id``, its per-org ``X-Documenso-Secret`` verified
    with a constant-time compare, and the session's RLS context scoped to the
    resolved ``org_id``. This function:

    1. Parses the body ``{ event, payload: { id, status, recipients[...] },
       createdAt }``. A body that cannot be parsed / carries no event id is a
       safe no-op (``ignored``) — the handler still acknowledges 200.
    2. **Idempotency (R8.3, R8.4).** Synthesizes ``dedupe_key`` =
       ``SHA-256(event_type + documenso_document_id + recipient identifier/status
       + createdAt)`` (the payload has no native event id) and inserts it into
       ``esign_webhook_events`` (UNIQUE), stamped with the resolved ``org_id``
       (R13.6). The insert is the source of truth: a unique-violation (race-safe)
       means the event was already processed → acknowledge without re-applying
       (``duplicate``).
    3. **Unmapped document (R8.5).** Resolves the envelope by
       ``documenso_document_id`` within the resolved org. If none maps, the
       event is acknowledged without modifying any envelope (``unmapped``); the
       dedupe key is still recorded so retries stay no-ops.
    4. **Per-recipient update (R4.5)** + **terminal-safe transition (R6).**
       Updates each persisted recipient's status from the payload and computes
       ``next_status(current, event, recipients_state)``. When it returns a new
       status, the envelope transitions (terminal envelopes never regress);
       when it returns ``None`` (terminal / no-op), the status is unchanged.
    5. **Audit + notify (R14)** on every applied transition (best-effort).
    6. **Signed-document retrieval (R9)** is triggered after commit when the
       envelope reaches ``completed`` (see :func:`_trigger_signed_document_retrieval`).

    This function **owns the transaction**: it commits the recorded event +
    recipient/status changes before returning, so the post-commit
    signed-document retrieval runs against committed state on a fresh session.
    It never raises — a verified webhook is always acknowledged 200 by the
    handler; failures degrade to a logged no-op.

    Args:
        db: The webhook session, already RLS-scoped to ``org_id`` by the handler.
        org_id: The organisation resolved from the webhook routing id.
        raw_body: The raw request body bytes.
        user_id: Always ``None`` on the public webhook path (no user context);
            accepted for symmetry with the other audit helpers.

    Returns:
        A :class:`WebhookApplyResult` describing what happened.
    """
    # --- Step 1: parse the body (a bad body is a safe no-op) --------------
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (ValueError, UnicodeDecodeError):
        logger.warning("esign webhook: body was not valid JSON; ignoring")
        await _safe_rollback(db)
        return WebhookApplyResult(outcome="ignored")

    if not isinstance(body, dict):
        await _safe_rollback(db)
        return WebhookApplyResult(outcome="ignored")

    event_type = str(body.get("event") or "")
    payload = body.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    documenso_document_id = payload.get("id")
    documenso_document_id = (
        str(documenso_document_id) if documenso_document_id is not None else ""
    )
    created_at = str(body.get("createdAt") or "")
    recipients_payload = payload.get("recipients")
    recipients_payload = (
        [r for r in recipients_payload if isinstance(r, dict)]
        if isinstance(recipients_payload, list)
        else []
    )

    # A webhook with neither an event nor a document id carries nothing to
    # dedupe or apply — treat as a safe no-op.
    if not event_type and not documenso_document_id:
        await _safe_rollback(db)
        return WebhookApplyResult(outcome="ignored")

    # --- Step 2: idempotency (R8.3, R8.4) ---------------------------------
    dedupe_key = _synthesize_dedupe_key(
        event_type=event_type,
        documenso_document_id=documenso_document_id,
        recipients=recipients_payload,
        created_at=created_at,
    )

    event_row = EsignWebhookEvent(
        org_id=org_id,
        dedupe_key=dedupe_key,
        event_type=event_type or None,
        documenso_document_id=documenso_document_id or None,
        payload=body,
    )
    try:
        async with db.begin_nested():
            db.add(event_row)
            await db.flush()
    except IntegrityError:
        # The UNIQUE(dedupe_key) constraint is the source of truth: a violation
        # means this exact event was already processed (R8.4). Acknowledge
        # without re-applying any state change. The savepoint already rolled
        # back the duplicate insert; nothing else was written.
        logger.info(
            "esign webhook: duplicate event (dedupe_key already recorded); "
            "acknowledging without re-applying"
        )
        await _safe_commit(db)
        return WebhookApplyResult(outcome="duplicate")

    # --- Step 3: resolve the envelope within the resolved org (R8.5) ------
    envelope: EsignEnvelope | None = None
    if documenso_document_id:
        result = await db.execute(
            select(EsignEnvelope).where(
                EsignEnvelope.documenso_document_id == documenso_document_id,
                EsignEnvelope.org_id == org_id,
            )
        )
        envelope = result.scalar_one_or_none()

    if envelope is None:
        # Document maps to no envelope in this org — acknowledge, modify
        # nothing further. The dedupe key stays recorded so retries are no-ops.
        logger.info(
            "esign webhook: document id maps to no envelope in org; "
            "acknowledging without modification"
        )
        await _safe_commit(db)
        return WebhookApplyResult(outcome="unmapped")

    # --- Step 4: per-recipient update (R4.5) + terminal-safe transition ----
    now = datetime.now(timezone.utc)
    recipients_state = _apply_recipient_updates(
        envelope, recipients_payload, now=now
    )

    from_status = envelope.status
    to_status = next_status(from_status, event_type, recipients_state)

    reached_completed = False
    if to_status is not None and to_status != from_status:
        envelope.status = to_status
        envelope.updated_at = now
        db.add(envelope)
        await db.flush()

        # --- Step 5: audit + notify on the applied transition (R14) -------
        await _audit_and_notify_transition(
            db,
            org_id=org_id,
            user_id=user_id,
            envelope=envelope,
            from_status=from_status,
            to_status=to_status,
        )
        reached_completed = to_status == "completed"
        outcome = "applied"
    else:
        outcome = "no_transition"

    await _safe_commit(db)

    # --- Step 6: signed-document retrieval on completion (R9) -------------
    # Post-commit + fresh session (ISSUE-005/048) — see the 13.1 seam.
    if reached_completed:
        await _trigger_signed_document_retrieval(
            org_id=org_id, envelope_id=envelope.id
        )

    return WebhookApplyResult(
        outcome=outcome,
        envelope_id=envelope.id,
        new_status=envelope.status,
        reached_completed=reached_completed,
    )


async def _safe_commit(db) -> None:
    """Commit the webhook session, swallowing/logging any failure.

    A verified webhook is always acknowledged 200 by the handler; a commit
    failure must not turn that into a 500. On failure the transaction is rolled
    back so the session is left clean.
    """
    try:
        await db.commit()
    except Exception:  # pragma: no cover - defensive
        logger.warning("esign webhook: commit failed; rolling back", exc_info=True)
        await _safe_rollback(db)


async def _safe_rollback(db) -> None:
    """Roll back the webhook session, swallowing/logging any failure."""
    try:
        await db.rollback()
    except Exception:  # pragma: no cover - defensive
        logger.warning("esign webhook: rollback failed", exc_info=True)
