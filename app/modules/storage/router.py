"""Storage module API router.

Endpoints:
- GET /api/v1/storage/usage — current storage usage, quota, and alert level

Requirements: 29.1, 29.2, 29.3, 29.4, 29.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.storage.schemas import StorageUsageResponse
from app.modules.storage.service import check_storage_quota

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Extract org_id and user_id from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None
    return org_uuid, user_uuid


@router.get("/usage", response_model=StorageUsageResponse)
async def get_storage_usage(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return current storage usage, quota, percentage, and alert level.

    Requirements: 29.1, 29.2, 29.3, 29.4
    """
    org_id, _ = _extract_org_context(request)
    if org_id is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    try:
        quota_status = await check_storage_quota(db, org_id)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return StorageUsageResponse(**quota_status)
