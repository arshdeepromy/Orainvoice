"""SQLAlchemy ORM models for the double-entry general ledger.

Tables:
- accounts: Chart of Accounts (COA) per organisation (RLS enabled)
- journal_entries: double-entry journal headers (RLS enabled)
- journal_lines: individual debit/credit lines (RLS enabled)
- accounting_periods: closable date-bounded periods (RLS enabled)
- gst_filing_periods: GST filing period tracking (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Account (Chart of Accounts)
# ---------------------------------------------------------------------------


class Account(Base):
    """Organisation-scoped chart-of-accounts entry."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sub_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )
    tax_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    xero_account_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True
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
        UniqueConstraint("org_id", "code", name="uq_accounts_org_code"),
        CheckConstraint(
            "account_type IN ('asset','liability','equity','revenue','expense','cogs')",
            name="ck_accounts_type",
        ),
    )

    # Relationships
    journal_lines: Mapped[list[JournalLine]] = relationship(
        back_populates="account",
    )
    children: Mapped[list[Account]] = relationship(
        "Account",
        back_populates="parent",
        foreign_keys=[parent_id],
    )
    parent: Mapped[Account | None] = relationship(
        "Account",
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_id],
    )


# ---------------------------------------------------------------------------
# Accounting Period
# ---------------------------------------------------------------------------


class AccountingPeriod(Base):
    """Date-bounded accounting period that can be closed."""

    __tablename__ = "accounting_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    period_name: Mapped[str] = mapped_column(String(50), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        CheckConstraint(
            "start_date < end_date",
            name="ck_accounting_periods_dates",
        ),
    )


# ---------------------------------------------------------------------------
# Journal Entry
# ---------------------------------------------------------------------------


class JournalEntry(Base):
    """Double-entry journal header with one or more lines."""

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    entry_number: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounting_periods.id"),
        nullable=True,
    )
    is_posted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
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
        CheckConstraint(
            "source_type IN ('invoice','payment','expense','credit_note','manual')",
            name="ck_journal_entries_source_type",
        ),
    )

    # Relationships
    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
    )
    period: Mapped[AccountingPeriod | None] = relationship()


# ---------------------------------------------------------------------------
# Journal Line
# ---------------------------------------------------------------------------


class JournalLine(Base):
    """Single debit or credit line within a journal entry."""

    __tablename__ = "journal_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    debit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    credit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0)",
            name="ck_journal_lines_one_side",
        ),
    )

    # Relationships
    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[Account] = relationship(back_populates="journal_lines")


# ---------------------------------------------------------------------------
# GST Filing Period
# ---------------------------------------------------------------------------


class GstFilingPeriod(Base):
    """GST filing period with status tracking from draft through IRD acceptance."""

    __tablename__ = "gst_filing_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    filed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    filed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    ird_reference: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    return_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
        CheckConstraint(
            "period_type IN ('two_monthly','six_monthly','annual')",
            name="ck_gst_filing_periods_type",
        ),
        CheckConstraint(
            "status IN ('draft','ready','filed','accepted','rejected')",
            name="ck_gst_filing_periods_status",
        ),
    )
