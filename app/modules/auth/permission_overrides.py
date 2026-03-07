"""User permission overrides model and service.

Supports custom permission overrides per user that can grant or revoke
specific capabilities within their base role.

**Validates: Requirement 8.5, 8.7**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserPermissionOverride(Base):
    """Per-user permission override — grants or revokes a specific permission."""

    __tablename__ = "user_permission_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    permission_key: Mapped[str] = mapped_column(String(100), nullable=False)
    is_granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# Service functions for managing permission overrides
# ---------------------------------------------------------------------------


async def create_or_update_permission_override(
    session,
    *,
    user_id,
    permission_key: str,
    is_granted: bool,
    granted_by,
    org_id=None,
) -> UserPermissionOverride:
    """Create or update a permission override and record it in the audit log.

    **Validates: Requirement 8.5, 8.7**
    """
    from sqlalchemy import select
    from app.core.audit import write_audit_log

    # Check for existing override
    result = await session.execute(
        select(UserPermissionOverride).where(
            UserPermissionOverride.user_id == user_id,
            UserPermissionOverride.permission_key == permission_key,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        before_value = {
            "permission_key": existing.permission_key,
            "is_granted": existing.is_granted,
        }
        existing.is_granted = is_granted
        existing.granted_by = granted_by
        override = existing
        action = "permission_override.updated"
    else:
        override = UserPermissionOverride(
            user_id=user_id,
            permission_key=permission_key,
            is_granted=is_granted,
            granted_by=granted_by,
        )
        session.add(override)
        before_value = None
        action = "permission_override.created"

    after_value = {
        "permission_key": permission_key,
        "is_granted": is_granted,
    }

    await write_audit_log(
        session,
        action=action,
        entity_type="user_permission_override",
        org_id=org_id,
        user_id=granted_by,
        entity_id=user_id,
        before_value=before_value,
        after_value=after_value,
    )

    return override


async def delete_permission_override(
    session,
    *,
    user_id,
    permission_key: str,
    deleted_by,
    org_id=None,
) -> bool:
    """Delete a permission override and record it in the audit log.

    Returns True if an override was deleted, False if none existed.
    """
    from sqlalchemy import select, delete
    from app.core.audit import write_audit_log

    result = await session.execute(
        select(UserPermissionOverride).where(
            UserPermissionOverride.user_id == user_id,
            UserPermissionOverride.permission_key == permission_key,
        )
    )
    existing = result.scalar_one_or_none()

    if not existing:
        return False

    before_value = {
        "permission_key": existing.permission_key,
        "is_granted": existing.is_granted,
    }

    await session.delete(existing)

    await write_audit_log(
        session,
        action="permission_override.deleted",
        entity_type="user_permission_override",
        org_id=org_id,
        user_id=deleted_by,
        entity_id=user_id,
        before_value=before_value,
        after_value=None,
    )

    return True
