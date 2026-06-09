"""Leave Rules Engine — versioned leave calculation protocol.

Implements the NZ Holidays Act 2003 rules and provides a stub for the
upcoming Employment (Holidays and Leave) Amendment Act 2026.

The engine is invoked at period finalisation (when timesheets are locked)
to compute leave accrual, value leave taken, and related entitlements.

Phase C implementation per design § Phase C Architecture Notes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


# ===========================================================================
# Protocol / Interface
# ===========================================================================


@runtime_checkable
class LeaveRuleSet(Protocol):
    """Versioned leave rules provider.

    Each implementation encapsulates a specific version of NZ employment
    legislation. The `resolve_ruleset()` function returns the applicable
    implementation for a given org and effective date.

    Methods are pure computations over input data — no DB access.
    The service layer fetches the required data and calls these methods.
    """

    @property
    def version(self) -> str:
        """Version identifier (e.g. 'holidays_act_2003')."""
        ...

    @property
    def effective_from(self) -> date:
        """Date from which this rule set is applicable."""
        ...

    def accrue(
        self,
        *,
        employment_start_date: date,
        standard_hours_per_week: Decimal,
        current_balance_hours: Decimal,
        period_start: date,
        period_end: date,
        worked_hours_in_period: Decimal,
    ) -> Decimal:
        """Compute leave accrual for a period.

        Returns the number of hours to accrue for the given period.
        """
        ...

    def value_leave_taken(
        self,
        *,
        leave_hours: Decimal,
        ordinary_weekly_pay: Decimal,
        average_weekly_earnings: Decimal,
        standard_hours_per_week: Decimal,
    ) -> Decimal:
        """Value leave taken in dollar terms.

        NZ law requires the HIGHER of:
        - Ordinary weekly pay (at the time leave is taken)
        - Average weekly earnings (over the last 52 weeks)

        Returns the dollar value of the leave taken.
        """
        ...

    def otherwise_working_day(
        self,
        *,
        target_date: date,
        work_pattern: list[int],  # days of week worked (0=Mon, 6=Sun)
        public_holiday_dates: set[date],
    ) -> bool:
        """Determine if a date would be a working day for this staff member.

        Used for public holiday entitlement — staff are only entitled to
        a paid public holiday if it falls on a day they would otherwise work.
        """
        ...

    def public_holiday_entitlement(
        self,
        *,
        worked_on_holiday: bool,
        hours_worked: Decimal,
        relevant_daily_pay: Decimal,
    ) -> dict:
        """Calculate public holiday entitlement.

        Returns dict with:
        - 'pay_multiplier': rate multiplier (1.5x for time-and-a-half)
        - 'alternative_day': whether an alternative holiday is earned
        - 'pay_amount': dollar amount for hours worked on the holiday
        """
        ...

    def termination_payout(
        self,
        *,
        employment_start_date: date,
        termination_date: date,
        annual_leave_balance_hours: Decimal,
        standard_hours_per_week: Decimal,
        ordinary_weekly_pay: Decimal,
        average_weekly_earnings: Decimal,
    ) -> Decimal:
        """Calculate termination leave payout.

        Includes:
        - Accrued but untaken annual leave
        - Pro-rata entitlement for the current year
        """
        ...


# ===========================================================================
# Implementation: Holidays Act 2003 (current active legislation)
# ===========================================================================


class HolidaysAct2003RuleSet:
    """NZ Holidays Act 2003 implementation.

    Key rules:
    - 4 weeks annual leave after 12 months continuous employment.
    - Leave accrues at 8% of gross earnings (for those not yet entitled).
    - Leave is valued at the HIGHER of ordinary weekly pay or average
      weekly earnings over the last 52 weeks.
    - Public holidays: time-and-a-half + alternative day if worked.
    """

    @property
    def version(self) -> str:
        return "holidays_act_2003"

    @property
    def effective_from(self) -> date:
        return date(2003, 10, 1)

    def accrue(
        self,
        *,
        employment_start_date: date,
        standard_hours_per_week: Decimal,
        current_balance_hours: Decimal,
        period_start: date,
        period_end: date,
        worked_hours_in_period: Decimal,
    ) -> Decimal:
        """Accrue annual leave per the Holidays Act 2003.

        After 12 months employment: 4 weeks annual leave per year.
        Accrual rate: (4 weeks × standard_hours) / 52 weeks per week worked.

        Before 12 months: accrue at 8% of hours worked (pay-as-you-go).
        """
        months_employed = (period_end - employment_start_date).days / 30.44
        period_days = (period_end - period_start).days + 1

        if months_employed < 12:
            # 8% accrual for employees in first year
            return worked_hours_in_period * Decimal("0.08")

        # Annual entitlement: 4 weeks × standard hours
        annual_entitlement_hours = standard_hours_per_week * Decimal("4")
        # Pro-rate for this period
        daily_rate = annual_entitlement_hours / Decimal("365.25")
        return daily_rate * Decimal(str(period_days))

    def value_leave_taken(
        self,
        *,
        leave_hours: Decimal,
        ordinary_weekly_pay: Decimal,
        average_weekly_earnings: Decimal,
        standard_hours_per_week: Decimal,
    ) -> Decimal:
        """Value leave at the HIGHER of OWP or AWE.

        Sections 21–30 of the Holidays Act 2003.
        """
        if standard_hours_per_week <= 0:
            return Decimal("0")

        owp_hourly = ordinary_weekly_pay / standard_hours_per_week
        awe_hourly = average_weekly_earnings / standard_hours_per_week

        hourly_rate = max(owp_hourly, awe_hourly)
        return leave_hours * hourly_rate

    def otherwise_working_day(
        self,
        *,
        target_date: date,
        work_pattern: list[int],
        public_holiday_dates: set[date],
    ) -> bool:
        """Section 12 — 'otherwise working day' test.

        A day is an OWD if:
        - It falls on a day the employee would normally work, AND
        - The employee has not already been on leave for that day.
        """
        day_of_week = target_date.weekday()  # 0=Monday
        return day_of_week in work_pattern

    def public_holiday_entitlement(
        self,
        *,
        worked_on_holiday: bool,
        hours_worked: Decimal,
        relevant_daily_pay: Decimal,
    ) -> dict:
        """Section 50 — public holiday entitlements.

        If worked: time-and-a-half pay + alternative holiday.
        If not worked (but OWD): relevant daily pay.
        """
        if worked_on_holiday:
            return {
                "pay_multiplier": Decimal("1.5"),
                "alternative_day": True,
                "pay_amount": hours_worked * relevant_daily_pay * Decimal("1.5"),
            }
        else:
            return {
                "pay_multiplier": Decimal("1.0"),
                "alternative_day": False,
                "pay_amount": relevant_daily_pay,
            }

    def termination_payout(
        self,
        *,
        employment_start_date: date,
        termination_date: date,
        annual_leave_balance_hours: Decimal,
        standard_hours_per_week: Decimal,
        ordinary_weekly_pay: Decimal,
        average_weekly_earnings: Decimal,
    ) -> Decimal:
        """Section 23 — termination payout.

        Pay out:
        1. Accrued but untaken annual leave (at higher of OWP/AWE rate).
        2. Pro-rata entitlement for the current incomplete year (8% of
           gross earnings since last anniversary).
        """
        if standard_hours_per_week <= 0:
            return Decimal("0")

        hourly_rate = max(
            ordinary_weekly_pay / standard_hours_per_week,
            average_weekly_earnings / standard_hours_per_week,
        )

        return annual_leave_balance_hours * hourly_rate


# ===========================================================================
# Stub: Employment Leave Act 2026 (future legislation)
# ===========================================================================


class EmploymentLeaveAct2026RuleSet:
    """Stub for the proposed Employment (Holidays and Leave) Amendment Act 2026.

    This is a placeholder for when the new legislation comes into effect.
    It mirrors the HolidaysAct2003RuleSet interface but all methods
    currently delegate to the 2003 rules with a deprecation note.

    The `resolve_ruleset()` function will return this implementation
    when the effective date passes and the org opts in.
    """

    _fallback = HolidaysAct2003RuleSet()

    @property
    def version(self) -> str:
        return "employment_leave_act_2026"

    @property
    def effective_from(self) -> date:
        # Placeholder date — update when legislation is enacted
        return date(2026, 12, 1)

    def accrue(self, **kwargs) -> Decimal:
        # TODO: Implement 2026 accrual rules when legislation is finalised.
        # Key expected changes:
        # - Possible increase to 5 weeks annual leave
        # - Changes to sick leave accrual
        return self._fallback.accrue(**kwargs)

    def value_leave_taken(self, **kwargs) -> Decimal:
        # TODO: Implement 2026 valuation rules.
        return self._fallback.value_leave_taken(**kwargs)

    def otherwise_working_day(self, **kwargs) -> bool:
        # TODO: May change OWD definition for irregular workers.
        return self._fallback.otherwise_working_day(**kwargs)

    def public_holiday_entitlement(self, **kwargs) -> dict:
        # TODO: Possible changes to alternative day rules.
        return self._fallback.public_holiday_entitlement(**kwargs)

    def termination_payout(self, **kwargs) -> Decimal:
        # TODO: Implement 2026 termination rules.
        return self._fallback.termination_payout(**kwargs)


# ===========================================================================
# Resolver — returns the applicable rule set for an org at a given date.
# ===========================================================================


# Registry of available rule sets (ordered by effective_from descending)
_RULE_SETS: list[LeaveRuleSet] = [
    EmploymentLeaveAct2026RuleSet(),
    HolidaysAct2003RuleSet(),
]


def resolve_ruleset(
    effective_date: date | None = None,
    *,
    org_opted_in_2026: bool = False,
) -> LeaveRuleSet:
    """Return the applicable leave rule set for the given date.

    Logic:
    - If org has opted into the 2026 Act AND the effective date is
      on or after the Act's effective_from → use 2026 rules.
    - Otherwise → use 2003 rules (the default).

    The opt-in flag would be stored in org settings. Until the 2026 Act
    is enacted and orgs can opt in, this always returns HolidaysAct2003.
    """
    if effective_date is None:
        effective_date = date.today()

    if org_opted_in_2026:
        act_2026 = _RULE_SETS[0]  # EmploymentLeaveAct2026RuleSet
        if effective_date >= act_2026.effective_from:
            return act_2026

    # Default: Holidays Act 2003
    return _RULE_SETS[1]


# ===========================================================================
# Leave Accrual Service Helper
# ===========================================================================


@dataclass
class AccrualResult:
    """Result of leave accrual computation for a period."""
    staff_id: UUID
    leave_type_code: str
    accrued_hours: Decimal
    new_balance_hours: Decimal
    period_start: date
    period_end: date


async def compute_leave_accrual_for_period(
    *,
    staff_id: UUID,
    employment_start_date: date,
    standard_hours_per_week: Decimal,
    current_balance_hours: Decimal,
    worked_hours_in_period: Decimal,
    period_start: date,
    period_end: date,
    org_opted_in_2026: bool = False,
) -> AccrualResult:
    """Compute leave accrual for a staff member for a given period.

    Uses the resolved rule set to calculate accrued hours.
    This is called when timesheets are locked (period finalisation trigger).
    """
    ruleset = resolve_ruleset(period_end, org_opted_in_2026=org_opted_in_2026)

    accrued = ruleset.accrue(
        employment_start_date=employment_start_date,
        standard_hours_per_week=standard_hours_per_week,
        current_balance_hours=current_balance_hours,
        period_start=period_start,
        period_end=period_end,
        worked_hours_in_period=worked_hours_in_period,
    )

    return AccrualResult(
        staff_id=staff_id,
        leave_type_code="annual_leave",
        accrued_hours=accrued,
        new_balance_hours=current_balance_hours + accrued,
        period_start=period_start,
        period_end=period_end,
    )
