"""Org-user ``/api/v2/esign`` endpoints (the Agreements API surface).

This router exposes the organisation-user e-signature endpoints — the send /
list / detail / void / signed-document surface backed by
:mod:`app.modules.esignatures.service`. It is mounted under ``/api/v2/esign``
in :mod:`app.main` and sits behind the standard JWT auth + tenant-context
middleware (so ``request.state.org_id`` / ``request.state.user_id`` are
resolved before any handler runs), exactly like the other ``/api/v2`` routers.

Routes
------
* ``POST   /envelopes``                       create + send (multipart PDF + JSON)
* ``GET    /envelopes``                       list (optional ``?status=`` filter)
* ``GET    /envelopes/{id}``                  envelope detail
* ``POST   /envelopes/{id}/void``             void a non-terminal envelope
* ``GET    /envelopes/{id}/signed-document``  download the stored signed PDF

Gating
------
Every route carries the router-level module gate
:func:`~app.modules.esignatures.dependencies.require_esign_module` (HTTP 403
when the ``esignatures`` module is disabled, R2.2) — defence-in-depth alongside
the ``MODULE_ENDPOINT_MAP`` middleware entry. The two **mutating** routes (send
and void) additionally carry the RBAC gate
:data:`~app.modules.esignatures.dependencies.require_esign_sender` (HTTP 403 for
any role other than ``org_admin`` / ``branch_admin`` / ``location_manager``,
R12). The public per-org webhook ingestion route is a *separate* router
(``webhook_router.py``, task 12.x) and is intentionally NOT mounted here, so it
is neither module-gated nor JWT-gated.

The webhook route is out of scope for this router (task 10.1 covers the org-user
endpoints only).

Refs: requirements 2.2, 11.1, 12.1, 12.2, 12.3, 13.4, 13.5; design
§"Components and Interfaces", §"Agreements dashboard".
"""

from __future__ import annotations

import logging
import zlib
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.encryption import envelope_decrypt
from app.modules.esignatures import service as esign_service
from app.modules.esignatures import templates_service
from app.modules.esignatures.dependencies import (
    require_esign_module,
    require_esign_sender,
)
from app.modules.esignatures.errors import (
    CODE_NOT_FOUND,
    CODE_SERVER_ERROR,
    esign_error,
    status_for_code,
)
from app.modules.esignatures.schemas import (
    EnvelopeCreate,
    EnvelopeFieldsOut,
    EnvelopeListResponse,
    EnvelopeOut,
    FieldSetReplace,
    FieldTemplateCreate,
    FieldTemplateListResponse,
    FieldTemplateOut,
)
from app.modules.uploads.router import COMP_ZLIB, UPLOAD_BASE

logger = logging.getLogger(__name__)

# Every route in this router is module-gated (R2.2). The webhook route lives in
# a separate, ungated router (task 12.x) so it is unaffected by this dependency.
router = APIRouter(dependencies=[Depends(require_esign_module)])


# ---------------------------------------------------------------------------
# Request-context helpers (mirrors the established v2-router pattern)
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    """Resolve the requesting organisation id from request state (else 401)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    """Resolve the calling user id from request state (``None`` when absent)."""
    raw = getattr(request.state, "user_id", None)
    if raw is None:
        return None
    try:
        return raw if isinstance(raw, UUID) else UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _esign_http_error(code: str, *, message: str | None = None) -> HTTPException:
    """Build an :class:`HTTPException` with the humanized ``{message, code}`` body."""
    err = esign_error(code, message=message)
    return HTTPException(status_code=status_for_code(err.code), detail=err.model_dump())


# ---------------------------------------------------------------------------
# POST /envelopes — create + send (multipart PDF + JSON body)
# ---------------------------------------------------------------------------


@router.post(
    "/envelopes",
    response_model=EnvelopeOut,
    status_code=201,
    dependencies=[require_esign_sender],
    summary="Create and send an envelope for signature",
    responses={
        403: {"description": "Module disabled or insufficient role"},
        422: {"description": "Validation error (non-PDF / no recipients / bad email)"},
        502: {"description": "Documenso API failure (envelope recorded with error status)"},
        503: {"description": "Organisation's Documenso connection not configured/verified"},
    },
)
async def create_envelope(
    request: Request,
    file: UploadFile = File(..., description="The source PDF to send for signature"),
    payload: str = Form(
        ...,
        description="EnvelopeCreate JSON (agreement_type, originating entity, recipients)",
    ),
    db: AsyncSession = Depends(get_db_session),
) -> EnvelopeOut:
    """Create a Documenso document from the uploaded PDF and send it for signature.

    The source PDF arrives as a multipart ``UploadFile`` (``file``) alongside the
    :class:`EnvelopeCreate` body, supplied as a JSON string in the ``payload``
    form field. The service performs the connection gate, pure PDF/recipient
    validation, the multi-step Documenso flow, and persistence; the router only
    parses the multipart inputs and resolves the org/user context (RBAC +
    module gate are enforced by the route dependencies).
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    try:
        create_payload = EnvelopeCreate.model_validate_json(payload)
    except ValidationError as exc:
        # Surface a humanized 422 without leaking raw exception internals.
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The agreement details are invalid. Check the "
                "agreement type, originating entity, and recipients.",
                "code": "invalid_payload",
                "errors": exc.errors(include_url=False, include_input=False),
            },
        ) from None

    pdf_bytes = await file.read()

    envelope = await esign_service.create_and_send_envelope(
        db,
        org_id=org_id,
        user_id=user_id,
        payload=create_payload,
        pdf_bytes=pdf_bytes,
        title=file.filename,
    )
    # A freshly-sent envelope never has a stored signed document, so the
    # service serializer (link present iff stored) yields signed_document_url=None.
    return esign_service._envelope_to_out(envelope)


