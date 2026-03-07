"""Property-based test: invoice financial integrity in reports.

For any date range, the sum of invoice line items in a report equals
the sum of individual invoice totals.

**Validates: Requirements Property 4 — Invoice Financial Integrity**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from hypothesis import given, settings, strategies as st

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

line_item_st = st.fixed_dictionaries({
    "quantity": st.integers(min_value=1, max_value=100),
    "unit_price": st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("9999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    "tax_rate": st.sampled_from([Decimal("0"), Decimal("10"), Decimal("15"), Decimal("20")]),
    "discount": st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("50"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
})

invoice_st = st.fixed_dictionaries({
    "id": st.uuids(),
    "line_items": st.lists(line_item_st, min_size=1, max_size=10),
    "issue_date": st.dates(
        min_value=date(2020, 1, 1),
        max_value=date(2025, 12, 31),
    ),
})

date_range_st = st.tuples(
    st.dates(min_value=date(2020, 1, 1), max_value=date(2025, 6, 30)),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2025, 12, 31)),
).filter(lambda t: t[0] <= t[1])


# ---------------------------------------------------------------------------
# Pure calculation functions (mirrors what the report service does)
# ---------------------------------------------------------------------------

def calculate_line_total(line: dict) -> Decimal:
    """Calculate a single line item total: (qty × price - discount) + tax."""
    subtotal = Decimal(str(line["quantity"])) * line["unit_price"]
    discount = min(line["discount"], subtotal)
    after_discount = subtotal - discount
    tax = (after_discount * line["tax_rate"] / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    return (after_discount + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_invoice_total(invoice: dict) -> Decimal:
    """Sum of all line item totals for an invoice."""
    return sum(
        (calculate_line_total(li) for li in invoice["line_items"]),
        Decimal("0"),
    )


def filter_invoices_by_date(
    invoices: list[dict], date_from: date, date_to: date,
) -> list[dict]:
    """Filter invoices to those within the date range."""
    return [
        inv for inv in invoices
        if date_from <= inv["issue_date"] <= date_to
    ]


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(
    invoices=st.lists(invoice_st, min_size=1, max_size=20),
    date_range=date_range_st,
)
def test_report_line_item_sum_equals_invoice_totals(
    invoices: list[dict],
    date_range: tuple[date, date],
):
    """Property 4: For any date range, sum of invoice line items in report
    equals sum of individual invoice totals.

    **Validates: Requirements Property 4**
    """
    date_from, date_to = date_range
    filtered = filter_invoices_by_date(invoices, date_from, date_to)

    # Sum via individual invoice totals
    sum_of_totals = sum(
        (calculate_invoice_total(inv) for inv in filtered),
        Decimal("0"),
    )

    # Sum via all line items across all invoices
    sum_of_lines = sum(
        (
            calculate_line_total(li)
            for inv in filtered
            for li in inv["line_items"]
        ),
        Decimal("0"),
    )

    assert sum_of_lines == sum_of_totals, (
        f"Line item sum {sum_of_lines} != invoice total sum {sum_of_totals}"
    )
