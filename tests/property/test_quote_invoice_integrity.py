"""Property-based test: converted quote has exactly one linked invoice
with matching line items.

**Validates: Requirements 12.5** — Property 6

For any quote Q with status "Converted", exactly one invoice I exists
with a reference to Q, and Q.converted_invoice_id = I.id. The invoice's
line items match the quote's line items at the time of conversion.

Uses Hypothesis to generate random quote line items and verifies that
after conversion the bidirectional reference is correct and line items
match.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.quotes_v2.models import Quote
from app.modules.quotes_v2.service import QuoteService


PBT_SETTINGS = h_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategy for generating line items
line_item_strategy = st.fixed_dictionaries({
    "description": st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    "quantity": st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999"), places=2, allow_nan=False, allow_infinity=False),
    "unit_price": st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999"), places=2, allow_nan=False, allow_infinity=False),
    "tax_rate": st.decimals(min_value=Decimal("0"), max_value=Decimal("25"), places=2, allow_nan=False, allow_infinity=False),
})

line_items_strategy = st.lists(line_item_strategy, min_size=1, max_size=10)


def _make_accepted_quote(line_items: list[dict]) -> Quote:
    """Create an accepted Quote instance with given line items."""
    # Convert Decimal values to strings for JSON serialisation
    serialised_items = []
    for item in line_items:
        serialised_items.append({
            "description": item["description"],
            "quantity": str(item["quantity"]),
            "unit_price": str(item["unit_price"]),
            "tax_rate": str(item["tax_rate"]),
        })

    subtotal, tax_amount, total = QuoteService._compute_totals(serialised_items)
    return Quote(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        quote_number="QT-00001",
        customer_id=uuid.uuid4(),
        status="accepted",
        line_items=serialised_items,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        version_number=1,
    )


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()

    async def fake_flush():
        pass

    def fake_add(obj):
        pass

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    return mock_db


class TestQuoteToInvoiceReferentialIntegrity:
    """For any converted quote, exactly one invoice exists with matching line items.

    **Validates: Requirements 12.5**
    """

    @given(line_items=line_items_strategy)
    @PBT_SETTINGS
    def test_converted_quote_has_one_linked_invoice_with_matching_items(
        self, line_items: list[dict],
    ) -> None:
        """Property 6: converted quote → exactly one invoice with matching line items."""
        import asyncio

        async def _run():
            quote = _make_accepted_quote(line_items)
            mock_db = _make_mock_db()

            # Mock get_quote to return our quote
            from unittest.mock import MagicMock
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = quote

            async def fake_execute(stmt):
                return mock_result

            mock_db.execute = fake_execute

            svc = QuoteService(mock_db)
            result = await svc.convert_to_invoice(quote.org_id, quote.id)

            # Property: exactly one invoice reference
            assert result["invoice_id"] is not None
            assert quote.converted_invoice_id == result["invoice_id"]

            # Property: quote status is now "converted"
            assert quote.status == "converted"

            # Property: line items match
            assert result["line_items_count"] == len(line_items)
            assert len(result["line_items"]) == len(line_items)

            # Verify each line item matches
            for original, converted in zip(quote.line_items, result["line_items"]):
                assert original["description"] == converted["description"]
                assert original["quantity"] == converted["quantity"]
                assert original["unit_price"] == converted["unit_price"]

            # Property: cannot convert again (idempotency guard)
            try:
                await svc.convert_to_invoice(quote.org_id, quote.id)
                assert False, "Should have raised ValueError for double conversion"
            except ValueError:
                pass  # Expected — either "already converted" or "not accepted"

        asyncio.run(_run())
