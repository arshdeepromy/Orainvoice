"""Pydantic v2 schemas for platform notifications.

Requirements: Platform Notification System — Task 48
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


NotificationType = Literal["maintenance", "alert", "feature", "info"]
Severity = Literal["info", "warning", "critical"]
TargetType = Literal["all", "country", "trade_family", "plan_tier", "specific_orgs"]


class NotificationCreateRequest(BaseModel):
    notification_type: NotificationType
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    severity: Severity = "info"
    target_type: TargetType = "all"
    target_value: str | None = None
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    maintenance_start: datetime | None = None
    maintenance_end: datetime | None = None


class NotificationUpdateRequest(BaseModel):
    title: str | None = None
    message: str | None = None
    severity: Severity | None = None
    target_type: TargetType | None = None
    target_value: str | None = None
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    maintenance_start: datetime | None = None
    maintenance_end: datetime | None = None
    is_active: bool | None = None


class NotificationResponse(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    severity: str
    target_type: str
    target_value: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    maintenance_start: datetime | None = None
    maintenance_end: datetime | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int


class ActiveNotificationResponse(BaseModel):
    id: str
    notification_type: str
    title: str
    message: str
    severity: str
    published_at: datetime | None = None
    expires_at: datetime | None = None
    maintenance_start: datetime | None = None
    maintenance_end: datetime | None = None


class ActiveNotificationsListResponse(BaseModel):
    notifications: list[ActiveNotificationResponse]


class MaintenanceWindowRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    maintenance_start: datetime
    maintenance_end: datetime
    target_type: TargetType = "all"
    target_value: str | None = None


class DismissRequest(BaseModel):
    notification_id: str
