"""Platform notifications router — Global Admin CRUD and org-facing active endpoint.

Admin endpoints require ``global_admin`` role.
The org-facing ``/active`` endpoint is accessible to any authenticated user.

Requirements: Platform Notification System — Task 48.3
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.notifications_schemas import (
    ActiveNotificationResponse,
    ActiveNotificationsListResponse,
    DismissRequest,
    MaintenanceWindowRequest,
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationUpdateRequest,
)
from app.modules.admin.notifications_service import PlatformNotificationService
from app.modules.auth.rbac import require_role

# ---------------------------------------------------------------------------
# Admin router (Global Admin CRUD)
# ---------------------------------------------------------------------------

admin_router = APIRouter(dependencies=[require_role("global_admin")])


def _get_service(db: AsyncSession = Depends(get_db_session)) -> PlatformNotificationService:
    return PlatformNotificationService(db)


@admin_router.get(
    "",
    response_model=NotificationListResponse,
    summary="List all platform notifications",
)
async def list_notifications(
    include_inactive: bool = Query(False),
    notification_type: str | None = Query(None),
    service: PlatformNotificationService = Depends(_get_service),
):
    """List all platform notifications (admin view)."""
    notifications = await service.list_notifications(
        include_inactive=include_inactive,
        notification_type=notification_type,
    )
    return NotificationListResponse(
        notifications=[NotificationResponse(**n) for n in notifications],
        total=len(notifications),
    )


@admin_router.post(
    "",
    response_model=NotificationResponse,
    status_code=201,
    summary="Create a platform notification",
)
async def create_notification(
    payload: NotificationCreateRequest,
    request: Request,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Create a new platform notification."""
    user_id = getattr(request.state, "user_id", None)
    try:
        result = await service.create_notification(
            notification_type=payload.notification_type,
            title=payload.title,
            message=payload.message,
            severity=payload.severity,
            target_type=payload.target_type,
            target_value=payload.target_value,
            scheduled_at=payload.scheduled_at,
            expires_at=payload.expires_at,
            maintenance_start=payload.maintenance_start,
            maintenance_end=payload.maintenance_end,
            created_by=uuid.UUID(user_id) if user_id else None,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return NotificationResponse(**result)


@admin_router.get(
    "/{notification_id}",
    response_model=NotificationResponse,
    summary="Get a platform notification",
)
async def get_notification(
    notification_id: str,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Get a single platform notification by ID."""
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid notification_id"})

    result = await service.get_notification(nid)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Notification not found"})
    return NotificationResponse(**result)


@admin_router.put(
    "/{notification_id}",
    response_model=NotificationResponse,
    summary="Update a platform notification",
)
async def update_notification(
    notification_id: str,
    payload: NotificationUpdateRequest,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Update a platform notification."""
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid notification_id"})

    updates = payload.model_dump(exclude_none=True)
    try:
        result = await service.update_notification(nid, updates)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return NotificationResponse(**result)


@admin_router.delete(
    "/{notification_id}",
    summary="Deactivate a platform notification",
)
async def deactivate_notification(
    notification_id: str,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Soft-delete (deactivate) a platform notification."""
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid notification_id"})

    try:
        result = await service.deactivate_notification(nid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return {"message": "Notification deactivated", "id": result["id"]}


@admin_router.post(
    "/{notification_id}/publish",
    response_model=NotificationResponse,
    summary="Publish a scheduled notification immediately",
)
async def publish_notification(
    notification_id: str,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Manually publish a scheduled notification."""
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid notification_id"})

    try:
        result = await service.publish_notification(nid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return NotificationResponse(**result)


@admin_router.post(
    "/maintenance-window",
    response_model=NotificationResponse,
    status_code=201,
    summary="Schedule a maintenance window",
)
async def schedule_maintenance_window(
    payload: MaintenanceWindowRequest,
    request: Request,
    service: PlatformNotificationService = Depends(_get_service),
):
    """Create a maintenance window notification with start/end times."""
    user_id = getattr(request.state, "user_id", None)
    try:
        result = await service.schedule_maintenance_window(
            title=payload.title,
            message=payload.message,
            maintenance_start=payload.maintenance_start,
            maintenance_end=payload.maintenance_end,
            target_type=payload.target_type,
            target_value=payload.target_value,
            created_by=uuid.UUID(user_id) if user_id else None,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return NotificationResponse(**result)


# ---------------------------------------------------------------------------
# Org-facing router (any authenticated user)
# ---------------------------------------------------------------------------

org_router = APIRouter()


@org_router.get(
    "/active",
    response_model=ActiveNotificationsListResponse,
    summary="Get active notifications for the current org",
)
async def get_active_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return active, published, non-expired notifications visible to the
    authenticated user's organisation. Excludes dismissed notifications.
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    org_country = getattr(request.state, "country_code", None)
    org_trade_family = getattr(request.state, "trade_family", None)
    org_plan_tier = getattr(request.state, "plan_tier", None)

    if not user_id or not org_id:
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    service = PlatformNotificationService(db)
    notifications = await service.get_active_for_org(
        org_id=uuid.UUID(org_id),
        user_id=uuid.UUID(user_id),
        org_country=org_country,
        org_trade_family=org_trade_family,
        org_plan_tier=org_plan_tier,
    )
    return ActiveNotificationsListResponse(
        notifications=[ActiveNotificationResponse(**n) for n in notifications],
    )


@org_router.post(
    "/dismiss",
    summary="Dismiss a notification for the current user",
)
async def dismiss_notification(
    payload: DismissRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Dismiss a notification so it no longer appears for this user."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    try:
        nid = uuid.UUID(payload.notification_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid notification_id"})

    service = PlatformNotificationService(db)
    try:
        result = await service.dismiss_for_user(nid, uuid.UUID(user_id))
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return result
