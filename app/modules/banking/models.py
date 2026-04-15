"""SQLAlchemy ORM models for the banking module.

Tables:
- akahu_connections: Akahu OAuth connection per organisation (RLS enabled)
- bank_accounts: Bank accounts synced from Akahu (RLS enabled)
- bank_transactions: Bank transactions with reconciliation tracking (RLS enabled)
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
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Akahu Connection
# ---------------------------------------------------------------------------


class AkahuConnection(Base):
    """Organisation-scoped Akahu OAuth connection with encrypted tokens."""

    __tablename__ = "akahu_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    access_token_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
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
        UniqueConstraint("org_id", name="uq_akahu_connections_org"),
    )


# ---------------------------------------------------------------------------
# Bank Account
# ---------------------------------------------------------------------------


class BankAccount(Base):
    """Bank account synced from Akahu, optionally linked to a GL account."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    akahu_account_id: Mapped[str] = mapped_column(String(100), nullable=False)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="NZD"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    linked_gl_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
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
        UniqueConstraint("org_id", "akahu_account_id", name="uq_bank_accounts_org_akahu"),
    )

    # Relationships
    transactions: Mapped[list[BankTransaction]] = relationship(
        back_populates="bank_account",
    )
    linked_gl_account = relationship("Account")


# ---------------------------------------------------------------------------
# Bank Transaction
# ---------------------------------------------------------------------------


class BankTransaction(Base):
    """Bank transaction imported from Akahu with reconciliation status."""

    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id"), nullable=False
    )
    akahu_transaction_id: Mapped[str] = mapped_column(String(100), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unmatched"
    )
    matched_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True
    )
    matched_expense_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expenses.id"), nullable=True
    )
    matched_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=True
    )
    akahu_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
        UniqueConstraint(
            "org_id", "akahu_transaction_id", name="uq_bank_transactions_org_akahu"
        ),
        CheckConstraint(
            "reconciliation_status IN ('unmatched','matched','excluded','manual')",
            name="ck_bank_transactions_status",
        ),
        CheckConstraint(
            "(CASE WHEN matched_invoice_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN matched_expense_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN matched_journal_id IS NOT NULL THEN 1 ELSE 0 END) <= 1",
            name="ck_bank_transactions_one_match",
        ),
    )

    # Relationships
    bank_account: Mapped[BankAccount] = relationship(back_populates="transactions")
