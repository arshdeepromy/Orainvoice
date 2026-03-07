"""Asset tracking API router.

Endpoints:
- GET    /api/v2/assets              — list assets
- POST   /api/v2/assets              — create asset
- GET    /api/v2/assets/{id}         — get asset
- PUT    /api/v2/assets/{id}         — update asset
- DELETE /api/v2/assets/{id}         — soft-delete asset
- GET    /api/v2/assets/{id}/history — service history
- POST   /api/v2/assets/{id}/link-job     — link to job
- POST   /api/v2/assets/{id}/link-invoice — link to invoice
- POST   /api/v2/assets/{id}/carjam       — Carjam lookup

**Validates: Extended Asset Tracking — Task 45.4**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.assets.schemas import (
    AssetCreate,
    AssetResponse,
    AssetServiceHistory,
    AssetUpdate,
)
from app.modules.assets.service import AssetService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_trade_family_slug(request: Request) -> str | None:
    """Extract trade family slug from request state (set by middleware)."""
    return getattr(request.state, "trade_family_slug", None)


@router.get("", response_model=list[AssetResponse], summary="List assets")
async def list_assets(
    request: Request,
    customer_id: UUID | None = Query(None),
    asset_type: str | None = Query(None),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    return await svc.list_assets(
        org_id, customer_id=customer_id, asset_type=asset_type, active_only=active_only,
    )


@router.post("", response_model=AssetResponse, status_code=201, summary="Create asset")
async def create_asset(
    request: Request,
    body: AssetCreate,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    asset = await svc.create_asset(org_id, **body.model_dump())
    return asset


@router.get("/{asset_id}", response_model=AssetResponse, summary="Get asset")
async def get_asset(
    request: Request,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    asset = await svc.get_asset(org_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.put("/{asset_id}", response_model=AssetResponse, summary="Update asset")
async def update_asset(
    request: Request,
    asset_id: UUID,
    body: AssetUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    asset = await svc.update_asset(org_id, asset_id, **body.model_dump())
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.delete("/{asset_id}", status_code=204, summary="Soft-delete asset")
async def delete_asset(
    request: Request,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    deleted = await svc.delete_asset(org_id, asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset not found")
    return None


@router.get(
    "/{asset_id}/history",
    response_model=AssetServiceHistory,
    summary="Get asset service history",
)
async def get_service_history(
    request: Request,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    asset = await svc.get_asset(org_id, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return await svc.get_service_history(org_id, asset_id)


class LinkJobRequest(BaseModel):
    job_id: UUID


class LinkInvoiceRequest(BaseModel):
    invoice_id: UUID


@router.post("/{asset_id}/link-job", status_code=200, summary="Link asset to job")
async def link_to_job(
    request: Request,
    asset_id: UUID,
    body: LinkJobRequest,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    linked = await svc.link_to_job(org_id, asset_id, body.job_id)
    if not linked:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "linked"}


@router.post("/{asset_id}/link-invoice", status_code=200, summary="Link asset to invoice")
async def link_to_invoice(
    request: Request,
    asset_id: UUID,
    body: LinkInvoiceRequest,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = AssetService(db)
    linked = await svc.link_to_invoice(org_id, asset_id, body.invoice_id)
    if not linked:
        raise HTTPException(status_code=404, detail="Invoice or associated job not found")
    return {"status": "linked"}


@router.post("/{asset_id}/carjam", status_code=200, summary="Carjam lookup")
async def carjam_lookup(
    request: Request,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    trade_family_slug = _get_trade_family_slug(request)
    svc = AssetService(db)
    try:
        data = await svc.carjam_lookup(org_id, asset_id, trade_family_slug)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if data is None:
        raise HTTPException(status_code=404, detail="Asset not found or no identifier set")
    return data
