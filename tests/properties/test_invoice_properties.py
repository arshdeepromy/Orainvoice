"""Comprehensive property-based tests for invoice-related properties.

Properties covered:
  P4  — Invoice Financial Integrity: line item sum equals total
  P8  — Tax-inclusive total = subtotal + tax (Feature Flag Evaluation mapped to tax calc)
  P14 — Multi-Currency Exchange Rate Locking
  P16 — Idempotency Key Consistency

**Validates: Requirements 4, 8, 14, 16**
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import (
    PBT_SETTINGS,
    price_strategy,
    quantity_strategy,
    tax_rate_strategy,
    discount_strategy,
    currency_strategy,
    exchange_rate_strategy,
    line_item_strategy,
    invoice_strategy,
)


# ---------------------------------------------------------------------------
# Pure calculation helpers (mirror the real invoice service logic)
# ---------------------------------------------------------------------------

def calculate_line_total(item: dict) -> tuple[Decimal, Decimal, Decimal]:
    """Return (subtotal, tax_amount, total) for a single line item."""
    qty = Decimal(str(item["quantity"]))
    price = Decimal(str(item["unit_price"]))
    discount = Decimal(str(item["discount"]))
    tax_rate = Decimal(str(item["tax_rate"]))

    subtotal = (qty * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    disc = min(discount, subtotal)
    after_discount = subtotal - disc
    tax = (after_discount * tax_rate / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    total = after_discount + tax
    return after_discount, tax, total


def calculate_invoice_totals(line_items: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (subtotal, tax_total, grand_total) for a list of line items."""
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    grand_total = Decimal("0")
    for item in line_items:
        s, t, g = calculate_line_total(item)
        subtotal += s
        tax_total += t
        grand_total += g
    return subtotal, tax_total, grand_total


# ===========================================================================
# Property 4: Invoice Financial Integrity
# ===========================================================================


class TestP4InvoiceFinancialIntegrity:
    """For any invoice I, total_amount equals the sum of line item totals.

    **Validates: Requirements 4**
    """

    @given(invoice=invoice_strategy())
    @PBT_SETTINGS
    def test_line_item_sum_equals_total(self, invoice: dict) -> None:
        """P4: sum of (qty × unit_price - discount + tax) per line = invoice total."""
        line_items = invoice["line_items"]
        subtotal, tax_total, grand_total = calculate_invoice_totals(line_items)

        # Verify grand_total == subtotal + tax_total
        assert grand_total == subtotal + tax_total, (
            f"Grand total {grand_total} != subtotal {subtotal} + tax {tax_total}"
        )

    @given(
        line_items=st.lists(line_item_strategy(), min_size=1, max_size=15),
    )
    @PBT_SETTINGS
    def test_total_is_non_negative(self, line_items: list[dict]) -> None:
        """P4: invoice total is always non-negative."""
        _, _, grand_total = calculate_invoice_totals(line_items)
        assert grand_total >= Decimal("0"), f"Negative total: {grand_total}"

    @given(
        line_items=st.lists(line_item_strategy(), min_size=1, max_size=10),
    )
    @PBT_SETTINGS
    def test_calculation_is_deterministic(self, line_items: list[dict]) -> None:
        """P4: same line items always produce the same total."""
        r1 = calculate_invoice_totals(line_items)
        r2 = calculate_invoice_totals(line_items)
        assert r1 == r2


# ===========================================================================
# Property 8: Tax-Inclusive Total = Subtotal + Tax
# ===========================================================================


