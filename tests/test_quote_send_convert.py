"""Unit tests for Task 18.2 — Quote sending and conversion.

Requirements: 58.3, 58.5
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
    send_quote,
    convert_quote_to_invoice,
    generate_quote_pdf,
)
from app.modules.quotes.schemas import (
    QuoteSendResponse,
    QuoteConvertResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
QUOTE_ID = uuid.uuid4()


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_org(org_id=None):
    org = MagicMock()
    org.id = org_id or ORG_ID
    org.name = "Test Workshop"
    org.settings = {
        "gst_percentage": 15,
        "quote_prefix": "QT-",
        "primary_colour": "#1a1a1a",
    }
    return org


def _make_customer(org_id=None, email="john@example.com"):
    cust = MagicMock()
    cust.id = CUSTOMER_ID
    cust.org_id = org_id or ORG_ID
    cust.first_name = "John"
    cust.last_name = "Doe"
    cust.email = email
    cust.phone = "021-555-1234"
    cust.address = "123 Main St"
    return cust


def _make_quote_dict(status="draft"):
    return {
        "id": QUOTE_ID,
        "org_id": ORG_ID,
        "customer_id": CUSTOMER_ID,
        "quote_number": "QT-0001",
        "vehicle_rego": "ABC123",
        "vehicle_make": "Toyota",
        "vehicle_model": "Corolla",
        "vehicle_year": 2020,
        "status": status,
        "valid_until": date.today() + timedelta(days=30),
        "subtotal": Decimal("100.00"),
        "gst_amount": Decimal("15.00"),
        "total": Decimal("115.00"),
        "notes": "Test quote notes",
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Oil Change",
                "quantity": Decimal("1"),
                "unit_price": Decimal("50.00"),
                "hours": None,
                "hourly_rate": None,
                "is_gst_exempt": False,
                "warranty_note": None,
                "line_total": Decimal("50.00"),
                "sort_order": 0,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "part",
                "description": "Oil Filter",
                "quantity": Decimal("1"),
                "unit_price": Decimal("50.00"),
                "hours": None,
                "hourly_rate": None,
                "is_gst_exempt": False,
                "warranty_note": None,
                "line_total": Decimal("50.00"),
                "sort_order": 1,
            },
        ],
        "created_by": USER_ID,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_quote_obj(status="draft"):
    q = MagicMock(spec=Quote)
    q.id = QUOTE_ID
    q.org_id = ORG_ID
    q.status = status
    return q


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestQuoteSendConvertSchemas:
    """Test response schemas for send and convert."""

    def test_quote_send_response(self):
        resp = QuoteSendResponse(
            quote_id=QUOTE_ID,
            quote_number="QT-0001",
            recipient_email="john@example.com",
            pdf_size_bytes=1024,
            status="queued",
        )
        assert resp.quote_id == QUOTE_ID
        assert resp.status == "queued"

    def test_quote_convert_response(self):
        inv_id = uuid.uuid4()
        resp = QuoteConvertResponse(
            quote_id=QUOTE_ID,
            quote_number="QT-0001",
            invoice_id=inv_id,
            invoice_status="draft",
            message="Converted",
        )
        assert resp.invoice_id == inv_id
        assert resp.invoice_status == "draft"


# ---------------------------------------------------------------------------
# send_quote tests
# ---------------------------------------------------------------------------


class TestSendQuote:
    """Test send_quote service function.

    Validates: Requirements 58.3
    """

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.generate_quote_pdf", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_draft_quote_transitions_to_sent(
        self, mock_get_quote, mock_gen_pdf, mock_audit
    ):
        """Sending a draft quote transitions it to 'sent' status."""
        mock_get_quote.return_value = _make_quote_dict(status="draft")
        mock_gen_pdf.return_value = b"fake-pdf-bytes"

        db = _mock_db()
        customer = _make_customer()
        quote_obj = _make_quote_obj(status="draft")

        # First execute returns customer, second returns quote object
        mock_result_cust = MagicMock()
        mock_result_cust.scalar_one_or_none.return_value = customer
        mock_result_quote = MagicMock()
        mock_result_quote.scalar_one_or_none.return_value = quote_obj
        db.execute = AsyncMock(side_effect=[mock_result_cust, mock_result_quote])

        result = await send_quote(
            db,
            org_id=ORG_ID,
            user_id=USER_ID,
            quote_id=QUOTE_ID,
        )

        assert result["status"] == "queued"
        assert result["quote_number"] == "QT-0001"
        assert result["recipient_email"] == "john@example.com"
        assert result["pdf_size_bytes"] == len(b"fake-pdf-bytes")
        assert quote_obj.status == "sent"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.generate_quote_pdf", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_already_sent_quote_does_not_change_status(
        self, mock_get_quote, mock_gen_pdf, mock_audit
    ):
        """Re-sending an already sent quote keeps status as 'sent'."""
        mock_get_quote.return_value = _make_quote_dict(status="sent")
        mock_gen_pdf.return_value = b"fake-pdf-bytes"

        db = _mock_db()
        customer = _make_customer()
        mock_result_cust = MagicMock()
        mock_result_cust.scalar_one_or_none.return_value = customer
        db.execute = AsyncMock(return_value=mock_result_cust)

        result = await send_quote(
            db,
            org_id=ORG_ID,
            user_id=USER_ID,
            quote_id=QUOTE_ID,
        )

        assert result["status"] == "queued"
        assert result["recipient_email"] == "john@example.com"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_accepted_quote_raises(self, mock_get_quote):
        """Cannot send a quote that is already accepted."""
        mock_get_quote.return_value = _make_quote_dict(status="accepted")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot send a quote"):
            await send_quote(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_expired_quote_raises(self, mock_get_quote):
        """Cannot send a quote that has expired."""
        mock_get_quote.return_value = _make_quote_dict(status="expired")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot send a quote"):
            await send_quote(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.generate_quote_pdf", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_with_explicit_recipient(
        self, mock_get_quote, mock_gen_pdf, mock_audit
    ):
        """Providing recipient_email overrides customer email."""
        mock_get_quote.return_value = _make_quote_dict(status="draft")
        mock_gen_pdf.return_value = b"pdf"

        db = _mock_db()
        quote_obj = _make_quote_obj(status="draft")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = quote_obj
        db.execute = AsyncMock(return_value=mock_result)

        result = await send_quote(
            db,
            org_id=ORG_ID,
            user_id=USER_ID,
            quote_id=QUOTE_ID,
            recipient_email="other@example.com",
        )

        assert result["recipient_email"] == "other@example.com"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_send_no_customer_email_raises(self, mock_get_quote):
        """Raises when customer has no email and none provided."""
        mock_get_quote.return_value = _make_quote_dict(status="draft")

        db = _mock_db()
        customer = _make_customer(email=None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = customer
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="no email address"):
            await send_quote(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )


# ---------------------------------------------------------------------------
# convert_quote_to_invoice tests
# ---------------------------------------------------------------------------


class TestConvertQuoteToInvoice:
    """Test convert_quote_to_invoice service function.

    Validates: Requirements 58.5
    """

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_sent_quote_creates_draft_invoice(
        self, mock_get_quote, mock_audit
    ):
        """Converting a sent quote creates a draft invoice with all details."""
        quote_dict = _make_quote_dict(status="sent")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        quote_obj = _make_quote_obj(status="sent")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = quote_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice_id = uuid.uuid4()
        fake_invoice = {
            "id": fake_invoice_id,
            "status": "draft",
            "invoice_number": None,
        }

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create_inv:
            result = await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

            # Verify invoice was created with quote details
            mock_create_inv.assert_called_once()
            call_kwargs = mock_create_inv.call_args.kwargs
            assert call_kwargs["customer_id"] == CUSTOMER_ID
            assert call_kwargs["vehicle_rego"] == "ABC123"
            assert call_kwargs["vehicle_make"] == "Toyota"
            assert call_kwargs["vehicle_model"] == "Corolla"
            assert call_kwargs["vehicle_year"] == 2020
            assert call_kwargs["status"] == "draft"
            assert call_kwargs["notes_customer"] == "Test quote notes"
            assert len(call_kwargs["line_items_data"]) == 2

        assert result["invoice_id"] == fake_invoice_id
        assert result["invoice_status"] == "draft"
        assert result["quote_number"] == "QT-0001"
        # Sent quote should transition to accepted
        assert quote_obj.status == "accepted"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_accepted_quote_keeps_status(
        self, mock_get_quote, mock_audit
    ):
        """Converting an already accepted quote does not change its status."""
        quote_dict = _make_quote_dict(status="accepted")
        mock_get_quote.return_value = quote_dict

        db = _mock_db()

        fake_invoice_id = uuid.uuid4()
        fake_invoice = {
            "id": fake_invoice_id,
            "status": "draft",
            "invoice_number": None,
        }

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ):
            result = await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

        assert result["invoice_id"] == fake_invoice_id
        assert result["invoice_status"] == "draft"

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_draft_quote_raises(self, mock_get_quote):
        """Cannot convert a draft quote — must be sent or accepted first."""
        mock_get_quote.return_value = _make_quote_dict(status="draft")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a quote"):
            await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_expired_quote_raises(self, mock_get_quote):
        """Cannot convert an expired quote."""
        mock_get_quote.return_value = _make_quote_dict(status="expired")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a quote"):
            await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_declined_quote_raises(self, mock_get_quote):
        """Cannot convert a declined quote."""
        mock_get_quote.return_value = _make_quote_dict(status="declined")
        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot convert a quote"):
            await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

    @pytest.mark.asyncio
    @patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.quotes.service.get_quote", new_callable=AsyncMock)
    async def test_convert_preserves_line_item_details(
        self, mock_get_quote, mock_audit
    ):
        """All line item fields are carried over to the invoice."""
        quote_dict = _make_quote_dict(status="sent")
        # Add a labour line item with hours/hourly_rate
        quote_dict["line_items"].append({
            "id": uuid.uuid4(),
            "item_type": "labour",
            "description": "Diagnostic",
            "quantity": Decimal("1"),
            "unit_price": Decimal("80.00"),
            "hours": Decimal("2"),
            "hourly_rate": Decimal("40.00"),
            "is_gst_exempt": True,
            "warranty_note": "6 month warranty",
            "line_total": Decimal("80.00"),
            "sort_order": 2,
        })
        mock_get_quote.return_value = quote_dict

        db = _mock_db()
        quote_obj = _make_quote_obj(status="sent")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = quote_obj
        db.execute = AsyncMock(return_value=mock_result)

        fake_invoice = {"id": uuid.uuid4(), "status": "draft", "invoice_number": None}

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value=fake_invoice,
        ) as mock_create_inv:
            await convert_quote_to_invoice(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
            )

            call_kwargs = mock_create_inv.call_args.kwargs
            line_items = call_kwargs["line_items_data"]
            assert len(line_items) == 3

            # Check labour item details preserved
            labour_item = line_items[2]
            assert labour_item["item_type"] == "labour"
            assert labour_item["hours"] == Decimal("2")
            assert labour_item["hourly_rate"] == Decimal("40.00")
            assert labour_item["is_gst_exempt"] is True
            assert labour_item["warranty_note"] == "6 month warranty"
