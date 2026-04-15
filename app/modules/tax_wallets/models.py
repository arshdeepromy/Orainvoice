"""SQLAlchemy ORM models for the tax wallets module.

Tables:
- tax_wallets: Virtual tax savings wallets per organisation (RLS enabled)
- tax_wallet_transactions: Deposits/withdrawals in tax wallets (RLS enabled)

Requirements: 20.1, 20.2
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TaxWallet(Base):
    """Organisation-scoped virtual tax savings wallet."""

    __tablename__ = "tax_wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    wallet_type: Mapped[str] = mapped_column(String(20), nullable=False)
    balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    target_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
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
        UniqueConstraint("org_id", "wallet_type", name="uq_tax_wallets_org_type"),
        CheckConstraint(
            "wallet_type IN ('gst','income_tax','provisional_tax')",
            name="ck_tax_wallets_type",
        ),
    )

    transactions: Mapped[list[TaxWalletTransaction]] = relationship(
        back_populates="wallet",
        cascade="all, delete-orphan",
    )


class TaxWalletTransaction(Base):
    """Single deposit or withdrawal in a tax wallet."""

    __tablename__ = "tax_wallet_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_wallets.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('auto_sweep','manual_deposit','manual_withdrawal','tax_payment')",
            name="ck_wallet_tx_type",
        ),
    )

    wallet: Mapped[TaxWallet] = relationship(back_populates="transactions")
