"""SQLAlchemy ORM model for the org_terminology_overrides table.

Maps to the existing ``org_terminology_overrides`` table created by
migration 0015.

**Validates: Requirement 4.4**
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OrgTerminologyOverride(Base):
    """Per-organisation terminology override.

    Each row maps a generic terminology key to a custom label for a
    specific organisation, taking precedence over trade category defaults.
    """

    __tablename__ = "org_terminology_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
        index=True,
    )
    generic_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    custom_label: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    __table_args__ = (
        # Unique constraint matching migration 0015
        {"info": {"unique_constraint": "uq_org_terminology_overrides_org_key"}},
    )