# ---------------------------------------------------------------------------
# GET /envelopes — dashboard list (optional ?status= filter)
# ---------------------------------------------------------------------------


@router.get(
    "/envelopes",
    summary="List the organisation's envelopes (optional ?status= filter)",
    responses={
        200: {"description": "Envelope list; fail-closed filter error is also 200"},
        403: {"description": "Module disabled"},
    },
)
async def list_envelopes(
    request: Request,
    status: str | None = Query(
        default=None, description="Optional Envelope_Status filter"
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """List the calling organisation's envelopes, newest-updated first (R11).

    Org-scoped by RLS + an explicit ``org_id`` predicate, wrapped as
    ``{ items, total }`` (R11.1, R13.3). When an unapplyable ``?status=`` filter
    is supplied the service fails **closed** (R11.6): this returns HTTP **200**
    with **no** envelopes plus a humanized ``error`` ({message, code}) in the
    body rather than an unfiltered list.
    """
    org_id = _get_org_id(request)
    response, error = await esign_service.list_envelopes(db, org_id=org_id, status=status)

    if error is not None:
        # Fail-closed filter: 200 with empty items + a humanized error in body.
        body = response.model_dump()
        body["error"] = error.model_dump()
        return JSONResponse(status_code=200, content=jsonable(body))

    return response


# ---------------------------------------------------------------------------
# GET /envelopes/{id} — envelope detail
# ---------------------------------------------------------------------------


@router.get(
    "/envelopes/{envelope_id}",
    response_model=EnvelopeOut,
    summary="Get one envelope's detail (per-recipient status + signed-doc link)",
    responses={
        403: {"description": "Module disabled"},
        404: {"description": "Envelope not found / belongs to another organisation"},
    },
)
async def get_envelope(
    envelope_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> EnvelopeOut:
    """Return the envelope's per-recipient signing status and signed-document link.

    Org-checked: a missing or cross-org envelope yields a humanized 404 that
    never confirms the envelope exists for another organisation (R13.4, R13.5).
    """
    org_id = _get_org_id(request)
    return await esign_service.get_envelope_detail(db, org_id=org_id, envelope_id=envelope_id)


# ---------------------------------------------------------------------------
# POST /envelopes/{id}/void — void a non-terminal envelope
# ---------------------------------------------------------------------------


@router.post(
    "/envelopes/{envelope_id}/void",
    response_model=EnvelopeOut,
    dependencies=[require_esign_sender],
    summary="Void a non-terminal envelope",
    responses={
        403: {"description": "Module disabled or insufficient role"},
        404: {"description": "Envelope not found / belongs to another organisation"},
        409: {"description": "Envelope already terminal (cannot be voided)"},
        502: {"description": "Documenso API failure"},
    },
)
async def void_envelope(
    envelope_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> EnvelopeOut:
    """Void a non-terminal envelope, cancelling it in Documenso (R7, R12.3).

    Rejects a terminal envelope with a humanized 409 and makes no Documenso
    call; a cross-org/missing envelope yields a 404.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    envelope = await esign_service.void_envelope(
        db,
        org_id=org_id,
        user_id=user_id,
        envelope_id=envelope_id,
    )
    return esign_service._envelope_to_out(envelope)


# ---------------------------------------------------------------------------
# GET /envelopes/{id}/signed-document — stream the stored signed PDF
# ---------------------------------------------------------------------------


def _read_stored_signed_document(file_key: str) -> bytes:
    """Read + decrypt a signed PDF stored via the encrypted uploads pipeline.

    The signed document is stored by the signed-document retrieval pipeline
    (task 13.x) through the same ``app/modules/uploads`` envelope-encryption
    flow used for every other encrypted upload: each file is ``flag + envelope
    encrypted(payload)`` on disk under ``UPLOAD_BASE/<file_key>``. Signed PDFs
    are zlib-compressed (``COMP_ZLIB``). This helper mirrors the uploads
    ``download_file`` read path and is path-traversal safe (the resolved path
    must live under ``UPLOAD_BASE``).
    """
    fp = UPLOAD_BASE / file_key
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise _esign_http_error(CODE_NOT_FOUND) from None
    if not fp.is_file():
        # Recorded as stored but the bytes are missing — treat as not found.
        raise _esign_http_error(CODE_NOT_FOUND) from None
    raw = fp.read_bytes()
    if len(raw) < 2:
        raise _esign_http_error(CODE_SERVER_ERROR) from None
    flag, blob = raw[0:1], raw[1:]
    try:
        decrypted = envelope_decrypt(blob)
    except Exception:  # noqa: BLE001 - never leak crypto internals
        raise _esign_http_error(CODE_SERVER_ERROR) from None
    return zlib.decompress(decrypted) if flag == COMP_ZLIB else decrypted


@router.get(
    "/envelopes/{envelope_id}/signed-document",
    summary="Download the stored signed PDF for an envelope",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The signed PDF"},
        403: {"description": "Module disabled"},
        404: {"description": "Envelope not found, cross-org, or signed doc not yet stored"},
    },
)
async def download_signed_document(
    envelope_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Serve the stored signed PDF for an envelope (org-checked, R13.4/13.5).

    The signed document is served from the encrypted uploads pipeline only when
    it has actually been stored (``signed_doc_status == 'stored'`` with a
    recorded ``signed_doc_file_key``). When the envelope is missing or belongs
    to another organisation, or no signed document has been stored yet (the
    retrieval/storage pipeline is task 13.x), a humanized 404 is returned —
    never confirming the envelope exists for another org.
    """
    org_id = _get_org_id(request)
    envelope = await esign_service._load_envelope_for_org(
        db, org_id=org_id, envelope_id=envelope_id
    )
    if envelope is None:
        raise _esign_http_error(CODE_NOT_FOUND)

    if envelope.signed_doc_status != "stored" or not envelope.signed_doc_file_key:
        # No signed document stored yet (or never will be) — nothing to serve.
        raise _esign_http_error(
            CODE_NOT_FOUND,
            message="The signed document for this agreement is not available yet.",
        )

    content = _read_stored_signed_document(envelope.signed_doc_file_key)
    filename = f"signed-agreement-{envelope.id}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


# ---------------------------------------------------------------------------
# GET /envelopes/{id}/fields — seed the editor with the live Field_Set (R13.1)
# ---------------------------------------------------------------------------


@router.get(
    "/envelopes/{envelope_id}/fields",
    response_model=EnvelopeFieldsOut,
    summary="Get an envelope's current Field_Set, recipients, and editable flag",
    responses={
        403: {"description": "Module disabled"},
        404: {"description": "Envelope not found / belongs to another organisation"},
        502: {"description": "Documenso API failure reading the field set"},
        503: {"description": "Organisation's Documenso connection not configured"},
    },
)
async def get_envelope_fields(
    envelope_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> EnvelopeFieldsOut:
    """Seed the field-placement editor for a sent envelope (R13.1).

    Returns the envelope's current Documenso Field_Set, its recipients (so
    fields can be re-assigned), and the pure ``editable`` gate (``status ==
    "sent"`` AND no recipient has signed). A missing or cross-org envelope
    yields a humanized 404 that never confirms it exists elsewhere (R13.4,
    R13.5). When not editable the response still carries the current fields +
    recipients with ``editable = false`` so the editor can render the
    Non_Editable_State banner and offer Void_And_Recreate.
    """
    org_id = _get_org_id(request)
    return await esign_service.get_envelope_fields(
        db, org_id=org_id, envelope_id=envelope_id
    )


# ---------------------------------------------------------------------------
# PUT /envelopes/{id}/fields — atomically replace the Field_Set (R13.3, R13.8)
# ---------------------------------------------------------------------------


@router.put(
    "/envelopes/{envelope_id}/fields",
    response_model=EnvelopeFieldsOut,
    dependencies=[require_esign_sender],
    summary="Replace a sent envelope's Field_Set in place",
    responses={
        403: {"description": "Module disabled or insufficient role"},
        404: {"description": "Envelope not found / belongs to another organisation"},
        422: {"description": "Not editable (a recipient has signed) or invalid Field_Set"},
        502: {"description": "Documenso API failure (prior field set left intact)"},
        503: {"description": "Organisation's Documenso connection not configured"},
    },
)
async def replace_envelope_fields(
    envelope_id: UUID,
    request: Request,
    body: FieldSetReplace,
    db: AsyncSession = Depends(get_db_session),
) -> EnvelopeFieldsOut:
    """Atomically replace a sent envelope's Field_Set in place (R13.3, R13.8).

    Re-checks the pure editable gate (a Non_Editable_State yields a humanized
    422 ``not_editable`` that offers Void_And_Recreate and makes no Documenso
    mutation, R13.4), re-validates the edited Field_Set with the same rules as
    an initial send (422 on failure), then reconciles each field's recipient and
    replaces the Documenso fields atomically (a replace failure leaves the prior
    set intact and returns a humanized 502, R13.8). RBAC
    (``require_esign_sender``, R13.2) and the module gate are enforced by the
    route + router dependencies. Returns the newly-applied Field_Set.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    return await esign_service.replace_envelope_fields(
        db,
        org_id=org_id,
        user_id=user_id,
        envelope_id=envelope_id,
        body=body,
    )


# ---------------------------------------------------------------------------
# POST /field-templates — create a reusable Field_Template
# ---------------------------------------------------------------------------


@router.post(
    "/field-templates",
    response_model=FieldTemplateOut,
    status_code=201,
    dependencies=[require_esign_sender],
    summary="Save the current Field_Set as a reusable, org-scoped template",
    responses={
        403: {"description": "Module disabled or insufficient role"},
        422: {"description": "Validation error (empty name / no fields / no roles)"},
    },
)
async def create_field_template(
    request: Request,
    payload: FieldTemplateCreate,
    db: AsyncSession = Depends(get_db_session),
) -> FieldTemplateOut:
    """Persist a reusable, org-scoped Field_Template (R17.1, R17.2).

    Stores roles, never people — the payload carries only abstract
    ``template_role`` slots, so no recipient name or email is ever persisted
    (R17.1). RBAC (``require_esign_sender``) and the module gate are enforced by
    the route + router dependencies; the org/user context is resolved here.
    """
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    template = await templates_service.create_template(
        db,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    return FieldTemplateOut.model_validate(template)


# ---------------------------------------------------------------------------
# GET /field-templates — list the organisation's templates
# ---------------------------------------------------------------------------


@router.get(
    "/field-templates",
    response_model=FieldTemplateListResponse,
    summary="List the organisation's saved Field_Templates",
    responses={
        403: {"description": "Module disabled"},
    },
)
async def list_field_templates(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> FieldTemplateListResponse:
    """List the calling organisation's Field_Templates, newest-updated first (R17.3).

    Org-scoped by RLS + an explicit ``org_id`` predicate and wrapped as
    ``{ items, total }`` per project convention; an org with none gets an empty
    list.
    """
    org_id = _get_org_id(request)
    return await templates_service.list_templates(db, org_id=org_id)


# ---------------------------------------------------------------------------
# GET /field-templates/{id} — fetch one template
# ---------------------------------------------------------------------------


@router.get(
    "/field-templates/{template_id}",
    response_model=FieldTemplateOut,
    summary="Get one saved Field_Template (to apply it)",
    responses={
        403: {"description": "Module disabled"},
        404: {"description": "Template not found / belongs to another organisation"},
    },
)
async def get_field_template(
    template_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> FieldTemplateOut:
    """Return one org-scoped Field_Template (R17.3).

    A missing or cross-org template yields a humanized 404 that never confirms
    the template exists for another organisation.
    """
    org_id = _get_org_id(request)
    template = await templates_service.get_template(
        db, org_id=org_id, template_id=template_id
    )
    return FieldTemplateOut.model_validate(template)


# ---------------------------------------------------------------------------
# DELETE /field-templates/{id} — delete one template
# ---------------------------------------------------------------------------


@router.delete(
    "/field-templates/{template_id}",
    status_code=204,
    dependencies=[require_esign_sender],
    summary="Delete one saved Field_Template",
    responses={
        403: {"description": "Module disabled or insufficient role"},
        404: {"description": "Template not found / belongs to another organisation"},
    },
)
async def delete_field_template(
    template_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Delete one Field_Template within the caller's organisation (R17.4).

    Removes only the caller-org's template; a cross-org/missing template yields
    a humanized 404 that never confirms it exists elsewhere. RBAC
    (``require_esign_sender``) and the module gate are enforced by the
    route + router dependencies.
    """
    org_id = _get_org_id(request)
    await templates_service.delete_template(
        db, org_id=org_id, template_id=template_id
    )
    return Response(status_code=204)


def jsonable(value):
    """Local import shim for ``fastapi.encoders.jsonable_encoder``.

    Kept as a tiny indirection so the list endpoint can serialise the
    ``{ items, total, error }`` fail-closed body (with UUID/datetime fields)
    without importing the encoder at module import time.
    """
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)
