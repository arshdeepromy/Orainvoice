"""Property tests for match engine — validates invariants across random inputs.

Uses Hypothesis to verify that for all valid combinations of clock entries
and match settings, the match engine produces results within bounds and
honours policy semantics.

**Validates: Requirements 8.1, 8.2**
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.modules.timesheets.match_engine import (
    ClockEntryData,
    MatchSettings,
    ScheduleEntryData,
    match_clock_to_roster,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def clock_entries(draw):
    """Strategy for valid clock entries within a single day."""
    hour = draw(st.integers(min_value=0, max_value=23))
    minute = draw(st.integers(min_value=0, max_value=59))
    duration = draw(st.integers(min_value=1, max_value=720))  # 1 min to 12 hours
    clock_in = datetime(2024, 6, 10, hour, minute)
    clock_out = clock_in + timedelta(minutes=duration)
    return ClockEntryData(
        id=uuid4(),
        clock_in_at=clock_in,
        clock_out_at=clock_out,
        worked_minutes=duration,
    )


@st.composite
def match_settings(draw):
    """Strategy for valid match settings covering all policy/rounding combos."""
    policy = draw(st.sampled_from(["pay_actual", "round_to_roster", "actual_rounded"]))
    rounding = draw(st.sampled_from([1, 5, 10, 15, 30]))
    direction = draw(st.sampled_from(["nearest", "up", "down"]))
    early = draw(st.integers(min_value=0, max_value=30))
    late = draw(st.integers(min_value=0, max_value=30))
    return MatchSettings(
        match_policy=policy,
        clock_rounding_minutes=rounding,
        clock_rounding_direction=direction,
        early_grace_minutes=early,
        late_grace_minutes=late,
    )


# ---------------------------------------------------------------------------
# Property 1: matched_minutes is bounded [0, 1440]
# ---------------------------------------------------------------------------


@given(clock=clock_entries(), settings=match_settings())
@h_settings(max_examples=100, deadline=None)
def test_matched_minutes_bounded(clock, settings):
    """For all valid inputs, matched_minutes >= 0 and <= 1440 (24h).

    **Validates: Requirements 8.1, 8.2**
    """
    result = match_clock_to_roster(clock, [], settings)
    assert 0 <= result.matched_minutes <= 1440, (
        f"matched_minutes={result.matched_minutes} out of [0, 1440] bounds"
    )


# ---------------------------------------------------------------------------
# Property 2: pay_actual returns raw_minutes when unmatched
# ---------------------------------------------------------------------------


@given(clock=clock_entries(), settings=match_settings())
@h_settings(max_examples=100, deadline=None)
def test_pay_actual_returns_raw(clock, settings):
    """If pay_actual, matched_minutes == raw_minutes (when unmatched — no schedules).

    **Validates: Requirements 8.1**
    """
    s = MatchSettings(
        match_policy="pay_actual",
        clock_rounding_minutes=settings.clock_rounding_minutes,
        clock_rounding_direction=settings.clock_rounding_direction,
        early_grace_minutes=settings.early_grace_minutes,
        late_grace_minutes=settings.late_grace_minutes,
    )
    result = match_clock_to_roster(clock, [], s)
    assert result.matched_minutes == clock.worked_minutes, (
        f"pay_actual should return raw worked_minutes={clock.worked_minutes}, "
        f"got matched_minutes={result.matched_minutes}"
    )
