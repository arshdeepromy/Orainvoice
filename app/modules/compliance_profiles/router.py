"""Compliance profile API routers.

Public endpoints (any authenticated user):
- GET  /api/v2/compliance-profiles
- GET  /api/v2/compliance-profiles/{country_code}

Admin endpoints (Global Admin only):
- POST /api/v2/admin/compliance-profiles
- PUT  /api/v2/admin/compliance-profiles/{country_code}

**Validates: Requirement 5.2**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.compliance_profiles.schemas import (
    ComplianceProfileCreate,
    ComplianceProfileListResponse,
    ComplianceProfileResponse,
    ComplianceProfileUpdate,
)
from app.modules.compliance_profiles.service import ComplianceProfileService

# ---------------------------------------------------------------------------
# Public router
# ---------------------------------------------------------------------------

public_router = APIRouter()


@public_router.get(
    "",
    response_model=ComplianceProfileListResponse,
    summary="List all compliance profiles",
)
async def list_compliance_profiles(
    db: AsyncSession = Depends(get_db_session),
):
    """Return all compliance profiles."""
    svc = ComplianceProfileService(db)
    profiles = await svc.list_all()
    return ComplianceProfileListResponse(
        profiles=[ComplianceProfileResponse.model_validate(p) for p in profiles],
        total=len(profiles),
    )


@public_router.get(
    "/{country_code}",
    response_model=ComplianceProfileResponse,
    summary="Get compliance profile by country code",
)
async def get_compliance_profile(
    country_code: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a single compliance profile by country code."""
    svc = ComplianceProfileService(db)
    profile = await svc.get_by_country_code(country_code)
    if profile is None:
        raise HTTPException(status_code=404, detail="Compliance profile not found")
    return ComplianceProfileResponse.model_validate(profile)


# ---------------------------------------------------------------------------
# Admin router — Global Admin only
# ---------------------------------------------------------------------------

admin_router = APIRouter()


@admin_router.post(
    "",
    response_model=ComplianceProfileResponse,
    status_code=201,
    summary="Create a compliance profile",
    dependencies=[require_role("global_admin")],
)
async def create_compliance_profile(
    payload: ComplianceProfileCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new compliance profile (Global Admin only)."""
    svc = ComplianceProfileService(db)
    try:
        profile = await svc.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ComplianceProfileResponse.model_validate(profile)


@admin_router.put(
    "/{country_code}",
    response_model=ComplianceProfileResponse,
    summary="Update a compliance profile",
    dependencies=[require_role("global_admin")],
)
async def update_compliance_profile(
    country_code: str,
    payload: ComplianceProfileUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a compliance profile (Global Admin only)."""
    svc = ComplianceProfileService(db)
    profile = await svc.update(country_code, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="Compliance profile not found")
    return ComplianceProfileResponse.model_validate(profile)
