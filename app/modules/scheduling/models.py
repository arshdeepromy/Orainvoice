"""SQLAlchemy ORM model for staff scheduling per branch.

Tables:
- schedules: shift assignments for users at specific branches (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Schedule(Base):
    """Staff schedule entry linking a user to a branch shift.

    Each entry represents a single shift for a user at a branch on a
    specific date with start/end times.

    **Validates: Requirements 19.1**
    """

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    shift_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    start_time: Mapped[time] = mapped_column(
        Time, nullable=False,
    )
    end_time: Mapped[time] = mapped_column(
        Time, nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="schedules")
    branch = relationship("Branch", backref="schedules")
    user = relationship("User", backref="schedules")
