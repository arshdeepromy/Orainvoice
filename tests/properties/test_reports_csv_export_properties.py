"""Property-based tests for the reports CSV export layer.

Feature: reports-remediation (C1 — Server-side export layer,
``app/modules/reports/export.py``).

Property 3 — CSV export round-trips the report figures:

  For any report dict, the CSV produced by ``render_report_csv(report_key, data)``
  round-trips the numeric figures: parsing the CSV back with the stdlib ``csv``
  module yields, for every row, the same numeric values that were in the report
  dict (money to two decimal places, integers exactly).

``render_report_csv`` is a PURE function (no DB/IO) — each per-report builder
turns the service return-dict into ``(header, rows)`` and the writer emits UTF-8
CSV. So this is a fast, unit-level Hypothesis test: we generate an arbitrary
report dict for every registered report key, render it to CSV, parse the bytes
back, and assert each numeric cell equals the corresponding source figure to
2dp. Money cells are formatted by the builder as ``f"{Decimal(str(v)):.2f}"``;
we compare with ``Decimal(cell) == Decimal(str(source)).quantize(Decimal("0.01"))``
so the comparison matches the builder's formatting exactly. Money values are
generated with ``places=2`` to avoid any half-even rounding ambiguity.

Text columns are generated with embedded punctuation (commas, quotes) to prove
the numeric columns still align after CSV quoting/round-trip.

**Validates: Requirements 10.5**
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from hypothesis import given, settings as hyp_settings, HealthCheck, strategies as st

from app.modules.reports.export import CSV_BUILDERS, render_report_csv


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = hyp_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

TWO_DP = Decimal("0.01")


# ---------------------------------------------------------------------------
# Primitive strategies
# ---------------------------------------------------------------------------

# Money formatted by the builder to 2dp. Generated WITH places=2 so the source
# is already an exact-2dp figure and there is no rounding ambiguity.
non_neg_money = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Money that may be negative (balances, credits, net GST refunds).
signed_money = st.decimals(
    min_value=Decimal("-99999.99"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

count_int = st.integers(min_value=0, max_value=1_000_000)
bytes_int = st.integers(min_value=0, max_value=10_000_000_000)

# Text containing letters, numbers, spaces AND punctuation (commas + quotes) so
# the round-trip exercises CSV quoting without breaking column alignment.
label_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Zs")),
    max_size=24,
)
opt_text = st.one_of(st.none(), label_text)

month_text = st.from_regex(r"[0-9]{4}-[0-9]{2}", fullmatch=True)
date_text = st.one_of(st.none(), st.dates().map(lambda d: d.isoformat()))


# ---------------------------------------------------------------------------
# Per-report dict strategies (mirror the service return-dict shapes)
# ---------------------------------------------------------------------------

revenue_data = st.fixed_dictionaries({
    "monthly_breakdown": st.lists(
        st.fixed_dictionaries({"month": month_text, "revenue": non_neg_money}),
        max_size=12,
    ),
    "total_inclusive": non_neg_money,
})

invoice_status_data = st.fixed_dictionaries({
    "breakdown": st.lists(
        st.fixed_dictionaries({
            "status": label_text,
            "count": count_int,
            "total": non_neg_money,
        }),
        max_size=8,
    ),
})

top_services_data = st.fixed_dictionaries({
    "services": st.lists(
        st.fixed_dictionaries({
            "description": label_text,
            "count": count_int,
            "total_revenue": non_neg_money,
        }),
        max_size=10,
    ),
})

outstanding_data = st.fixed_dictionaries({
    "invoices": st.lists(
        st.fixed_dictionaries({
            "invoice_number": opt_text,
            "customer_name": opt_text,
            "vehicle_rego": opt_text,
            "due_date": date_text,
            "total": non_neg_money,
            "balance_due": signed_money,
            "days_overdue": count_int,
        }),
        max_size=10,
    ),
})

_GST_KEYS = [
    "total_sales",
    "total_gst_collected",
    "standard_rated_sales",
    "standard_rated_gst",
    "zero_rated_sales",
    "total_purchases",
    "total_input_tax",
    "net_gst_payable",
]
gst_return_data = st.fixed_dictionaries({k: signed_money for k in _GST_KEYS})

fleet_data = st.fixed_dictionaries({
    "vehicles": st.lists(
        st.fixed_dictionaries({
            "rego": label_text,
            "make": opt_text,
            "model": opt_text,
            "total_spend": non_neg_money,
            "last_service_date": date_text,
        }),
        max_size=10,
    ),
})

storage_data = st.fixed_dictionaries({
    "breakdown": st.lists(
        st.fixed_dictionaries({"category": label_text, "bytes": bytes_int}),
        max_size=8,
    ),
})

sms_data = st.fixed_dictionaries({
    "daily_breakdown": st.lists(
        st.fixed_dictionaries({"date": date_text, "sms_count": count_int}),
        max_size=31,
    ),
})

carjam_data = st.fixed_dictionaries({
    "daily_breakdown": st.lists(
        st.fixed_dictionaries({"date": date_text, "lookups": count_int}),
        max_size=31,
    ),
})

customer_statement_data = st.fixed_dictionaries({
    "items": st.lists(
        st.fixed_dictionaries({
            "date": date_text,
            "description": label_text,
            "reference": opt_text,
            "debit": signed_money,
            "credit": signed_money,
            "balance": signed_money,
        }),
        max_size=15,
    ),
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_csv(report_key: str, data: dict) -> tuple[list[str], list[list[str]]]:
    """Render via the real builder, decode and parse back. Returns (header, body)."""
    raw = render_report_csv(report_key, data)
    assert isinstance(raw, bytes)
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    assert rows, "CSV must contain at least a header row"
    return rows[0], rows[1:]


def _money_2dp(value) -> Decimal:
    """Quantize a source money value to 2dp exactly as the builder formats it."""
    return Decimal(str(value)).quantize(TWO_DP)


def _assert_money(cell: str, source) -> None:
    assert Decimal(cell) == _money_2dp(source), (
        f"money cell {cell!r} != source {source!r} to 2dp"
    )


def _assert_int(cell: str, source) -> None:
    assert int(cell) == int(source), f"int cell {cell!r} != source {source!r}"


# ---------------------------------------------------------------------------
# Property 3 — CSV export round-trips the report figures
# ---------------------------------------------------------------------------

class TestP3CsvRoundTrip:
    """Property 3: every numeric figure in a report dict round-trips through
    ``render_report_csv`` to 2dp (money) / exactly (integers), for every
    registered report key.

    **Validates: Requirements 10.5**
    """

    def test_all_report_keys_are_covered(self) -> None:
        """Guard: this suite exercises every key in the CSV_BUILDERS registry,
        so a newly-added report cannot silently skip the round-trip property."""
        covered = {
            "revenue", "invoice_status", "top_services", "outstanding",
            "gst_return", "fleet", "storage", "sms", "carjam",
            "customer_statement",
        }
        assert set(CSV_BUILDERS) == covered, (
            f"CSV_BUILDERS keys {set(CSV_BUILDERS)} != covered {covered}; "
            "add a round-trip property for the new report key."
        )

    @PBT_SETTINGS
    @given(data=revenue_data)
    def test_revenue_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("revenue", data)
        months = data["monthly_breakdown"]
        # Builder appends a final TOTAL row after the per-month rows.
        assert len(body) == len(months) + 1
        for src, row in zip(months, body[:-1]):
            _assert_money(row[1], src["revenue"])
        total_row = body[-1]
        assert total_row[0] == "TOTAL"
        _assert_money(total_row[1], data["total_inclusive"])

    @PBT_SETTINGS
    @given(data=invoice_status_data)
    def test_invoice_status_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("invoice_status", data)
        rows = data["breakdown"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_int(row[1], src["count"])
            _assert_money(row[2], src["total"])

    @PBT_SETTINGS
    @given(data=top_services_data)
    def test_top_services_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("top_services", data)
        rows = data["services"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_int(row[1], src["count"])
            _assert_money(row[2], src["total_revenue"])

    @PBT_SETTINGS
    @given(data=outstanding_data)
    def test_outstanding_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("outstanding", data)
        rows = data["invoices"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_money(row[4], src["total"])
            _assert_money(row[5], src["balance_due"])
            _assert_int(row[6], src["days_overdue"])

    @PBT_SETTINGS
    @given(data=gst_return_data)
    def test_gst_return_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("gst_return", data)
        # Builder emits one fixed label/value row per GST field, in order.
        assert len(body) == len(_GST_KEYS)
        for key, row in zip(_GST_KEYS, body):
            _assert_money(row[1], data[key])

    @PBT_SETTINGS
    @given(data=fleet_data)
    def test_fleet_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("fleet", data)
        rows = data["vehicles"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_money(row[3], src["total_spend"])

    @PBT_SETTINGS
    @given(data=storage_data)
    def test_storage_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("storage", data)
        rows = data["breakdown"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_int(row[1], src["bytes"])

    @PBT_SETTINGS
    @given(data=sms_data)
    def test_sms_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("sms", data)
        rows = data["daily_breakdown"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_int(row[1], src["sms_count"])

    @PBT_SETTINGS
    @given(data=carjam_data)
    def test_carjam_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("carjam", data)
        rows = data["daily_breakdown"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_int(row[1], src["lookups"])

    @PBT_SETTINGS
    @given(data=customer_statement_data)
    def test_customer_statement_round_trip(self, data: dict) -> None:
        _, body = _parse_csv("customer_statement", data)
        rows = data["items"]
        assert len(body) == len(rows)
        for src, row in zip(rows, body):
            _assert_money(row[3], src["debit"])
            _assert_money(row[4], src["credit"])
            _assert_money(row[5], src["balance"])
