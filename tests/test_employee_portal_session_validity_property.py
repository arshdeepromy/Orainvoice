"""Property-based test: the employee portal session validity window.

# Feature: organisation-employee-portal, Property 16: Session validity window

**Validates: Requirements 6.10**

R6.10 states: *WHILE an Employee_Portal_Session has been inactive for more than
30 minutes OR has existed for more than 12 hours since establishment, THE
Employee_Portal SHALL treat the session as invalid AND SHALL require
re-authentication.*

The pure predicate
``app.modules.employee_portal.services.session_service.is_session_valid`` makes
that decision from three timestamps — ``created_at`` (establishment),
``last_seen_at`` (last activity), and ``now`` — with no I/O or side effects, so
it can be exhaustively property-tested in isolation.

A session is valid **iff both** windows hold:

* **Absolute** — ``now - created_at <= 12h`` (existed no longer than 12 hours), and
* **Idle**     — ``now - last_seen_at <= 30 min`` (inactive no longer than 30 minutes).

The exact boundaries (precisely 12h / precisely 30 min) are treated as still
valid; *strictly greater* than either bound is invalid, matching R6.10's "more
than" wording. Crossing **either** bound alone is sufficient to invalidate.

The assertions below use an **independent reference oracle** that recomputes the
verdict from raw elapsed seconds (43 200 s = 12h, 1 800 s = 30 min) rather than
reusing the implementation's ``timedelta`` constants, so the test does not
merely echo the code under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.employee_portal.services.session_service import (
    is_session_valid,
)

# ---------------------------------------------------------------------------
# Independent reference oracle — raw-seconds restatement of R6.10. Deliberately
# expressed with literal second thresholds (not the implementation's timedelta
# constants) so the property checks behaviour, not a copy of the code.
# ---------------------------------------------------------------------------

_ABSOLUTE_LIMIT_SECONDS = 12 * 60 * 60  # 12 hours -> 43_200 s
_IDLE_LIMIT_SECONDS = 30 * 60  # 30 minutes -> 1_800 s


def _oracle_valid(created_at: datetime, last_seen_at: datetime, now: datetime) -> bool:
    """Reference verdict: valid iff within BOTH the 12h and 30-min bounds."""
    absolute_elapsed = (now - created_at).total_seconds()
    idle_elapsed = (now - last_seen_at).total_seconds()
    within_absolute = absolute_elapsed <= _ABSOLUTE_LIMIT_SECONDS
    within_idle = idle_elapsed <= _IDLE_LIMIT_SECONDS
    return within_absolute and within_idle


# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure in-memory predicate.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# A fixed reference "now". The session timestamps are derived from this by
# subtracting generated elapsed-second offsets, so absolute/idle ages are
# controlled directly and span inside *and* outside both bounds.
_NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)

# Elapsed-seconds offsets that straddle every interesting point: well inside,
# the exact boundary (still valid), just past the boundary (invalid), far past,
# and slightly negative (clock skew where a timestamp is marginally ahead of
# ``now`` — still "within" since elapsed is negative). Boundaries for both the
# 30-min idle window and the 12h absolute window are seeded explicitly so they
# are always hit, not left to chance.
_elapsed_seconds = st.one_of(
    st.integers(min_value=-120, max_value=200_000),
    st.sampled_from(
        [
            -1,
            0,
            1,
            1_799,  # just inside idle bound
            1_800,  # exactly idle bound (valid)
            1_801,  # just past idle bound (invalid)
            3_600,  # 1h
            43_199,  # just inside absolute bound
            43_200,  # exactly absolute bound (valid)
            43_201,  # just past absolute bound (invalid)
            86_400,  # 24h
        ]
    ),
)


# ---------------------------------------------------------------------------
# Property 16: Session validity window
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(created_ago=_elapsed_seconds, idle_ago=_elapsed_seconds)
def test_session_validity_window(created_ago, idle_ago):
    """is_session_valid holds iff within BOTH the 12h and 30-min bounds (R6.10).

    **Validates: Requirements 6.10**
    """
    created_at = _NOW - timedelta(seconds=created_ago)
    last_seen_at = _NOW - timedelta(seconds=idle_ago)

    actual = is_session_valid(created_at, last_seen_at, _NOW)
    expected = _oracle_valid(created_at, last_seen_at, _NOW)

    # 1. The predicate matches the independent oracle on every generated triple.
    assert actual == expected

    # 2. Crossing EITHER bound alone is sufficient to invalidate (R6.10's OR).
    over_absolute = created_ago > _ABSOLUTE_LIMIT_SECONDS
    over_idle = idle_ago > _IDLE_LIMIT_SECONDS
    if over_absolute or over_idle:
        assert actual is False
    else:
        # Within both bounds (boundaries inclusive) => valid.
        assert actual is True


# ---------------------------------------------------------------------------
# Worked unit examples — concrete anchors for each branch and boundary.
# ---------------------------------------------------------------------------


def test_fresh_session_is_valid():
    """A just-created, just-seen session is valid."""
    assert is_session_valid(_NOW, _NOW, _NOW) is True


def test_exact_idle_boundary_is_valid():
    """Inactive for exactly 30 minutes is still valid (boundary inclusive)."""
    last_seen = _NOW - timedelta(minutes=30)
    assert is_session_valid(_NOW, last_seen, _NOW) is True


def test_just_past_idle_boundary_is_invalid():
    """Inactive for 30 min + 1s is invalid (idle window exceeded)."""
    last_seen = _NOW - timedelta(minutes=30, seconds=1)
    assert is_session_valid(_NOW, last_seen, _NOW) is False


def test_exact_absolute_boundary_is_valid():
    """Existed for exactly 12 hours (and recently active) is still valid."""
    created = _NOW - timedelta(hours=12)
    last_seen = _NOW - timedelta(minutes=1)
    assert is_session_valid(created, last_seen, _NOW) is True


def test_just_past_absolute_boundary_is_invalid():
    """Existed for 12h + 1s is invalid even if recently active."""
    created = _NOW - timedelta(hours=12, seconds=1)
    last_seen = _NOW - timedelta(seconds=5)
    assert is_session_valid(created, last_seen, _NOW) is False


def test_idle_alone_invalidates_within_absolute():
    """Within the 12h absolute window but idle > 30 min => invalid."""
    created = _NOW - timedelta(hours=1)
    last_seen = _NOW - timedelta(minutes=31)
    assert is_session_valid(created, last_seen, _NOW) is False


def test_absolute_alone_invalidates_within_idle():
    """Recently active but established > 12h ago => invalid."""
    created = _NOW - timedelta(hours=13)
    last_seen = _NOW - timedelta(seconds=10)
    assert is_session_valid(created, last_seen, _NOW) is False
