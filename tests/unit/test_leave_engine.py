"""Unit tests for the leave rules engine."""
import pytest
from datetime import date
from decimal import Decimal

from app.modules.timesheets.leave_engine import (
    HolidaysAct2003RuleSet,
    EmploymentLeaveAct2026RuleSet,
    resolve_ruleset,
)


class TestHolidaysAct2003:
    """Tests for HolidaysAct2003RuleSet."""

    def setup_method(self):
        self.ruleset = HolidaysAct2003RuleSet()

    def test_version(self):
        assert self.ruleset.version == "holidays_act_2003"

    def test_effective_from(self):
        assert self.ruleset.effective_from == date(2003, 10, 1)

    def test_accrue_first_year_8_percent(self):
        """Before 12 months: 8% of hours worked."""
        accrued = self.ruleset.accrue(
            employment_start_date=date(2026, 3, 1),  # Only ~3 months ago
            standard_hours_per_week=Decimal("40"),
            current_balance_hours=Decimal("0"),
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 14),
            worked_hours_in_period=Decimal("80"),
        )
        # 8% of 80 = 6.4
        assert accrued == Decimal("6.4")

    def test_accrue_after_12_months_pro_rata(self):
        """After 12 months: 4 weeks × standard hours, pro-rated."""
        accrued = self.ruleset.accrue(
            employment_start_date=date(2025, 1, 1),  # > 12 months
            standard_hours_per_week=Decimal("40"),
            current_balance_hours=Decimal("0"),
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 14),
            worked_hours_in_period=Decimal("80"),
        )
        # Annual entitlement: 40 * 4 = 160 hours
        # Daily rate: 160 / 365.25 ≈ 0.4379 per day
        # 14 days: ≈ 6.13
        assert accrued > Decimal("6")
        assert accrued < Decimal("7")

    def test_value_leave_taken_uses_higher_rate(self):
        """Should use the HIGHER of OWP or AWE."""
        # OWP rate higher
        value = self.ruleset.value_leave_taken(
            leave_hours=Decimal("8"),
            ordinary_weekly_pay=Decimal("1200"),  # $30/hr
            average_weekly_earnings=Decimal("1000"),  # $25/hr
            standard_hours_per_week=Decimal("40"),
        )
        # Higher rate = $30/hr × 8 hours = $240
        assert value == Decimal("240")

    def test_value_leave_taken_awe_higher(self):
        """AWE rate higher."""
        value = self.ruleset.value_leave_taken(
            leave_hours=Decimal("8"),
            ordinary_weekly_pay=Decimal("800"),  # $20/hr
            average_weekly_earnings=Decimal("1000"),  # $25/hr
            standard_hours_per_week=Decimal("40"),
        )
        assert value == Decimal("200")  # $25 × 8

    def test_value_leave_zero_hours(self):
        value = self.ruleset.value_leave_taken(
            leave_hours=Decimal("0"),
            ordinary_weekly_pay=Decimal("1000"),
            average_weekly_earnings=Decimal("1000"),
            standard_hours_per_week=Decimal("40"),
        )
        assert value == Decimal("0")

    def test_otherwise_working_day_true(self):
        """Monday (0) in a Mon-Fri pattern."""
        assert self.ruleset.otherwise_working_day(
            target_date=date(2026, 6, 8),  # Monday
            work_pattern=[0, 1, 2, 3, 4],  # Mon-Fri
            public_holiday_dates=set(),
        ) is True

    def test_otherwise_working_day_false(self):
        """Saturday (5) in a Mon-Fri pattern."""
        assert self.ruleset.otherwise_working_day(
            target_date=date(2026, 6, 13),  # Saturday
            work_pattern=[0, 1, 2, 3, 4],  # Mon-Fri
            public_holiday_dates=set(),
        ) is False

    def test_public_holiday_worked(self):
        result = self.ruleset.public_holiday_entitlement(
            worked_on_holiday=True,
            hours_worked=Decimal("8"),
            relevant_daily_pay=Decimal("30"),
        )
        assert result["pay_multiplier"] == Decimal("1.5")
        assert result["alternative_day"] is True
        assert result["pay_amount"] == Decimal("360")  # 8 × 30 × 1.5

    def test_public_holiday_not_worked(self):
        result = self.ruleset.public_holiday_entitlement(
            worked_on_holiday=False,
            hours_worked=Decimal("0"),
            relevant_daily_pay=Decimal("240"),
        )
        assert result["pay_multiplier"] == Decimal("1.0")
        assert result["alternative_day"] is False
        assert result["pay_amount"] == Decimal("240")

    def test_termination_payout(self):
        payout = self.ruleset.termination_payout(
            employment_start_date=date(2025, 1, 1),
            termination_date=date(2026, 6, 9),
            annual_leave_balance_hours=Decimal("40"),
            standard_hours_per_week=Decimal("40"),
            ordinary_weekly_pay=Decimal("1200"),
            average_weekly_earnings=Decimal("1000"),
        )
        # Higher rate = $1200/40 = $30/hr
        # 40 hours × $30 = $1200
        assert payout == Decimal("1200")


class TestEmploymentLeaveAct2026Stub:
    """Tests for EmploymentLeaveAct2026RuleSet (stub)."""

    def setup_method(self):
        self.ruleset = EmploymentLeaveAct2026RuleSet()

    def test_version(self):
        assert self.ruleset.version == "employment_leave_act_2026"

    def test_effective_from(self):
        assert self.ruleset.effective_from == date(2026, 12, 1)

    def test_delegates_to_2003(self):
        """Stub delegates to 2003 implementation."""
        accrued = self.ruleset.accrue(
            employment_start_date=date(2026, 3, 1),
            standard_hours_per_week=Decimal("40"),
            current_balance_hours=Decimal("0"),
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 14),
            worked_hours_in_period=Decimal("80"),
        )
        # Same as 2003: 8% of 80 = 6.4
        assert accrued == Decimal("6.4")


class TestResolveRuleset:
    """Tests for resolve_ruleset()."""

    def test_default_returns_2003(self):
        ruleset = resolve_ruleset()
        assert ruleset.version == "holidays_act_2003"

    def test_explicit_date_returns_2003(self):
        ruleset = resolve_ruleset(date(2026, 6, 1))
        assert ruleset.version == "holidays_act_2003"

    def test_2026_opt_in_before_effective(self):
        """Opted in but before effective date → still 2003."""
        ruleset = resolve_ruleset(date(2026, 6, 1), org_opted_in_2026=True)
        assert ruleset.version == "holidays_act_2003"

    def test_2026_opt_in_after_effective(self):
        """Opted in and after effective date → 2026."""
        ruleset = resolve_ruleset(date(2027, 1, 1), org_opted_in_2026=True)
        assert ruleset.version == "employment_leave_act_2026"

    def test_2026_not_opted_in_after_effective(self):
        """After effective date but NOT opted in → still 2003."""
        ruleset = resolve_ruleset(date(2027, 1, 1), org_opted_in_2026=False)
        assert ruleset.version == "holidays_act_2003"
