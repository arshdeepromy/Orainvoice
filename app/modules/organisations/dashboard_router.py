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
