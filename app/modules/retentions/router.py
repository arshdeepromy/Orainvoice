"""Retention tracking API router.

Endpoints:
- POST   /api/v2/retentions/{project_id}/release   — release retention
- GET    /api/v2/retentions/{project_id}/summary    — get retention summary

**Validates: Requirement — Retention Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.retentions.schemas import (
    RetentionReleaseCreate,
    RetentionReleaseResponse,
    RetentionSummary,
)
from app.modules.retentions.service import RetentionService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.post(
    "/{project_id}/release",
    response_model=RetentionReleaseResponse,
    status_code=201,
    summary="Release retention for a project",
)
async def release_retention(
    project_id: UUID,
    payload: RetentionReleaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)  # ensure org context
    svc = RetentionService(db)
    try:
        release = await svc.release_retention(project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RetentionReleaseResponse.model_validate(release)


@router.get(
    "/{project_id}/summary",
    response_model=RetentionSummary,
    summary="Get retention summary for a project",
)
async def get_retention_summary(
    project_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)  # ensure org context
    svc = RetentionService(db)
    summary = await svc.get_retention_summary(project_id)
    return RetentionSummary(
        project_id=summary["project_id"],
        total_retention_withheld=summary["total_retention_withheld"],
        total_retention_released=summary["total_retention_released"],
        retention_balance=summary["retention_balance"],
        releases=[RetentionReleaseResponse.model_validate(r) for r in summary["releases"]],
    )
