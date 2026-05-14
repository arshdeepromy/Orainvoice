"""Service layer for in-app notifications.

Provides helpers for creating notifications (exception-safe), listing the
inbox, counting unread items, and managing read/dismiss state.

Requirements: 4.1, 4.2, 8.4
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.in_app_notifications.models import AppNotification, NotificationRead

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_link_url(link_url: str | None) -> str | None:
    """Validate link_url is relative (starts with /, no ://).

    Returns the url if valid, None otherwise (with a warning log).
    """
    if link_url is None:
        return None
    if not link_url.startswith("/") or "://" in link_url:
        logger.warning(
            "in_app_notification.invalid_link_url url=%s — must start with / and not contain ://",
            link_url,
        )
        return None
    return link_url


def _build_visibility_filter(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
):
    """Build the WHERE clause for notification visibility per design §13.

    A notification is visible to a user if:
    - It targets them specifically (user_id == current user), OR
    - It is org-wide (user_id IS NULL) AND the user's role is in audience_roles
    """
    return and_(
        AppNotification.org_id == org_id,
        (
            AppNotification.user_id == user_id
        ) | (
            and_(
                AppNotification.user_id.is_(None),
                AppNotification.audience_roles.op("@>")(
                    func.cast(f'["{role}"]', type_=AppNotification.audience_roles.type)
                ),
            )
        ),
    )


def _not_dismissed_subquery(user_id: uuid.UUID):
    """Build a NOT EXISTS subquery excluding dismissed notifications."""
    return ~(
        select(NotificationRead.id)
        .where(
            NotificationRead.notification_id == AppNotification.id,
            NotificationRead.user_id == user_id,
            NotificationRead.dismissed_at.is_not(None),
        )
        .correlate(AppNotification)
        .exists()
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_in_app_notification(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    category: str,
    severity: str,
    title: str,
    body: str | None = None,
    user_id: uuid.UUID | None = None,
    link_url: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    audience_roles: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    expires_at: datetime | None = None,
) -> uuid.UUID | None:
    """Create one notification row. Returns the new id, or None on failure.

    Never raises. All exceptions caught and logged. The helper is safe to
    call from any service without try/except at the call site.

    Requirements: 4.1, 8.4
    """
    try:
        # Validate link_url — reject invalid but still create the notification
        validated_link_url = _validate_link_url(link_url)

        notif = AppNotification(
            org_id=org_id,
            user_id=user_id,
            category=category,
            severity=severity,
            title=title[:255],
            body=body[:2000] if body else None,
            link_url=validated_link_url,
            entity_type=entity_type,
            entity_id=entity_id,
            audience_roles=audience_roles or ["org_admin"],
            metadata_=metadata or {},
            expires_at=expires_at,
        )
        db.add(notif)
        await db.flush()
        await db.refresh(notif)
        return notif.id
    except Exception as exc:
        logger.warning(
            "in_app_notification.create_failed category=%s err=%s",
            category,
            exc,
        )
        return None


async def list_inbox(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
    category: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    """Return { items: [...], total, unread_count }.

    Visibility filter per design §13:
    - notifications where user_id == current user, OR
    - notifications where user_id IS NULL AND role IN audience_roles

    Excludes rows where notification_reads.dismissed_at IS NOT NULL.

    Requirements: 4.2
    """
    visibility = _build_visibility_filter(org_id, user_id, role)
    not_dismissed = _not_dismissed_subquery(user_id)

    # Base query for items — LEFT JOIN to get read state
    read_subq = (
        select(
            NotificationRead.notification_id,
            NotificationRead.read_at,
            NotificationRead.dismissed_at,
        )
        .where(NotificationRead.user_id == user_id)
        .subquery()
    )

    base_filter = and_(visibility, not_dismissed)

    # Apply optional filters
    extra_filters = []
    if category:
        extra_filters.append(AppNotification.category == category)
    if severity:
        extra_filters.append(AppNotification.severity == severity)
    if unread_only:
        # Unread = no read row OR read_at IS NULL
        unread_subq = ~(
            select(NotificationRead.id)
            .where(
                NotificationRead.notification_id == AppNotification.id,
                NotificationRead.user_id == user_id,
                NotificationRead.read_at.is_not(None),
            )
            .correlate(AppNotification)
            .exists()
        )
        extra_filters.append(unread_subq)

    all_filters = and_(base_filter, *extra_filters) if extra_filters else base_filter

    # Total count
    count_stmt = select(func.count(AppNotification.id)).where(all_filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Unread count (always unfiltered by category/severity — badge number)
    unread_count = await get_unread_count(db, org_id=org_id, user_id=user_id, role=role)

    # Fetch items with read state
    items_stmt = (
        select(
            AppNotification,
            read_subq.c.read_at,
        )
        .outerjoin(
            read_subq,
            AppNotification.id == read_subq.c.notification_id,
        )
        .where(all_filters)
        .order_by(AppNotification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(items_stmt)
    rows = result.all()

    items = []
    for row in rows:
        notif = row[0]
        read_at = row[1]
        items.append({
            "id": str(notif.id),
            "category": notif.category,
            "severity": notif.severity,
            "title": notif.title,
            "body": notif.body,
            "link_url": notif.link_url,
            "entity_type": notif.entity_type,
            "entity_id": str(notif.entity_id) if notif.entity_id else None,
            "metadata": notif.metadata_,
            "created_at": notif.created_at.isoformat() if notif.created_at else "",
            "is_read": read_at is not None,
            "read_at": read_at.isoformat() if read_at else None,
        })

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
    }


async def get_unread_count(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> int:
    """Return the number of unread, non-dismissed notifications for a user.

    Uses the visibility filter from design §13 and a NOT EXISTS subquery
    for read/dismissed state. Designed to be cheap for 30s polling.

    Requirements: 4.2.6
    """
    visibility = _build_visibility_filter(org_id, user_id, role)

    # NOT EXISTS: no read row with read_at or dismissed_at set
    not_read_or_dismissed = ~(
        select(NotificationRead.id)
        .where(
            NotificationRead.notification_id == AppNotification.id,
            NotificationRead.user_id == user_id,
            (NotificationRead.read_at.is_not(None)) | (NotificationRead.dismissed_at.is_not(None)),
        )
        .correlate(AppNotification)
        .exists()
    )

    stmt = select(func.count(AppNotification.id)).where(
        and_(visibility, not_read_or_dismissed)
    )
    result = await db.execute(stmt)
    return result.scalar() or 0


async def mark_read(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> bool:
    """Mark a single notification as read for the given user.

    Creates a notification_reads row if missing, sets read_at.
    Idempotent — calling again on an already-read notification is a no-op.

    Requirements: 4.2.3
    """
    # Check if a read row already exists
    stmt = select(NotificationRead).where(
        NotificationRead.notification_id == notification_id,
        NotificationRead.user_id == user_id,
    )
    result = await db.execute(stmt)
    read_row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if read_row is None:
        # Create new read row
        read_row = NotificationRead(
            org_id=org_id,
            notification_id=notification_id,
            user_id=user_id,
            read_at=now,
        )
        db.add(read_row)
        await db.flush()
        return True

    if read_row.read_at is None:
        read_row.read_at = now
        await db.flush()
        return True

    # Already read — idempotent
    return True


async def mark_all_read(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> int:
    """Mark all visible, unread notifications as read for the user.

    Returns the count of notifications marked read.

    Requirements: 4.2
    """
    visibility = _build_visibility_filter(org_id, user_id, role)
    not_dismissed = _not_dismissed_subquery(user_id)

    # Find all visible notification IDs that are not yet read
    not_read = ~(
        select(NotificationRead.id)
        .where(
            NotificationRead.notification_id == AppNotification.id,
            NotificationRead.user_id == user_id,
            NotificationRead.read_at.is_not(None),
        )
        .correlate(AppNotification)
        .exists()
    )

    notif_ids_stmt = select(AppNotification.id).where(
        and_(visibility, not_dismissed, not_read)
    )
    result = await db.execute(notif_ids_stmt)
    notif_ids = [row[0] for row in result.all()]

    if not notif_ids:
        return 0

    now = datetime.now(timezone.utc)
    count = 0

    for nid in notif_ids:
        # Check if read row exists
        existing_stmt = select(NotificationRead).where(
            NotificationRead.notification_id == nid,
            NotificationRead.user_id == user_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()

        if existing is None:
            read_row = NotificationRead(
                org_id=org_id,
                notification_id=nid,
                user_id=user_id,
                read_at=now,
            )
            db.add(read_row)
            count += 1
        elif existing.read_at is None:
            existing.read_at = now
            count += 1

    if count > 0:
        await db.flush()

    return count


async def dismiss(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> bool:
    """Dismiss a notification for the given user.

    Sets dismissed_at on the notification_reads row. Creates the row if
    it doesn't exist. Idempotent.

    Requirements: 4.2.4
    """
    stmt = select(NotificationRead).where(
        NotificationRead.notification_id == notification_id,
        NotificationRead.user_id == user_id,
    )
    result = await db.execute(stmt)
    read_row = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if read_row is None:
        read_row = NotificationRead(
            org_id=org_id,
            notification_id=notification_id,
            user_id=user_id,
            read_at=now,
            dismissed_at=now,
        )
        db.add(read_row)
        await db.flush()
        return True

    if read_row.dismissed_at is None:
        read_row.dismissed_at = now
        if read_row.read_at is None:
            read_row.read_at = now
        await db.flush()
        return True

    # Already dismissed — idempotent
    return True


async def dismiss_all_read(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> int:
    """Dismiss all notifications that are currently read (but not yet dismissed).

    Returns the count of notifications dismissed.

    Requirements: 4.2
    """
    stmt = (
        update(NotificationRead)
        .where(
            NotificationRead.org_id == org_id,
            NotificationRead.user_id == user_id,
            NotificationRead.read_at.is_not(None),
            NotificationRead.dismissed_at.is_(None),
        )
        .values(dismissed_at=datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0
