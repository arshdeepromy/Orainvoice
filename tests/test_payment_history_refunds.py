"""Unit tests for Task 11.5 — payment history and refunds.

Tests cover:
  - Schema validation for RefundRequest and PaymentHistoryResponse
  - Payment history retrieval (empty, single, multiple payments + refunds)
  - Cash refund processing and invoice balance updates
  - Stripe refund processing (mocked Stripe API)
  - Refund rejection for invalid states and amounts
  - Audit log writing for refund events

Requirements: 26.1, 26.2, 26.3, 26.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.payments.schemas import (
    PaymentHistoryItem,
    PaymentHistoryResponse,
    RefundRequest,
    RefundResponse,
)
from app.modules.payments.service import get_payment_history, process_refund
from app.modules.payments.models import Payment
from app.modules.invoices.models import Invoice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_invoice(
    org_id=None,
    status="paid",
    total=Decimal("200.00"),
    amount_paid=Decimal("200.00"),
    balance_due=Decimal("0.00"),
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.status = status
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.invoice_number = "INV-0001"
    inv.currency = "NZD"
    inv.created_by = uuid.uuid4()
    return inv


def _make_payment(
    org_id=None,
    invoice_id=None,
    amount=Decimal("100.00"),
    method="cash",
    is_refund=False,
    refund_note=None,
    stripe_payment_intent_id=None,
):
    p = MagicMock(spec=Payment)
    p.id = uuid.uuid4()
    p.org_id = org_id or uuid.uuid4()
    p.invoice_id = invoice_id or uuid.uuid4()
    p.amount = amount
    p.method = method
    p.is_refund = is_refund
    p.refund_note = refund_note
    p.stripe_payment_intent_id = stripe_payment_intent_id
    p.recorded_by = uuid.uuid4()
    p.created_at = datetime.now(timezone.utc)
    return p


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestRefundRequestSchema:
    """Validate RefundRequest schema constraints."""

    def test_valid_cash_refund(self):
        req = RefundRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("50.00"),
            method="cash",
            notes="Customer returned item",
        )
        assert req.amount == Decimal("50.00")
        assert req.method == "cash"

    def test_valid_stripe_refund(self):
        req = RefundRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("75.50"),
            method="stripe",
        )
        assert req.method == "stripe"

    def test_rejects_zero_amount(self):
        with pytest.raises(Exception):
            RefundRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("0"),
                method="cash",
            )

    def test_rejects_negative_amount(self):
        with pytest.raises(Exception):
            RefundRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("-10.00"),
                method="cash",
            )

    def test_rejects_invalid_method(self):
        with pytest.raises(Exception):
            RefundRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("10.00"),
                method="bitcoin",
            )

    def test_rejects_too_many_decimal_places(self):
        with pytest.raises(Exception):
            RefundRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("10.123"),
                method="cash",
            )


# ---------------------------------------------------------------------------
# Payment history tests
# ---------------------------------------------------------------------------

class TestGetPaymentHistory:
    """Tests for get_payment_history service function."""

    @pytest.mark.asyncio
    async def test_returns_empty_history(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)

        db = _mock_db()
        # First call: invoice lookup
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        # Second call: payments query
        pay_mock = MagicMock()
        pay_scalars = MagicMock()
        pay_scalars.all.return_value = []
        pay_mock.scalars.return_value = pay_scalars

        db.execute = AsyncMock(side_effect=[inv_mock, pay_mock])

        result = await get_payment_history(
            db, org_id=org_id, invoice_id=invoice.id
        )

        assert result["invoice_id"] == invoice.id
        assert result["payments"] == []
        assert result["total_paid"] == Decimal("0")
        assert result["total_refunded"] == Decimal("0")
        assert result["net_paid"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_returns_payments_and_refunds(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        inv_id = invoice.id

        payment1 = _make_payment(
            org_id=org_id, invoice_id=inv_id,
            amount=Decimal("150.00"), method="cash",
        )
        payment2 = _make_payment(
            org_id=org_id, invoice_id=inv_id,
            amount=Decimal("50.00"), method="stripe",
        )
        refund1 = _make_payment(
            org_id=org_id, invoice_id=inv_id,
            amount=Decimal("30.00"), method="cash",
            is_refund=True, refund_note="Overcharged",
        )

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        pay_mock = MagicMock()
        pay_scalars = MagicMock()
        pay_scalars.all.return_value = [payment1, payment2, refund1]
        pay_mock.scalars.return_value = pay_scalars

        db.execute = AsyncMock(side_effect=[inv_mock, pay_mock])

        result = await get_payment_history(
            db, org_id=org_id, invoice_id=inv_id
        )

        assert len(result["payments"]) == 3
        assert result["total_paid"] == Decimal("200.00")
        assert result["total_refunded"] == Decimal("30.00")
        assert result["net_paid"] == Decimal("170.00")

    @pytest.mark.asyncio
    async def test_rejects_invoice_not_found(self):
        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=inv_mock)

        with pytest.raises(ValueError, match="Invoice not found"):
            await get_payment_history(
                db, org_id=uuid.uuid4(), invoice_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# Refund processing tests
# ---------------------------------------------------------------------------

class TestProcessRefund:
    """Tests for process_refund service function."""

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_cash_refund_updates_balance(self, mock_audit):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        result = await process_refund(
            db,
            org_id=org_id,
            user_id=user_id,
            invoice_id=invoice.id,
            amount=Decimal("50.00"),
            method="cash",
            notes="Customer returned item",
        )

        assert result["invoice_balance_due"] == Decimal("50.00")
        assert result["invoice_amount_paid"] == Decimal("150.00")
        assert result["invoice_status"] == "partially_paid"
        assert result["stripe_refund_id"] is None
        assert "50" in result["message"]
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_full_cash_refund_sets_issued(self, mock_audit):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("100.00"),
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("0.00"),
        )

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        result = await process_refund(
            db,
            org_id=org_id,
            user_id=user_id,
            invoice_id=invoice.id,
            amount=Decimal("100.00"),
            method="cash",
            notes="Full refund",
        )

        assert result["invoice_amount_paid"] == Decimal("0.00")
        assert result["invoice_balance_due"] == Decimal("100.00")
        assert result["invoice_status"] == "issued"

    @pytest.mark.asyncio
    @patch("app.integrations.stripe_connect.create_stripe_refund", new_callable=AsyncMock)
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_stripe_refund_calls_api(self, mock_audit, mock_stripe_refund):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )

        stripe_payment = _make_payment(
            org_id=org_id,
            invoice_id=invoice.id,
            amount=Decimal("200.00"),
            method="stripe",
            stripe_payment_intent_id="pi_test123",
        )

        org_mock = MagicMock()
        org_mock.id = org_id
        org_mock.stripe_connect_account_id = "acct_test456"

        mock_stripe_refund.return_value = {
            "refund_id": "re_test789",
            "status": "succeeded",
            "amount": 5000,
        }

        db = _mock_db()
        # Call 1: invoice lookup
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        # Call 2: stripe payment lookup
        stripe_pay_result = MagicMock()
        stripe_pay_result.scalar_one_or_none.return_value = stripe_payment
        # Call 3: org lookup
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org_mock

        db.execute = AsyncMock(
            side_effect=[inv_result, stripe_pay_result, org_result]
        )

        result = await process_refund(
            db,
            org_id=org_id,
            user_id=user_id,
            invoice_id=invoice.id,
            amount=Decimal("50.00"),
            method="stripe",
        )

        mock_stripe_refund.assert_called_once_with(
            payment_intent_id="pi_test123",
            amount=5000,
            stripe_account_id="acct_test456",
        )
        assert result["stripe_refund_id"] == "re_test789"
        assert result["invoice_amount_paid"] == Decimal("150.00")
        assert result["invoice_balance_due"] == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_rejects_refund_on_draft_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        with pytest.raises(ValueError, match="Cannot refund"):
            await process_refund(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("10.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    async def test_rejects_refund_on_voided_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        with pytest.raises(ValueError, match="Cannot refund"):
            await process_refund(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("10.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    async def test_rejects_refund_exceeding_amount_paid(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("100.00"),
        )

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        with pytest.raises(ValueError, match="exceeds total amount paid"):
            await process_refund(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    async def test_rejects_invoice_not_found(self):
        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=inv_mock)

        with pytest.raises(ValueError, match="Invoice not found"):
            await process_refund(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                amount=Decimal("10.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    async def test_stripe_refund_rejects_no_stripe_payment(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="paid")

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        stripe_pay_result = MagicMock()
        stripe_pay_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(
            side_effect=[inv_result, stripe_pay_result]
        )

        with pytest.raises(ValueError, match="No Stripe payment found"):
            await process_refund(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
                method="stripe",
            )

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_audit_log_written_on_refund(self, mock_audit):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("0.00"),
        )

        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        await process_refund(
            db,
            org_id=org_id,
            user_id=user_id,
            invoice_id=invoice.id,
            amount=Decimal("25.00"),
            method="cash",
            notes="Partial refund",
            ip_address="192.168.1.1",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "payment.refund_processed"
        assert call_kwargs["entity_type"] == "payment"
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "192.168.1.1"
