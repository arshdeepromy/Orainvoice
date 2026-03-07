"""Integration test: quote-to-invoice conversion flow.

Flow: create quote → send to customer → customer accepts via portal
      → convert to invoice → verify linkage.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.quotes_v2.models import Quote
from app.modules.quotes_v2.service import QuoteService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_quote(org_id, *, status="draft", with_token=False, expiry_days=30):
    q = Quote()
    q.id = uuid.uuid4()
    q.org_id = org_id
    q.quote_number = "QTE-00001"
    q.customer_id = uuid.uuid4()
    q.project_id = None
    q.status = status
    q.expiry_date = date.today().replace(year=date.today().year + 1)
    q.terms = "Net 30"
    q.internal_notes = None
    q.line_items = [
        {"description": "Consulting", "quantity": 10, "unit_price": 150.0, "total": 1500.0}
    ]
    q.subtotal = Decimal("1500.00")
    q.tax_amount = Decimal("225.00")
    q.total = Decimal("1725.00")
    q.currency = "NZD"
    q.version_number = 1
    q.previous_version_id = None
    q.converted_invoice_id = None
    q.acceptance_token = secrets.token_urlsafe(32) if with_token else None
    q.accepted_at = None
    q.created_by = uuid.uuid4()
    q.created_at = datetime.now(timezone.utc)
    q.updated_at = datetime.now(timezone.utc)
    return q


def _make_db_for_quote(quote):
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = quote

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    async def mock_execute(stmt, params=None):
        sql_str = str(stmt) if not isinstance(stmt, MagicMock) else ""
        if "count" in sql_str.lower():
            return count_result
        return result

    db.execute = mock_execute
    return db


class TestQuoteToInvoiceFlow:
    """End-to-end quote lifecycle: create → send → accept → convert."""

    @pytest.mark.asyncio
    async def test_send_quote_to_customer(self):
        """Sending a draft quote changes status to 'sent' and generates token."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="draft")
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        result = await svc.send_to_customer(org_id, quote.id)

        assert result.status == "sent"
        assert result.acceptance_token is not None

    @pytest.mark.asyncio
    async def test_cannot_send_non_draft_quote(self):
        """Only draft quotes can be sent."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="sent")
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        with pytest.raises(ValueError, match="Only draft quotes"):
            await svc.send_to_customer(org_id, quote.id)

    @pytest.mark.asyncio
    async def test_customer_accepts_quote_via_token(self):
        """Customer accepts a sent quote using the acceptance token."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="sent", with_token=True)
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        result = await svc.accept_quote(quote.acceptance_token)

        assert result.status == "accepted"
        assert result.accepted_at is not None

    @pytest.mark.asyncio
    async def test_cannot_accept_non_sent_quote(self):
        """Only sent quotes can be accepted."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="draft", with_token=True)
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        with pytest.raises(ValueError, match="cannot be accepted"):
            await svc.accept_quote(quote.acceptance_token)

    @pytest.mark.asyncio
    async def test_convert_accepted_quote_to_invoice(self):
        """Converting an accepted quote creates an invoice with linkage."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="accepted", with_token=True)
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        result = await svc.convert_to_invoice(org_id, quote.id)

        assert result["quote_id"] == quote.id
        assert result["invoice_id"] is not None
        assert result["line_items_count"] == 1
        assert quote.status == "converted"
        assert quote.converted_invoice_id == result["invoice_id"]

    @pytest.mark.asyncio
    async def test_cannot_convert_non_accepted_quote(self):
        """Only accepted quotes can be converted to invoices."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="sent", with_token=True)
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        with pytest.raises(ValueError, match="Only accepted quotes"):
            await svc.convert_to_invoice(org_id, quote.id)

    @pytest.mark.asyncio
    async def test_cannot_convert_already_converted_quote(self):
        """A quote that's already been converted cannot be converted again."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="accepted", with_token=True)
        quote.converted_invoice_id = uuid.uuid4()
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        with pytest.raises(ValueError, match="already been converted"):
            await svc.convert_to_invoice(org_id, quote.id)

    @pytest.mark.asyncio
    async def test_full_quote_to_invoice_flow(self):
        """Complete flow: draft → sent → accepted → converted with linkage."""
        org_id = uuid.uuid4()
        quote = _make_quote(org_id, status="draft")
        db = _make_db_for_quote(quote)
        svc = QuoteService(db)

        # Send
        await svc.send_to_customer(org_id, quote.id)
        assert quote.status == "sent"
        assert quote.acceptance_token is not None

        # Accept
        await svc.accept_quote(quote.acceptance_token)
        assert quote.status == "accepted"

        # Convert
        result = await svc.convert_to_invoice(org_id, quote.id)
        assert quote.status == "converted"
        assert result["invoice_id"] is not None
        assert quote.converted_invoice_id == result["invoice_id"]
