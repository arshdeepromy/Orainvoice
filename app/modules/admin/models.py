"""SQLAlchemy ORM models for global (platform-wide) tables.

These tables have NO row-level security — they are shared across all
organisations or managed exclusively by Global Admins.

Tables:
- subscription_plans: plan definitions configured by Global Admin
- organisations: tenant records
- global_vehicles: shared Carjam vehicle cache
- integration_configs: encrypted third-party credentials
- platform_settings: key-value platform configuration
"""

from __future__ import annotations

import uuid
from datetime import datetime, date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Subscription Plans
# ---------------------------------------------------------------------------

class SubscriptionPlan(Base):
    """Subscription plans configured by Global Admin."""

    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_price_nzd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    user_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_quota_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    carjam_lookups_included: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled_modules: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    storage_tier_pricing: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="'{}'")
    trial_duration: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="0")
    trial_duration_unit: Mapped[str | None] = mapped_column(String(10), nullable=True, server_default="'days'")
    sms_included: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    per_sms_cost_nzd: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, server_default="0")
    sms_included_quota: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sms_package_pricing: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="'[]'")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organisations: Mapped[list[Organisation]] = relationship(back_populates="plan")


# ---------------------------------------------------------------------------
# Organisations (tenants)
# ---------------------------------------------------------------------------

class Organisation(Base):
    """Organisation / tenant record."""

    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="'active'",
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_connect_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_quota_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    carjam_lookups_this_month: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    carjam_lookups_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sms_sent_this_month: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sms_sent_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'")
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="'en'"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('trial','active','grace_period','suspended','deleted')",
            name="ck_organisations_status",
        ),
    )

    # Relationships
    plan: Mapped[SubscriptionPlan] = relationship(back_populates="organisations")
    users: Mapped[list] = relationship("User", back_populates="organisation")
    sms_package_purchases: Mapped[list[SmsPackagePurchase]] = relationship(back_populates="organisation")


# ---------------------------------------------------------------------------
# SMS Package Purchases
# ---------------------------------------------------------------------------

class SmsPackagePurchase(Base):
    """SMS package purchase record for FIFO credit tracking."""

    __tablename__ = "sms_package_purchases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    tier_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sms_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_nzd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organisation: Mapped[Organisation] = relationship(back_populates="sms_package_purchases")


# ---------------------------------------------------------------------------
# Global Vehicles (shared Carjam cache)
# ---------------------------------------------------------------------------

class GlobalVehicle(Base):
    """Global vehicle database — shared across all organisations."""

    __tablename__ = "global_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    rego: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    colour: Mapped[str | None] = mapped_column(String(50), nullable=True)
    body_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engine_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    num_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wof_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    odometer_last_recorded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    
    # Extended fields
    vin: Mapped[str | None] = mapped_column(String(17), nullable=True)
    chassis: Mapped[str | None] = mapped_column(String(50), nullable=True)
    engine_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String(50), nullable=True)
    number_of_owners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reported_stolen: Mapped[str | None] = mapped_column(String(10), nullable=True)
    power_kw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tare_weight: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gross_vehicle_mass: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_first_registered_nz: Mapped[date | None] = mapped_column(Date, nullable=True)
    plate_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    submodel: Mapped[str | None] = mapped_column(String(150), nullable=True)
    second_colour: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # Lookup metadata
    lookup_type: Mapped[str | None] = mapped_column(String(10), nullable=True, server_default='basic')
    
    last_pulled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_global_vehicles_rego", "rego"),
        Index("idx_global_vehicles_vin", "vin"),
    )


# ---------------------------------------------------------------------------
# Integration Configs
# ---------------------------------------------------------------------------

class IntegrationConfig(Base):
    """Global admin integration configuration (encrypted credentials)."""

    __tablename__ = "integration_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "name IN ('carjam','stripe','smtp','twilio')",
            name="ck_integration_configs_name",
        ),
    )


# ---------------------------------------------------------------------------
# Platform Settings
# ---------------------------------------------------------------------------

class PlatformSetting(Base):
    """Key-value platform settings (T&C, announcements, etc.)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Audit Log (append-only, no RLS)
# ---------------------------------------------------------------------------

class AuditLog(Base):
    """Append-only audit log. UPDATE and DELETE are revoked at the DB level."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    before_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_log_org", "org_id", "created_at"),
        Index("idx_audit_log_entity", "entity_type", "entity_id"),
    )


# ---------------------------------------------------------------------------
# Error Log (no RLS, Global Admin only)
# ---------------------------------------------------------------------------

class ErrorLog(Base):
    """Error log for platform-wide error tracking. Global Admin access only."""

    __tablename__ = "error_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    module: Mapped[str] = mapped_column(String(100), nullable=False)
    function_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    http_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_body_sanitised: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_body_sanitised: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'open'"
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','warning','error','critical')",
            name="ck_error_log_severity",
        ),
        CheckConstraint(
            "category IN ('payment','integration','storage','authentication','data','background_job','application')",
            name="ck_error_log_category",
        ),
        CheckConstraint(
            "status IN ('open','investigating','resolved')",
            name="ck_error_log_status",
        ),
    )


# ---------------------------------------------------------------------------
# SMS Verification Providers
# ---------------------------------------------------------------------------

class SmsVerificationProvider(Base):
    """SMS verification provider configuration for phone number verification."""

    __tablename__ = "sms_verification_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credentials_set: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="'{}'::jsonb")
    setup_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Email Providers
# ---------------------------------------------------------------------------

class EmailProvider(Base):
    """Email/SMTP provider configuration for transactional email delivery."""

    __tablename__ = "email_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    provider_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_encryption: Mapped[str | None] = mapped_column(String(10), nullable=True, server_default="'tls'")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credentials_set: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="'{}'::jsonb")
    setup_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Public Holidays
# ---------------------------------------------------------------------------

class PublicHoliday(Base):
    """Public holiday records synced from external calendar APIs."""

    __tablename__ = "public_holidays"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("country_code", "holiday_date", "name", name="uq_public_holidays_country_date_name"),
        Index("ix_public_holidays_country_year", "country_code", "year"),
    )
