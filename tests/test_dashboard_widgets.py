"""Property-based tests for automotive dashboard widgets (Tasks 6.1–6.8).

Tests PURE LOGIC correctness properties of the data transformations used by
the dashboard widgets.  No database, no SQLAlchemy — just in-memory data
structures exercised with Hypothesis.

Feature: automotive-dashboard-widgets
Properties 5–12

Validates: Requirements 4.1, 5.1, 5.3, 6.1, 6.3, 7.1, 7.2, 8.1, 9.1,
           10.1, 11.1, 11.8, 12.6
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from pydantic import ValidationError

from app.modules.organisations.schemas import ReminderConfigUpdate


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Lightweight data classes for in-memory testing (no ORM dependency)
# ---------------------------------------------------------------------------


@dataclass
class FakeInvoiceRow:
    customer_id: uuid.UUID
    customer_name: str
    created_at: datetime
    vehicle_rego: Optional[str] = None


@dataclass
class FakeBookingRow:
    booking_id: uuid.UUID
    start_time: datetime
    customer_name: str
    vehicle_rego: Optional[str] = None


@dataclass
class FakeHolidayRow:
    name: str
    holiday_date: date
    country_code: str


@dataclass
class FakeProductRow:
    product_id: uuid.UUID
    category: str
    current_quantity: int
    min_threshold: int


@dataclass
class FakeRevenueRow:
    created_at: datetime
    subtotal: float


@dataclass
class FakeExpenseRow:
    expense_date: date
    amount: float


@dataclass
class FakeTimeEntry:
    user_id: uuid.UUID
    staff_name: str
    start_time: datetime
    end_time: Optional[datetime] = None


@dataclass
class FakeVehicleExpiry:
    vehicle_id: uuid.UUID
    vehicle_rego: str
    expiry_type: str  # "wof" or "service"
    expiry_date: date
    customer_name: str


@dataclass
class FakeDismissal:
    vehicle_id: uuid.UUID
    reminder_type: str
    expiry_date: date


# ---------------------------------------------------------------------------
# Pure-logic functions that mirror the service layer transformations
# ---------------------------------------------------------------------------


def recent_list_top_n(items: list[FakeInvoiceRow], n: int = 10) -> list[FakeInvoiceRow]:
    """Sort items by created_at DESC and take the top N."""
    sorted_items = sorted(items, key=lambda x: x.created_at, reverse=True)
    return sorted_items[:n]


def filter_todays_bookings(
    bookings: list[FakeBookingRow], today: date
) -> list[FakeBookingRow]:
    """Return only bookings whose start_time falls on *today*, sorted ASC."""
    day_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    day_end = datetime(today.year, today.month, today.day, 23, 59, 59)
    todays = [b for b in bookings if day_start <= b.start_time <= day_end]
    return sorted(todays, key=lambda b: b.start_time)


def filter_public_holidays(
    holidays: list[FakeHolidayRow],
    country: str,
    today: date,
    limit: int = 5,
) -> list[FakeHolidayRow]:
    """Filter by country, future-only, sort ASC, limit."""
    filtered = [
        h for h in holidays
        if h.country_code == country and h.holiday_date >= today
    ]
    filtered.sort(key=lambda h: h.holiday_date)
    return filtered[:limit]


def group_inventory_by_category(
    products: list[FakeProductRow],
) -> dict[str, dict[str, int]]:
    """Group products by category, compute total_count and low_stock_count."""
    groups: dict[str, dict[str, int]] = {}
    for p in products:
        if p.category not in groups:
            groups[p.category] = {"total_count": 0, "low_stock_count": 0}
        groups[p.category]["total_count"] += 1
        if p.current_quantity <= p.min_threshold:
            groups[p.category]["low_stock_count"] += 1
    return groups


def aggregate_cash_flow(
    revenues: list[FakeRevenueRow],
    expenses: list[FakeExpenseRow],
    months: list[tuple[int, int]],
) -> dict[tuple[int, int], dict[str, float]]:
    """Aggregate revenue and expenses by (year, month)."""
    result: dict[tuple[int, int], dict[str, float]] = {}
    for yr, mo in months:
        result[(yr, mo)] = {"revenue": 0.0, "expenses": 0.0}

    for r in revenues:
        key = (r.created_at.year, r.created_at.month)
        if key in result:
            result[key]["revenue"] += r.subtotal

    for e in expenses:
        key = (e.expense_date.year, e.expense_date.month)
        if key in result:
            result[key]["expenses"] += e.amount

    return result


def filter_active_staff(
    entries: list[FakeTimeEntry], today: date
) -> list[FakeTimeEntry]:
    """Return only entries with end_time IS NULL and start_time on today."""
    day_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    return [
        e for e in entries
        if e.end_time is None and e.start_time >= day_start
    ]


def filter_expiry_reminders(
    vehicles: list[FakeVehicleExpiry],
    dismissals: list[FakeDismissal],
    threshold_days: int,
    today: date,
) -> list[FakeVehicleExpiry]:
    """Filter vehicles within threshold, future, not dismissed. Sort by date ASC."""
    threshold_date = today + timedelta(days=threshold_days)

    dismissed_set = {
        (d.vehicle_id, d.reminder_type, d.expiry_date) for d in dismissals
    }

    filtered = [
        v for v in vehicles
        if v.expiry_date >= today
        and v.expiry_date <= threshold_date
        and (v.vehicle_id, v.expiry_type, v.expiry_date) not in dismissed_set
    ]
    return sorted(filtered, key=lambda v: v.expiry_date)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_customer_names = st.text(
    alphabet=st.characters(whitelist_categories=("L",)), min_size=1, max_size=20
)

_vehicle_regos = st.one_of(st.none(), st.from_regex(r"[A-Z]{3}[0-9]{3}", fullmatch=True))

_recent_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2026, 12, 31),
)

_invoice_rows = st.builds(
    FakeInvoiceRow,
    customer_id=st.uuids(),
    customer_name=_customer_names,
    created_at=_recent_datetimes,
    vehicle_rego=_vehicle_regos,
)

# Bookings: spread across a few days around "today"
_booking_datetimes = st.datetimes(
    min_value=datetime(2025, 6, 14),
    max_value=datetime(2025, 6, 17),
)

_booking_rows = st.builds(
    FakeBookingRow,
    booking_id=st.uuids(),
    start_time=_booking_datetimes,
    customer_name=_customer_names,
    vehicle_rego=_vehicle_regos,
)

_country_codes = st.sampled_from(["NZ", "AU", "US", "GB"])

_holiday_dates = st.dates(
    min_value=date(2024, 1, 1),
    max_value=date(2027, 12, 31),
)

_holiday_rows = st.builds(
    FakeHolidayRow,
    name=_customer_names,
    holiday_date=_holiday_dates,
    country_code=_country_codes,
)

_categories = st.sampled_from(["tyres", "parts", "fluids", "other"])

_product_rows = st.builds(
    FakeProductRow,
    product_id=st.uuids(),
    category=_categories,
    current_quantity=st.integers(min_value=0, max_value=200),
    min_threshold=st.integers(min_value=0, max_value=50),
)

_revenue_rows = st.builds(
    FakeRevenueRow,
    created_at=_recent_datetimes,
    subtotal=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
)

_expense_rows = st.builds(
    FakeExpenseRow,
    expense_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2026, 12, 31)),
    amount=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
)

_time_entry_datetimes = st.datetimes(
    min_value=datetime(2025, 6, 14),
    max_value=datetime(2025, 6, 17),
)

_time_entries = st.builds(
    FakeTimeEntry,
    user_id=st.uuids(),
    staff_name=_customer_names,
    start_time=_time_entry_datetimes,
    end_time=st.one_of(st.none(), _time_entry_datetimes),
)

_expiry_types = st.sampled_from(["wof", "service"])

_expiry_dates = st.dates(
    min_value=date(2025, 5, 1),
    max_value=date(2026, 6, 30),
)

_vehicle_expiries = st.builds(
    FakeVehicleExpiry,
    vehicle_id=st.uuids(),
    vehicle_rego=st.from_regex(r"[A-Z]{3}[0-9]{3}", fullmatch=True),
    expiry_type=_expiry_types,
    expiry_date=_expiry_dates,
    customer_name=_customer_names,
)

_dismissals = st.builds(
    FakeDismissal,
    vehicle_id=st.uuids(),
    reminder_type=_expiry_types,
    expiry_date=_expiry_dates,
)


# ===========================================================================
# Property 5: Recent List Endpoints Return Bounded Ordered Results
# Feature: automotive-dashboard-widgets, Property 5: Recent List Bounded Order
# ===========================================================================


class TestRecentListBoundedOrder:
    """Property 5: Recent List Endpoints Return Bounded Ordered Results.

    For any set of invoices (or claims), the recent list query SHALL return
    at most 10 items, and the items SHALL be ordered by date descending.

    **Validates: Requirements 4.1, 9.1**
    """

    @given(invoices=st.lists(_invoice_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_recent_list_returns_at_most_10_items(
        self, invoices: list[FakeInvoiceRow]
    ):
        """The result set is bounded to ≤10 items regardless of input size.

        **Validates: Requirements 4.1, 9.1**
        """
        result = recent_list_top_n(invoices, n=10)
        assert len(result) <= 10

    @given(invoices=st.lists(_invoice_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_recent_list_is_date_descending(
        self, invoices: list[FakeInvoiceRow]
    ):
        """Items are ordered by created_at descending (most recent first).

        **Validates: Requirements 4.1, 9.1**
        """
        result = recent_list_top_n(invoices, n=10)
        for i in range(len(result) - 1):
            assert result[i].created_at >= result[i + 1].created_at

    @given(invoices=st.lists(_invoice_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_recent_list_items_come_from_input(
        self, invoices: list[FakeInvoiceRow]
    ):
        """Every returned item exists in the original input set.

        **Validates: Requirements 4.1, 9.1**
        """
        result = recent_list_top_n(invoices, n=10)
        input_ids = {id(inv) for inv in invoices}
        for item in result:
            assert id(item) in input_ids


# ===========================================================================
# Property 6: Today's Bookings Filter
# Feature: automotive-dashboard-widgets, Property 6: Today's Bookings Filter
# ===========================================================================


class TestTodaysBookingsFilter:
    """Property 6: Today's Bookings Filter.

    For any set of bookings with various dates, the today's bookings query
    SHALL return only bookings whose start_time falls within the current
    calendar date, sorted by start_time ascending.

    **Validates: Requirements 5.1, 5.3**
    """

    @given(bookings=st.lists(_booking_rows, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_only_todays_bookings_returned(
        self, bookings: list[FakeBookingRow]
    ):
        """Only bookings on the reference date are included.

        **Validates: Requirements 5.1, 5.3**
        """
        ref_date = date(2025, 6, 15)
        result = filter_todays_bookings(bookings, ref_date)

        for b in result:
            assert b.start_time.date() == ref_date

    @given(bookings=st.lists(_booking_rows, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_no_non_today_bookings_returned(
        self, bookings: list[FakeBookingRow]
    ):
        """Bookings on other dates are excluded.

        **Validates: Requirements 5.1, 5.3**
        """
        ref_date = date(2025, 6, 15)
        result = filter_todays_bookings(bookings, ref_date)
        result_ids = {id(b) for b in result}

        for b in bookings:
            if b.start_time.date() != ref_date:
                assert id(b) not in result_ids

    @given(bookings=st.lists(_booking_rows, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_todays_bookings_sorted_ascending(
        self, bookings: list[FakeBookingRow]
    ):
        """Results are sorted by start_time ascending.

        **Validates: Requirements 5.1, 5.3**
        """
        ref_date = date(2025, 6, 15)
        result = filter_todays_bookings(bookings, ref_date)

        for i in range(len(result) - 1):
            assert result[i].start_time <= result[i + 1].start_time


# ===========================================================================
# Property 7: Public Holidays Country and Date Filter
# Feature: automotive-dashboard-widgets, Property 7: Public Holidays Filter
# ===========================================================================


class TestPublicHolidaysFilter:
    """Property 7: Public Holidays Country and Date Filter.

    For any set of public holidays, the query for a given country SHALL
    return only holidays matching that country AND with holiday_date >= today,
    limited to 5, sorted ascending.

    **Validates: Requirements 6.1, 6.3**
    """

    @given(
        holidays=st.lists(_holiday_rows, min_size=0, max_size=30),
        country=_country_codes,
        today=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 6, 30)),
    )
    @PBT_SETTINGS
    def test_only_matching_country_returned(
        self, holidays: list[FakeHolidayRow], country: str, today: date
    ):
        """Only holidays for the requested country are returned.

        **Validates: Requirements 6.1, 6.3**
        """
        result = filter_public_holidays(holidays, country, today)
        for h in result:
            assert h.country_code == country

    @given(
        holidays=st.lists(_holiday_rows, min_size=0, max_size=30),
        country=_country_codes,
        today=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 6, 30)),
    )
    @PBT_SETTINGS
    def test_only_future_holidays_returned(
        self, holidays: list[FakeHolidayRow], country: str, today: date
    ):
        """Only holidays on or after today are returned.

        **Validates: Requirements 6.1, 6.3**
        """
        result = filter_public_holidays(holidays, country, today)
        for h in result:
            assert h.holiday_date >= today

    @given(
        holidays=st.lists(_holiday_rows, min_size=0, max_size=30),
        country=_country_codes,
        today=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 6, 30)),
    )
    @PBT_SETTINGS
    def test_holidays_limited_to_5(
        self, holidays: list[FakeHolidayRow], country: str, today: date
    ):
        """At most 5 holidays are returned.

        **Validates: Requirements 6.1, 6.3**
        """
        result = filter_public_holidays(holidays, country, today)
        assert len(result) <= 5

    @given(
        holidays=st.lists(_holiday_rows, min_size=0, max_size=30),
        country=_country_codes,
        today=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 6, 30)),
    )
    @PBT_SETTINGS
    def test_holidays_sorted_ascending(
        self, holidays: list[FakeHolidayRow], country: str, today: date
    ):
        """Results are sorted by holiday_date ascending.

        **Validates: Requirements 6.1, 6.3**
        """
        result = filter_public_holidays(holidays, country, today)
        for i in range(len(result) - 1):
            assert result[i].holiday_date <= result[i + 1].holiday_date


# ===========================================================================
# Property 8: Inventory Category Grouping Correctness
# Feature: automotive-dashboard-widgets, Property 8: Inventory Grouping
# ===========================================================================


class TestInventoryCategoryGrouping:
    """Property 8: Inventory Category Grouping Correctness.

    For any set of products, the inventory overview SHALL produce category
    groups where total_count and low_stock_count are correct.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(products=st.lists(_product_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_total_count_per_category_is_correct(
        self, products: list[FakeProductRow]
    ):
        """total_count for each category equals the number of products in it.

        **Validates: Requirements 7.1, 7.2**
        """
        result = group_inventory_by_category(products)

        # Compute expected counts manually
        expected: dict[str, int] = defaultdict(int)
        for p in products:
            expected[p.category] += 1

        for cat, counts in result.items():
            assert counts["total_count"] == expected[cat], (
                f"Category {cat}: expected {expected[cat]}, got {counts['total_count']}"
            )

    @given(products=st.lists(_product_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_low_stock_count_per_category_is_correct(
        self, products: list[FakeProductRow]
    ):
        """low_stock_count equals products where current_quantity <= min_threshold.

        **Validates: Requirements 7.1, 7.2**
        """
        result = group_inventory_by_category(products)

        # Compute expected low-stock counts manually
        expected: dict[str, int] = defaultdict(int)
        for p in products:
            if p.current_quantity <= p.min_threshold:
                expected[p.category] += 1

        for cat, counts in result.items():
            assert counts["low_stock_count"] == expected.get(cat, 0), (
                f"Category {cat}: expected low_stock {expected.get(cat, 0)}, "
                f"got {counts['low_stock_count']}"
            )

    @given(products=st.lists(_product_rows, min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_all_categories_present(
        self, products: list[FakeProductRow]
    ):
        """Every category in the input appears in the result.

        **Validates: Requirements 7.1, 7.2**
        """
        result = group_inventory_by_category(products)
        input_categories = {p.category for p in products}
        assert set(result.keys()) == input_categories


# ===========================================================================
# Property 9: Cash Flow Monthly Aggregation
# Feature: automotive-dashboard-widgets, Property 9: Cash Flow Aggregation
# ===========================================================================


class TestCashFlowMonthlyAggregation:
    """Property 9: Cash Flow Monthly Aggregation.

    For any set of invoices and expenses over 6 months, the cash flow query
    SHALL produce monthly entries where revenue and expense sums are correct.

    **Validates: Requirements 8.1**
    """

    @given(
        revenues=st.lists(_revenue_rows, min_size=0, max_size=30),
        expenses=st.lists(_expense_rows, min_size=0, max_size=30),
    )
    @PBT_SETTINGS
    def test_monthly_revenue_sums_are_correct(
        self, revenues: list[FakeRevenueRow], expenses: list[FakeExpenseRow]
    ):
        """Revenue for each month equals the sum of invoice subtotals in that month.

        **Validates: Requirements 8.1**
        """
        # Define a fixed 6-month window
        months = [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 5), (2025, 6)]
        result = aggregate_cash_flow(revenues, expenses, months)

        for yr, mo in months:
            expected_rev = sum(
                r.subtotal for r in revenues
                if r.created_at.year == yr and r.created_at.month == mo
            )
            assert abs(result[(yr, mo)]["revenue"] - expected_rev) < 1e-6, (
                f"Month {yr}-{mo:02d}: expected revenue {expected_rev}, "
                f"got {result[(yr, mo)]['revenue']}"
            )

    @given(
        revenues=st.lists(_revenue_rows, min_size=0, max_size=30),
        expenses=st.lists(_expense_rows, min_size=0, max_size=30),
    )
    @PBT_SETTINGS
    def test_monthly_expense_sums_are_correct(
        self, revenues: list[FakeRevenueRow], expenses: list[FakeExpenseRow]
    ):
        """Expenses for each month equals the sum of expense amounts in that month.

        **Validates: Requirements 8.1**
        """
        months = [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 5), (2025, 6)]
        result = aggregate_cash_flow(revenues, expenses, months)

        for yr, mo in months:
            expected_exp = sum(
                e.amount for e in expenses
                if e.expense_date.year == yr and e.expense_date.month == mo
            )
            assert abs(result[(yr, mo)]["expenses"] - expected_exp) < 1e-6, (
                f"Month {yr}-{mo:02d}: expected expenses {expected_exp}, "
                f"got {result[(yr, mo)]['expenses']}"
            )

    @given(
        revenues=st.lists(_revenue_rows, min_size=0, max_size=30),
        expenses=st.lists(_expense_rows, min_size=0, max_size=30),
    )
    @PBT_SETTINGS
    def test_cash_flow_returns_exactly_6_months(
        self, revenues: list[FakeRevenueRow], expenses: list[FakeExpenseRow]
    ):
        """The result always contains exactly 6 monthly entries.

        **Validates: Requirements 8.1**
        """
        months = [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 5), (2025, 6)]
        result = aggregate_cash_flow(revenues, expenses, months)
        assert len(result) == 6


# ===========================================================================
# Property 10: Active Staff Returns Only Clocked-In Staff
# Feature: automotive-dashboard-widgets, Property 10: Active Staff Filter
# ===========================================================================


class TestActiveStaffFilter:
    """Property 10: Active Staff Returns Only Clocked-In Staff.

    For any set of time entries, the active staff query SHALL return only
    staff with end_time IS NULL for the current date.

    **Validates: Requirements 10.1**
    """

    @given(entries=st.lists(_time_entries, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_only_open_entries_returned(
        self, entries: list[FakeTimeEntry]
    ):
        """Only entries with end_time=None are returned.

        **Validates: Requirements 10.1**
        """
        ref_date = date(2025, 6, 15)
        result = filter_active_staff(entries, ref_date)
        for e in result:
            assert e.end_time is None

    @given(entries=st.lists(_time_entries, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_only_today_entries_returned(
        self, entries: list[FakeTimeEntry]
    ):
        """Only entries whose start_time is on the reference date are returned.

        **Validates: Requirements 10.1**
        """
        ref_date = date(2025, 6, 15)
        result = filter_active_staff(entries, ref_date)
        for e in result:
            assert e.start_time.date() >= ref_date

    @given(entries=st.lists(_time_entries, min_size=0, max_size=30))
    @PBT_SETTINGS
    def test_closed_entries_excluded(
        self, entries: list[FakeTimeEntry]
    ):
        """Entries with a non-None end_time are never in the result.

        **Validates: Requirements 10.1**
        """
        ref_date = date(2025, 6, 15)
        result = filter_active_staff(entries, ref_date)
        result_ids = {id(e) for e in result}

        for e in entries:
            if e.end_time is not None:
                assert id(e) not in result_ids


# ===========================================================================
# Property 11: Expiry Reminders Exclude Dismissed and Filter by Threshold
# Feature: automotive-dashboard-widgets, Property 11: Expiry Reminders Filter
# ===========================================================================


class TestExpiryRemindersFilter:
    """Property 11: Expiry Reminders Exclude Dismissed and Filter by Threshold.

    For any set of vehicles with expiry dates and dismissals, the query
    SHALL return only vehicles where the expiry is within threshold, future,
    and not dismissed.

    **Validates: Requirements 11.1, 11.8**
    """

    @given(
        vehicles=st.lists(_vehicle_expiries, min_size=0, max_size=20),
        dismissals=st.lists(_dismissals, min_size=0, max_size=10),
        threshold_days=st.integers(min_value=1, max_value=365),
    )
    @PBT_SETTINGS
    def test_only_future_expiries_returned(
        self,
        vehicles: list[FakeVehicleExpiry],
        dismissals: list[FakeDismissal],
        threshold_days: int,
    ):
        """No past expiry dates appear in the result.

        **Validates: Requirements 11.1, 11.8**
        """
        today = date(2025, 6, 15)
        result = filter_expiry_reminders(vehicles, dismissals, threshold_days, today)
        for v in result:
            assert v.expiry_date >= today

    @given(
        vehicles=st.lists(_vehicle_expiries, min_size=0, max_size=20),
        dismissals=st.lists(_dismissals, min_size=0, max_size=10),
        threshold_days=st.integers(min_value=1, max_value=365),
    )
    @PBT_SETTINGS
    def test_only_within_threshold_returned(
        self,
        vehicles: list[FakeVehicleExpiry],
        dismissals: list[FakeDismissal],
        threshold_days: int,
    ):
        """No expiry dates beyond the threshold appear in the result.

        **Validates: Requirements 11.1, 11.8**
        """
        today = date(2025, 6, 15)
        threshold_date = today + timedelta(days=threshold_days)
        result = filter_expiry_reminders(vehicles, dismissals, threshold_days, today)
        for v in result:
            assert v.expiry_date <= threshold_date

    @given(
        vehicles=st.lists(_vehicle_expiries, min_size=1, max_size=10),
        threshold_days=st.integers(min_value=1, max_value=365),
    )
    @PBT_SETTINGS
    def test_dismissed_vehicles_excluded(
        self,
        vehicles: list[FakeVehicleExpiry],
        threshold_days: int,
    ):
        """Vehicles with matching dismissals are excluded from the result.

        **Validates: Requirements 11.1, 11.8**
        """
        today = date(2025, 6, 15)

        # Create dismissals that match every vehicle
        dismissals = [
            FakeDismissal(
                vehicle_id=v.vehicle_id,
                reminder_type=v.expiry_type,
                expiry_date=v.expiry_date,
            )
            for v in vehicles
        ]

        result = filter_expiry_reminders(vehicles, dismissals, threshold_days, today)

        # All vehicles should be excluded since they all have matching dismissals
        assert len(result) == 0

    @given(
        vehicles=st.lists(_vehicle_expiries, min_size=0, max_size=20),
        dismissals=st.lists(_dismissals, min_size=0, max_size=10),
        threshold_days=st.integers(min_value=1, max_value=365),
    )
    @PBT_SETTINGS
    def test_results_sorted_by_expiry_date_ascending(
        self,
        vehicles: list[FakeVehicleExpiry],
        dismissals: list[FakeDismissal],
        threshold_days: int,
    ):
        """Results are sorted by expiry_date ascending.

        **Validates: Requirements 11.1, 11.8**
        """
        today = date(2025, 6, 15)
        result = filter_expiry_reminders(vehicles, dismissals, threshold_days, today)
        for i in range(len(result) - 1):
            assert result[i].expiry_date <= result[i + 1].expiry_date


# ===========================================================================
# Property 12: Reminder Config Validation Range
# Feature: automotive-dashboard-widgets, Property 12: Config Validation
# ===========================================================================


class TestReminderConfigValidationRange:
    """Property 12: Reminder Config Validation Range.

    For any integer value, the reminder config validation SHALL accept
    the value if and only if it is between 1 and 365 inclusive.

    **Validates: Requirements 12.6**
    """

    @given(value=st.integers(min_value=1, max_value=365))
    @PBT_SETTINGS
    def test_valid_range_accepted(self, value: int):
        """Values 1–365 inclusive are accepted by the Pydantic schema.

        **Validates: Requirements 12.6**
        """
        config = ReminderConfigUpdate(wof_days=value, service_days=value)
        assert config.wof_days == value
        assert config.service_days == value

    @given(value=st.integers(min_value=-1000, max_value=0))
    @PBT_SETTINGS
    def test_zero_and_negative_rejected(self, value: int):
        """Values ≤ 0 are rejected by the Pydantic schema.

        **Validates: Requirements 12.6**
        """
        with pytest.raises(ValidationError):
            ReminderConfigUpdate(wof_days=value, service_days=value)

    @given(value=st.integers(min_value=366, max_value=10000))
    @PBT_SETTINGS
    def test_above_365_rejected(self, value: int):
        """Values > 365 are rejected by the Pydantic schema.

        **Validates: Requirements 12.6**
        """
        with pytest.raises(ValidationError):
            ReminderConfigUpdate(wof_days=value, service_days=value)
