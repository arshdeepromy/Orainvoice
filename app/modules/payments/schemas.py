"""Pydantic schemas for Payment module.

Requirements: 24.1, 24.2, 24.3
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CashPaymentRequest(BaseModel):
    """Request body for recording a cash payment against an invoice."""

    invoice_id: uuid.UUID = Field(..., description="ID of the invoice to pay")
    amount: Decimal = Field(
        ..., gt=0, description="Cash amount received (must be > 0)"
    )
    notes: str | None = Field(
        None, max_length=500, description="Optional payment notes"
    )

    @field_validator("amount")
    @classmethod
    def validate_amount_precision(cls, v: Decimal) -> Decimal:
        """Ensure amount has at most 2 decimal places."""
        if v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v


class PaymentResponse(BaseModel):
    """Response for a single payment record."""

    id: uuid.UUID
    org_id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    method: str
    recorded_by: uuid.UUID
    created_at: datetime
    notes: str | None = None

    # Invoice status after payment
    invoice_status: str
    invoice_balance_due: Decimal
    invoice_amount_paid: Decimal

    model_config = {"from_attributes": True}


class CashPaymentResponse(BaseModel):
    """Wrapper response for the POST /payments/cash endpoint."""

    payment: PaymentResponse
    message: str


# ---------------------------------------------------------------------------
# Stripe Connect OAuth schemas (Req 25.1, 25.2)
# ---------------------------------------------------------------------------


class StripeConnectInitResponse(BaseModel):
    """Response from POST /billing/stripe/connect — returns the OAuth URL."""

    authorize_url: str = Field(..., description="Stripe Connect OAuth URL to redirect the user to")
    message: str = Field(
        default="Redirect the Org Admin to this URL to connect their Stripe account",
    )


class StripeConnectCallbackResponse(BaseModel):
    """Response from GET /billing/stripe/connect/callback — confirms connection."""

    stripe_account_id: str = Field(..., description="Connected Stripe account ID (acct_...)")
    org_id: uuid.UUID = Field(..., description="Organisation that was connected")
    message: str = Field(default="Stripe account connected successfully")


# ---------------------------------------------------------------------------
# Stripe payment link schemas (Req 25.3, 25.5)
# ---------------------------------------------------------------------------


class StripePaymentLinkRequest(BaseModel):
    """Request body for generating a Stripe payment link."""

    invoice_id: uuid.UUID = Field(
        ..., description="ID of the invoice to generate a payment link for"
    )
    amount: Decimal | None = Field(
        None,
        gt=0,
        description=(
            "Optional partial payment amount. If omitted, the full "
            "balance_due is used. Supports deposit scenarios (Req 25.5)."
        ),
    )
    send_via: str = Field(
        "none",
        description="How to deliver the link: 'email', 'sms', or 'none'",
    )

    @field_validator("amount")
    @classmethod
    def validate_amount_precision(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v

    @field_validator("send_via")
    @classmethod
    def validate_send_via(cls, v: str) -> str:
        allowed = {"email", "sms", "none"}
        if v not in allowed:
            raise ValueError(f"send_via must be one of {allowed}")
        return v


class StripePaymentLinkResponse(BaseModel):
    """Response from POST /payments/stripe/create-link."""

    payment_url: str = Field(
        ..., description="Stripe Checkout Session URL for the customer"
    )
    invoice_id: uuid.UUID = Field(
        ..., description="The invoice this payment link is for"
    )
    amount: Decimal = Field(
        ..., description="The payment amount (may be partial)"
    )
    send_via: str = Field(
        ..., description="Delivery method used: email, sms, or none"
    )
    message: str = Field(default="Payment link generated successfully")


# ---------------------------------------------------------------------------
# Stripe webhook schemas (Req 25.4)
# ---------------------------------------------------------------------------


class StripeWebhookResponse(BaseModel):
    """Response from POST /payments/stripe/webhook."""

    status: str = Field(
        ..., description="Processing result: 'processed', 'ignored', or 'error'"
    )
    reason: str | None = Field(
        None, description="Explanation when status is 'ignored' or 'error'"
    )
    payment_id: str | None = Field(
        None, description="Created payment ID when status is 'processed'"
    )
    invoice_id: str | None = Field(
        None, description="Invoice ID when status is 'processed'"
    )
    invoice_status: str | None = Field(
        None, description="New invoice status when status is 'processed'"
    )
    amount: str | None = Field(
        None, description="Payment amount when status is 'processed'"
    )


# ---------------------------------------------------------------------------
# Payment history schemas (Req 26.1)
# ---------------------------------------------------------------------------


class PaymentHistoryItem(BaseModel):
    """A single payment/refund event in the payment history."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    amount: Decimal
    method: str
    is_refund: bool = False
    refund_note: str | None = None
    stripe_payment_intent_id: str | None = None
    recorded_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentHistoryResponse(BaseModel):
    """Response for GET /payments/invoice/{id}/history."""

    invoice_id: uuid.UUID
    payments: list[PaymentHistoryItem]
    total_paid: Decimal
    total_refunded: Decimal
    net_paid: Decimal


# ---------------------------------------------------------------------------
# Refund schemas (Req 26.2, 26.3)
# ---------------------------------------------------------------------------


class RefundRequest(BaseModel):
    """Request body for processing a refund."""

    invoice_id: uuid.UUID = Field(..., description="ID of the invoice to refund")
    amount: Decimal = Field(..., gt=0, description="Refund amount (must be > 0)")
    method: str = Field(
        ...,
        description="Refund method: 'cash' for manual refund, 'stripe' for Stripe API refund",
    )
    notes: str | None = Field(
        None, max_length=1000, description="Reason or note for the refund"
    )

    @field_validator("amount")
    @classmethod
    def validate_amount_precision(cls, v: Decimal) -> Decimal:
        if v.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        allowed = {"cash", "stripe"}
        if v not in allowed:
            raise ValueError(f"method must be one of {allowed}")
        return v


class RefundResponse(BaseModel):
    """Response from POST /payments/refund."""

    refund: PaymentHistoryItem
    invoice_id: uuid.UUID
    invoice_status: str
    invoice_balance_due: Decimal
    invoice_amount_paid: Decimal
    stripe_refund_id: str | None = None
    message: str
