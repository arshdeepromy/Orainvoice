"""Unit tests for pay cycle period computation and generation."""
import pytest
from datetime import date, timedelta

from app.modules.timesheets.pay_cycles import (
    compute_period_boundaries,
    generate_upcoming_periods,
)


class TestComputePeriodBoundaries:
    """Tests for compute_period_boundaries()."""

    def test_weekly_from_anchor(self):
        start, end = compute_period_boundaries("weekly", date(2026, 6, 1), date(2026, 6, 3))
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 7)

    def test_weekly_second_period(self):
        start, end = compute_period_boundaries("weekly", date(2026, 6, 1), date(2026, 6, 10))
        assert start == date(2026, 6, 8)
        assert end == date(2026, 6, 14)

    def test_fortnightly_from_anchor(self):
        start, end = compute_period_boundaries("fortnightly", date(2026, 6, 1), date(2026, 6, 9))
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 14)

    def test_fortnightly_second_period(self):
        start, end = compute_period_boundaries("fortnightly", date(2026, 6, 1), date(2026, 6, 20))
        assert start == date(2026, 6, 15)
        assert end == date(2026, 6, 28)

    def test_monthly_mid_month(self):
        start, end = compute_period_boundaries("monthly", date(2026, 1, 1), date(2026, 6, 15))
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 30)

    def test_monthly_february(self):
        start, end = compute_period_boundaries("monthly", date(2026, 1, 1), date(2026, 2, 15))
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_monthly_december(self):
        start, end = compute_period_boundaries("monthly", date(2026, 1, 1), date(2026, 12, 25))
        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)

    def test_weekly_boundary_date(self):
        """Date that falls exactly on an anchor boundary."""
        start, end = compute_period_boundaries("weekly", date(2026, 6, 1), date(2026, 6, 1))
        assert start == date(2026, 6, 1)
        assert end == date(2026, 6, 7)


class TestGenerateUpcomingPeriods:
    """Tests for generate_upcoming_periods()."""

    def test_generates_four_fortnightly_periods(self):
        periods = generate_upcoming_periods(
            frequency="fortnightly",
            anchor_date=date(2026, 6, 1),
            pay_date_offset_days=3,
            from_date=date(2026, 6, 1),
            count=4,
        )
        assert len(periods) == 4
        assert periods[0]["start_date"] == date(2026, 6, 1)
        assert periods[0]["end_date"] == date(2026, 6, 14)
        assert periods[0]["pay_date"] == date(2026, 6, 17)

    def test_generates_monthly_periods(self):
        periods = generate_upcoming_periods(
            frequency="monthly",
            anchor_date=date(2026, 1, 1),
            pay_date_offset_days=5,
            from_date=date(2026, 6, 1),
            count=3,
        )
        assert len(periods) == 3
        assert periods[0]["start_date"] == date(2026, 6, 1)
        assert periods[0]["end_date"] == date(2026, 6, 30)
        assert periods[0]["pay_date"] == date(2026, 7, 5)

    def test_pay_date_offset(self):
        periods = generate_upcoming_periods(
            frequency="weekly",
            anchor_date=date(2026, 6, 1),
            pay_date_offset_days=2,
            from_date=date(2026, 6, 1),
            count=1,
        )
        assert periods[0]["pay_date"] == date(2026, 6, 9)  # end (Jun 7) + 2 days
