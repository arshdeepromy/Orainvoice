"""FastAPI router for enhanced reporting endpoints.

GET  /api/v2/reports/{report_type}  — generate a report with filters
POST /api/v2/reports/schedule       — create a scheduled report
GET  /api/v2/reports/schedules      — list scheduled reports
DELETE /api/v2/reports/schedule/{id} — delete a scheduled report

**Validates: Task 54.11 — Report Endpoints**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.reports_v2.models import ReportSchedule
from app.modules.reports_v2.schemas import (
    ReportFilters,
    ReportResponse,
    ReportScheduleCreate,
    ReportScheduleResponse,
)
from app.modules.reports_v2.service import REPORT_TYPES, ReportService

router = APIRouter()


def _get_org_id(org_id: str = Query(default="00000000-0000-0000-0000-000000000000")) -> uuid.UUID:
    """Extract org_id from query param (in production, from auth middleware)."""
    return uuid.UUID(org_id)


@router.get("/{report_type}")
async def generate_report(
    report_type: str,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    location_id: uuid.UUID | None = Query(None),
    currency: str | None = Query(None),
    org_id: uuid.UUID = Depends(_get_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Generate a report by type with optional filters."""
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {report_type}. Available: {list(REPORT_TYPES.keys())}")

    filters = ReportFilters(
        date_from=date_from,
        date_to=date_to,
        location_id=location_id,
        currency=currency,
    )
    svc = ReportService(db)
    data = await svc.generate_report(org_id, report_type, filters, base_currency=currency or "NZD")

    return ReportResponse(
        report_type=report_type,
        generated_at=datetime.now(timezone.utc),
        filters=filters,
        data=data,
    )


@router.post("/schedule", response_model=ReportScheduleResponse)
async def create_schedule(
    body: ReportScheduleCreate,
    org_id: uuid.UUID = Depends(_get_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Create a scheduled report."""
    if body.report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {body.report_type}")

    schedule = ReportSchedule(
        org_id=org_id,
        report_type=body.report_type,
        frequency=body.frequency,
        filters=body.filters,
        recipients=body.recipients,
        is_active=body.is_active,
    )
    db.add(schedule)
    await db.flush()

    return ReportScheduleResponse(
        id=schedule.id,
        org_id=schedule.org_id,
        report_type=schedule.report_type,
        frequency=schedule.frequency,
        filters=schedule.filters,
        recipients=schedule.recipients,
        is_active=schedule.is_active,
        last_generated_at=schedule.last_generated_at,
        created_at=schedule.created_at,
    )


@router.get("/schedules", response_model=list[ReportScheduleResponse])
async def list_schedules(
    org_id: uuid.UUID = Depends(_get_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List all report schedules for the org."""
    stmt = select(ReportSchedule).where(ReportSchedule.org_id == org_id).order_by(ReportSchedule.created_at.desc())
    result = await db.execute(stmt)
    schedules = list(result.scalars().all())
    return [
        ReportScheduleResponse(
            id=s.id,
            org_id=s.org_id,
            report_type=s.report_type,
            frequency=s.frequency,
            filters=s.filters,
            recipients=s.recipients,
            is_active=s.is_active,
            last_generated_at=s.last_generated_at,
            created_at=s.created_at,
        )
        for s in schedules
    ]


@router.delete("/schedule/{schedule_id}")
async def delete_schedule(
    schedule_id: uuid.UUID,
    org_id: uuid.UUID = Depends(_get_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scheduled report."""
    stmt = select(ReportSchedule).where(
        ReportSchedule.id == schedule_id,
        ReportSchedule.org_id == org_id,
    )
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(schedule)
    return {"status": "deleted"}
