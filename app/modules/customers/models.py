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
    """Customer record — scoped to a single organisation.
    
    Supports both individual and business customers with comprehensive
    contact, billing, and preference fields.
    """

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
    
    # Customer type and identity
    customer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="individual",
        comment="business or individual"
    )
    salutation: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Mr, Mrs, Ms, Dr, etc."
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    company_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Company name for business customers"
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Display name for invoices"
    )
    
    # Contact information
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    work_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Work phone number"
    )
    mobile_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Mobile phone number"
    )
    
    # Preferences
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="NZD",
        comment="ISO 4217 currency code"
    )
    language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="en",
        comment="Customer preferred language"
    )
    
    # Business/Tax settings
    tax_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Default tax rate"
    )
    company_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Business registration number"
    )
    payment_terms: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="due_on_receipt",
        comment="Payment terms: due_on_receipt, net_15, net_30, net_60"
    )
    
    # Portal and payment options
    enable_bank_payment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
        comment="Allow bank account payment"
    )
    enable_portal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
        comment="Allow customer portal access"
    )
    
    # Addresses (structured JSONB)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_address: Mapped[dict] = mapped_column(
        JSONB, nullable=True, server_default=text("'{}'::jsonb"),
        comment="Structured billing address"
    )
    shipping_address: Mapped[dict] = mapped_column(
        JSONB, nullable=True, server_default=text("'{}'::jsonb"),
        comment="Structured shipping address"
    )
    
    # Additional data
    contact_persons: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
        comment="Additional contact persons"
    )
    custom_fields: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
        comment="Custom fields key-value pairs"
    )
    documents: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"),
        comment="Attached document references"
    )
    
    # Notes and remarks
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    remarks: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Additional remarks"
    )
    
    # Ownership and fleet
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="Customer owner/assigned user"
    )
    fleet_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fleet_accounts.id"), nullable=True
    )
    
    # Status flags
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
    portal_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=text("now() + interval '90 days'"),
        comment="Portal token expiry timestamp (REM-15)",
    )
    
    # Timestamps
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
        Index("idx_customers_type", "org_id", "customer_type"),
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
