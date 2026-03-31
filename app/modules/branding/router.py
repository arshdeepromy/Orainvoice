"""Platform branding API router (Global Admin).

Endpoints:
- GET  /api/v2/admin/branding  — get platform branding
- PUT  /api/v2/admin/branding  — update platform branding

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.branding.schemas import BrandingResponse, BrandingUpdate, PublicBrandingResponse
from app.modules.branding.service import BrandingService

router = APIRouter()
public_router = APIRouter()


@public_router.get("", response_model=PublicBrandingResponse, summary="Get public platform branding")
async def get_public_branding(db: AsyncSession = Depends(get_db_session)):
    """Public endpoint — no auth required. Returns branding for login/signup pages."""
    svc = BrandingService(db)
    branding = await svc.get_branding()
    if branding is None:
        return PublicBrandingResponse(
            platform_name="OraInvoice",
            primary_colour="#2563EB",
            secondary_colour="#1E40AF",
        )
    return PublicBrandingResponse.model_validate(branding)


@router.get("", response_model=BrandingResponse, summary="Get platform branding")
async def get_branding(db: AsyncSession = Depends(get_db_session)):
    svc = BrandingService(db)
    branding = await svc.get_branding()
    if branding is None:
        raise HTTPException(status_code=404, detail="Branding not configured")
    return BrandingResponse.model_validate(branding)


@router.put("", response_model=BrandingResponse, summary="Update platform branding")
async def update_branding(
    payload: BrandingUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    svc = BrandingService(db)
    try:
        branding = await svc.update_branding(
            platform_name=payload.platform_name,
            logo_url=payload.logo_url,
            primary_colour=payload.primary_colour,
            secondary_colour=payload.secondary_colour,
            website_url=payload.website_url,
            signup_url=payload.signup_url,
            support_email=payload.support_email,
            terms_url=payload.terms_url,
            auto_detect_domain=payload.auto_detect_domain,
            platform_theme=payload.platform_theme,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return BrandingResponse.model_validate(branding)
