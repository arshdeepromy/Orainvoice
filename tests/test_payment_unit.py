"""Consolidated unit tests for Payment module (Task 11.6).

Covers:
  1. Cash payment status transitions (Partially Paid, Paid)
  2. Stripe webhook signature verification
  3. Refund balance calculations

Requirements: 24.1, 24.2, 24.3, 25.4, 26.2
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
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

from app.integrations.stripe_connect import verify_webhook_signature
from app.modules.payments.service import record_cash_payment, process_refund
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
    inv.created_by = uuid.uuid4()
    inv.status = status
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.invoice_number = "INV-0001"
    inv.currency = "NZD"
    inv.issue_date = date.today()
    inv.due_date = date.today()
    return inv


def _build_stripe_signature(
    payload: bytes, secret: str, timestamp: int | None = None
) -> str:
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ---------------------------------------------------------------------------
# 1. Cash payment status transitions
#    Validates: Requirements 24.1, 24.2, 24.3
# ---------------------------------------------------------------------------


class TestCashPaymentStatusTransitions:
    """Cash payment recording and invoice status transitions."""

    @pytest.mark.asyncio
    async def test_full_payment_transitions_to_paid(self):
        """Req 24.2: Paying the full balance sets status to 'paid'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            total=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("300.00"),
        )
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("300.00"),
            )

        assert result["payment"]["invoice_status"] == "paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("0.00")
        assert result["payment"]["invoice_amount_paid"] == Decimal("300.00")

    @pytest.mark.asyncio
    async def test_partial_payment_transitions_to_partially_paid(self):
        """Req 24.3: Partial payment sets status to 'partially_paid'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            total=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            balance_due=Decimal("300.00"),
        )
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("120.00"),
            )

        assert result["payment"]["invoice_status"] == "partially_paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("180.00")
        assert result["payment"]["invoice_amount_paid"] == Decimal("120.00")
        assert "180" in result["message"]

    @pytest.mark.asyncio
    async def test_second_payment_clears_remaining_balance(self):
        """Req 24.2: Second payment clearing balance transitions to 'paid'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="partially_paid",
            total=Decimal("300.00"),
            amount_paid=Decimal("120.00"),
            balance_due=Decimal("180.00"),
        )
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("180.00"),
            )

        assert result["payment"]["invoice_status"] == "paid"
        assert result["payment"]["invoice_balance_due"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_payment_on_wrong_status_raises_error(self):
        """Cannot record payment on draft, voided, or paid invoices."""
        org_id = uuid.uuid4()
        for bad_status in ("draft", "voided", "paid"):
            invoice = _make_invoice(org_id=org_id, status=bad_status)
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
                    amount=Decimal("10.00"),
                )

    @pytest.mark.asyncio
    async def test_payment_exceeding_balance_raises_error(self):
        """Cannot pay more than the outstanding balance."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="issued",
            balance_due=Decimal("50.00"),
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
                amount=Decimal("100.00"),
            )

    @pytest.mark.asyncio
    async def test_zero_amount_raises_error(self):
        """Zero payment amount is rejected."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued")
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="greater than zero"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_negative_amount_raises_error(self):
        """Negative payment amount is rejected."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued")
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="greater than zero"):
            await record_cash_payment(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("-5.00"),
            )


# ---------------------------------------------------------------------------
# 2. Stripe webhook signature verification
#    Validates: Requirement 25.4
# ---------------------------------------------------------------------------


class TestStripeWebhookSignatureVerification:
    """Stripe webhook signature verification via verify_webhook_signature."""

    def test_valid_signature_passes(self):
        """A correctly signed payload is accepted and parsed."""
        secret = "whsec_test_abc123"
        payload = json.dumps({"type": "checkout.session.completed", "id": "evt_1"}).encode()
        sig_header = _build_stripe_signature(payload, secret)

        result = verify_webhook_signature(payload, sig_header, secret)
        assert result["type"] == "checkout.session.completed"
        assert result["id"] == "evt_1"

    def test_invalid_signature_raises_value_error(self):
        """A payload signed with the wrong secret is rejected."""
        payload = json.dumps({"type": "test"}).encode()
        sig_header = _build_stripe_signature(payload, "wrong_secret")

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(payload, sig_header, "correct_secret")

    def test_expired_timestamp_raises_value_error(self):
        """A signature with a timestamp older than 5 minutes is rejected."""
        secret = "whsec_replay_test"
        payload = json.dumps({"type": "test"}).encode()
        old_ts = int(time.time()) - 400  # ~6.7 minutes ago
        sig_header = _build_stripe_signature(payload, secret, timestamp=old_ts)

        with pytest.raises(ValueError, match="replay attack"):
            verify_webhook_signature(payload, sig_header, secret)

    def test_missing_timestamp_raises_value_error(self):
        """A header without the 't' component is rejected."""
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(b'{"ok":true}', "v1=somesig", "secret")

    def test_missing_v1_raises_value_error(self):
        """A header without the 'v1' component is rejected."""
        ts = int(time.time())
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(b'{"ok":true}', f"t={ts}", "secret")

    def test_tampered_payload_rejected(self):
        """Modifying the payload after signing causes rejection."""
        secret = "whsec_tamper_test"
        original = json.dumps({"amount": 100}).encode()
        sig_header = _build_stripe_signature(original, secret)
        tampered = json.dumps({"amount": 999}).encode()

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(tampered, sig_header, secret)


# ---------------------------------------------------------------------------
# 3. Refund balance calculations
#    Validates: Requirement 26.2
# ---------------------------------------------------------------------------


class TestRefundBalanceCalculations:
    """Refund processing and invoice balance recalculation."""

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_full_refund_resets_to_issued(self, mock_audit):
        """Full refund of amount_paid resets invoice status to 'issued'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("250.00"),
            amount_paid=Decimal("250.00"),
            balance_due=Decimal("0.00"),
        )
        db = _mock_db()
        inv_mock = MagicMock()
        inv_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_mock)

        result = await process_refund(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice.id,
            amount=Decimal("250.00"),
            method="cash",
            notes="Full refund",
        )

        assert result["invoice_status"] == "refunded"
        assert result["invoice_amount_paid"] == Decimal("0.00")
        # balance_due stays at 0 — refund doesn't create new debt for customer
        assert result["invoice_balance_due"] == Decimal("0.00")

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_partial_refund_keeps_partially_paid(self, mock_audit):
        """Partial refund on a paid invoice transitions to 'partially_paid'."""
        org_id = uuid.uuid4()
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
            user_id=uuid.uuid4(),
            invoice_id=invoice.id,
            amount=Decimal("80.00"),
            method="cash",
        )

        assert result["invoice_status"] == "partially_refunded"
        assert result["invoice_amount_paid"] == Decimal("120.00")
        # balance_due stays at 0 — refund doesn't create new debt for customer
        assert result["invoice_balance_due"] == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_refund_exceeding_amount_paid_raises_error(self):
        """Cannot refund more than what has been paid."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("150.00"),
            balance_due=Decimal("50.00"),
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
                amount=Decimal("200.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_cash_refund_records_with_note(self, mock_audit):
        """Req 26.3: Cash refund is recorded with a note and method='cash'."""
        org_id = uuid.uuid4()
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
            user_id=uuid.uuid4(),
            invoice_id=invoice.id,
            amount=Decimal("30.00"),
            method="cash",
            notes="Customer overcharged",
        )

        refund_record = db.add.call_args[0][0]
        assert isinstance(refund_record, Payment)
        assert refund_record.method == "cash"
        assert refund_record.is_refund is True
        assert refund_record.refund_note == "Customer overcharged"
        assert result["stripe_refund_id"] is None

    @pytest.mark.asyncio
    @patch("app.integrations.stripe_connect.create_stripe_refund", new_callable=AsyncMock)
    @patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock)
    async def test_stripe_refund_calls_stripe_api(self, mock_audit, mock_stripe):
        """Req 26.2: Stripe refund calls the Stripe API and records the refund."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )

        stripe_payment = MagicMock(spec=Payment)
        stripe_payment.stripe_payment_intent_id = "pi_original_123"

        org_mock = MagicMock()
        org_mock.id = org_id
        org_mock.stripe_connect_account_id = "acct_org_456"

        mock_stripe.return_value = {
            "refund_id": "re_refund_789",
            "status": "succeeded",
            "amount": 6000,
        }

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        stripe_pay_result = MagicMock()
        stripe_pay_result.scalar_one_or_none.return_value = stripe_payment
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org_mock
        db.execute = AsyncMock(side_effect=[inv_result, stripe_pay_result, org_result])

        result = await process_refund(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice.id,
            amount=Decimal("60.00"),
            method="stripe",
        )

        mock_stripe.assert_called_once_with(
            payment_intent_id="pi_original_123",
            amount=6000,
            stripe_account_id="acct_org_456",
        )
        assert result["stripe_refund_id"] == "re_refund_789"
        assert result["invoice_amount_paid"] == Decimal("140.00")
        assert result["invoice_balance_due"] == Decimal("60.00")
        assert result["invoice_status"] == "partially_paid"
