"""Pure-function pay-period rolling algorithm (G5 + G14).

Implements task B4a from ``.kiro/specs/staff-management-p4/tasks.md``.
The single public entry point :func:`compute_next_period_dates` returns
the ``(start_date, end_date, pay_date)`` triple for the next pay
period given the org's cadence + anchor + offset settings and the
existing latest-end watermark.

This module is deliberately side-effect free — no DB, no Redis, no
clock reads. The caller (the ``roll_pay_periods`` daily task at
:mod:`app.tasks.scheduled` and the termination flow at
:mod:`app.modules.payslips.termination`) owns its own ``today`` and
``latest_end`` reads. That makes the algorithm trivial to property-
test (G5 verify in :mod:`tests.unit.test_period_rolling`).

Algorithm (per design §4.2.1):

  weekly:
    - When ``latest_end is None``: start = the day in the current
      week whose ISO weekday matches ``anchor_day`` (1=Mon … 7=Sun).
    - Else: start = ``latest_end + 1 day``.
    - end = ``start + 6 days``.

  fortnightly:
    - When ``latest_end is None``: same anchor logic as weekly.
    - Else: start = ``latest_end + 1 day``.
    - end = ``start + 13 days``.

  monthly:
    - When ``latest_end is None``: start = ``anchor_day`` of the
      current month, clamped to the month length. ``anchor_day=29``
      in February → clamped to 28 (or 29 in a leap year).
    - Else: start = ``anchor_day`` of the month after
      ``latest_end``'s month, clamped to the month length.
    - end = day before the next anchor (i.e. ``next_anchor - 1
      day``), so consecutive periods chain end-to-start.

  pay_date:
    - ``end + pay_date_offset_days`` for every cadence.
    - Roll forward to the next weekday when it lands on Sat/Sun.
      Public holidays are NOT skipped — that would require a DB
      read, and admin can manually adjust pay_date if it lands on
      a PH (deferred to Phase 5 if it ever becomes a pain point).

G14 — cadence change: changing
``organisations.pay_period_cadence`` does NOT retroactively merge or
extend existing periods. The next call uses ``latest_end + 1`` with
the new cadence rules. Existing finalised/paid periods stay as-is.

**Validates: Requirements R1.5, R1.6 — Staff Management Phase 4 task B4a.**
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

__all__ = [
    "compute_next_period_dates",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _add_months(d: date, n: int) -> date:
    """Return the date N months after ``d`` with day clamped to the
    target month's actual length (handles 28/29/30/31 boundaries).

    Examples:
      ``_add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)``
      ``_add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)``
    """
    m_total = d.month - 1 + n
    y = d.year + m_total // 12
    m = m_total % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def _clamp_day_in_month(year: int, month: int, day: int) -> date:
    """Return ``date(year, month, day)`` with ``day`` clamped to the
    month's actual length. Used for ``anchor_day=31`` in 30-day
    months and February.
    """
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(day, 1), last))


def _next_business_day(d: date) -> date:
    """Roll forward through Sat/Sun to the next Mon–Fri (G5).

    ``date.isoweekday()`` returns 1=Mon … 7=Sun, so a value > 5
    means weekend. We bump one day at a time so a date already on
    Friday is unchanged.
    """
    while d.isoweekday() > 5:
        d += timedelta(days=1)
    return d


def _anchor_start_for_first_period(
    *, cadence: str, anchor_day: int, today: date,
) -> date:
    """Compute the start date for the very first period when an org
    has no history (``latest_end is None``).

    For weekly / fortnightly cadences the anchor_day is an ISO
    weekday (1=Mon … 7=Sun) — we step backward from ``today`` to
    the most recent matching weekday. So an org configured for
    "weeks starting Monday" that runs the daily task on a Wednesday
    gets a start date of that week's Monday.

    For monthly cadence the anchor_day is a day-of-month; we use
    that day in ``today``'s month, clamped to month length.
    """
    if cadence in ("weekly", "fortnightly"):
        # Map anchor_day to ISO weekday (1..7); guard out-of-range.
        target_weekday = max(1, min(7, int(anchor_day)))
        diff = today.isoweekday() - target_weekday
        if diff < 0:
            # The anchor weekday is later in this same week than today
            # — but we want the CURRENT week's anchor, which is the
            # most recent past instance. With ISO Mon=1, if today is
            # Wed (3) and anchor is Sun (7), the diff is -4 — go back
            # 7 + (-4) = 3 days to last Sunday. But that's PAST
            # today's week (Mon-Sun). The clearer rule: anchor_day in
            # the current Mon→Sun week, not "most recent". Concretely,
            # for weekly with anchor=1 (Mon) and today=Wed, the desired
            # start is THIS Monday (diff=2 → step back 2 days). For
            # anchor=7 (Sun) and today=Wed, the desired start is the
            # PRIOR Sunday (the start of the rolling week ending Sat).
            # We resolve by stepping back diff days when diff>=0, and
            # stepping back diff+7 days when diff<0.
            diff += 7
        return today - timedelta(days=diff)
    # monthly
    return _clamp_day_in_month(today.year, today.month, int(anchor_day))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_next_period_dates(
    *,
    cadence: str,
    anchor_day: int,
    pay_date_offset_days: int,
    latest_end: date | None,
    today: date,
) -> tuple[date, date, date]:
    """Return ``(start_date, end_date, pay_date)`` for the next pay period.

    Args:
      cadence: ``'weekly'`` | ``'fortnightly'`` | ``'monthly'``.
      anchor_day: ISO weekday for weekly/fortnightly (1=Mon … 7=Sun);
        day-of-month for monthly (1..31, clamped at month-end).
      pay_date_offset_days: business days added to ``end_date`` to get
        ``pay_date``. Then rolled forward Sat/Sun → next weekday.
      latest_end: ``MAX(pay_periods.end_date)`` for the org, or
        ``None`` when the org has no history yet.
      today: caller-supplied "now" for first-period anchoring. Use
        ``date.today()`` in production; tests can pass deterministic
        values to assert anchor-day behaviour.

    Raises:
      ValueError: when ``cadence`` is unknown.
    """
    cadence_normalised = (cadence or "").lower().strip()

    if cadence_normalised == "weekly":
        if latest_end is None:
            start = _anchor_start_for_first_period(
                cadence=cadence_normalised,
                anchor_day=anchor_day,
                today=today,
            )
        else:
            start = latest_end + timedelta(days=1)
        end = start + timedelta(days=6)

    elif cadence_normalised == "fortnightly":
        if latest_end is None:
            start = _anchor_start_for_first_period(
                cadence=cadence_normalised,
                anchor_day=anchor_day,
                today=today,
            )
        else:
            start = latest_end + timedelta(days=1)
        end = start + timedelta(days=13)

    elif cadence_normalised == "monthly":
        if latest_end is None:
            start = _clamp_day_in_month(
                today.year, today.month, int(anchor_day),
            )
        else:
            # Step into the month following ``latest_end``, then anchor
            # to ``anchor_day`` (clamped). This means cadence flips
            # from weekly→monthly land on the next anchor without
            # retroactively merging the existing weekly periods (G14).
            after = latest_end + timedelta(days=1)
            start = _clamp_day_in_month(
                after.year, after.month, int(anchor_day),
            )
            # Edge case: when ``after`` is before the anchor day in
            # its month (e.g. latest_end=2026-06-15, anchor=20 →
            # after=2026-06-16, start=2026-06-20). When ``after`` is
            # after the anchor in its month (latest_end=2026-06-25,
            # anchor=20 → after=2026-06-26 → naive clamp gives
            # 2026-06-20 which is BEFORE latest_end). In that case
            # we move into the next month.
            if start <= latest_end:
                next_month = _add_months(after, 1)
                start = _clamp_day_in_month(
                    next_month.year, next_month.month, int(anchor_day),
                )
        # End is the day before the next anchor in the following month.
        next_anchor_month = _add_months(start, 1)
        next_anchor = _clamp_day_in_month(
            next_anchor_month.year,
            next_anchor_month.month,
            int(anchor_day),
        )
        end = next_anchor - timedelta(days=1)

    else:
        raise ValueError(f"Unknown cadence: {cadence!r}")

    raw_pay = end + timedelta(days=int(pay_date_offset_days))
    pay_date = _next_business_day(raw_pay)
    return start, end, pay_date
