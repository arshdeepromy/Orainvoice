"""Hours_Test evaluation (pure predicate) + worked-hours aggregator (I/O).

The Hours_Test gates sick / bereavement / family-violence eligibility for staff
who are not obviously full-time. It is met when, over the qualifying period, the
staff member worked on average **at least 10 hours per week** AND **at least 1
hour every week** OR **at least 40 hours every month** (R8.1).

``evaluate_hours_test`` is a **pure** function over an in-memory
``HoursTestInput`` (or ``None`` when no worked-hours data is available, in which
case the test is treated as not-met with a recorded reason — never an exception,
never a silent pass, R8.5).

``aggregate_hours_test_input`` is the effectful aggregator that sums
``time_clock_entries.worked_minutes`` over the qualifying period (the 6 months
ending at the evaluation date), bucketed by ISO week and calendar month. It
returns ``None`` when there is no usable data.

**Validates: Requirements 8.1, 8.5**
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leave.rules.registry import HoursTestBounds

__all__ = [
    "HoursTestInput",
    "HoursTestResult",
    "evaluate_hours_test",
    "aggregate_hours_test_input",
    "QUALIFYING_PERIOD_DAYS",
]

# The qualifying period for the Hours_Test: the ~6 months (183 days) ending at
# the evaluation date, aligned to the 6-month milestone that gates these types.
QUALIFYING_PERIOD_DAYS = 183


@dataclass(frozen=True)
class HoursTestInput:
    weeks: tuple[Decimal, ...]  # hours worked per ISO week in the qualifying period
    months: tuple[Decimal, ...]  # hours worked per calendar month
    total_hours: Decimal
    period_weeks: int  # number of whole weeks in the qualifying period


@dataclass(frozen=True)
class HoursTestResult:
    met: bool
    reason: str | None  # e.g. "no_worked_hours_data", "avg_below_10h"


def evaluate_hours_test(
    inp: HoursTestInput | None, bounds: HoursTestBounds
) -> HoursTestResult:
    """Pure Hours_Test predicate.

    Met iff average >= ``min_avg_hours_per_week`` AND
    (every week >= ``min_hours_every_week`` OR every month >= ``min_hours_every_month``).
    ``inp is None`` (no worked-hours data) -> ``met=False, reason='no_worked_hours_data'``.
    """
    if inp is None:
        return HoursTestResult(met=False, reason="no_worked_hours_data")

    # Average hours per week over the period. Guard against a zero-length period.
    period_weeks = inp.period_weeks if inp.period_weeks > 0 else len(inp.weeks)
    if period_weeks <= 0:
        return HoursTestResult(met=False, reason="no_worked_hours_data")

    avg_per_week = inp.total_hours / Decimal(period_weeks)
    if avg_per_week < bounds.min_avg_hours_per_week:
        return HoursTestResult(met=False, reason="avg_below_10h")

    every_week_ok = len(inp.weeks) > 0 and all(
        w >= bounds.min_hours_every_week for w in inp.weeks
    )
    every_month_ok = len(inp.months) > 0 and all(
        m >= bounds.min_hours_every_month for m in inp.months
    )

    if every_week_ok or every_month_ok:
        return HoursTestResult(met=True, reason=None)
    return HoursTestResult(met=False, reason="weekly_or_monthly_minimum_not_met")


async def aggregate_hours_test_input(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    evaluation_date: date,
) -> HoursTestInput | None:
    """Sum ``time_clock_entries.worked_minutes`` over the qualifying period.

    Buckets worked hours by ISO week ``(year, week)`` and by calendar month
    ``(year, month)``. Returns ``None`` when there are no completed entries with
    usable ``worked_minutes`` in the period (so the pure predicate records
    ``no_worked_hours_data`` rather than silently passing).
    """
    from app.modules.time_clock.models import TimeClockEntry

    period_start = evaluation_date - timedelta(days=QUALIFYING_PERIOD_DAYS)

    stmt = (
        select(TimeClockEntry.clock_in_at, TimeClockEntry.worked_minutes)
        .where(
            TimeClockEntry.staff_id == staff_id,
            TimeClockEntry.worked_minutes.is_not(None),
            TimeClockEntry.clock_in_at >= period_start,
            TimeClockEntry.clock_in_at < evaluation_date + timedelta(days=1),
        )
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return None

    week_buckets: dict[tuple[int, int], Decimal] = {}
    month_buckets: dict[tuple[int, int], Decimal] = {}
    total = Decimal("0")

    for clock_in_at, worked_minutes in rows:
        if worked_minutes is None:
            continue
        hours = (Decimal(int(worked_minutes)) / Decimal(60)).quantize(Decimal("0.01"))
        d = clock_in_at.date()
        iso_year, iso_week, _ = d.isocalendar()
        week_buckets[(iso_year, iso_week)] = (
            week_buckets.get((iso_year, iso_week), Decimal("0")) + hours
        )
        month_buckets[(d.year, d.month)] = (
            month_buckets.get((d.year, d.month), Decimal("0")) + hours
        )
        total += hours

    if total <= 0:
        return None

    period_weeks = max(1, QUALIFYING_PERIOD_DAYS // 7)
    return HoursTestInput(
        weeks=tuple(week_buckets.values()),
        months=tuple(month_buckets.values()),
        total_hours=total,
        period_weeks=period_weeks,
    )
