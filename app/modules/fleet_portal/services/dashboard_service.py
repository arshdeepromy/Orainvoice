"""Dashboard summary aggregations.

Implements: B2B Fleet Portal task 13.2 — Requirements 15.1, 15.2, 15.3,
15.4, 15.5, 15.6.

Property 17 — every aggregation is a direct enumeration over the same
underlying set the vehicle list view enumerates. The function does not
maintain any side cache; the values are recomputed on every call so
they cannot drift from the source of truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import (
    FleetChecklistSubmission,
    FleetQuotationRequest,
    FleetServiceBookingRequest,
)
from app.modules.fleet_portal.services.expiry import badge as expiry_badge
from app.modules.fleet_portal.services.vehicle_service import (
    _vehicle_query_for_session,
)


async def dashboard_for_session(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
) -> S.DashboardSummaryResponse:
    """Property 17 — recompute every aggregation directly from sources."""
    from app.modules.vehicles.models import CustomerVehicle

    today = datetime.now(timezone.utc).date()
    base_q = await _vehicle_query_for_session(db, ctx)
    rows = await db.execute(base_q)
    cvs = list(rows.scalars().all())

    total_vehicles = len(cvs)
    valid_wof_cof = 0
    expiring_within_28 = 0
    service_overdue = 0

    for cv in cvs:
        v = cv.global_vehicle if cv.global_vehicle is not None else cv.org_vehicle
        if v is None:
            continue
        wof = getattr(v, "wof_expiry", None)
        cof = getattr(v, "cof_expiry", None)
        service = getattr(v, "service_due_date", None)

        if wof is not None and cof is not None and wof > today and cof > today:
            valid_wof_cof += 1
        if expiry_badge(wof, today) == "amber" or expiry_badge(cof, today) == "amber":
            expiring_within_28 += 1
        if service is not None and service < today:
            service_overdue += 1

    # Today's checklist completions
    if ctx.fleet_account_id is not None:
        completed_today_q = select(func.count()).where(
            FleetChecklistSubmission.fleet_account_id == ctx.fleet_account_id,
            FleetChecklistSubmission.org_id == ctx.org_id,
            FleetChecklistSubmission.completed_at.isnot(None),
            func.date(FleetChecklistSubmission.completed_at) == today,
        )
        checklists_completed_today = int(
            (await db.execute(completed_today_q)).scalar() or 0
        )
    else:
        checklists_completed_today = 0

    # Pending bookings + quotes (admin-only signal; drivers see 0).
    pending_bookings = 0
    pending_quotes = 0
    if ctx.fleet_account_id is not None:
        pending_bookings = int(
            (await db.execute(
                select(func.count()).where(
                    FleetServiceBookingRequest.fleet_account_id == ctx.fleet_account_id,
                    FleetServiceBookingRequest.status == "pending",
                )
            )).scalar() or 0
        )
        pending_quotes = int(
            (await db.execute(
                select(func.count()).where(
                    FleetQuotationRequest.fleet_account_id == ctx.fleet_account_id,
                    FleetQuotationRequest.status == "pending",
                )
            )).scalar() or 0
        )

    # Recent failures (last 7 days, up to 5 — Req 15.3)
    recent_failures_list: list[S.ChecklistSubmissionSchema] = []
    if ctx.fleet_account_id is not None:
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        failures_q = (
            select(FleetChecklistSubmission)
            .where(
                FleetChecklistSubmission.fleet_account_id == ctx.fleet_account_id,
                FleetChecklistSubmission.org_id == ctx.org_id,
                FleetChecklistSubmission.status == "completed",
                FleetChecklistSubmission.failed_item_count > 0,
                FleetChecklistSubmission.completed_at >= seven_days_ago,
            )
            .order_by(FleetChecklistSubmission.completed_at.desc())
            .limit(5)
        )
        failure_rows = (await db.execute(failures_q)).scalars().all()
        recent_failures_list = [
            S.ChecklistSubmissionSchema(
                id=s.id,
                customer_vehicle_id=s.customer_vehicle_id,
                portal_account_id=s.portal_account_id,
                template_id=s.template_id,
                status=s.status,
                started_at=s.started_at,
                completed_at=s.completed_at,
                passed_item_count=s.passed_item_count or 0,
                failed_item_count=s.failed_item_count or 0,
                na_item_count=s.na_item_count or 0,
                items=[],
            )
            for s in failure_rows
        ]

    return S.DashboardSummaryResponse(
        total_vehicles=total_vehicles,
        valid_wof_cof=valid_wof_cof,
        expiring_within_28=expiring_within_28,
        service_overdue=service_overdue,
        checklists_completed_today=checklists_completed_today,
        pending_booking_requests=pending_bookings,
        pending_quote_requests=pending_quotes,
        recent_failures=recent_failures_list,
    )


__all__ = ["dashboard_for_session"]
