"""Org-scoped CRUD for saved Field_Templates (R17).

A Field_Template is a reusable, named, **organisation-scoped** collection of
placed fields — their type, page, normalized coordinates, required flag, and
(for ``text``) label/placeholder — each carrying an abstract
``Template_Recipient_Role`` slot rather than a specific person. A template
stores **roles, never people**: no recipient name or email is ever persisted
(R17.1). A template may optionally be associated with one agreement type
(R17.2).

This module owns the create / list / get / delete flow over the
:class:`~app.modules.esignatures.models.EsignFieldTemplate` ORM model
(``esign_field_templates`` table). The router (task 21.1) applies the
authentication, module-gate and RBAC (``require_esign_sender``) dependencies and
passes the resolved ``org_id`` plus calling user; this service performs the
business flow only.

Org-scoping is enforced **twice** (mirroring ``service.py``): the request
session's RLS context is already scoped to ``org_id`` (so cross-org rows are
invisible), **and** every statement carries an explicit ``org_id`` predicate as
a belt-and-braces ownership check (R17.3, R17.4). A missing or cross-org
template yields a humanized **404** (``template_not_found``) that never confirms
the template exists for another organisation.

Persistence follows the project rule: use ``flush()`` (not ``commit()`` — the
``get_db_session`` dependency auto-commits) then ``await db.refresh(obj)``
before returning ORM objects for Pydantic serialisation (prevents
``MissingGreenlet``).

Refs: requirements 17.1, 17.2, 17.3, 17.4; design §"Saved field templates".
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.modules.esignatures.errors import (
    CODE_TEMPLATE_NOT_FOUND,
    esign_error,
    status_for_code,
)
from app.modules.esignatures.models import EsignFieldTemplate
from app.modules.esignatures.schemas import (
    FieldTemplateCreate,
    FieldTemplateListResponse,
    FieldTemplateOut,
)

logger = logging.getLogger(__name__)


def _esign_http_error(code: str, *, message: str | None = None) -> HTTPException:
    """Build an :class:`HTTPException` carrying the humanized ``{message, code}``.

    The HTTP status code is derived from the design's Error Handling table via
    :func:`status_for_code`, and the body matches the module's canonical error
    shape (``detail = { "message", "code" }``). Raw exception text is never
    embedded (R15.5). Mirrors the same helper in ``service.py``.
    """
    err = esign_error(code, message=message)
    return HTTPException(
        status_code=status_for_code(err.code),
        detail=err.model_dump(),
    )


async def _load_template_for_org(
    db, *, org_id: UUID, template_id: UUID
) -> EsignFieldTemplate | None:
    """Load a template under the org's RLS context, ownership-checked.

    The request session's RLS context is already scoped to ``org_id`` so a
    cross-org row is invisible; the explicit ``org_id`` predicate is a
    belt-and-braces ownership check (R17.3, R17.4). Returns ``None`` when the
    template does not exist for this organisation — the caller maps that to a
    404 that never confirms the template exists elsewhere.
    """
    result = await db.execute(
        select(EsignFieldTemplate).where(
            EsignFieldTemplate.id == template_id,
            EsignFieldTemplate.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def create_template(
    db,
    *,
    org_id: UUID,
    user_id: UUID | None,
    payload: FieldTemplateCreate,
) -> EsignFieldTemplate:
    """Persist a new org-scoped Field_Template (R17.1, R17.2).

    Stores the template ``name``, optional ``agreement_type`` association
    (R17.2), the placed ``fields`` (each carrying its type, page, normalized
    coordinates, required flag, optional label/placeholder, and abstract
    ``template_role`` slot), and the distinct ``roles`` set — all as JSONB.
    **No recipient name or email is ever stored** (R17.1): the payload schema
    (:class:`FieldTemplateCreate` / :class:`~app.modules.esignatures.schemas.TemplateFieldIn`)
    carries only roles, so dumping it cannot leak a person.

    Uses ``flush()`` (not ``commit()`` — ``get_db_session`` auto-commits) then
    ``await db.refresh()`` before returning so the row is fully populated
    (server defaults for ``created_at`` / ``updated_at``) for Pydantic
    serialisation.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The owning organisation.
        user_id: The initiating user (stored as ``created_by``); may be ``None``.
        payload: The validated create payload.

    Returns:
        The persisted, refreshed :class:`EsignFieldTemplate`.
    """
    template = EsignFieldTemplate(
        org_id=org_id,
        name=payload.name,
        agreement_type=payload.agreement_type,
        # Dump to plain JSON-serialisable structures for the JSONB columns. The
        # schema carries only roles (``template_role``) — never a person — so
        # this can never persist a recipient name/email (R17.1).
        fields=[field.model_dump() for field in payload.fields],
        roles=list(payload.roles),
        created_by=user_id,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def list_templates(
    db,
    *,
    org_id: UUID,
) -> FieldTemplateListResponse:
    """List the calling organisation's Field_Templates (R17.3).

    Returns the org's templates wrapped in ``{ items, total }`` per project
    convention, newest-updated first. Org-scoping is enforced by RLS *and* an
    explicit ``org_id`` predicate, so another organisation's templates are
    never returned and an org with none gets an empty list (R17.3).

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.

    Returns:
        A :class:`FieldTemplateListResponse` with the org's templates.
    """
    stmt = (
        select(EsignFieldTemplate)
        .where(EsignFieldTemplate.org_id == org_id)
        # Most-recently-updated first; tie-break on id for a deterministic order
        # when two templates share an ``updated_at``.
        .order_by(
            EsignFieldTemplate.updated_at.desc(),
            EsignFieldTemplate.id.desc(),
        )
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()
    items = [FieldTemplateOut.model_validate(t) for t in templates]
    return FieldTemplateListResponse(items=items, total=len(items))


async def get_template(
    db,
    *,
    org_id: UUID,
    template_id: UUID,
) -> EsignFieldTemplate:
    """Fetch one org-scoped Field_Template (used to apply it, R17.3).

    Loads the template under the org's RLS context with an explicit ``org_id``
    ownership predicate. A missing or cross-org template yields a humanized
    **404** (``template_not_found``) that never confirms the template exists
    for another organisation.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        template_id: The template to read.

    Returns:
        The :class:`EsignFieldTemplate` for the requested id.

    Raises:
        HTTPException: ``404`` when the template is missing or belongs to
            another organisation.
    """
    template = await _load_template_for_org(
        db, org_id=org_id, template_id=template_id
    )
    if template is None:
        raise _esign_http_error(CODE_TEMPLATE_NOT_FOUND)
    return template


async def delete_template(
    db,
    *,
    org_id: UUID,
    template_id: UUID,
) -> None:
    """Delete one Field_Template within the caller's organisation (R17.4).

    Removes **only** the caller-org's template: the row is loaded under the
    org's RLS context with an explicit ``org_id`` ownership predicate, so a
    cross-org template is never deleted and instead yields a humanized **404**
    (``template_not_found``) that never confirms it exists elsewhere (R17.4).

    Uses ``flush()`` (not ``commit()`` — ``get_db_session`` auto-commits) so the
    delete is staged within the request transaction.

    Args:
        db: The request-scoped async session (RLS already scoped to ``org_id``).
        org_id: The calling organisation.
        template_id: The template to delete.

    Raises:
        HTTPException: ``404`` when the template is missing or belongs to
            another organisation.
    """
    template = await _load_template_for_org(
        db, org_id=org_id, template_id=template_id
    )
    if template is None:
        raise _esign_http_error(CODE_TEMPLATE_NOT_FOUND)
    await db.delete(template)
    await db.flush()
