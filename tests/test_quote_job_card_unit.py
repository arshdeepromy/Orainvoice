"""Unit tests for Task 18.5 — Quote and Job Card modules.

Covers quote auto-expiry, quote-to-invoice conversion detail preservation,
job card and quote status transitions, and calculation helpers.

Validates: Requirements 58.2, 58.4, 58.5, 59.2, 59.3
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Model imports required for SQLAlchemy mapper resolution
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem
from app.modules.job_cards.models import JobCard, JobCardItem

from app.modules.quotes.service import (
    _calculate_line_total as quote_calc_line_total,
    _calculate_quote_totals,
    _validate_status_transition as quote_validate_transition,
    expire_quotes,
    convert_quote_to_invoice,
    VALID_TRANSITIONS as QUOTE_TRANSITIONS,
)
from app.modules.job_cards.service import (
    _calculate_line_total as jc_calc_line_total,
    _validate_status_transition as jc_validate_transition,
    convert_job_card_to_invoice,
    VALID_TRANSITIONS as JC_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_quote_dict(status="sent", vehicle_rego="ABC123"):
    """Build a quote dict as returned by get_quote."""
    return {
        "id": uuid.uuid4(),
        "org_id": ORG_ID,
        "customer_id": CUSTOMER_ID,
        "quote_number": "QT-0001",
        "vehicle_rego": vehicle_rego,
        "vehicle_make": "Toyota",
        "vehicle_model": "Corolla",
        "vehicle_year": 2020,
        "status": status,
        "valid_until": date.today() + timedelta(days=30),
        "subtotal": Decimal("200.00"),
        "gst_amount": Decimal("22.50"),
        "total": Decimal("222.50"),
        "notes": "Please check alignment",
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Wheel Alignment",
                "quantity": Decimal("1"),
                "unit_price": Decimal("150.00"),
                "hours": None,
                "hourly_rate": None,
                "is_gst_exempt": False,
                "warranty_note": "12 month warranty",
                "line_total": Decimal("150.00"),
                "sort_order": 0,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "part",
                "description": "Tie Rod End",
                "quantity": Decimal("2"),
                "unit_price": Decimal("25.00"),
                "hours": None,
                "hourly_rate": None,
                "is_gst_exempt": True,
                "warranty_note": None,
                "line_total": Decimal("50.00"),
                "sort_order": 1,
            },
        ],
        "created_by": USER_ID,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_jc_dict(status="completed"):
    """Build a job card dict as returned by get_job_card."""
    return {
        "id": uuid.uuid4(),
        "org_id": ORG_ID,
        "customer_id": CUSTOMER_ID,
        "vehicle_rego": "XYZ789",
        "status": status,
        "description": "Full service",
        "notes": "Customer waiting",
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Oil Change",
                "quantity": Decimal("1"),
                "unit_price": Decimal("80.00"),
                "is_completed": True,
                "is_gst_exempt": False,
                "line_total": Decimal("80.00"),
                "sort_order": 0,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "part",
                "description": "Oil Filter",
                "quantity": Decimal("1"),
                "unit_price": Decimal("20.00"),
                "is_completed": True,
                "is_gst_exempt": False,
                "line_total": Decimal("20.00"),
                "sort_order": 1,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "labour",
                "description": "Diagnostic",
                "quantity": Decimal("1"),
                "unit_price": Decimal("60.00"),
                "is_completed": True,
                "is_gst_exempt": True,
                "line_total": Decimal("60.00"),
                "sort_order": 2,
            },
        ],
        "created_by": USER_ID,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ===================================================================
# 1. Quote auto-expiry logic  (Validates: Requirement 58.4)
# ===================================================================


class TestQuoteAutoExpiry:
    """Test expire_quotes transitions only sent quotes past valid_until."""

    @pytest.mark.asyncio
    async def test_expires_sent_quotes_past_valid_until(self):
        """Sent quotes whose valid_until is in the past are expired."""
        db = _mock_db()

        q1 = MagicMock(spec=Quote)
        q1.status = "sent"
        q1.valid_until = date.today() - timedelta(days=1)

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [q1]
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 1
        assert q1.status == "expired"

    @pytest.mark.asyncio
    async def test_skips_sent_quotes_with_future_valid_until(self):
        """Sent quotes still within validity are not expired.

        The DB query filters valid_until < today, so future quotes
        never appear in the result set.
        """
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_non_sent_statuses(self):
        """Only 'sent' quotes are candidates for auto-expiry.

        Draft, accepted, declined, and already-expired quotes are
        excluded by the DB query filter (status == 'sent').
        """
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_expires_multiple_quotes_at_once(self):
        """Multiple expired quotes are all transitioned in one call."""
        db = _mock_db()

        quotes = []
        for i in range(5):
            q = MagicMock(spec=Quote)
            q.status = "sent"
            q.valid_until = date.today() - timedelta(days=i + 1)
            quotes.append(q)

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = quotes
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 5
        for q in quotes:
            assert q.status == "expired"

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_quotes_to_expire(self):
        """Returns 0 when there are no quotes to expire."""
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        count = await expire_quotes(db)
        assert count == 0
        db.flush.assert_not_awaited()


# ===================================================================
# 2. Quote-to-invoice conversion preserves all details (Req 58.5)
# ===================================================================


class TestQuoteToInvoicePreservation:
    """Verify convert_quote_to_invoice carries over customer, vehicle, and line items."""

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_customer_and_vehicle_info_preserved(self, mock_get_quote, mock_audit):
        """Customer ID, vehicle rego/make/model/year are passed to create_invoice."""
        quote_dict = _make_quote_dict(status="accepted")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=quote_dict["id"],
            )

            kw = mock_create.call_args.kwargs
            assert kw["customer_id"] == CUSTOMER_ID
            assert kw["vehicle_rego"] == "ABC123"
            assert kw["vehicle_make"] == "Toyota"
            assert kw["vehicle_model"] == "Corolla"
            assert kw["vehicle_year"] == 2020

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_line_items_count_preserved(self, mock_get_quote, mock_audit):
        """All line items from the quote are passed to the invoice."""
        quote_dict = _make_quote_dict(status="accepted")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=quote_dict["id"],
            )

            kw = mock_create.call_args.kwargs
            assert len(kw["line_items_data"]) == 2

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_line_item_fields_preserved(self, mock_get_quote, mock_audit):
        """Each line item's type, description, quantity, price, GST, warranty are preserved."""
        quote_dict = _make_quote_dict(status="accepted")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=quote_dict["id"],
            )

            items = mock_create.call_args.kwargs["line_items_data"]

            # First item: service with warranty
            assert items[0]["item_type"] == "service"
            assert items[0]["description"] == "Wheel Alignment"
            assert items[0]["quantity"] == Decimal("1")
            assert items[0]["unit_price"] == Decimal("150.00")
            assert items[0]["is_gst_exempt"] is False
            assert items[0]["warranty_note"] == "12 month warranty"

            # Second item: GST-exempt part
            assert items[1]["item_type"] == "part"
            assert items[1]["description"] == "Tie Rod End"
            assert items[1]["quantity"] == Decimal("2")
            assert items[1]["unit_price"] == Decimal("25.00")
            assert items[1]["is_gst_exempt"] is True

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_notes_preserved(self, mock_get_quote, mock_audit):
        """Quote notes are passed as notes_customer on the invoice."""
        quote_dict = _make_quote_dict(status="accepted")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=quote_dict["id"],
            )

            kw = mock_create.call_args.kwargs
            assert kw["notes_customer"] == "Please check alignment"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_sent_quote_transitions_to_accepted_on_convert(
        self, mock_get_quote, mock_audit
    ):
        """A sent quote is automatically accepted when converted."""
        quote_dict = _make_quote_dict(status="sent")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        quote_obj = MagicMock(spec=Quote)
        quote_obj.id = quote_dict["id"]
        quote_obj.org_id = ORG_ID
        quote_obj.status = "sent"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = quote_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ):
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=quote_dict["id"],
            )

        assert quote_obj.status == "accepted"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_draft_quote_cannot_be_converted(self, mock_get_quote):
        """Draft quotes must be sent or accepted before conversion."""
        mock_get_quote.return_value = _make_quote_dict(status="draft")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert"):
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_declined_quote_cannot_be_converted(self, mock_get_quote):
        """Declined quotes cannot be converted."""
        mock_get_quote.return_value = _make_quote_dict(status="declined")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert"):
            await convert_quote_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, quote_id=uuid.uuid4(),
            )


