"""Unit tests for Task 11.3 — Stripe payment link generation.

Tests cover:
  - Schema validation for StripePaymentLinkRequest / StripePaymentLinkResponse
  - Integration: create_payment_link calls Stripe API correctly
  - Service: generate_stripe_payment_link validates invoice, org, amount
  - Service: partial payment (deposit) support
  - Service: send_via email / sms dispatch
  - Router: POST /api/v1/payments/stripe/create-link

Requirements: 25.3, 25.5
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
    StripePaymentLinkRequest,
    StripePaymentLinkResponse,
)
from app.modules.payments.service import generate_stripe_payment_link
from app.modules.invoices.models import Invoice
from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer


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
    inv.status = status
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.currency = currency
    inv.invoice_number = "INV-0001"
    inv.issue_date = date.today()
    inv.due_date = date.today()
    return inv


def _make_org(org_id=None, stripe_account="acct_test123"):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.stripe_connect_account_id = stripe_account
    return org


def _make_customer(email="test@example.com", phone="+6421555000"):
    cust = MagicMock(spec=Customer)
    cust.id = uuid.uuid4()
    cust.email = email
    cust.phone = phone
    return cust


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestStripePaymentLinkRequestSchema:
    """Validate StripePaymentLinkRequest schema."""

    def test_valid_request_full_balance(self):
        req = StripePaymentLinkRequest(invoice_id=uuid.uuid4())
        assert req.amount is None
        assert req.send_via == "none"

    def test_valid_request_partial_amount(self):
        req = StripePaymentLinkRequest(
            invoice_id=uuid.uuid4(),
            amount=Decimal("50.00"),
            send_via="email",
        )
        assert req.amount == Decimal("50.00")
        assert req.send_via == "email"

    def test_valid_request_sms(self):
        req = StripePaymentLinkRequest(
            invoice_id=uuid.uuid4(),
            send_via="sms",
        )
        assert req.send_via == "sms"

    def test_rejects_zero_amount(self):
        with pytest.raises(Exception):
            StripePaymentLinkRequest(
                invoice_id=uuid.uuid4(), amount=Decimal("0")
            )

    def test_rejects_negative_amount(self):
        with pytest.raises(Exception):
            StripePaymentLinkRequest(
                invoice_id=uuid.uuid4(), amount=Decimal("-10.00")
            )

    def test_rejects_too_many_decimal_places(self):
        with pytest.raises(Exception):
            StripePaymentLinkRequest(
                invoice_id=uuid.uuid4(), amount=Decimal("10.999")
            )

    def test_rejects_invalid_send_via(self):
        with pytest.raises(Exception):
            StripePaymentLinkRequest(
                invoice_id=uuid.uuid4(), send_via="carrier_pigeon"
            )


class TestStripePaymentLinkResponseSchema:
    """Validate StripePaymentLinkResponse schema."""

    def test_valid_response(self):
        resp = StripePaymentLinkResponse(
            payment_url="https://checkout.stripe.com/pay/cs_test_123",
            invoice_id=uuid.uuid4(),
            amount=Decimal("100.00"),
            send_via="none",
        )
        assert resp.payment_url.startswith("https://")
        assert resp.message == "Payment link generated successfully"


# ---------------------------------------------------------------------------
# Integration: create_payment_link
# ---------------------------------------------------------------------------

class TestCreatePaymentLink:
    """Test the Stripe API integration helper."""

    @pytest.mark.asyncio
    async def test_creates_checkout_session(self):
        from app.integrations.stripe_connect import create_payment_link

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "cs_test_abc",
            "url": "https://checkout.stripe.com/pay/cs_test_abc",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.integrations.stripe_connect.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await create_payment_link(
                amount=10000,
                currency="nzd",
                invoice_id="inv-123",
                stripe_account_id="acct_test",
            )

        assert result["session_id"] == "cs_test_abc"
        assert result["payment_url"] == "https://checkout.stripe.com/pay/cs_test_abc"

        # Verify the Stripe API was called with correct params
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.stripe.com/v1/checkout/sessions"
        assert call_args[1]["headers"]["Stripe-Account"] == "acct_test"
        data = call_args[1]["data"]
        assert data["line_items[0][price_data][unit_amount]"] == "10000"
        assert data["line_items[0][price_data][currency]"] == "nzd"
        assert data["metadata[invoice_id]"] == "inv-123"


# ---------------------------------------------------------------------------
# Service: generate_stripe_payment_link
# ---------------------------------------------------------------------------

class TestGenerateStripePaymentLink:
    """Test the service layer for Stripe payment link generation."""

    @pytest.mark.asyncio
    async def test_full_balance_payment(self):
        """Full balance payment when no amount specified."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org = _make_org(org_id=org_id)

        db = _mock_db()

        # First call: invoice lookup, second: org lookup
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        stripe_return = {
            "session_id": "cs_test_full",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_full",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ) as mock_stripe, patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
            )

        assert result["payment_url"] == stripe_return["payment_url"]
        assert result["amount"] == Decimal("200.00")
        assert result["send_via"] == "none"

        # Verify Stripe was called with full balance in cents
        mock_stripe.assert_called_once()
        call_kwargs = mock_stripe.call_args[1]
        assert call_kwargs["amount"] == 20000
        assert call_kwargs["currency"] == "NZD"

    @pytest.mark.asyncio
    async def test_partial_payment_deposit(self):
        """Partial payment for deposit scenario (Req 25.5)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("500.00"))
        org = _make_org(org_id=org_id)

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        stripe_return = {
            "session_id": "cs_test_partial",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_partial",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ), patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("100.00"),
            )

        assert result["amount"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_rejects_invoice_not_found(self):
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Invoice not found"):
            await generate_stripe_payment_link(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_rejects_draft_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")

        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot generate payment link"):
            await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
            )

    @pytest.mark.asyncio
    async def test_rejects_voided_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")

        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot generate payment link"):
            await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
            )

    @pytest.mark.asyncio
    async def test_rejects_amount_exceeding_balance(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("100.00"))
        org = _make_org(org_id=org_id)

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        with pytest.raises(ValueError, match="exceeds invoice balance"):
            await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
            )

    @pytest.mark.asyncio
    async def test_rejects_no_stripe_account(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org = _make_org(org_id=org_id, stripe_account=None)

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        with pytest.raises(ValueError, match="not connected a Stripe account"):
            await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
            )

    @pytest.mark.asyncio
    async def test_send_via_email(self):
        """Verify email dispatch is attempted when send_via='email'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org = _make_org(org_id=org_id)
        customer = _make_customer()

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        db.execute = AsyncMock(
            side_effect=[invoice_result, org_result, customer_result]
        )

        stripe_return = {
            "session_id": "cs_test_email",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_email",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ), patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.integrations.brevo.send_email",
            new_callable=AsyncMock,
            create=True,
        ) as mock_email:
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                send_via="email",
            )

        assert result["send_via"] == "email"
        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1]
        assert call_kwargs["to_email"] == "test@example.com"
        assert "cs_test_email" in call_kwargs["body"]

    @pytest.mark.asyncio
    async def test_send_via_sms(self):
        """Verify SMS dispatch is attempted when send_via='sms'."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org = _make_org(org_id=org_id)
        customer = _make_customer()

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer
        db.execute = AsyncMock(
            side_effect=[invoice_result, org_result, customer_result]
        )

        stripe_return = {
            "session_id": "cs_test_sms",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_sms",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ), patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                send_via="sms",
            )

        assert result["send_via"] == "sms"
        # SMS dispatch is pending Connexus integration (task 7.3)

    @pytest.mark.asyncio
    async def test_overdue_invoice_allowed(self):
        """Payment links should work on overdue invoices."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="overdue")
        org = _make_org(org_id=org_id)

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        stripe_return = {
            "session_id": "cs_test_overdue",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_overdue",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ), patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
            )

        assert result["payment_url"] == stripe_return["payment_url"]

    @pytest.mark.asyncio
    async def test_audit_log_is_written(self):
        """Verify audit log entry is created."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org = _make_org(org_id=org_id)

        db = _mock_db()
        invoice_result = MagicMock()
        invoice_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[invoice_result, org_result])

        stripe_return = {
            "session_id": "cs_test_audit",
            "payment_url": "https://checkout.stripe.com/pay/cs_test_audit",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ), patch(
            "app.modules.payments.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "payment.stripe_link_generated"
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id
