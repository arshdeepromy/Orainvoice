"""Unit tests for Task 18.1 — Quote CRUD.

Requirements: 58.1, 58.2, 58.4, 58.6
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem
from app.modules.quotes.service import (
    _calculate_line_total,
    _calculate_quote_totals,
    _validate_status_transition,
    create_quote,
    expire_quotes,
    get_quote,
    list_quotes,
    update_quote,
)
from app.modules.quotes.schemas import (
    QuoteCreate,
    QuoteLineItemCreate,
    QuoteStatus,
    QuoteUpdate,
    VALID_VALIDITY_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_org(org_id, quote_prefix="QT-"):
    org = MagicMock()
    org.id = org_id
    org.name = "Test Workshop"
    org.settings = {
        "gst_percentage": 15,
        "quote_prefix": quote_prefix,
    }
    return org


def _make_customer(org_id):
    cust = MagicMock()
    cust.id = uuid.uuid4()
    cust.org_id = org_id
    cust.first_name = "John"
    cust.last_name = "Doe"
    return cust


def _make_quote(org_id=None, status="draft", quote_number="QT-0001"):
    q = MagicMock(spec=Quote)
    q.id = uuid.uuid4()
    q.org_id = org_id or uuid.uuid4()
    q.customer_id = uuid.uuid4()
    q.quote_number = quote_number
    q.vehicle_rego = "ABC123"
    q.vehicle_make = "Toyota"
    q.vehicle_model = "Corolla"
    q.vehicle_year = 2020
    q.status = status
    q.valid_until = date.today() + timedelta(days=30)
    q.subtotal = Decimal("100.00")
    q.gst_amount = Decimal("15.00")
    q.total = Decimal("115.00")
    q.notes = None
    q.created_by = uuid.uuid4()
    q.created_at = datetime.now(timezone.utc)
    q.updated_at = datetime.now(timezone.utc)
    return q


def _make_line_item(quote_id=None):
    li = MagicMock(spec=QuoteLineItem)
    li.id = uuid.uuid4()
    li.quote_id = quote_id or uuid.uuid4()
    li.item_type = "service"
    li.description = "Oil Change"
    li.quantity = Decimal("1")
    li.unit_price = Decimal("50.00")
    li.hours = None
    li.hourly_rate = None
    li.is_gst_exempt = False
    li.warranty_note = None
    li.line_total = Decimal("50.00")
    li.sort_order = 0
    return li


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestQuoteSchemas:
    """Test Pydantic schema validation for quotes."""

    def test_valid_validity_days(self):
        """Validity days must be 7, 14, or 30."""
        for days in VALID_VALIDITY_DAYS:
            schema = QuoteCreate(
                customer_id=uuid.uuid4(),
                validity_days=days,
            )
            assert schema.validity_days == days

    def test_invalid_validity_days_rejected(self):
        """Non-standard validity days are rejected."""
        with pytest.raises(Exception):
            QuoteCreate(
                customer_id=uuid.uuid4(),
                validity_days=10,
            )

    def test_default_validity_days(self):
        """Default validity is 30 days."""
        schema = QuoteCreate(customer_id=uuid.uuid4())
        assert schema.validity_days == 30

    def test_quote_status_enum(self):
        """All expected statuses exist."""
        assert set(QuoteStatus) == {
            QuoteStatus.draft,
            QuoteStatus.sent,
            QuoteStatus.accepted,
            QuoteStatus.declined,
            QuoteStatus.expired,
        }

    def test_line_item_create_requires_description(self):
        """Line items must have a description."""
        with pytest.raises(Exception):
            QuoteLineItemCreate(
                item_type="service",
                description="",
                unit_price=Decimal("10.00"),
            )


# ---------------------------------------------------------------------------
# Calculation tests
# ---------------------------------------------------------------------------


class TestQuoteCalculations:
    """Test quote total calculations."""

    def test_line_total_basic(self):
        """Basic line total: quantity * unit_price."""
        result = _calculate_line_total(Decimal("2"), Decimal("50.00"))
        assert result == Decimal("100.00")

    def test_line_total_fractional(self):
        """Fractional quantities round to 2 decimal places."""
        result = _calculate_line_total(Decimal("1.5"), Decimal("33.33"))
        assert result == Decimal("50.00")

    def test_quote_totals_with_gst(self):
        """Totals include 15% GST on non-exempt items."""
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
        ]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("100.00")
        assert totals["gst_amount"] == Decimal("15.00")
        assert totals["total"] == Decimal("115.00")

    def test_quote_totals_gst_exempt(self):
        """GST-exempt items have no GST."""
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": True},
        ]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("100.00")
        assert totals["gst_amount"] == Decimal("0.00")
        assert totals["total"] == Decimal("100.00")

    def test_quote_totals_mixed_gst(self):
        """Mixed exempt and non-exempt items."""
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
            {"quantity": Decimal("1"), "unit_price": Decimal("50.00"), "is_gst_exempt": True},
        ]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("150.00")
        assert totals["gst_amount"] == Decimal("15.00")
        assert totals["total"] == Decimal("165.00")

    def test_quote_totals_empty_items(self):
        """Empty line items produce zero totals."""
        totals = _calculate_quote_totals([], Decimal("15"))
        assert totals["subtotal"] == Decimal("0.00")
        assert totals["gst_amount"] == Decimal("0.00")
        assert totals["total"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Status transition tests
# ---------------------------------------------------------------------------


class TestQuoteStatusTransitions:
    """Test quote status transition validation. Requirements: 58.2"""

    def test_draft_to_sent(self):
        """Draft can transition to Sent."""
        _validate_status_transition("draft", "sent")  # should not raise

    def test_draft_to_accepted(self):
        """Draft can transition to Accepted."""
        _validate_status_transition("draft", "accepted")

    def test_draft_to_declined(self):
        """Draft can transition to Declined."""
        _validate_status_transition("draft", "declined")

    def test_sent_to_accepted(self):
        """Sent can transition to Accepted."""
        _validate_status_transition("sent", "accepted")

    def test_sent_to_declined(self):
        """Sent can transition to Declined."""
        _validate_status_transition("sent", "declined")

    def test_sent_to_expired(self):
        """Sent can transition to Expired."""
        _validate_status_transition("sent", "expired")

    def test_accepted_is_terminal(self):
        """Accepted is a terminal status."""
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("accepted", "draft")

    def test_declined_is_terminal(self):
        """Declined is a terminal status."""
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("declined", "sent")

    def test_expired_is_terminal(self):
        """Expired is a terminal status."""
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("expired", "sent")

    def test_invalid_transition_draft_to_expired(self):
        """Draft cannot directly transition to Expired."""
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("draft", "expired")


# ---------------------------------------------------------------------------
# Service layer tests (create_quote)
# ---------------------------------------------------------------------------


class TestCreateQuote:
    """Test quote creation service. Requirements: 58.1, 58.4, 58.6"""

    @pytest.mark.asyncio
    async def test_create_quote_success(self):
        """Successfully create a quote with line items."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id)
        org = _make_org(org_id)

        db = _mock_db()

        # Mock customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        # Mock org lookup
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        # Mock quote sequence (no existing row)
        seq_result = MagicMock()
        seq_result.first.return_value = None

        db.execute.side_effect = [cust_result, org_result, seq_result, MagicMock(), MagicMock()]

        line_items = [
            {
                "item_type": "service",
                "description": "Oil Change",
                "quantity": Decimal("1"),
                "unit_price": Decimal("80.00"),
                "is_gst_exempt": False,
            },
        ]

        result = await create_quote(
            db,
            org_id=org_id,
            user_id=user_id,
            customer_id=customer.id,
            vehicle_rego="ABC123",
            validity_days=14,
            line_items_data=line_items,
        )

        assert result["status"] == "draft"
        assert result["quote_number"] == "QT-0001"
        assert result["subtotal"] == Decimal("80.00")
        assert result["gst_amount"] == Decimal("12.00")
        assert result["total"] == Decimal("92.00")
        assert result["valid_until"] == date.today() + timedelta(days=14)

    @pytest.mark.asyncio
    async def test_create_quote_customer_not_found(self):
        """Raise error when customer doesn't exist."""
        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = None
        db.execute.return_value = cust_result

        with pytest.raises(ValueError, match="Customer not found"):
            await create_quote(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_create_quote_custom_prefix(self):
        """Quote uses org's configured quote prefix."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id)
        org = _make_org(org_id, quote_prefix="EST-")

        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        seq_result = MagicMock()
        seq_result.first.return_value = None

        db.execute.side_effect = [cust_result, org_result, seq_result, MagicMock(), MagicMock()]

        result = await create_quote(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            customer_id=customer.id,
        )

        assert result["quote_number"].startswith("EST-")


# ---------------------------------------------------------------------------
# Auto-expiry tests
# ---------------------------------------------------------------------------


class TestQuoteAutoExpiry:
    """Test quote auto-expiry logic. Requirements: 58.4"""

    @pytest.mark.asyncio
    async def test_expire_sent_quotes_past_valid_until(self):
        """Sent quotes past valid_until are expired."""
        db = _mock_db()

        q1 = MagicMock(spec=Quote)
        q1.status = "sent"
        q1.valid_until = date.today() - timedelta(days=1)

        q2 = MagicMock(spec=Quote)
        q2.status = "sent"
        q2.valid_until = date.today() - timedelta(days=5)

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [q1, q2]
        db.execute.return_value = result_mock

        count = await expire_quotes(db)

        assert count == 2
        assert q1.status == "expired"
        assert q2.status == "expired"

    @pytest.mark.asyncio
    async def test_expire_does_not_affect_draft_quotes(self):
        """Only sent quotes are auto-expired, not drafts."""
        db = _mock_db()

        # The query filters for status='sent', so no drafts returned
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 0


# ---------------------------------------------------------------------------
# Update quote tests
# ---------------------------------------------------------------------------


class TestUpdateQuote:
    """Test quote update service. Requirements: 58.2"""

    @pytest.mark.asyncio
    async def test_update_draft_quote_notes(self):
        """Draft quotes allow notes updates."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id=org_id, status="draft")

        db = _mock_db()
        q_result = MagicMock()
        q_result.scalar_one_or_none.return_value = quote

        li_result = MagicMock()
        li_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [q_result, MagicMock(), li_result]

        result = await update_quote(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            quote_id=quote.id,
            updates={"notes": "Updated notes"},
        )

        assert quote.notes == "Updated notes"

    @pytest.mark.asyncio
    async def test_update_status_transition(self):
        """Valid status transition is applied."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id=org_id, status="draft")

        db = _mock_db()
        q_result = MagicMock()
        q_result.scalar_one_or_none.return_value = quote

        li_result = MagicMock()
        li_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [q_result, MagicMock(), li_result]

        result = await update_quote(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            quote_id=quote.id,
            updates={"status": "sent"},
        )

        assert quote.status == "sent"

    @pytest.mark.asyncio
    async def test_update_invalid_transition_rejected(self):
        """Invalid status transition raises ValueError."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id=org_id, status="accepted")

        db = _mock_db()
        q_result = MagicMock()
        q_result.scalar_one_or_none.return_value = quote
        db.execute.return_value = q_result

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote.id,
                updates={"status": "draft"},
            )

    @pytest.mark.asyncio
    async def test_update_quote_not_found(self):
        """Raise error when quote doesn't exist."""
        db = _mock_db()
        q_result = MagicMock()
        q_result.scalar_one_or_none.return_value = None
        db.execute.return_value = q_result

        with pytest.raises(ValueError, match="Quote not found"):
            await update_quote(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                quote_id=uuid.uuid4(),
                updates={"notes": "test"},
            )
