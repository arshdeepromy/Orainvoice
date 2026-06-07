"""Email compose router — ``GET /api/v2/email-preview``.

Single read endpoint backing the Send Email Modal. Given
``(template_type, entity_type, entity_id)`` plus the JWT-derived ``org_id``,
it resolves the default subject + body, recipients, attachments, sender
identity, and blocklist via :func:`build_email_preview`.

Middleware posture (R25): authenticated (the path is NOT in ``PUBLIC_PATHS`` /
``PUBLIC_PREFIXES``), the RLS GUC ``app.current_org_id`` is set by the existing
auth dependency chain, ``require_role`` gates the role, and the standard
per-user rate limit applies (no exemption). Being a GET it carries no CSRF
requirement but still requires a valid JWT (R8.11).

Design ref: Backend Components → ``router.py``.
Requirements: 3.1, 3.7, 8.11, 18.3, 25.1, 25.2, 25.3, 25.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.request_utils import extract_request_base_url
from app.modules.auth.rbac import require_role
from app.modules.email_compose.schemas import EmailPreviewResponse
from app.modules.email_compose.service import EntityNotFound, build_email_preview

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.get(
    "/email-preview",
    response_model=EmailPreviewResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required / permission denied"},
        404: {"description": "Entity not found"},
    },
    summary="Resolve default Send Email content for a surface",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def email_preview_endpoint(
    request: Request,
    template_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the default subject/body/recipients/attachments for a surface.

    Maps :class:`EntityNotFound` → 404 and ``PermissionError`` → 403 so a
    missing or cross-org entity never leaks as a 500.

    Requirements: 3.1, 3.7, 25.1, 25.2, 25.3, 25.4
    """
    org_uuid, _user_uuid, _ip = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await build_email_preview(
            db,
            org_id=org_uuid,
            template_type=template_type,
            entity_type=entity_type,
            entity_id=entity_id,
            base_url=extract_request_base_url(request),
        )
    except EntityNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return EmailPreviewResponse(**result)
