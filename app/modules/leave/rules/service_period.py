"""Continuous service computation + the immutable staff snapshot.

``compute_continuous_service`` measures completed months of unbroken employment
from ``employment_start_date`` to the evaluation date. A trial / probation period
is irrelevant — it never delays or resets Continuous_Service (R7.3). Returns
``None`` when there is no start date (R7.4: the evaluator then skips all milestone
processing without any partial calculation).

``StaffSnapshot`` is the immutable input to the pure eligibility evaluator. It
carries ``employment_type`` for **casual identification only** — eligibility never
branches on it otherwise (R7.5).

**Validates: Requirements 7.1, 7.2, 7.3, 7.4**
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.leave.rules.hours_test import HoursTestInput

__all__ = [
    "StaffSnapshot",
    "ServicePeriod",
    "compute_continuous_service",
]


@dataclass(frozen=True)
class StaffSnapshot:
    staff_id: uuid.UUID
    org_id: uuid.UUID
    employment_start_date: date | None
    employment_type: str  # for casual identification ONLY (R7.5)
    standard_hours_per_week: Decimal | None
    holiday_pay_method: str  # "accrued" | "casual_payg"
    fixed_term_months: int | None  # for casual_payg fixed-term rules
    hours_test_input: HoursTestInput | None  # worked-hours aggregates, or None


@dataclass(frozen=True)
class ServicePeriod:
    start_date: date
    evaluation_date: date
    completed_months: int

    def is_milestone_reached(self, months_threshold: int) -> bool:
        """True when completed service has reached the given month threshold."""
        return self.completed_months >= months_threshold


def _completed_months(start: date, end: date) -> int:
    """Whole calendar months elapsed from ``start`` to ``end``.

    A month is "completed" only once the day-of-month is reached (so
    start=Jan 15 → end=Feb 14 is 0 completed months, Feb 15 is 1). Leap-safe:
    when ``start`` is the 29th/30th/31st and ``end``'s month is shorter, the
    last day of ``end``'s month counts as reaching the anniversary day.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # Determine the effective day-of-month for the anniversary in end's month,
    # clamping to the last day of that month for short months (e.g. Feb).
    if end.day < start.day:
        # Could still be "reached" if start.day exceeds the days in end's month
        # and end is on the last day of its month.
        import calendar

        last_day_of_end_month = calendar.monthrange(end.year, end.month)[1]
        if not (start.day > last_day_of_end_month and end.day == last_day_of_end_month):
            months -= 1
    return months


def compute_continuous_service(
    start: date | None, evaluation_date: date
) -> ServicePeriod | None:
    """Completed-months continuous service, or ``None`` when no start date.

    Trial/probation periods are not consulted and never delay or reset the
    computation (R7.3).
    """
    if start is None:
        return None
    return ServicePeriod(
        start_date=start,
        evaluation_date=evaluation_date,
        completed_months=_completed_months(start, evaluation_date),
    )
