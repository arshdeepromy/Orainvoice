"""IRD Gateway API router.

Provides endpoints for IRD credential management, GST filing,
income tax filing, and filing audit log.

Requirements: 24.1–24.6, 25.1–25.6, 26.1–26.7, 27.1–27.4, 28.1–28.3
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ird import schemas, service

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Extract org_id and user_id from request state (set by auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    if org_id is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id)), uuid.UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# POST /connect — store IRD credentials (encrypted)
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=schemas.IrdStatusResponse)
async def connect_ird_endpoint(
    body: schemas.IrdConnectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Store IRD Gateway credentials (encrypted).

    Validates IRD number using mod-11, encrypts credentials with
    envelope encryption, stores in accounting_integrations.
    """
    org_id, user_id = _extract_org_context(request)
    return await service.connect_ird(
        db, org_id,
        ird_number=body.ird_number,
        username=body.username,
        password=body.password,
        environment=body.environment,
    )


# ---------------------------------------------------------------------------
# GET /status — connection status + active services
# ---------------------------------------------------------------------------

@router.get("/status", response_model=schemas.IrdStatusResponse)
async def get_ird_status_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get IRD connection status and active services."""
    org_id, _ = _extract_org_context(request)
    return await service.get_ird_status(db, org_id)


# ---------------------------------------------------------------------------
# POST /gst/preflight/{period_id} — preflight check (RFO + RR)
# ---------------------------------------------------------------------------

@router.post("/gst/preflight/{period_id}", response_model=schemas.IrdPreflightResponse)
async def preflight_gst_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Preflight check before GST filing.

    Calls RFO (Retrieve Filing Obligation) and RR (Retrieve Return)
    to verify the period is due and no existing return exists.
    """
    org_id, _ = _extract_org_context(request)
    return await service.preflight_gst(db, org_id, period_id)


# ---------------------------------------------------------------------------
# POST /gst/file/{period_id} — submit GST return
# ---------------------------------------------------------------------------

@router.post("/gst/file/{period_id}", response_model=schemas.IrdFilingResponse)
async def file_gst_return_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Submit GST return to IRD.

    Maps GST return data to IRD XML schema and submits.
    Rate limited: max 1 filing per period per org.
    """
    org_id, user_id = _extract_org_context(request)
    return await service.file_gst_return(db, org_id, period_id, user_id)


# ---------------------------------------------------------------------------
# GET /gst/status/{period_id} — poll filing status
# ---------------------------------------------------------------------------

@router.get("/gst/status/{period_id}", response_model=schemas.IrdFilingResponse)
async def get_gst_status_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Poll GST filing status for a period."""
    org_id, _ = _extract_org_context(request)

    from sqlalchemy import select
    from app.modules.ird.models import IrdFilingLog

    result = await db.execute(
        select(IrdFilingLog)
        .where(
            IrdFilingLog.org_id == org_id,
            IrdFilingLog.period_id == period_id,
            IrdFilingLog.filing_type == "gst",
        )
        .order_by(IrdFilingLog.created_at.desc())
        .limit(1)
    )
    log = result.scalar_one_or_none()
    if not log:
        return schemas.IrdFilingResponse(
            success=False,
            filing_type="gst",
            status="not_filed",
            message="No filing found for this period",
        )

    return schemas.IrdFilingResponse(
        success=log.status in ("accepted", "filed", "submitted"),
        filing_type="gst",
        status=log.status,
        ird_reference=log.ird_reference,
        message=f"Filing status: {log.status}",
    )


# ---------------------------------------------------------------------------
# POST /income-tax/file — submit income tax return
# ---------------------------------------------------------------------------

@router.post("/income-tax/file", response_model=schemas.IrdFilingResponse)
async def file_income_tax_endpoint(
    body: schemas.IncomeTaxFileRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Submit income tax return to IRD.

    Maps P&L data to IR3 (sole_trader) or IR4 (company) format.
    """
    org_id, user_id = _extract_org_context(request)
    return await service.file_income_tax(db, org_id, body.tax_year, user_id)


# ---------------------------------------------------------------------------
# GET /filing-log — filing audit log
# ---------------------------------------------------------------------------

@router.get("/filing-log", response_model=schemas.IrdFilingLogListResponse)
async def get_filing_log_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get filing audit log for the organisation."""
    org_id, _ = _extract_org_context(request)
    logs = await service.get_filing_log(db, org_id)
    return schemas.IrdFilingLogListResponse(items=logs, total=len(logs))
