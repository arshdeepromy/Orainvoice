"""Unit tests for Task 11.1 — cash payment recording.

Tests cover:
  - Schema validation for CashPaymentRequest
  - Cash payment recording (full and partial)
  - Invoice status transitions (issued→paid, issued→partially_paid,
    partially_paid→paid, overdue→paid, overdue→partially_paid)
  - Rejection for invalid states (draft, voided, paid)
  - Amount validation (zero, negative, exceeds balance)
  - Audit log writing

Requirements: 24.1, 24.2, 24.3
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.payments.schemas import (
    CashPaymentRequest,
    CashPaymentResponse,
    PaymentResponse,
)
from app.modules.payments.service import record_cash_payment
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
    status="issued",
    total=Decimal("200.00"),
    amount_paid=Decimal("0.00"),
    balance_due=Decimal("200.00"),
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
    inv.issue_date = date.today()
    inv.due_date = date.today()
    return inv


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestCashPaymentRequestSchema:
    """Tests for CashPaymentRequest Pydantic schema."""

    def test_valid_request(self):
        req = CashPaymentRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("50.00"),
        )
        assert req.amount == Decimal("50.00")
        assert req.notes is None

    def test_valid_request_with_notes(self):
        req = CashPaymentRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            notes="Cash received at counter",
        )
        assert req.notes == "Cash received at counter"

    def test_rejects_zero_amount(self):
        with pytest.raises(Exception):
            CashPaymentRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("0.00"),
            )

    def test_rejects_negative_amount(self):
        with pytest.raises(Exception):
            CashPaymentRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("-10.00"),
            )

    def test_rejects_too_many_decimal_places(self):
        with pytest.raises(Exception):
            CashPaymentRequest(
                invoice_id=uuid.uuid4(),
                amount=Decimal("10.123"),
            )

    def test_accepts_integer_amount(self):
        req = CashPaymentRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("100"),
        )
        assert req.amount == Decimal("100")


# ---------------------------------------------------------------------------
# Service tests — record_cash_payment
# ---------------------------------------------------------------------------

class TestRecordCashPayment:
    """Tests for the record_cash_payment service function."""

    @pytest.mark.asyncio
    async def test_full_payment_sets_status_paid(self):
        """Req 24.2: Full balance cleared → status = paid."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            total=Decimal("200.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("200.00"),
        )

        db = _mock_db()
        # First execute returns the invoice
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("200.00"),
            )

        assert result["payment"]["invoice_status"] == "paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("0.00")
        assert result["payment"]["invoice_amount_paid"] == Decimal("200.00")
        assert "paid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_partial_payment_sets_status_partially_paid(self):
        """Req 24.3: Partial amount → status = partially_paid, remaining balance shown."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            total=Decimal("200.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("200.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("75.00"),
            )

        assert result["payment"]["invoice_status"] == "partially_paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("125.00")
        assert result["payment"]["invoice_amount_paid"] == Decimal("75.00")
        assert "125" in result["message"]

    @pytest.mark.asyncio
    async def test_payment_on_partially_paid_clears_balance(self):
        """Req 24.2: Second payment clears remaining → status = paid."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="partially_paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("100.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("100.00"),
            )

        assert result["payment"]["invoice_status"] == "paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_payment_on_overdue_invoice_paid(self):
        """Overdue invoice fully paid → status = paid."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="overdue",
            total=Decimal("150.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("150.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
            )

        assert result["payment"]["invoice_status"] == "paid"

    @pytest.mark.asyncio
    async def test_payment_on_overdue_invoice_partial(self):
        """Overdue invoice partially paid → status = partially_paid."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="overdue",
            total=Decimal("150.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("150.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
            )

        assert result["payment"]["invoice_status"] == "partially_paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_rejects_payment_on_draft_invoice(self):
        """Cannot pay a draft invoice."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Cannot record payment"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_payment_on_voided_invoice(self):
        """Cannot pay a voided invoice."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Cannot record payment"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_payment_on_already_paid_invoice(self):
        """Cannot pay an already-paid invoice."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Cannot record payment"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_amount_exceeding_balance(self):
        """Cannot pay more than the balance due."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            balance_due=Decimal("100.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="exceeds"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_invoice_not_found(self):
        """Raises error when invoice doesn't exist in org."""
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invoice not found"):
            await record_cash_payment(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                amount=Decimal("50.00"),
            )

    @pytest.mark.asyncio
    async def test_payment_creates_record_with_cash_method(self):
        """Req 24.1: Payment record created with method='cash'."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            balance_due=Decimal("200.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("100.00"),
            )

        assert result["payment"]["method"] == "cash"
        assert result["payment"]["amount"] == Decimal("100.00")
        assert result["payment"]["recorded_by"] == user_id

    @pytest.mark.asyncio
    async def test_audit_log_is_written(self):
        """Verify audit log is called with correct parameters."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            balance_due=Decimal("200.00"),
        )

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("200.00"),
                ip_address="192.168.1.1",
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args.kwargs
            assert call_kwargs["action"] == "payment.cash_recorded"
            assert call_kwargs["entity_type"] == "payment"
            assert call_kwargs["org_id"] == org_id
            assert call_kwargs["user_id"] == user_id
            assert call_kwargs["ip_address"] == "192.168.1.1"
