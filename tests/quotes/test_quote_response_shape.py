# Feature: quote-settings-parity, Task 12: GET /quotes/{id} response shape
"""Integration-style tests for the quote response shape.

**Validates: Requirements 5.6**

Calls ``get_quote`` directly with a mocked DB, mirroring the testing pattern in
``tests/test_quotes.py``. The service layer's returned dict is the wire format
(the router serialises it via ``QuoteResponse(**result)``), so these tests
exercise the same boundary as a TestClient-based integration test would.

Each test case asserts:
1. The returned dict carries ``payment_terms_text``, ``terms_and_conditions``,
   and ``terms_and_conditions_enabled``.
2. Each value equals what ``_resolve_document_settings`` returns for the same
   ``(org.settings, per_quote_terms=quote.terms)`` inputs — so the response
   shape stays in lock-step with the helper.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.quotes.models import Quote
from app.modules.quotes.service import (
    _resolve_document_settings,
    get_quote,
)


# ---------------------------------------------------------------------------
# Local mock helpers (kept inline — mirrors the pattern in tests/test_quotes.py)
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_quote(*, quote_id, org_id, customer_id, terms: str | None = None):
    q = MagicMock(spec=Quote)
    q.id = quote_id
    q.org_id = org_id
    q.customer_id = customer_id
    q.quote_number = "QT-0001"
    q.vehicle_rego = "ABC123"
    q.vehicle_make = "Toyota"
    q.vehicle_model = "Corolla"
    q.vehicle_year = 2020
    q.vehicle_odometer = None
    q.vehicle_wof_expiry = None
    q.vehicle_cof_expiry = None
    q.status = "draft"
    q.valid_until = date.today() + timedelta(days=30)
    q.subtotal = Decimal("100.00")
    q.gst_amount = Decimal("15.00")
    q.total = Decimal("115.00")
    q.discount_type = None
    q.discount_value = Decimal("0")
    q.discount_amount = Decimal("0")
    q.shipping_charges = Decimal("0")
    q.adjustment = Decimal("0")
    q.notes = None
    q.terms = terms
    q.subject = None
    q.acceptance_token = None
    q.converted_invoice_id = None
    q.created_by = uuid.uuid4()
    q.created_at = datetime.now(timezone.utc)
    q.updated_at = datetime.now(timezone.utc)
    q.order_number = None
    # No salesperson — get_quote skips the User SELECT when salesperson_id is None.
    q.salesperson_id = None
    q.salesperson_name = None
    q.additional_vehicles = []
    q.fluid_usage = []
    q.cancel_reason = None
    q.cancelled_at = None
    q.cancelled_by = None
    q.is_estimate = False
    q.project_id = None
    return q


def _make_org(org_id, *, settings: dict):
    org = MagicMock()
    org.id = org_id
    org.name = "Test Workshop"
    org.settings = settings
    return org


async def _call_get_quote(*, org_settings: dict, per_quote_terms: str | None) -> dict:
    """Invoke ``get_quote`` with a wired-up mocked DB.

    Mirrors ``get_quote``'s DB call sequence (with ``salesperson_id=None`` so
    the User SELECT is skipped):

      1. ``select(Quote)``                  → ``quote_result``
      2. ``select(QuoteLineItem)``          → ``line_items_result``
      3. ``get_attachment_count`` SELECT    → ``attachment_count_result``
      4. ``select(Customer)``               → ``customer_result``
      5. ``select(Organisation)``           → ``org_result``
    """
    org_id = uuid.uuid4()
    quote_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    quote = _make_quote(
        quote_id=quote_id,
        org_id=org_id,
        customer_id=customer_id,
        terms=per_quote_terms,
    )
    org = _make_org(org_id, settings=org_settings)

    db = _mock_db()

    # 1. Quote SELECT
    quote_result = MagicMock()
    quote_result.scalar_one_or_none.return_value = quote

    # 2. Line items SELECT
    line_items_result = MagicMock()
    line_items_result.scalars.return_value.all.return_value = []

    # 3. Attachment count SELECT (used by get_attachment_count → .scalar())
    attachment_count_result = MagicMock()
    attachment_count_result.scalar.return_value = 0

    # 4. Customer SELECT
    customer = MagicMock()
    customer.id = customer_id
    customer.first_name = "Jane"
    customer.last_name = "Doe"
    customer.email = "jane@example.com"
    customer.phone = None
    customer.display_name = None
    customer.portal_token = None
    customer.enable_portal = False
    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = customer

    # 5. Organisation SELECT
    org_result = MagicMock()
    org_result.scalar_one_or_none.return_value = org

    db.execute.side_effect = [
        quote_result,
        line_items_result,
        attachment_count_result,
        customer_result,
        org_result,
    ]

    return await get_quote(db, org_id=org_id, quote_id=quote_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQuoteResponseShape:
    """Verify the GET /quotes/{id} response carries the helper-resolved triple
    and that it matches what ``_resolve_document_settings`` produces for the
    same inputs (Requirement 5.6)."""

    @pytest.mark.asyncio
    async def test_payment_terms_enabled_with_text(self):
        """Org payment_terms_enabled=True + non-empty text → payment_terms_text populated."""
        settings = {
            "payment_terms_enabled": True,
            "payment_terms_text": "Net 7",
            "terms_and_conditions_enabled": True,
            "terms_and_conditions": "Org T&C",
        }

        result = await _call_get_quote(org_settings=settings, per_quote_terms=None)
        expected = _resolve_document_settings(settings, per_quote_terms=None)

        assert "payment_terms_text" in result
        assert "terms_and_conditions" in result
        assert "terms_and_conditions_enabled" in result

        assert result["payment_terms_text"] == "Net 7"
        assert result["payment_terms_text"] == expected["payment_terms_text"]
        assert result["terms_and_conditions"] == expected["terms_and_conditions"]
        assert result["terms_and_conditions_enabled"] == expected["terms_and_conditions_enabled"]

    @pytest.mark.asyncio
    async def test_payment_terms_disabled(self):
        """Org payment_terms_enabled=False → payment_terms_text is None."""
        settings = {
            "payment_terms_enabled": False,
            "payment_terms_text": "ignored because disabled",
            "terms_and_conditions_enabled": True,
            "terms_and_conditions": "Org T&C",
        }

        result = await _call_get_quote(org_settings=settings, per_quote_terms=None)
        expected = _resolve_document_settings(settings, per_quote_terms=None)

        assert result["payment_terms_text"] is None
        assert result["payment_terms_text"] == expected["payment_terms_text"]

    @pytest.mark.asyncio
    async def test_org_tc_enabled_with_no_per_quote_terms(self):
        """Org T&C enabled + non-empty + no per-quote terms → terms_and_conditions equals org value."""
        settings = {
            "payment_terms_enabled": True,
            "payment_terms_text": "Net 7",
            "terms_and_conditions_enabled": True,
            "terms_and_conditions": "Org T&C body",
        }

        result = await _call_get_quote(org_settings=settings, per_quote_terms=None)
        expected = _resolve_document_settings(settings, per_quote_terms=None)

        assert result["terms_and_conditions"] == "Org T&C body"
        assert result["terms_and_conditions"] == expected["terms_and_conditions"]
        assert result["terms_and_conditions_enabled"] is True
        assert result["terms_and_conditions_enabled"] == expected["terms_and_conditions_enabled"]

    @pytest.mark.asyncio
    async def test_per_quote_terms_used_when_org_tc_disabled(self):
        """Per-quote terms with org T&C disabled → terms_and_conditions equals per-quote value."""
        settings = {
            "payment_terms_enabled": True,
            "payment_terms_text": "Net 7",
            "terms_and_conditions_enabled": False,
            "terms_and_conditions": "Should be ignored",
        }
        per_quote = "Per-quote terms win"

        result = await _call_get_quote(org_settings=settings, per_quote_terms=per_quote)
        expected = _resolve_document_settings(settings, per_quote_terms=per_quote)

        assert result["terms_and_conditions"] == per_quote
        assert result["terms_and_conditions"] == expected["terms_and_conditions"]
        # The toggle reflects the org-level setting, regardless of whether a
        # per-quote override is in play.
        assert result["terms_and_conditions_enabled"] is False
        assert result["terms_and_conditions_enabled"] == expected["terms_and_conditions_enabled"]

    @pytest.mark.asyncio
    async def test_empty_per_quote_terms_with_disabled_org_tc(self):
        """Empty per-quote terms + org T&C disabled → terms_and_conditions is None, toggle is False."""
        settings = {
            "payment_terms_enabled": True,
            "payment_terms_text": "Net 7",
            "terms_and_conditions_enabled": False,
            "terms_and_conditions": "Org T&C body (ignored — toggle off)",
        }

        result = await _call_get_quote(org_settings=settings, per_quote_terms=None)
        expected = _resolve_document_settings(settings, per_quote_terms=None)

        assert result["terms_and_conditions"] is None
        assert result["terms_and_conditions"] == expected["terms_and_conditions"]
        assert result["terms_and_conditions_enabled"] is False
        assert result["terms_and_conditions_enabled"] == expected["terms_and_conditions_enabled"]
