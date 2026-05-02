"""SQLAlchemy ORM models for the Customer Portal module.

Tables:
- portal_sessions: session-based portal access with HttpOnly cookies

Requirements: 40.1, 40.2, 40.3, 40.4
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PortalSession(Base):
    """Portal session — tracks authenticated portal access via HttpOnly cookie.

    After initial token validation, a session is created and the
    session_token is stored in an HttpOnly cookie.  Subsequent requests
    validate the cookie instead of requiring the portal token in the URL.

    Sessions expire after 4 hours of inactivity (last_seen + 4h < now).
    """

    __tablename__ = "portal_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_token: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_portal_sessions_session_token", "session_token"),
        Index("ix_portal_sessions_customer_id", "customer_id"),
    )
