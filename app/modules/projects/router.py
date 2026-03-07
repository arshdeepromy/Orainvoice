"""Project API router.

Endpoints:
- GET    /api/v2/projects                     — list (paginated/filterable)
- POST   /api/v2/projects                     — create
- GET    /api/v2/projects/{id}                — get project with profitability
- PUT    /api/v2/projects/{id}                — update
- GET    /api/v2/projects/{id}/profitability   — profitability dashboard
- GET    /api/v2/projects/{id}/progress        — progress tracking
- GET    /api/v2/projects/{id}/activity        — activity feed

**Validates: Requirement 14.1 (Project Module)**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.projects.schemas import (
    ActivityFeedResponse,
    ProfitabilityResponse,
    ProgressResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.modules.projects.service import ProjectService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    """Extract org_id from request state (set by auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    """Extract user_id from request state if available."""
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=ProjectListResponse, summary="List projects")
async def list_projects(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    projects, total = await svc.list_projects(
        org_id, page=page, page_size=page_size,
        status=status, customer_id=customer_id, search=search,
    )
    return ProjectListResponse(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=201, summary="Create project")
async def create_project(
    payload: ProjectCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = ProjectService(db)
    try:
        project = await svc.create_project(org_id, payload, created_by=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get project")
async def get_project(
    project_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    project = await svc.get_project(org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.put("/{project_id}", response_model=ProjectResponse, summary="Update project")
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    try:
        project = await svc.update_project(org_id, project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


# ---------------------------------------------------------------------------
# Profitability, progress, activity feed
# ---------------------------------------------------------------------------

@router.get(
    "/{project_id}/profitability",
    response_model=ProfitabilityResponse,
    summary="Get project profitability",
)
async def get_profitability(
    project_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    project = await svc.get_project(org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await svc.calculate_profitability(org_id, project_id)
    return ProfitabilityResponse(**data)


@router.get(
    "/{project_id}/progress",
    response_model=ProgressResponse,
    summary="Get project progress",
)
async def get_progress(
    project_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    project = await svc.get_project(org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await svc.get_progress(org_id, project_id)
    return ProgressResponse(**data)


@router.get(
    "/{project_id}/activity",
    response_model=ActivityFeedResponse,
    summary="Get project activity feed",
)
async def get_activity_feed(
    project_id: UUID,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProjectService(db)
    project = await svc.get_project(org_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await svc.get_activity_feed(org_id, project_id, limit=limit)
    return ActivityFeedResponse(**data)
