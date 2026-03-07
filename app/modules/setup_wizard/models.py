"""SQLAlchemy ORM model for the setup_wizard_progress table.

Maps to the table created by migration 0014.

**Validates: Requirement 5.8**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SetupWizardProgress(Base):
    """Tracks setup wizard completion state per organisation.

    Each org has at most one progress record (org_id is UNIQUE).
    Individual step completion is tracked via boolean columns.
    """

    __tablename__ = "setup_wizard_progress"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        unique=True,
        nullable=False,
    )
    step_1_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_2_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_3_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_4_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_5_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_6_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    step_7_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    wizard_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
