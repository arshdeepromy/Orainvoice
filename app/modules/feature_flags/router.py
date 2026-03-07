"""Feature flag API routers.

Two routers are exposed:
- ``admin_router``: Global Admin CRUD mounted at ``/api/v2/admin/flags``
- ``org_router``: Org-context evaluation mounted at ``/api/v2/flags``
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.feature_flags.schemas import (
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagResponse,
    FeatureFlagUpdate,
    OrgFlagsResponse,
)
from app.modules.feature_flags.service import FeatureFlagCRUDService

# ---------------------------------------------------------------------------
# Global Admin CRUD router  →  /api/v2/admin/flags
# ---------------------------------------------------------------------------

admin_router = APIRouter()


@admin_router.get(
    "",
    response_model=FeatureFlagListResponse,
    summary="List all feature flags",
    dependencies=[require_role("global_admin")],
)
async def list_flags(
    db: AsyncSession = Depends(get_db_session),
):
    """Return all feature flags (active and inactive)."""
    svc = FeatureFlagCRUDService(db)
    flags, total = await svc.list_flags()
    return FeatureFlagListResponse(flags=flags, total=total)


@admin_router.post(
    "",
    response_model=FeatureFlagResponse,
    status_code=201,
    summary="Create a feature flag",
    dependencies=[require_role("global_admin")],
)
async def create_flag(
    payload: FeatureFlagCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new feature flag. Requires Global Admin."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None
    svc = FeatureFlagCRUDService(db)
    try:
        flag = await svc.create_flag(payload, created_by=user_id, ip_address=ip_address)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return flag


@admin_router.put(
    "/{key}",
    response_model=FeatureFlagResponse,
    summary="Update a feature flag",
    dependencies=[require_role("global_admin")],
)
async def update_flag(
    key: str,
    payload: FeatureFlagUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing feature flag by key. Requires Global Admin."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None
    svc = FeatureFlagCRUDService(db)
    try:
        flag = await svc.update_flag(key, payload, updated_by=user_id, ip_address=ip_address)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return flag


@admin_router.delete(
    "/{key}",
    status_code=204,
    summary="Archive (delete) a feature flag",
    dependencies=[require_role("global_admin")],
)
async def delete_flag(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Archive a feature flag (sets is_active=False). Requires Global Admin."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None
    svc = FeatureFlagCRUDService(db)
    try:
        await svc.archive_flag(key, archived_by=user_id, ip_address=ip_address)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Org-context evaluation router  →  /api/v2/flags
# ---------------------------------------------------------------------------

org_router = APIRouter()


@org_router.get(
    "",
    response_model=OrgFlagsResponse,
    summary="Get active flags for current org context",
)
async def get_org_flags(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Evaluate all active feature flags for the authenticated org.

    Returns a list of flag keys with their evaluated boolean values.
    Requirement 2.7.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return OrgFlagsResponse(flags=[])

    svc = FeatureFlagCRUDService(db)
    flags = await svc.evaluate_all_for_org(org_id)
    return OrgFlagsResponse(flags=flags)
