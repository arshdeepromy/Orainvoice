"""Unit tests for Customer Portal module (Task 24.2).

Covers:
  1. Secure token access — valid, invalid, anonymised
  2. Portal payment flow — ownership, status, balance, amount validation

Requirements: 61.1, 61.3
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

from app.modules.portal.service import (
    _build_branding,
    _resolve_token,
    get_portal_access,
    create_portal_payment,
)
from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
PORTAL_TOKEN = uuid.uuid4()


def _make_org(
    org_id=None,
    name="Test Workshop",
    settings=None,
    stripe_connect_account_id="acct_test123",
    locale=None,
):
    org = MagicMock(spec=Organisation)
    org.id = org_id or ORG_ID
    org.name = name
    org.settings = settings if settings is not None else {
        "logo_url": "https://example.com/logo.png",
        "primary_colour": "#FF0000",
        "secondary_colour": "#00FF00",
    }
    org.stripe_connect_account_id = stripe_connect_account_id
    org.locale = locale
    return org


def _make_customer(
    customer_id=None,
    org_id=None,
    portal_token=None,
    is_anonymised=False,
):
    cust = MagicMock(spec=Customer)
    cust.id = customer_id or CUSTOMER_ID
    cust.org_id = org_id or ORG_ID
    cust.portal_token = portal_token or PORTAL_TOKEN
    cust.is_anonymised = is_anonymised
    cust.first_name = "Jane"
    cust.last_name = "Doe"
    cust.email = "jane@example.com"
    cust.phone = "021-555-1234"
    cust.portal_token_expires_at = None
    return cust


def _make_invoice(
    org_id=None,
    customer_id=None,
    status="issued",
    total=Decimal("230.00"),
    amount_paid=Decimal("0.00"),
    balance_due=Decimal("230.00"),
    currency="NZD",
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or ORG_ID
    inv.customer_id = customer_id or CUSTOMER_ID
    inv.invoice_number = "INV-0042"
    inv.status = status
    inv.issue_date = date.today()
    inv.due_date = date.today()
    inv.currency = currency
    inv.subtotal = Decimal("200.00")
    inv.gst_amount = Decimal("30.00")
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.vehicle_rego = "ABC123"
    inv.payments = []
    inv.line_items = []
    return inv


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _db_returning(db, *results):
    """Configure db.execute to return a sequence of scalar_one_or_none results."""
    side_effects = []
    for r in results:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = r
        # Also support .one() for aggregate queries
        mock_result.one.return_value = r
        # Also support .scalars().all() for list queries
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = r if isinstance(r, list) else [r]
        mock_result.scalars.return_value = scalars_mock
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)


# ---------------------------------------------------------------------------
# 1. _build_branding helper
# ---------------------------------------------------------------------------


class TestBuildBranding:
    """Validates: Requirements 61.1"""

    def test_extracts_branding_from_settings(self):
        org = _make_org(settings={
            "logo_url": "https://example.com/logo.png",
            "primary_colour": "#123456",
            "secondary_colour": "#654321",
        })
        branding = _build_branding(org)
        assert branding.org_name == "Test Workshop"
        assert branding.logo_url == "https://example.com/logo.png"
        assert branding.primary_colour == "#123456"
        assert branding.secondary_colour == "#654321"

    def test_handles_empty_settings(self):
        org = _make_org(settings={})
        branding = _build_branding(org)
        assert branding.org_name == "Test Workshop"
        assert branding.logo_url is None
        assert branding.primary_colour is None

    def test_handles_none_settings(self):
        org = _make_org(settings=None)
        org.settings = None
        branding = _build_branding(org)
        assert branding.org_name == "Test Workshop"
        assert branding.logo_url is None


# ---------------------------------------------------------------------------
# 2. Token resolution — valid, invalid, anonymised
#    Validates: Requirements 61.1
# ---------------------------------------------------------------------------


class TestResolveToken:
    """Token-based access: valid token, invalid token, anonymised customer."""

    @pytest.mark.asyncio
    async def test_valid_token_returns_customer_and_org(self):
        db = _mock_db()
        customer = _make_customer()
        customer.portal_token_expires_at = None
        org = _make_org()
        _db_returning(db, customer, org)

        result_customer, result_org = await _resolve_token(db, PORTAL_TOKEN)
        assert result_customer.id == customer.id
        assert result_org.id == org.id

    @pytest.mark.asyncio
    async def test_invalid_token_raises_value_error(self):
        db = _mock_db()
        _db_returning(db, None)  # no customer found

        with pytest.raises(ValueError, match="Invalid or expired portal token"):
            await _resolve_token(db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_anonymised_customer_token_raises_value_error(self):
        """An anonymised customer's token should not resolve.

        The query filters is_anonymised=False, so the DB returns None.
        """
        db = _mock_db()
        _db_returning(db, None)  # anonymised customer filtered out by query

        with pytest.raises(ValueError, match="Invalid or expired portal token"):
            await _resolve_token(db, PORTAL_TOKEN)

    @pytest.mark.asyncio
    async def test_expired_token_raises_value_error(self):
        """A customer with portal_token_expires_at in the past should be rejected."""
        from datetime import timedelta

        db = _mock_db()
        customer = _make_customer()
        customer.portal_token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        _db_returning(db, customer)

        with pytest.raises(ValueError, match="Invalid or expired portal token"):
            await _resolve_token(db, PORTAL_TOKEN)

    @pytest.mark.asyncio
    async def test_non_expired_token_passes_expiry_check(self):
        """A customer with portal_token_expires_at in the future should pass."""
        from datetime import timedelta

        db = _mock_db()
        customer = _make_customer()
        customer.portal_token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        org = _make_org()
        _db_returning(db, customer, org)

        result_customer, result_org = await _resolve_token(db, PORTAL_TOKEN)
        assert result_customer.id == customer.id
        assert result_org.id == org.id

    @pytest.mark.asyncio
    async def test_null_expiry_passes_expiry_check(self):
        """A customer with portal_token_expires_at=None should pass (no expiry set)."""
        db = _mock_db()
        customer = _make_customer()
        customer.portal_token_expires_at = None
        org = _make_org()
        _db_returning(db, customer, org)

        result_customer, result_org = await _resolve_token(db, PORTAL_TOKEN)
        assert result_customer.id == customer.id
        assert result_org.id == org.id

    @pytest.mark.asyncio
    async def test_missing_org_raises_value_error(self):
        db = _mock_db()
        customer = _make_customer()
        customer.portal_token_expires_at = None
        _db_returning(db, customer, None)  # customer found, org missing

        with pytest.raises(ValueError, match="Organisation not found"):
            await _resolve_token(db, PORTAL_TOKEN)


# ---------------------------------------------------------------------------
# 3. get_portal_access — full flow
#    Validates: Requirements 61.1
# ---------------------------------------------------------------------------


class TestGetPortalAccess:
    """Full portal access flow returning customer info + branding."""

    @pytest.mark.asyncio
    @patch("app.modules.portal.service._get_powered_by", new_callable=AsyncMock)
    async def test_returns_customer_info_and_branding(self, mock_powered_by):
        mock_powered_by.return_value = None

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()

        # Aggregate result mock
        agg = MagicMock()
        agg.cnt = 3
        agg.outstanding = Decimal("500.00")
        agg.paid = Decimal("1200.00")

        agg_result = MagicMock()
        agg_result.one.return_value = agg

        # _resolve_token needs 2 calls, then get_portal_access needs 1 more
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute = AsyncMock(side_effect=[cust_result, org_result, agg_result])

        resp = await get_portal_access(db, PORTAL_TOKEN)

        assert resp.customer.customer_id == customer.id
        assert resp.customer.first_name == "Jane"
        assert resp.customer.last_name == "Doe"
        assert resp.branding.org_name == "Test Workshop"
        assert resp.outstanding_balance == Decimal("500.00")
        assert resp.invoice_count == 3


# ---------------------------------------------------------------------------
# 4. Portal payment flow
#    Validates: Requirements 61.3
# ---------------------------------------------------------------------------


class TestCreatePortalPayment:
    """Payment flow: ownership, status, balance, and amount validation."""

    @pytest.mark.asyncio
    @patch("app.modules.portal.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.get_application_fee_percent", new_callable=AsyncMock, return_value=None)
    @patch("app.integrations.stripe_connect.create_payment_link", new_callable=AsyncMock)
    @patch("app.config.settings")
    async def test_successful_full_payment(self, mock_settings, mock_create_link, mock_fee, mock_audit):
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_create_link.return_value = {"payment_url": "https://checkout.stripe.com/pay/cs_test"}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice()

        _db_returning(db, customer, org, invoice)

        resp = await create_portal_payment(db, PORTAL_TOKEN, invoice.id)

        assert resp.payment_url == "https://checkout.stripe.com/pay/cs_test"
        assert resp.amount == Decimal("230.00")
        assert resp.invoice_id == invoice.id
        mock_create_link.assert_awaited_once()
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invoice_not_found_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        _db_returning(db, customer, org, None)  # invoice not found

        with pytest.raises(ValueError, match="Invoice not found"):
            await create_portal_payment(db, PORTAL_TOKEN, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_draft_invoice_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(status="draft")
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Cannot pay an invoice with status 'draft'"):
            await create_portal_payment(db, PORTAL_TOKEN, invoice.id)

    @pytest.mark.asyncio
    async def test_voided_invoice_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(status="voided")
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Cannot pay an invoice with status 'voided'"):
            await create_portal_payment(db, PORTAL_TOKEN, invoice.id)

    @pytest.mark.asyncio
    async def test_paid_invoice_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(status="paid")
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Cannot pay an invoice with status 'paid'"):
            await create_portal_payment(db, PORTAL_TOKEN, invoice.id)

    @pytest.mark.asyncio
    async def test_zero_balance_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(
            status="issued",
            balance_due=Decimal("0.00"),
        )
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Invoice has no outstanding balance"):
            await create_portal_payment(db, PORTAL_TOKEN, invoice.id)

    @pytest.mark.asyncio
    async def test_amount_exceeding_balance_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(balance_due=Decimal("100.00"))
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Payment amount exceeds outstanding balance"):
            await create_portal_payment(
                db, PORTAL_TOKEN, invoice.id, amount=Decimal("150.00")
            )

    @pytest.mark.asyncio
    @patch("app.modules.portal.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.get_application_fee_percent", new_callable=AsyncMock, return_value=None)
    @patch("app.integrations.stripe_connect.create_payment_link", new_callable=AsyncMock)
    @patch("app.config.settings")
    async def test_partial_payment_within_balance(self, mock_settings, mock_create_link, mock_fee, mock_audit):
        mock_settings.frontend_base_url = "http://localhost:3000"
        mock_create_link.return_value = {"payment_url": "https://checkout.stripe.com/pay/cs_partial"}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        invoice = _make_invoice(balance_due=Decimal("200.00"))
        _db_returning(db, customer, org, invoice)

        resp = await create_portal_payment(
            db, PORTAL_TOKEN, invoice.id, amount=Decimal("50.00")
        )

        assert resp.amount == Decimal("50.00")
        assert resp.payment_url == "https://checkout.stripe.com/pay/cs_partial"
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_stripe_account_raises_error(self):
        db = _mock_db()
        customer = _make_customer()
        org = _make_org(stripe_connect_account_id=None)
        invoice = _make_invoice()
        _db_returning(db, customer, org, invoice)

        with pytest.raises(ValueError, match="Organisation has not connected a Stripe account"):
            await create_portal_payment(db, PORTAL_TOKEN, invoice.id)