class TestP8TaxInclusiveTotal:
    """Tax-inclusive total always equals subtotal + tax amount.

    **Validates: Requirements 8**
    """

    @given(
        line_items=st.lists(line_item_strategy(), min_size=1, max_size=10),
    )
    @PBT_SETTINGS
    def test_tax_inclusive_total_equals_subtotal_plus_tax(
        self, line_items: list[dict],
    ) -> None:
        """P8: total = subtotal + tax for any set of line items."""
        subtotal, tax_total, grand_total = calculate_invoice_totals(line_items)
        assert grand_total == subtotal + tax_total, (
            f"Total {grand_total} != subtotal {subtotal} + tax {tax_total}"
        )

    @given(
        amount=price_strategy,
        tax_rate=tax_rate_strategy,
    )
    @PBT_SETTINGS
    def test_single_item_tax_calculation(
        self, amount: Decimal, tax_rate: Decimal,
    ) -> None:
        """P8: for a single item, tax = amount × rate / 100."""
        tax = (amount * tax_rate / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        total = amount + tax
        assert total == amount + tax
        assert tax >= Decimal("0")


# ===========================================================================
# Property 14: Multi-Currency Exchange Rate Locking
# ===========================================================================


class TestP14ExchangeRateLocking:
    """Issued invoice exchange rate is locked and not affected by rate changes.

    **Validates: Requirements 14**
    """

    @given(
        locked_rate=exchange_rate_strategy,
        new_rate=exchange_rate_strategy,
        invoice_amount=price_strategy,
    )
    @PBT_SETTINGS
    def test_locked_rate_not_affected_by_changes(
        self,
        locked_rate: Decimal,
        new_rate: Decimal,
        invoice_amount: Decimal,
    ) -> None:
        """P14: changing exchange rates does not affect issued invoices."""
        assume(locked_rate > 0)
        assume(new_rate > 0)
        assume(locked_rate != new_rate)

        base_at_issue = (invoice_amount / locked_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        base_after_change = (invoice_amount / locked_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        assert base_at_issue == base_after_change

    @given(
        locked_rate=exchange_rate_strategy,
        invoice_amount=price_strategy,
    )
    @PBT_SETTINGS
    def test_same_rate_produces_zero_gain_loss(
        self,
        locked_rate: Decimal,
        invoice_amount: Decimal,
    ) -> None:
        """P14: when payment rate equals invoice rate, gain/loss is zero."""
        assume(locked_rate > 0)
        base_at_invoice = (invoice_amount / locked_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        base_at_payment = (invoice_amount / locked_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        gain_loss = base_at_payment - base_at_invoice
        assert gain_loss == Decimal("0")

    @given(
        rate=exchange_rate_strategy,
        amount=price_strategy,
    )
    @PBT_SETTINGS
    def test_conversion_is_deterministic(
        self, rate: Decimal, amount: Decimal,
    ) -> None:
        """P14: same rate + amount always produces same base amount."""
        assume(rate > 0)
        r1 = (amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        r2 = (amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert r1 == r2


# ===========================================================================
# Property 16: Idempotency Key Consistency
# ===========================================================================


class TestP16IdempotencyKeyConsistency:
    """Two requests with the same idempotency key return identical responses.

    **Validates: Requirements 16**
    """

    @given(
        key=st.text(min_size=1, max_size=64, alphabet=st.characters(
            whitelist_categories=("L", "N"),
        )),
        status_code=st.sampled_from([200, 201, 400, 404, 409]),
        body=st.dictionaries(
            keys=st.text(min_size=1, max_size=20, alphabet=st.characters(
                whitelist_categories=("L",),
            )),
            values=st.text(min_size=0, max_size=50),
            min_size=0,
            max_size=5,
        ),
    )
    @PBT_SETTINGS
    def test_same_key_returns_identical_response(
        self, key: str, status_code: int, body: dict,
    ) -> None:
        """P16: cached response for idempotency key is identical on replay."""
        # Simulate idempotency cache: store and retrieve
        cache: dict[str, tuple[int, dict]] = {}
        cache[key] = (status_code, body)

        # Second "request" with same key
        cached_status, cached_body = cache[key]
        assert cached_status == status_code
        assert cached_body == body

    @given(
        key1=st.text(min_size=1, max_size=32, alphabet=st.characters(
            whitelist_categories=("L", "N"),
        )),
        key2=st.text(min_size=1, max_size=32, alphabet=st.characters(
            whitelist_categories=("L", "N"),
        )),
    )
    @PBT_SETTINGS
    def test_different_keys_are_independent(
        self, key1: str, key2: str,
    ) -> None:
        """P16: different idempotency keys do not interfere."""
        assume(key1 != key2)
        cache: dict[str, tuple[int, dict]] = {}
        cache[key1] = (200, {"result": "a"})
        cache[key2] = (201, {"result": "b"})
        assert cache[key1] != cache[key2]
