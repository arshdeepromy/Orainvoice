"""Franchise & multi-location API router.

Endpoints:
- GET    /api/v2/locations                    — list locations
- POST   /api/v2/locations                    — create location
- GET    /api/v2/locations/{id}               — get location
- PUT    /api/v2/locations/{id}               — update location
- POST   /api/v2/stock-transfers              — create stock transfer
- GET    /api/v2/stock-transfers              — list stock transfers
- PUT    /api/v2/stock-transfers/{id}/approve — approve transfer
- PUT    /api/v2/stock-transfers/{id}/execute — execute transfer
- GET    /api/v2/franchise/dashboard          — franchise aggregate dashboard
- GET    /api/v2/franchise/head-office        — head-office aggregate view

**Validates: Requirement 8 — Extended RBAC / Multi-Location**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.franchise.schemas import (
    FranchiseDashboardMetrics,
    FranchiseGroupCreate,
    FranchiseGroupResponse,
    HeadOfficeView,
    LocationCreate,
    LocationResponse,
    LocationUpdate,
    StockTransferCreate,
    StockTransferResponse,
)
from app.modules.franchise.service import FranchiseService

locations_router = APIRouter()
transfers_router = APIRouter()
franchise_router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ------------------------------------------------------------------
# Location endpoints
# ------------------------------------------------------------------

@locations_router.get("", response_model=list[LocationResponse], summary="List locations")
async def list_locations(request: Request, db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)

    # Location-scoped filtering for location_manager
    role = getattr(request.state, "role", None)
    locations = await svc.list_locations(org_id)

    if role == "location_manager":
        assigned = getattr(request.state, "assigned_location_ids", [])
        assigned_set = {str(lid) for lid in assigned}
        locations = [loc for loc in locations if str(loc.id) in assigned_set]

    return [LocationResponse.model_validate(loc) for loc in locations]


@locations_router.post("", response_model=LocationResponse, status_code=201, summary="Create location")
async def create_location(
    payload: LocationCreate, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)
    location = await svc.create_location(
        org_id,
        name=payload.name,
        address=payload.address,
        phone=payload.phone,
        email=payload.email,
        invoice_prefix=payload.invoice_prefix,
        has_own_inventory=payload.has_own_inventory,
    )
    await db.commit()
    await db.refresh(location)
    return LocationResponse.model_validate(location)


@locations_router.get("/{location_id}", response_model=LocationResponse, summary="Get location")
async def get_location(
    location_id: UUID, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)
    location = await svc.get_location(org_id, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return LocationResponse.model_validate(location)


@locations_router.put("/{location_id}", response_model=LocationResponse, summary="Update location")
async def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)
    location = await svc.get_location(org_id, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    updated = await svc.update_location(
        location, **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(updated)
    return LocationResponse.model_validate(updated)


# ------------------------------------------------------------------
# Stock Transfer endpoints
# ------------------------------------------------------------------

@transfers_router.get("", response_model=list[StockTransferResponse], summary="List stock transfers")
async def list_transfers(
    request: Request,
    status: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)

    # Location-scoped filtering for location_manager
    role = getattr(request.state, "role", None)
    location_filter = None
    if role == "location_manager":
        assigned = getattr(request.state, "assigned_location_ids", [])
        if assigned:
            location_filter = UUID(str(assigned[0]))

    transfers = await svc.list_transfers(org_id, status=status, location_id=location_filter)
    return [StockTransferResponse.model_validate(t) for t in transfers]


@transfers_router.post("", response_model=StockTransferResponse, status_code=201, summary="Create stock transfer")
async def create_transfer(
    payload: StockTransferCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = FranchiseService(db)
    try:
        transfer = await svc.create_stock_transfer(
            org_id,
            from_location_id=payload.from_location_id,
            to_location_id=payload.to_location_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            requested_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    await db.refresh(transfer)
    return StockTransferResponse.model_validate(transfer)


@transfers_router.put("/{transfer_id}/approve", response_model=StockTransferResponse, summary="Approve transfer")
async def approve_transfer(
    transfer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = FranchiseService(db)
    transfer = await svc.get_transfer(org_id, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    try:
        updated = await svc.approve_transfer(transfer, approved_by=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    await db.refresh(updated)
    return StockTransferResponse.model_validate(updated)


@transfers_router.put("/{transfer_id}/execute", response_model=StockTransferResponse, summary="Execute transfer")
async def execute_transfer(
    transfer_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Execute an approved transfer — creates stock movements at both locations."""
    org_id = _get_org_id(request)
    svc = FranchiseService(db)
    transfer = await svc.get_transfer(org_id, transfer_id)
    if transfer is None:
        raise HTTPException(status_code=404, detail="Transfer not found")
    try:
        updated = await svc.execute_transfer(transfer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Create stock movements at both locations
    from app.modules.stock.service import StockService
    from app.modules.products.models import Product
    from sqlalchemy import select, and_

    stock_svc = StockService(db)
    stmt = select(Product).where(
        and_(Product.id == transfer.product_id, Product.org_id == org_id),
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if product:
        # Decrement at source location
        await stock_svc._create_movement(
            product, -abs(transfer.quantity), "transfer",
            reference_type="stock_transfer", reference_id=transfer.id,
            location_id=transfer.from_location_id,
        )
        # Increment at destination location
        await stock_svc._create_movement(
            product, abs(transfer.quantity), "transfer",
            reference_type="stock_transfer", reference_id=transfer.id,
            location_id=transfer.to_location_id,
        )

    await db.commit()
    await db.refresh(updated)
    return StockTransferResponse.model_validate(updated)


# ------------------------------------------------------------------
# Franchise Dashboard endpoints
# ------------------------------------------------------------------

@franchise_router.get("/head-office", response_model=HeadOfficeView, summary="Head-office aggregate view")
async def head_office_view(
    request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = FranchiseService(db)
    data = await svc.get_head_office_view(org_id)
    return data


@franchise_router.get("/dashboard", response_model=FranchiseDashboardMetrics, summary="Franchise dashboard")
async def franchise_dashboard(
    request: Request, db: AsyncSession = Depends(get_db_session),
):
    franchise_group_id = getattr(request.state, "franchise_group_id", None)
    if not franchise_group_id:
        raise HTTPException(status_code=403, detail="Franchise group context required")
    svc = FranchiseService(db)
    data = await svc.get_franchise_dashboard(UUID(str(franchise_group_id)))
    return data
