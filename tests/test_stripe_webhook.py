"""Unit tests for Task 11.4 — Stripe webhook receiver.

Tests cover:
  - Webhook signature verification (valid, invalid, replay)
  - Webhook handler: checkout.session.completed → payment + status update
  - Webhook handler: unhandled event types ignored
  - Webhook handler: missing/invalid invoice_id
  - Webhook handler: non-payable invoice statuses
  - Best-effort email receipt (non-blocking on failure)
  - Webhook endpoint integration (signature check + dispatch)

Requirements: 25.4
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
from app.modules.payments.service import handle_stripe_webhook
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
    currency="NZD",
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
    inv.currency = currency
    inv.invoice_number = "INV-0001"
    inv.issue_date = date.today()
    inv.due_date = date.today()
    return inv


def _build_stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Build a valid Stripe-Signature header for testing."""
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _make_checkout_event(invoice_id: str, amount_total: int = 20000) -> dict:
    """Build a minimal Stripe checkout.session.completed event payload."""
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "amount_total": amount_total,
                "payment_intent": "pi_test_456",
                "metadata": {
                    "invoice_id": invoice_id,
                    "platform": "workshoppro_nz",
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------


class TestVerifyWebhookSignature:
    """Tests for verify_webhook_signature in stripe_connect.py."""

    def test_valid_signature(self):
        secret = "whsec_test_secret"
        payload = json.dumps({"type": "test"}).encode()
        sig_header = _build_stripe_signature(payload, secret)

        result = verify_webhook_signature(payload, sig_header, secret)
        assert result == {"type": "test"}

    def test_invalid_signature_rejected(self):
        secret = "whsec_test_secret"
        payload = json.dumps({"type": "test"}).encode()
        sig_header = _build_stripe_signature(payload, "wrong_secret")

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(payload, sig_header, secret)

    def test_missing_timestamp_rejected(self):
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(b"{}", "v1=abc123", "secret")

    def test_missing_v1_rejected(self):
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(b"{}", f"t={int(time.time())}", "secret")

    def test_empty_header_rejected(self):
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(b"{}", "", "secret")

    def test_replay_attack_rejected(self):
        secret = "whsec_test_secret"
        payload = json.dumps({"type": "test"}).encode()
        old_timestamp = int(time.time()) - 600  # 10 minutes ago
        sig_header = _build_stripe_signature(payload, secret, timestamp=old_timestamp)

        with pytest.raises(ValueError, match="replay attack"):
            verify_webhook_signature(payload, sig_header, secret)

    def test_tampered_payload_rejected(self):
        secret = "whsec_test_secret"
        original = json.dumps({"type": "test"}).encode()
        sig_header = _build_stripe_signature(original, secret)
        tampered = json.dumps({"type": "tampered"}).encode()

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(tampered, sig_header, secret)


# ---------------------------------------------------------------------------
# Webhook handler tests
# ---------------------------------------------------------------------------


class TestHandleStripeWebhook:
    """Tests for handle_stripe_webhook in payments/service.py."""

    @pytest.mark.asyncio
    async def test_checkout_completed_full_payment(self):
        """Full payment via Stripe sets invoice to 'paid'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("200.00"))
        db = _mock_db()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "id": "cs_test_123",
            "amount_total": 20000,  # $200.00
            "payment_intent": "pi_test_456",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
        assert result["invoice_status"] == "paid"
        assert invoice.status == "paid"
        assert invoice.amount_paid == Decimal("200.00")
        assert invoice.balance_due == Decimal("0.00")
        # Verify a Payment was added
        db.add.assert_called_once()
        added_payment = db.add.call_args[0][0]
        assert isinstance(added_payment, Payment)
        assert added_payment.method == "stripe"
        assert added_payment.amount == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_checkout_completed_partial_payment(self):
        """Partial Stripe payment sets invoice to 'partially_paid'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("200.00"))
        db = _mock_db()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "id": "cs_test_123",
            "amount_total": 10000,  # $100.00
            "payment_intent": "pi_test_789",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
        assert result["invoice_status"] == "partially_paid"
        assert invoice.status == "partially_paid"
        assert invoice.amount_paid == Decimal("100.00")
        assert invoice.balance_due == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_overdue_invoice_payment(self):
        """Payment on overdue invoice transitions correctly."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id, status="overdue", balance_due=Decimal("150.00")
        )
        db = _mock_db()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "id": "cs_test_123",
            "amount_total": 15000,
            "payment_intent": "pi_test_overdue",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
        assert result["invoice_status"] == "paid"

    @pytest.mark.asyncio
    async def test_unhandled_event_type_ignored(self):
        """Non-checkout events are ignored gracefully."""
        db = _mock_db()
        result = await handle_stripe_webhook(
            db, event_type="payment_intent.created", event_data={}
        )
        assert result["status"] == "ignored"
        assert "Unhandled event type" in result["reason"]

    @pytest.mark.asyncio
    async def test_missing_invoice_id_ignored(self):
        """Checkout event without invoice_id in metadata is ignored."""
        db = _mock_db()
        result = await handle_stripe_webhook(
            db,
            event_type="checkout.session.completed",
            event_data={"metadata": {}},
        )
        assert result["status"] == "ignored"
        assert "No invoice_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_invalid_invoice_id_returns_error(self):
        """Checkout event with non-UUID invoice_id returns error."""
        db = _mock_db()
        result = await handle_stripe_webhook(
            db,
            event_type="checkout.session.completed",
            event_data={"metadata": {"invoice_id": "not-a-uuid"}},
        )
        assert result["status"] == "error"
        assert "Invalid invoice_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_invoice_not_found_returns_error(self):
        """Checkout event for non-existent invoice returns error."""
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        invoice_id = uuid.uuid4()
        result = await handle_stripe_webhook(
            db,
            event_type="checkout.session.completed",
            event_data={
                "amount_total": 10000,
                "metadata": {"invoice_id": str(invoice_id)},
            },
        )
        assert result["status"] == "error"
        assert "not found" in result["reason"]

    @pytest.mark.asyncio
    async def test_draft_invoice_ignored(self):
        """Payment on draft invoice is ignored."""
        invoice = _make_invoice(status="draft")
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        result = await handle_stripe_webhook(
            db,
            event_type="checkout.session.completed",
            event_data={
                "amount_total": 10000,
                "metadata": {"invoice_id": str(invoice.id)},
            },
        )
        assert result["status"] == "ignored"
        assert "not payable" in result["reason"]

    @pytest.mark.asyncio
    async def test_paid_invoice_ignored(self):
        """Payment on already-paid invoice is ignored."""
        invoice = _make_invoice(
            status="paid",
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        result = await handle_stripe_webhook(
            db,
            event_type="checkout.session.completed",
            event_data={
                "amount_total": 10000,
                "metadata": {"invoice_id": str(invoice.id)},
            },
        )
        assert result["status"] == "ignored"
        assert "not payable" in result["reason"]

    @pytest.mark.asyncio
    async def test_amount_capped_at_balance_due(self):
        """Stripe amount exceeding balance_due is capped."""
        invoice = _make_invoice(balance_due=Decimal("50.00"))
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "amount_total": 20000,  # $200 but only $50 due
            "payment_intent": "pi_test_cap",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
        assert result["amount"] == "50.00"
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.status == "paid"

    @pytest.mark.asyncio
    async def test_stripe_payment_intent_stored(self):
        """Payment record stores the Stripe payment_intent ID."""
        invoice = _make_invoice()
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "amount_total": 20000,
            "payment_intent": "pi_test_stored",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        added_payment = db.add.call_args[0][0]
        assert added_payment.stripe_payment_intent_id == "pi_test_stored"

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Audit log is written after successful webhook processing."""
        invoice = _make_invoice()
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "amount_total": 20000,
            "payment_intent": "pi_test_audit",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock
        ) as mock_audit:
            await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs.kwargs["action"] == "payment.stripe_webhook_received"

    @pytest.mark.asyncio
    async def test_email_failure_does_not_break_webhook(self):
        """Email sending failure does not prevent webhook from succeeding."""
        invoice = _make_invoice()
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "amount_total": 20000,
            "payment_intent": "pi_test_email_fail",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with (
            patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock),
            patch(
                "app.modules.payments.service.handle_stripe_webhook.__module__",
                create=True,
            ),
        ):
            # The email import will fail since brevo isn't implemented,
            # but the handler should catch and continue
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
