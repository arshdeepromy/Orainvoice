"""Platform notification service for Global Admin notifications.

Provides create, publish, target-matching, dismissal, and maintenance
window scheduling for platform-wide notifications.

Requirements: Platform Notification System — Task 48.2, 48.4, 48.5
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.notifications_models import (
    NotificationDismissal,
    PlatformNotification,
)

logger = logging.getLogger(__name__)

# Valid notification types and severities
VALID_NOTIFICATION_TYPES = {"maintenance", "alert", "feature", "info"}
VALID_SEVERITIES = {"info", "warning", "critical"}
VALID_TARGET_TYPES = {"all", "country", "trade_family", "plan_tier", "specific_orgs"}


class PlatformNotificationService:
    """Service for managing platform-wide notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # create_notification
    # ------------------------------------------------------------------

    async def create_notification(
        self,
        notification_type: str,
        title: str,
        message: str,
        severity: str = "info",
        target_type: str = "all",
        target_value: str | None = None,
        scheduled_at: datetime | None = None,
        expires_at: datetime | None = None,
        maintenance_start: datetime | None = None,
        maintenance_end: datetime | None = None,
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Create a new platform notification.

        If scheduled_at is provided, the notification will not be published
        until that time (handled by the Celery task). Otherwise it is
        published immediately.
        """
        if notification_type not in VALID_NOTIFICATION_TYPES:
            raise ValueError(f"Invalid notification_type: {notification_type}")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {severity}")
        if target_type not in VALID_TARGET_TYPES:
            raise ValueError(f"Invalid target_type: {target_type}")

        now = datetime.now(timezone.utc)
        published = None if scheduled_at else now

        notif = PlatformNotification(
            notification_type=notification_type,
            title=title,
            message=message,
            severity=severity,
            target_type=target_type,
            target_value=target_value,
            scheduled_at=scheduled_at,
            published_at=published,
            expires_at=expires_at,
            maintenance_start=maintenance_start,
            maintenance_end=maintenance_end,
            is_active=True,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(notif)
        await self.db.flush()

        logger.info("Created platform notification %s: %s", notif.id, title)
        return _notification_to_dict(notif)

    # ------------------------------------------------------------------
    # publish_notification
    # ------------------------------------------------------------------

    async def publish_notification(self, notification_id: uuid.UUID) -> dict[str, Any]:
        """Publish a notification (set published_at to now)."""
        result = await self.db.execute(
            select(PlatformNotification).where(PlatformNotification.id == notification_id)
        )
        notif = result.scalar_one_or_none()
        if notif is None:
            raise ValueError(f"Notification {notification_id} not found")

        now = datetime.now(timezone.utc)
        notif.published_at = now
        notif.updated_at = now
        await self.db.flush()

        logger.info("Published notification %s", notification_id)
        return _notification_to_dict(notif)

    # ------------------------------------------------------------------
    # get_active_for_org — targeted delivery (Task 48.4)
    # ------------------------------------------------------------------

    async def get_active_for_org(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        org_country: str | None = None,
        org_trade_family: str | None = None,
        org_plan_tier: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return active, published, non-expired notifications visible to the org.

        Filters by target_type/target_value matching and excludes dismissed.
        """
        now = datetime.now(timezone.utc)

        # Fetch all active, published, non-expired notifications
        stmt = select(PlatformNotification).where(
            and_(
                PlatformNotification.is_active.is_(True),
                PlatformNotification.published_at.isnot(None),
                PlatformNotification.published_at <= now,
            )
        )
        result = await self.db.execute(stmt)
        all_notifs = list(result.scalars().all())

        # Fetch dismissed notification IDs for this user
        dismiss_stmt = select(NotificationDismissal.notification_id).where(
            NotificationDismissal.user_id == user_id
        )
        dismiss_result = await self.db.execute(dismiss_stmt)
        dismissed_ids = {row[0] for row in dismiss_result.all()}

        visible: list[dict[str, Any]] = []
        for notif in all_notifs:
            # Skip expired
            if notif.expires_at and notif.expires_at <= now:
                continue

            # Skip dismissed
            if notif.id in dismissed_ids:
                continue

            # Check target matching
            if not _matches_target(
                notif,
                org_id=org_id,
                org_country=org_country,
                org_trade_family=org_trade_family,
                org_plan_tier=org_plan_tier,
            ):
                continue

            visible.append({
                "id": str(notif.id),
                "notification_type": notif.notification_type,
                "title": notif.title,
                "message": notif.message,
                "severity": notif.severity,
                "published_at": notif.published_at,
                "expires_at": notif.expires_at,
                "maintenance_start": notif.maintenance_start,
                "maintenance_end": notif.maintenance_end,
            })

        return visible

    # ------------------------------------------------------------------
    # dismiss_for_user
    # ------------------------------------------------------------------

    async def dismiss_for_user(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Dismiss a notification for a specific user."""
        # Verify notification exists
        result = await self.db.execute(
            select(PlatformNotification).where(PlatformNotification.id == notification_id)
        )
        notif = result.scalar_one_or_none()
        if notif is None:
            raise ValueError(f"Notification {notification_id} not found")

        # Check if already dismissed
        existing = await self.db.execute(
            select(NotificationDismissal).where(
                and_(
                    NotificationDismissal.notification_id == notification_id,
                    NotificationDismissal.user_id == user_id,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            return {"status": "already_dismissed", "notification_id": str(notification_id)}

        dismissal = NotificationDismissal(
            notification_id=notification_id,
            user_id=user_id,
            dismissed_at=datetime.now(timezone.utc),
        )
        self.db.add(dismissal)
        await self.db.flush()

        return {"status": "dismissed", "notification_id": str(notification_id)}

    # ------------------------------------------------------------------
    # schedule_maintenance_window (Task 48.5)
    # ------------------------------------------------------------------

    async def schedule_maintenance_window(
        self,
        title: str,
        message: str,
        maintenance_start: datetime,
        maintenance_end: datetime,
        target_type: str = "all",
        target_value: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Create a maintenance window notification.

        Published immediately with maintenance_start/end times for
        countdown display in the frontend banner.
        """
        if maintenance_end <= maintenance_start:
            raise ValueError("maintenance_end must be after maintenance_start")

        return await self.create_notification(
            notification_type="maintenance",
            title=title,
            message=message,
            severity="warning",
            target_type=target_type,
            target_value=target_value,
            expires_at=maintenance_end,
            maintenance_start=maintenance_start,
            maintenance_end=maintenance_end,
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Admin CRUD helpers
    # ------------------------------------------------------------------

    async def list_notifications(
        self,
        include_inactive: bool = False,
        notification_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all notifications (admin view)."""
        conditions = []
        if not include_inactive:
            conditions.append(PlatformNotification.is_active.is_(True))
        if notification_type:
            conditions.append(PlatformNotification.notification_type == notification_type)

        stmt = select(PlatformNotification)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(PlatformNotification.created_at.desc())

        result = await self.db.execute(stmt)
        return [_notification_to_dict(n) for n in result.scalars().all()]

    async def get_notification(self, notification_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a single notification by ID."""
        result = await self.db.execute(
            select(PlatformNotification).where(PlatformNotification.id == notification_id)
        )
        notif = result.scalar_one_or_none()
        if notif is None:
            return None
        return _notification_to_dict(notif)

    async def update_notification(
        self,
        notification_id: uuid.UUID,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a notification."""
        result = await self.db.execute(
            select(PlatformNotification).where(PlatformNotification.id == notification_id)
        )
        notif = result.scalar_one_or_none()
        if notif is None:
            raise ValueError(f"Notification {notification_id} not found")

        for key, value in updates.items():
            if hasattr(notif, key) and key not in ("id", "created_at", "created_by"):
                setattr(notif, key, value)

        notif.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return _notification_to_dict(notif)

    async def deactivate_notification(self, notification_id: uuid.UUID) -> dict[str, Any]:
        """Soft-delete a notification by setting is_active=False."""
        result = await self.db.execute(
            select(PlatformNotification).where(PlatformNotification.id == notification_id)
        )
        notif = result.scalar_one_or_none()
        if notif is None:
            raise ValueError(f"Notification {notification_id} not found")

        notif.is_active = False
        notif.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return _notification_to_dict(notif)

    # ------------------------------------------------------------------
    # Scheduled publishing (used by Celery task 48.6)
    # ------------------------------------------------------------------

    async def publish_due_notifications(self) -> int:
        """Publish all notifications whose scheduled_at has passed.

        Returns the count of newly published notifications.
        """
        now = datetime.now(timezone.utc)
        stmt = select(PlatformNotification).where(
            and_(
                PlatformNotification.is_active.is_(True),
                PlatformNotification.scheduled_at.isnot(None),
                PlatformNotification.scheduled_at <= now,
                PlatformNotification.published_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        notifications = list(result.scalars().all())

        for notif in notifications:
            notif.published_at = now
            notif.updated_at = now

        await self.db.flush()
        count = len(notifications)
        if count > 0:
            logger.info("Published %d scheduled notification(s)", count)
        return count


# ---------------------------------------------------------------------------
# Target matching logic (Task 48.4)
# ---------------------------------------------------------------------------


def _matches_target(
    notif: PlatformNotification,
    org_id: uuid.UUID,
    org_country: str | None = None,
    org_trade_family: str | None = None,
    org_plan_tier: str | None = None,
) -> bool:
    """Check if a notification's target matches the given org context."""
    if notif.target_type == "all":
        return True

    target_value = notif.target_value
    if not target_value:
        return True  # No target_value means all

    # Parse target_value — could be JSON array or single value
    try:
        values = json.loads(target_value)
        if isinstance(values, str):
            values = [values]
    except (json.JSONDecodeError, TypeError):
        values = [target_value]

    if notif.target_type == "country":
        return org_country is not None and org_country in values

    if notif.target_type == "trade_family":
        return org_trade_family is not None and org_trade_family in values

    if notif.target_type == "plan_tier":
        return org_plan_tier is not None and org_plan_tier in values

    if notif.target_type == "specific_orgs":
        return str(org_id) in values

    return False


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def _notification_to_dict(notif: PlatformNotification) -> dict[str, Any]:
    """Convert a PlatformNotification ORM instance to a dict."""
    return {
        "id": str(notif.id),
        "notification_type": notif.notification_type,
        "title": notif.title,
        "message": notif.message,
        "severity": notif.severity,
        "target_type": notif.target_type,
        "target_value": notif.target_value,
        "scheduled_at": notif.scheduled_at,
        "published_at": notif.published_at,
        "expires_at": notif.expires_at,
        "maintenance_start": notif.maintenance_start,
        "maintenance_end": notif.maintenance_end,
        "is_active": notif.is_active,
        "created_by": str(notif.created_by) if notif.created_by else None,
        "created_at": notif.created_at,
        "updated_at": notif.updated_at,
    }
