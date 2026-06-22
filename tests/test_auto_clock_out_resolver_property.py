"""Property-based tests for the auto-clock-out end-time resolver.

# Feature: auto-clock-out, Task 2.2 — resolver invariants

**Validates: Requirements 2.2, 2.3, 2.4, 2.5**

The pure function under test is
:func:`app.tasks.scheduled._resolve_auto_clock_out_end`. It resolves the
``clock_out_at`` timestamp for an auto-closed entry using a strict basis
hierarchy and then clamps the result to ``[clock_in_at, now]``:

    1. ``scheduled_end + grace``     (when a linked scheduled shift exists)
    2. fixed day's end ``+ grace``   (fixed working arrangement)
    3. ``clock_in_at + after_hours`` (safety-net cap, no schedule)

The function is pure and deterministic (all DB reads happen in the caller), so
it is exercised directly over many generated inputs. The four design
correctness properties pinned down here are:

* **Property 3 — End never before clock-in:** ``clock_out_at >= clock_in_at``.
* **Property 4 — End never in the future:** ``clock_out_at <= now``.
* **Property 5 — Basis hierarchy priority:** scheduled wins over fixed wins
  over the safety-net cap.
* **Property 6 — Grace applied:** for the scheduled/fixed bases the pre-clamp
  end equals the basis end plus exactly ``auto_clock_out_grace_minutes``.

Because the clamp to ``[clock_in_at, now]`` can mask the raw basis+grace value,
the strategies for Properties 5 and 6 are constructed so the pre-clamp end
deliberately falls inside ``[clock_in_at, now]`` (``now`` is placed at or after
the pre-clamp end and ``clock_in_at`` at or before it), so the asserted
relationship is the one actually produced by the resolver.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.tasks.scheduled import _resolve_auto_clock_out_end

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure, in-memory resolver.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

_UTC = st.just(timezone.utc)

# A timezone-aware UTC datetime in a sane, overflow-safe window. The window is
# kept well inside datetime.min/max so adding the largest timedeltas the
# strategies generate (≈ 48 days) can never overflow.
aware_dt = st.datetimes(
    min_value=datetime(2020, 1, 1, 0, 0, 0),
    max_value=datetime(2030, 1, 1, 0, 0, 0),
    timezones=_UTC,
)

grace_minutes_st = st.integers(min_value=0, max_value=240)
after_hours_st = st.integers(min_value=1, max_value=48)
fixed_end_minutes_st = st.integers(min_value=0, max_value=24 * 60 - 1)


# ---------------------------------------------------------------------------
# Strategy: arbitrary, fully-general inputs with now >= clock_in_at.
#
# An open entry is always observed at or after its clock-in, so `now` is placed
# at/after `clock_in_at`. Every basis (scheduled / fixed / cap) is exercised by
# letting both optional inputs be present or absent and unconstrained.
# ---------------------------------------------------------------------------
@st.composite
def general_inputs(draw):
    clock_in_at = draw(aware_dt)
    # now is some non-negative span after clock-in (up to ~40 days open).
    open_minutes = draw(st.integers(min_value=0, max_value=40 * 24 * 60))
    now = clock_in_at + timedelta(minutes=open_minutes)

    scheduled_end = draw(st.none() | aware_dt)
    fixed_end_minutes = draw(st.none() | fixed_end_minutes_st)
    after_hours = draw(after_hours_st)
    grace_minutes = draw(grace_minutes_st)
    return {
        "clock_in_at": clock_in_at,
        "now": now,
        "after_hours": after_hours,
        "grace_minutes": grace_minutes,
        "scheduled_end": scheduled_end,
        "fixed_end_minutes": fixed_end_minutes,
    }


# ---------------------------------------------------------------------------
# Property 3: End never before clock-in.
# Property 4: End never in the future.
# ---------------------------------------------------------------------------
class TestClampInvariants:
    """Properties 3 & 4 — the resolved end is always within [clock_in_at, now].

    **Validates: Requirements 2.5, 2.1**
    """

    @given(kw=general_inputs())
    @PBT_SETTINGS
    def test_end_never_before_clock_in(self, kw):
        """Property 3: ``clock_out_at >= clock_in_at`` for every basis.

        **Validates: Requirements 2.5**
        """
        end = _resolve_auto_clock_out_end(**kw)
        assert end >= kw["clock_in_at"]

    @given(kw=general_inputs())
    @PBT_SETTINGS
    def test_end_never_in_the_future(self, kw):
        """Property 4: ``clock_out_at <= now`` for every basis.

        **Validates: Requirements 2.1**
        """
        end = _resolve_auto_clock_out_end(**kw)
        assert end <= kw["now"]

    @given(kw=general_inputs())
    @PBT_SETTINGS
    def test_end_within_inclusive_window(self, kw):
        """Combined: the result always lands in the inclusive [clock_in, now].

        **Validates: Requirements 2.5, 2.1**
        """
        end = _resolve_auto_clock_out_end(**kw)
        assert kw["clock_in_at"] <= end <= kw["now"]


# ---------------------------------------------------------------------------
# Property 5: Basis hierarchy priority.
# Property 6: Grace applied (scheduled/fixed pre-clamp == basis end + grace).
#
# These two properties are tested together because the in-range generators that
# make Property 6's exact equality observable (no clamping) also reveal which
# basis was selected (Property 5).
# ---------------------------------------------------------------------------
class TestBasisHierarchyAndGrace:
    """Properties 5 & 6 — basis selection priority and grace application.

    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    @st.composite
    def _scheduled_in_range(draw):
        """Scheduled basis whose ``scheduled_end + grace`` lands in [clock_in, now].

        ``fixed_end_minutes`` is left free (often present) so a passing equality
        proves the scheduled basis is chosen *over* any fixed basis (priority),
        and ``after_hours`` is free so it also wins over the cap.
        """
        clock_in_at = draw(aware_dt)
        grace = draw(grace_minutes_st)
        # basis end (pre-clamp) sits at/after clock-in, within ~30 days.
        basis_offset = draw(st.integers(min_value=0, max_value=30 * 24 * 60))
        pre_clamp = clock_in_at + timedelta(minutes=basis_offset)
        scheduled_end = pre_clamp - timedelta(minutes=grace)
        # now is at/after the pre-clamp end so no high-side clamping occurs.
        now = pre_clamp + timedelta(minutes=draw(st.integers(0, 24 * 60)))
        return {
            "clock_in_at": clock_in_at,
            "now": now,
            "after_hours": draw(after_hours_st),
            "grace_minutes": grace,
            "scheduled_end": scheduled_end,
            "fixed_end_minutes": draw(st.none() | fixed_end_minutes_st),
            "_pre_clamp": pre_clamp,
        }

    @st.composite
    def _fixed_in_range(draw):
        """Fixed basis (no scheduled link) with the result inside [clock_in, now].

        ``clock_in_at`` is anchored to midnight UTC so ``day_start`` equals it,
        making the configured end deterministic and free of the overnight wrap
        (the wrap only triggers when ``fixed_end_minutes + grace == 0``, excluded
        here). ``after_hours`` is left free so a passing equality proves the
        fixed basis wins over the safety-net cap.
        """
        date = draw(
            st.dates(min_value=datetime(2020, 1, 1).date(),
                     max_value=datetime(2030, 1, 1).date())
        )
        clock_in_at = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)
        grace = draw(grace_minutes_st)
        # Avoid the only wrap case (end == clock_in) by ensuring end > clock_in.
        fixed_end_minutes = draw(
            fixed_end_minutes_st.filter(lambda m: m + grace >= 1)
        )
        pre_clamp = clock_in_at + timedelta(minutes=fixed_end_minutes + grace)
        now = pre_clamp + timedelta(minutes=draw(st.integers(0, 24 * 60)))
        return {
            "clock_in_at": clock_in_at,
            "now": now,
            "after_hours": draw(after_hours_st),
            "grace_minutes": grace,
            "scheduled_end": None,
            "fixed_end_minutes": fixed_end_minutes,
            "_pre_clamp": pre_clamp,
        }

    @st.composite
    def _cap_in_range(draw):
        """Safety-net cap basis (no scheduled, no fixed) inside [clock_in, now]."""
        clock_in_at = draw(aware_dt)
        after_hours = draw(after_hours_st)
        pre_clamp = clock_in_at + timedelta(hours=after_hours)
        now = pre_clamp + timedelta(minutes=draw(st.integers(0, 24 * 60)))
        return {
            "clock_in_at": clock_in_at,
            "now": now,
            "after_hours": after_hours,
            "grace_minutes": draw(grace_minutes_st),
            "scheduled_end": None,
            "fixed_end_minutes": None,
            "_pre_clamp": pre_clamp,
        }

    @given(kw=_scheduled_in_range())
    @PBT_SETTINGS
    def test_scheduled_basis_wins_and_applies_grace(self, kw):
        """Scheduled basis is selected over fixed/cap and adds exactly grace.

        Property 5 (priority) + Property 6 (grace): with both a scheduled_end
        and (often) a fixed_end present, the result equals
        ``scheduled_end + grace``.

        **Validates: Requirements 2.2, 2.3**
        """
        pre_clamp = kw.pop("_pre_clamp")
        end = _resolve_auto_clock_out_end(**kw)
        assert end == pre_clamp
        assert end == kw["scheduled_end"] + timedelta(minutes=kw["grace_minutes"])

    @given(kw=_fixed_in_range())
    @PBT_SETTINGS
    def test_fixed_basis_wins_over_cap_and_applies_grace(self, kw):
        """Fixed basis is selected over the cap and adds exactly grace.

        Property 5 (priority) + Property 6 (grace): with no scheduled link but a
        fixed end available, the result equals that day's configured end
        ``+ grace`` — independent of ``after_hours``.

        **Validates: Requirements 2.3**
        """
        pre_clamp = kw.pop("_pre_clamp")
        end = _resolve_auto_clock_out_end(**kw)
        assert end == pre_clamp
        # basis end == day-start + fixed_end_minutes; result == basis + grace.
        basis_end = kw["clock_in_at"] + timedelta(minutes=kw["fixed_end_minutes"])
        assert end == basis_end + timedelta(minutes=kw["grace_minutes"])

    @given(kw=_cap_in_range())
    @PBT_SETTINGS
    def test_cap_basis_used_when_no_schedule(self, kw):
        """Safety-net cap is used when neither scheduled nor fixed basis exists.

        Property 5 (cap branch): the result equals
        ``clock_in_at + after_hours`` (no grace is added to the cap).

        **Validates: Requirements 2.4**
        """
        pre_clamp = kw.pop("_pre_clamp")
        end = _resolve_auto_clock_out_end(**kw)
        assert end == pre_clamp
        assert end == kw["clock_in_at"] + timedelta(hours=kw["after_hours"])

    @given(
        clock_in_at=aware_dt,
        grace=grace_minutes_st,
        after_hours=after_hours_st,
        fixed_end_minutes=fixed_end_minutes_st,
        sched_offset=st.integers(min_value=0, max_value=30 * 24 * 60),
    )
    @PBT_SETTINGS
    def test_scheduled_present_ignores_fixed_and_cap(
        self, clock_in_at, grace, after_hours, fixed_end_minutes, sched_offset
    ):
        """Priority: a present scheduled_end is used even when a fixed end exists.

        The pre-clamp scheduled end is placed inside [clock_in, now] so the
        equality is observable; the result must match the scheduled basis and
        not the fixed or cap bases.

        **Validates: Requirements 2.2**
        """
        pre_clamp = clock_in_at + timedelta(minutes=sched_offset)
        scheduled_end = pre_clamp - timedelta(minutes=grace)
        now = pre_clamp + timedelta(hours=1)
        end = _resolve_auto_clock_out_end(
            clock_in_at=clock_in_at,
            now=now,
            after_hours=after_hours,
            grace_minutes=grace,
            scheduled_end=scheduled_end,
            fixed_end_minutes=fixed_end_minutes,
        )
        assert end == scheduled_end + timedelta(minutes=grace)
