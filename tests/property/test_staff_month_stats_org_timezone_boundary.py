"""Property-based test for the org-timezone month boundary helper.

Covers task **2.6** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 5: This_Month boundary is evaluated in the org timezone**

*For any* organisation timezone and *for any* candidate timestamp ``t``,
``org_month_bounds_utc(org_tz_name, now=now)`` SHALL return a half-open
UTC window ``[month_start_utc, month_end_utc)`` such that ``t`` falls
inside the window **if and only if** ``t``, when converted to the org
timezone, lies in the same calendar ``(year, month)`` as ``now``
converted to the org timezone. This is the meaning of "the current
calendar month evaluated in the organisation timezone" (R11.7).

**Feature: staff-redesign, Property 5**

**Validates: Requirements 11.7**

Unlike the other staff-redesign property tests, ``org_month_bounds_utc``
is a PURE function — it takes an org timezone name and an injectable
``now`` and returns a ``(start, end)`` UTC tuple with no database access.
The test therefore runs entirely in-process: Hypothesis generates a real
IANA timezone, a timezone-aware UTC ``now``, and candidate timestamps
clustered near the local month boundary (where off-by-one timezone bugs
hide), then checks inclusion against an independent reference predicate.

Run via: ``docker compose exec -T app python -m pytest \
tests/property/test_staff_month_stats_org_timezone_boundary.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.modules.staff.service import org_month_bounds_utc


# ---------------------------------------------------------------------------
# Hypothesis configuration
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(max_examples=100, deadline=None)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A spread of IANA zones covering whole-hour, half-hour, three-quarter-hour
# (Pacific/Chatham), and the prime-meridian / DST-observing cases. Each
# exercises a different month-boundary offset from UTC.
_VALID_TIMEZONES = [
    "Pacific/Auckland",
    "UTC",
    "America/New_York",
    "Asia/Kolkata",
    "Europe/London",
    "Australia/Sydney",
    "America/Los_Angeles",
    "Pacific/Chatham",
]

_tz_strategy = st.sampled_from(_VALID_TIMEZONES)

# ``now`` anywhere in a multi-year range so DST transitions and varying
# month lengths (28/29/30/31 days) are all reachable.
_now_strategy = st.datetimes(
    min_value=datetime(2023, 1, 1),
    max_value=datetime(2027, 12, 31, 23, 59, 59),
).map(lambda d: d.replace(tzinfo=timezone.utc))

# Candidate offsets (in minutes) relative to ``now``. We bias toward
# values near +/- a month so timestamps land close to the local month
# boundary, where timezone-conversion off-by-one errors surface; a few
# large offsets keep clearly-outside cases represented.
_offset_minutes_strategy = st.one_of(
    st.integers(min_value=-45 * 24 * 60, max_value=45 * 24 * 60),
    st.integers(min_value=-200 * 24 * 60, max_value=200 * 24 * 60),
)


# ---------------------------------------------------------------------------
# Reference predicate
# ---------------------------------------------------------------------------


def _in_org_month(t: datetime, now: datetime, tz: ZoneInfo) -> bool:
    """Independent reference: ``t`` is in the org-tz calendar month of
    ``now`` iff their (year, month) match once both are viewed in ``tz``."""
    local_t = t.astimezone(tz)
    local_now = now.astimezone(tz)
    return (local_t.year, local_t.month) == (local_now.year, local_now.month)


# ===========================================================================
# Property 5 — org-timezone month boundary
# ===========================================================================


class TestOrgTimezoneMonthBoundary:
    """**Feature: staff-redesign, Property 5**

    The ``[month_start_utc, month_end_utc)`` window from
    ``org_month_bounds_utc`` includes a timestamp exactly when that
    timestamp shares the org-timezone calendar month of ``now``.

    **Validates: Requirements 11.7**
    """

    @PBT_SETTINGS
    @given(
        tz_name=_tz_strategy,
        now=_now_strategy,
        offsets=st.lists(_offset_minutes_strategy, min_size=1, max_size=8),
    )
    def test_inclusion_matches_org_tz_calendar_month(
        self,
        tz_name: str,
        now: datetime,
        offsets: list[int],
    ) -> None:
        tz = ZoneInfo(tz_name)
        month_start_utc, month_end_utc = org_month_bounds_utc(tz_name, now=now)

        # Boundaries are timezone-aware UTC and form a non-empty window.
        assert month_start_utc.tzinfo is not None
        assert month_end_utc.tzinfo is not None
        assert month_start_utc < month_end_utc

        # ``now`` itself always falls inside its own month window.
        assert month_start_utc <= now < month_end_utc

        # The window endpoints land on a local month boundary (day 1, 00:00).
        local_start = month_start_utc.astimezone(tz)
        assert (local_start.day, local_start.hour, local_start.minute) == (1, 0, 0)

        for off in offsets:
            t = now + timedelta(minutes=off)
            in_window = month_start_utc <= t < month_end_utc
            expected = _in_org_month(t, now, tz)
            assert in_window is expected, (
                f"tz={tz_name} now={now.isoformat()} "
                f"t={t.isoformat()} in_window={in_window} expected={expected} "
                f"window=[{month_start_utc.isoformat()}, "
                f"{month_end_utc.isoformat()})"
            )

    @PBT_SETTINGS
    @given(now=_now_strategy)
    def test_invalid_zone_name_falls_back_to_utc(self, now: datetime) -> None:
        """A bad/invalid zone name behaves exactly like UTC (R11.7)."""
        bad_start, bad_end = org_month_bounds_utc(
            "Not/AReal_Zone", now=now,
        )
        utc_start, utc_end = org_month_bounds_utc("UTC", now=now)
        assert bad_start == utc_start
        assert bad_end == utc_end
