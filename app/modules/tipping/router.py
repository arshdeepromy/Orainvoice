"""Tipping API router — tip recording, allocation, and summary reports.

Endpoints (all under /api/v2/tips):
- POST /              — record a new tip
- GET /{tip_id}       — get a single tip
- POST /{tip_id}/allocate       — allocate tip to staff (custom amounts)
- POST /{tip_id}/allocate/even  — split tip evenly across staff
- GET /summary        — tip summary report (filterable)

**Validates: Requirement 24 — Tipping Module**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.tipping.schemas import (
    TipAllocateRequest,
    TipCreate,
    TipEvenSplitRequest,
    TipResponse,
    TipSummaryResponse,
    InvoiceTipCreate,
)
from app.modules.tipping.service import TippingService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.post("/", response_model=TipResponse, status_code=201, summary="Record a tip")
async def record_tip(
    payload: TipCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TippingService(db)
    tip = await svc.record_tip(org_id, payload)
    return TipResponse.model_validate(tip)


@router.get("/{tip_id}", response_model=TipResponse, summary="Get a tip")
async def get_tip(
    tip_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TippingService(db)
    tip = await svc.get_tip(org_id, tip_id)
    if tip is None:
        raise HTTPException(status_code=404, detail="Tip not found")
    return TipResponse.model_validate(tip)


@router.post(
    "/{tip_id}/allocate",
    response_model=TipResponse,
    summary="Allocate tip to staff (custom amounts)",
)
async def allocate_tip(
    tip_id: UUID,
    payload: TipAllocateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TippingService(db)
    try:
        tip = await svc.allocate_to_staff(org_id, tip_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if tip is None:
        raise HTTPException(status_code=404, detail="Tip not found")
    return TipResponse.model_validate(tip)


@router.post(
    "/{tip_id}/allocate/even",
    response_model=TipResponse,
    summary="Split tip evenly across staff",
)
async def allocate_tip_even(
    tip_id: UUID,
    payload: TipEvenSplitRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TippingService(db)
    tip = await svc.allocate_even_split(org_id, tip_id, payload)
    if tip is None:
        raise HTTPException(status_code=404, detail="Tip not found")
    return TipResponse.model_validate(tip)


@router.get("/summary", response_model=TipSummaryResponse, summary="Tip summary report")
async def tip_summary(
    request: Request,
    start_date: date | None = Query(None, description="Filter start date"),
    end_date: date | None = Query(None, description="Filter end date"),
    staff_id: UUID | None = Query(None, description="Filter by staff member"),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = TippingService(db)
    summary = await svc.get_tip_summary(
        org_id, start_date=start_date, end_date=end_date, staff_id=staff_id,
    )
    return TipSummaryResponse(**summary)


@router.post(
    "/invoice/{invoice_id}",
    response_model=TipResponse,
    status_code=201,
    summary="Add tip to invoice payment",
)
async def add_invoice_tip(
    invoice_id: UUID,
    payload: InvoiceTipCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Add an optional tip during online invoice payment."""
    org_id = _get_org_id(request)
    svc = TippingService(db)
    tip_payload = TipCreate(
        invoice_id=invoice_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
    )
    tip = await svc.record_tip(org_id, tip_payload)
    return TipResponse.model_validate(tip)
