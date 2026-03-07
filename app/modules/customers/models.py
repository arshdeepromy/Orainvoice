"""SQLAlchemy ORM models for customer-scoped tables.

Tables:
- fleet_accounts: commercial customer accounts (RLS enabled)
- customers: individual customer records (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FleetAccount(Base):
    """Fleet account — groups multiple vehicles under a commercial customer."""

    __tablename__ = "fleet_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_contact_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    primary_contact_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    primary_contact_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    pricing_overrides: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="fleet_accounts")
    customers: Mapped[list[Customer]] = relationship(back_populates="fleet_account")


class Customer(Base):
    """Customer record — scoped to a single organisation."""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    fleet_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fleet_accounts.id"), nullable=True
    )
    is_anonymised: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_bounced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    tags: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    portal_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_customers_org", "org_id"),
        Index(
            "idx_customers_search",
            text(
                "to_tsvector('english', "
                "first_name || ' ' || last_name || ' ' || "
                "COALESCE(email,'') || ' ' || COALESCE(phone,''))"
            ),
            postgresql_using="gin",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="customers")
    fleet_account: Mapped[FleetAccount | None] = relationship(
        back_populates="customers"
    )
