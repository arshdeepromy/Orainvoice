"""GST Filing API router — GST filing periods, readiness, and locking.

Registered at /api/v1/gst (separate from the ledger router).

Requirements: 11.1–11.4, 14.1
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.ledger.schemas import (
    GstFilingPeriodListResponse,
    GstFilingPeriodResponse,
    GstPeriodGenerateRequest,
    GstPeriodReadyRequest,
)
from app.modules.ledger.service import (
    generate_gst_periods,
    get_gst_period,
    list_gst_periods,
    lock_gst_period,
    mark_period_ready,
)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Extract org_id and user_id from request state."""
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid auth context")
    if org_uuid is None or user_uuid is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    return org_uuid, user_uuid


# ---------------------------------------------------------------------------
# GST Filing Period endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/periods",
    response_model=GstFilingPeriodListResponse,
    summary="List GST filing periods",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_gst_periods_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all GST filing periods for the current organisation."""
    org_id, _ = _extract_org_context(request)
    periods, total = await list_gst_periods(db, org_id)
    return GstFilingPeriodListResponse(
        items=[GstFilingPeriodResponse.model_validate(p) for p in periods],
        total=total,
    )


@router.post(
    "/periods/generate",
    response_model=GstFilingPeriodListResponse,
    status_code=201,
    summary="Generate GST filing periods for a tax year",
    dependencies=[require_role("org_admin")],
)
async def generate_gst_periods_endpoint(
    payload: GstPeriodGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate GST filing periods for a given tax year and period type."""
    org_id, _ = _extract_org_context(request)
    periods = await generate_gst_periods(
        db, org_id, period_type=payload.period_type, tax_year=payload.tax_year
    )
    return GstFilingPeriodListResponse(
        items=[GstFilingPeriodResponse.model_validate(p) for p in periods],
        total=len(periods),
    )


@router.get(
    "/periods/{period_id}",
    response_model=GstFilingPeriodResponse,
    summary="Get GST filing period detail",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_gst_period_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get a single GST filing period with return data."""
    org_id, _ = _extract_org_context(request)
    period = await get_gst_period(db, org_id, period_id)
    return GstFilingPeriodResponse.model_validate(period)


@router.post(
    "/periods/{period_id}/ready",
    response_model=GstFilingPeriodResponse,
    summary="Mark GST period as ready for filing",
    dependencies=[require_role("org_admin")],
)
async def mark_period_ready_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Transition a GST filing period from draft to ready."""
    org_id, _ = _extract_org_context(request)
    period = await mark_period_ready(db, org_id, period_id)
    return GstFilingPeriodResponse.model_validate(period)


@router.post(
    "/periods/{period_id}/lock",
    response_model=GstFilingPeriodResponse,
    summary="Lock invoices/expenses in GST period",
    dependencies=[require_role("org_admin")],
)
async def lock_gst_period_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Lock all invoices and expenses within the GST period's date range."""
    org_id, _ = _extract_org_context(request)
    period = await lock_gst_period(db, org_id, period_id)
    return GstFilingPeriodResponse.model_validate(period)
