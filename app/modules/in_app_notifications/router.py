"""API router for in-app notification inbox.

Endpoints:
  GET  /inbox                    — paginated inbox list
  GET  /inbox/unread-count       — unread count for bell badge polling
  POST /inbox/{id}/read          — mark single notification read
  POST /inbox/mark-all-read      — mark all visible notifications read
  POST /inbox/{id}/dismiss       — dismiss single notification
  POST /inbox/dismiss-all-read   — dismiss all read notifications

All endpoints require an authenticated org user. global_admin is explicitly
rejected — the inbox is an org-user feature only.

Requirements: 5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.in_app_notifications.service import (
    dismiss,
    dismiss_all_read,
    get_unread_count,
    list_inbox,
    mark_all_read,
    mark_read,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and role from request state.

    Returns (org_uuid, user_uuid, role). Any parse failure yields None
    for the corresponding field.
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, role
    return org_uuid, user_uuid, role


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/inbox")
async def get_inbox(
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    unread_only: bool = Query(False, description="Show only unread notifications"),
    category: str = Query("", description="Filter by category"),
    severity: str = Query("", description="Filter by severity"),
    db: AsyncSession = Depends(get_db_session),
):
    """List inbox notifications for the current org user.

    Returns paginated items with total count and unread count for badge.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    result = await list_inbox(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        role=role or "",
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        category=category or None,
        severity=severity or None,
    )

    return JSONResponse(content=result)


@router.get("/inbox/unread-count")
async def get_inbox_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return unread notification count for the bell badge.

    Designed to be cheap for 30s polling — single indexed COUNT query.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    count = await get_unread_count(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        role=role or "",
    )

    return JSONResponse(content={"count": count})


@router.post("/inbox/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Mark a single notification as read for the current user.

    Idempotent — calling again on an already-read notification is a no-op.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    try:
        notif_uuid = uuid.UUID(notification_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid notification ID"},
        )

    await mark_read(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        notification_id=notif_uuid,
    )

    return JSONResponse(content={"message": "Notification marked as read"})


@router.post("/inbox/mark-all-read")
async def mark_all_notifications_read(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Mark all visible notifications as read for the current user.

    Returns the count of notifications that were marked read.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    count = await mark_all_read(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        role=role or "",
    )

    return JSONResponse(content={"message": "All notifications marked as read", "count": count})


@router.post("/inbox/{notification_id}/dismiss")
async def dismiss_notification(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Dismiss a notification for the current user only.

    Dismissed notifications are hidden from the inbox and badge count.
    Other users still see the notification. Idempotent.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    try:
        notif_uuid = uuid.UUID(notification_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid notification ID"},
        )

    await dismiss(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
        notification_id=notif_uuid,
    )

    return JSONResponse(content={"message": "Notification dismissed"})


@router.post("/inbox/dismiss-all-read")
async def dismiss_all_read_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Dismiss all notifications that are currently marked as read.

    Returns the count of notifications dismissed.

    Requirements: 5
    """
    org_uuid, user_uuid, role = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role == "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Inbox is for org users only"},
        )

    count = await dismiss_all_read(
        db,
        org_id=org_uuid,
        user_id=user_uuid,
    )

    return JSONResponse(content={"message": "All read notifications dismissed", "count": count})
