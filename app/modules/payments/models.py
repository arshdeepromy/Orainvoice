"""SQLAlchemy ORM models for payment-scoped tables.

Tables:
- payments: cash and Stripe payment records per organisation (RLS enabled)
- payment_tokens: secure, time-limited tokens for public payment page access
- pending_qr_sessions: active Stripe Checkout Sessions for kiosk QR payment flow
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Payment(Base):
    """Organisation-scoped payment record (cash or Stripe)."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    is_refund: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    refund_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    surcharge_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0.00"
    )
    payment_method_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "method IN ('cash','stripe')",
            name="ck_payments_method",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="payments")
    invoice = relationship("Invoice", back_populates="payments")
    recorded_by_user = relationship("User", backref="recorded_payments")


class PaymentToken(Base):
    """Secure, time-limited token for public payment page access.

    Token format: ``secrets.token_urlsafe(48)`` (~64 chars).
    Expiry: 72 hours from creation.
    When a new token is generated for the same invoice, all previous
    tokens are set to ``is_active = False``.
    """

    __tablename__ = "payment_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    amount_override: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
        comment=(
            "Partial-payment amount for the QR partial-payment flow. "
            "NULL means use invoice.balance_due (default behaviour)."
        ),
    )
    last_pi_amount_cents: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment=(
            "Cached cents value of the PaymentIntent's last-known "
            "amount, used by create_qr_session_for_existing_invoice "
            "to make a same-amount-reuse decision without a "
            "synchronous Stripe API call. Refreshed on every "
            "successful PI create or update-surcharge call."
        ),
    )

    # Relationships
    invoice = relationship("Invoice", backref="payment_tokens")
    organisation = relationship("Organisation", backref="payment_tokens")


class PendingQrSession(Base):
    """Active Stripe Checkout Session for kiosk QR payment flow.

    One active session per org (UNIQUE on org_id). The kiosk polls for
    pending sessions and displays the QR code encoding the checkout_url.
    Rows are deleted when payment completes (webhook), session expires,
    or a new session replaces the old one for the same org.
    """

    __tablename__ = "pending_qr_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True,
    )
    checkout_url: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    # Soft-dismiss marker: set when the kiosk's "Close" button is pressed.
    # The poll filters out rows where dismissed_at IS NOT NULL so the
    # popup doesn't re-appear on kiosk page refresh, but the row + the
    # underlying Stripe PaymentIntent stay alive so the customer who
    # already scanned can complete payment from their phone. Cleared
    # by create_qr_session_for_existing_invoice when staff re-fires QR
    # Payment (so the popup re-appears for the new attempt).
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "When the kiosk dismissed this pending session display. "
            "NULL = visible to kiosk poll. NOT NULL = hidden but Stripe "
            "session stays alive for the customer to complete payment."
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="pending_qr_sessions")
    invoice = relationship("Invoice", backref="pending_qr_sessions")