# ===================================================================
# 3. Job card status transitions  (Validates: Requirement 59.2)
# ===================================================================


class TestJobCardStatusTransitions:
    """Exhaustive test of job card status transition validation."""

    @pytest.mark.parametrize(
        "current,target",
        [
            ("open", "in_progress"),
            ("in_progress", "completed"),
            ("completed", "invoiced"),
        ],
    )
    def test_valid_transitions_succeed(self, current, target):
        """Each valid forward transition does not raise."""
        jc_validate_transition(current, target)  # should not raise

    @pytest.mark.parametrize(
        "current,target",
        [
            ("open", "completed"),
            ("open", "invoiced"),
            ("in_progress", "open"),
            ("in_progress", "invoiced"),
            ("completed", "open"),
            ("completed", "in_progress"),
            ("invoiced", "open"),
            ("invoiced", "in_progress"),
            ("invoiced", "completed"),
        ],
    )
    def test_invalid_transitions_raise(self, current, target):
        """Invalid transitions raise ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Cannot transition job card"):
            jc_validate_transition(current, target)

    def test_all_terminal_states_have_no_transitions(self):
        """Invoiced is the only terminal state with no outgoing transitions."""
        assert JC_TRANSITIONS["invoiced"] == set()

    def test_each_state_has_exactly_one_forward_transition(self):
        """Open, in_progress, completed each have exactly one valid target."""
        assert len(JC_TRANSITIONS["open"]) == 1
        assert len(JC_TRANSITIONS["in_progress"]) == 1
        assert len(JC_TRANSITIONS["completed"]) == 1


# ===================================================================
# 4. Quote status transitions  (Validates: Requirement 58.2)
# ===================================================================


class TestQuoteStatusTransitions:
    """Exhaustive test of quote status transition validation."""

    @pytest.mark.parametrize(
        "current,target",
        [
            ("draft", "sent"),
            ("draft", "accepted"),
            ("draft", "declined"),
            ("sent", "accepted"),
            ("sent", "declined"),
            ("sent", "expired"),
        ],
    )
    def test_valid_transitions_succeed(self, current, target):
        """Each valid transition does not raise."""
        quote_validate_transition(current, target)  # should not raise

    @pytest.mark.parametrize(
        "current,target",
        [
            ("draft", "expired"),
            ("accepted", "draft"),
            ("accepted", "sent"),
            ("accepted", "declined"),
            ("accepted", "expired"),
            ("declined", "draft"),
            ("declined", "sent"),
            ("declined", "accepted"),
            ("declined", "expired"),
            ("expired", "draft"),
            ("expired", "sent"),
            ("expired", "accepted"),
            ("expired", "declined"),
        ],
    )
    def test_invalid_transitions_raise(self, current, target):
        """Invalid transitions raise ValueError with descriptive message."""
        with pytest.raises(ValueError, match="Cannot transition quote"):
            quote_validate_transition(current, target)

    def test_terminal_states_have_no_transitions(self):
        """Accepted, declined, and expired are terminal states."""
        assert QUOTE_TRANSITIONS["accepted"] == set()
        assert QUOTE_TRANSITIONS["declined"] == set()
        assert QUOTE_TRANSITIONS["expired"] == set()

    def test_draft_has_three_targets(self):
        """Draft can go to sent, accepted, or declined."""
        assert QUOTE_TRANSITIONS["draft"] == {"sent", "accepted", "declined"}

    def test_sent_has_three_targets(self):
        """Sent can go to accepted, declined, or expired."""
        assert QUOTE_TRANSITIONS["sent"] == {"accepted", "declined", "expired"}


# ===================================================================
# 5. Calculation helpers  (Validates: Requirements 58.2, 59.2)
# ===================================================================


class TestQuoteCalculationHelpers:
    """Test _calculate_line_total and _calculate_quote_totals."""

    def test_line_total_integer_quantities(self):
        assert quote_calc_line_total(Decimal("3"), Decimal("40.00")) == Decimal("120.00")

    def test_line_total_zero_quantity(self):
        assert quote_calc_line_total(Decimal("0"), Decimal("100.00")) == Decimal("0.00")

    def test_line_total_zero_price(self):
        assert quote_calc_line_total(Decimal("5"), Decimal("0.00")) == Decimal("0.00")

    def test_line_total_rounds_half_up(self):
        # 3 * 33.335 = 100.005 → rounds to 100.01
        result = quote_calc_line_total(Decimal("3"), Decimal("33.335"))
        assert result == Decimal("100.01")

    def test_quote_totals_single_taxable_item(self):
        items = [{"quantity": Decimal("2"), "unit_price": Decimal("50.00")}]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("100.00")
        assert totals["gst_amount"] == Decimal("15.00")
        assert totals["total"] == Decimal("115.00")
        assert totals["line_totals"] == [Decimal("100.00")]

    def test_quote_totals_all_exempt(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("200.00"), "is_gst_exempt": True},
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": True},
        ]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("300.00")
        assert totals["gst_amount"] == Decimal("0.00")
        assert totals["total"] == Decimal("300.00")

    def test_quote_totals_mixed_exempt_and_taxable(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": True},
        ]
        totals = _calculate_quote_totals(items, Decimal("15"))
        assert totals["subtotal"] == Decimal("200.00")
        # GST only on the non-exempt $100
        assert totals["gst_amount"] == Decimal("15.00")
        assert totals["total"] == Decimal("215.00")

    def test_quote_totals_custom_gst_rate(self):
        items = [{"quantity": Decimal("1"), "unit_price": Decimal("100.00")}]
        totals = _calculate_quote_totals(items, Decimal("10"))
        assert totals["gst_amount"] == Decimal("10.00")
        assert totals["total"] == Decimal("110.00")

    def test_quote_totals_empty_items(self):
        totals = _calculate_quote_totals([], Decimal("15"))
        assert totals["subtotal"] == Decimal("0.00")
        assert totals["gst_amount"] == Decimal("0.00")
        assert totals["total"] == Decimal("0.00")
        assert totals["line_totals"] == []


class TestJobCardCalculationHelpers:
    """Test job card _calculate_line_total."""

    def test_basic_calculation(self):
        assert jc_calc_line_total(Decimal("2"), Decimal("75.00")) == Decimal("150.00")

    def test_fractional_quantity(self):
        assert jc_calc_line_total(Decimal("0.5"), Decimal("100.00")) == Decimal("50.00")

    def test_rounding_half_up(self):
        # 7 * 14.285 = 99.995 → rounds to 100.00
        result = jc_calc_line_total(Decimal("7"), Decimal("14.285"))
        assert result == Decimal("100.00")

    def test_zero_values(self):
        assert jc_calc_line_total(Decimal("0"), Decimal("50.00")) == Decimal("0.00")
        assert jc_calc_line_total(Decimal("3"), Decimal("0.00")) == Decimal("0.00")


# ===================================================================
# 6. Job card conversion preserves details  (Validates: Req 59.3)
# ===================================================================


class TestJobCardToInvoicePreservation:
    """Verify convert_job_card_to_invoice carries over all details."""

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_customer_and_vehicle_preserved(self, mock_get_jc, mock_audit):
        """Customer ID and vehicle rego are passed to create_invoice."""
        jc_dict = _make_jc_dict(status="completed")
        mock_get_jc.return_value = jc_dict

        db = _mock_db()
        jc_obj = MagicMock(spec=JobCard)
        jc_obj.id = jc_dict["id"]
        jc_obj.org_id = ORG_ID
        jc_obj.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jc_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=jc_dict["id"],
            )

            kw = mock_create.call_args.kwargs
            assert kw["customer_id"] == CUSTOMER_ID
            assert kw["vehicle_rego"] == "XYZ789"
            assert kw["status"] == "draft"

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_all_line_items_preserved(self, mock_get_jc, mock_audit):
        """All three line items (service, part, labour) are carried over."""
        jc_dict = _make_jc_dict(status="completed")
        mock_get_jc.return_value = jc_dict

        db = _mock_db()
        jc_obj = MagicMock(spec=JobCard)
        jc_obj.id = jc_dict["id"]
        jc_obj.org_id = ORG_ID
        jc_obj.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jc_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create:
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=jc_dict["id"],
            )

            items = mock_create.call_args.kwargs["line_items_data"]
            assert len(items) == 3
            assert items[0]["item_type"] == "service"
            assert items[0]["description"] == "Oil Change"
            assert items[1]["item_type"] == "part"
            assert items[1]["unit_price"] == Decimal("20.00")
            assert items[2]["item_type"] == "labour"
            assert items[2]["is_gst_exempt"] is True

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_transitions_to_invoiced(self, mock_get_jc, mock_audit):
        """Job card status transitions to 'invoiced' after conversion."""
        jc_dict = _make_jc_dict(status="completed")
        mock_get_jc.return_value = jc_dict

        db = _mock_db()
        jc_obj = MagicMock(spec=JobCard)
        jc_obj.id = jc_dict["id"]
        jc_obj.org_id = ORG_ID
        jc_obj.status = "completed"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jc_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=jc_dict["id"],
            )

        assert jc_obj.status == "invoiced"

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_open_job_card_cannot_convert(self, mock_get_jc):
        """Open job cards cannot be converted to invoices."""
        mock_get_jc.return_value = _make_jc_dict(status="open")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert"):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    @patch("app.modules.job_cards.service.get_job_card", new_callable=AsyncMock)
    async def test_in_progress_job_card_cannot_convert(self, mock_get_jc):
        """In-progress job cards cannot be converted to invoices."""
        mock_get_jc.return_value = _make_jc_dict(status="in_progress")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert"):
            await convert_job_card_to_invoice(
                db, org_id=ORG_ID, user_id=USER_ID, job_card_id=uuid.uuid4(),
            )
