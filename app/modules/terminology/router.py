"""Terminology API router.

Mounted at ``/api/v2/terminology``.

- GET  /  — returns the merged terminology map for the current org
- PUT  /  — set org-level terminology overrides (Org Admin only)

**Validates: Requirement 4**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.terminology import TerminologyService
from app.modules.auth.rbac import require_role
from app.modules.terminology.schemas import (
    TerminologyMapResponse,
    TerminologyOverrideRequest,
)

router = APIRouter()


@router.get(
    "",
    response_model=TerminologyMapResponse,
    summary="Get terminology map for current org",
)
async def get_terminology(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the fully-merged terminology map for the authenticated org.

    Merge priority: DEFAULT_TERMS → trade category → org overrides.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation context required"},
        )

    svc = TerminologyService(db)
    terms = await svc.get_terminology_map(org_id)
    return TerminologyMapResponse(terms=terms)


@router.put(
    "",
    response_model=TerminologyMapResponse,
    summary="Set org-level terminology overrides",
    dependencies=[require_role("org_admin")],
)
async def set_terminology(
    payload: TerminologyOverrideRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Upsert org-level terminology overrides.

    Returns the new fully-merged terminology map after applying overrides.
    Requires Org Admin role.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation context required"},
        )

    svc = TerminologyService(db)
    terms = await svc.set_org_overrides(org_id, payload.overrides)
    return TerminologyMapResponse(terms=terms)
