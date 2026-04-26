"""Dashboard router — branch-scoped metrics and comparison endpoints.

Requirements: 15.1, 15.2, 16.1, 16.2, 16.3
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role

router = APIRouter()


@router.get(
    "/branch-metrics",
    summary="Get branch-scoped dashboard metrics",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_branch_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return dashboard metrics scoped to the current branch context."""
    org_id = getattr(request.state, "org_id", None)
    branch_id = getattr(request.state, "branch_id", None)

    if not org_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation context required"})

    from app.modules.organisations.dashboard_service import get_branch_metrics as _get_metrics
    result = await _get_metrics(db, uuid.UUID(str(org_id)), branch_id=branch_id)
    return result


@router.get(
    "/branch-comparison",
    summary="Compare multiple branches side by side",
    dependencies=[require_role("org_admin")],
)
async def get_branch_comparison(
    request: Request,
    branch_ids: str = Query(..., description="Comma-separated branch UUIDs"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return side-by-side metrics for selected branches."""
    org_id = getattr(request.state, "org_id", None)

    if not org_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation context required"})

    ids = [uuid.UUID(bid.strip()) for bid in branch_ids.split(",") if bid.strip()]
    if len(ids) < 2:
        return JSONResponse(status_code=400, content={"detail": "At least 2 branch IDs required"})

    from app.modules.organisations.dashboard_service import get_branch_comparison as _get_comparison
    result = await _get_comparison(db, uuid.UUID(str(org_id)), ids)
    return result


# ---------------------------------------------------------------------------
# Dashboard Widget Endpoints (automotive-dashboard-widgets spec)
# ---------------------------------------------------------------------------


@router.get(
    "/widgets",
    summary="Get all dashboard widget data in one call",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_dashboard_widgets(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return aggregated data for all dashboard widgets."""
    org_id = getattr(request.state, "org_id", None)
    branch_id = getattr(request.state, "branch_id", None)

    if not org_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation context required"})

    from app.modules.organisations.dashboard_service import get_all_widget_data
    result = await get_all_widget_data(db, uuid.UUID(str(org_id)), branch_id=branch_id)
    return result


@router.post(
    "/reminders/{reminder_type}/dismiss",
    summary="Dismiss or mark a WOF/service reminder as sent",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def dismiss_dashboard_reminder(
    reminder_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a dismissal record for a WOF/service expiry reminder."""
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)

    if not org_id or not user_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation and user context required"})

    if reminder_type not in ("wof", "service"):
        return JSONResponse(status_code=400, content={"detail": "reminder_type must be 'wof' or 'service'"})

    body = await request.json()
    vehicle_id = body.get("vehicle_id")
    expiry_date = body.get("expiry_date")
    action = body.get("action", "dismissed")

    if not vehicle_id or not expiry_date:
        return JSONResponse(status_code=422, content={"detail": "vehicle_id and expiry_date are required"})

    from app.modules.organisations.dashboard_service import dismiss_reminder
    result = await dismiss_reminder(
        db, uuid.UUID(str(org_id)), uuid.UUID(str(user_id)),
        vehicle_id, reminder_type, expiry_date, action
    )
    return result


@router.get(
    "/reminder-config",
    summary="Get reminder threshold configuration",
    dependencies=[require_role("org_admin")],
)
async def get_reminder_config_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the org's WOF/service reminder threshold config."""
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation context required"})

    from app.modules.organisations.dashboard_service import get_reminder_config
    result = await get_reminder_config(db, uuid.UUID(str(org_id)))
    return result


@router.put(
    "/reminder-config",
    summary="Update reminder threshold configuration",
    dependencies=[require_role("org_admin")],
)
async def update_reminder_config_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update the org's WOF/service reminder thresholds."""
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)

    if not org_id or not user_id:
        return JSONResponse(status_code=400, content={"detail": "Organisation and user context required"})

    from app.modules.organisations.schemas import ReminderConfigUpdate
    body = await request.json()
    try:
        config_update = ReminderConfigUpdate(**body)
    except Exception as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})

    from app.modules.organisations.dashboard_service import update_reminder_config
    result = await update_reminder_config(
        db, uuid.UUID(str(org_id)), uuid.UUID(str(user_id)),
        config_update.wof_days, config_update.service_days
    )
    return result
