"""Property-based test: the Employee Portal lockout state machine.

# Feature: organisation-employee-portal, Property 14: Lockout state machine

**Validates: Requirements 6.5, 6.6**

The portal login flow leans on a small, pure lockout state machine in
``app/modules/employee_portal/auth.py`` — :func:`is_locked`,
:func:`record_failed_attempt`, and :func:`reset_lockout`. The state is the
pair ``(failed_attempts, locked_until)`` and every helper takes an injectable
``now`` so the time-dependent behaviour is fully deterministic under test
(no clock, no database, no I/O).

The specification fixes two behaviours this test pins down:

* **R6.5** — when a Portal_User reaches 5 *consecutive* failed login attempts
  the account is locked for 15 minutes, and every attempt during that window
  is rejected as locked. Concretely: the 5th consecutive failure sets
  ``locked_until = now + 15min``; ``is_locked`` is ``True`` for the whole
  window; and a failed attempt arriving while locked does not mutate the
  state (the lock neither extends nor the count climbs).
* **R6.6** — once the 15-minute window elapses the consecutive failed-attempt
  count resets to 0 and login attempts are accepted again; a successful login
  unconditionally clears the lock via :func:`reset_lockout`.

All three helpers are pure and side-effect-free, so they are exercised
directly over >= 100 generated examples with an injected ``now``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.employee_portal.auth import (
    LOCKOUT_MINUTES,
    LOCKOUT_THRESHOLD,
    is_locked,
    record_failed_attempt,
    reset_lockout,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure, in-memory state machine.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# A fixed, timezone-aware anchor so generated "now" values are deterministic.
_BASE_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# Offsets (in seconds) used to probe instants strictly inside and strictly
# outside the 15-minute lock window.
_LOCK_SECONDS = LOCKOUT_MINUTES * 60


def _apply_failures(count: int, now: datetime) -> tuple[int, datetime | None]:
    """Apply ``count`` consecutive failures from the clean state at ``now``.

    Returns the resulting ``(failed_attempts, locked_until)`` pair. ``now`` is
    held fixed across the streak so the failures are genuinely consecutive
    within one instant (the realistic worst case for a burst of bad guesses).
    """
    failed_attempts, locked_until = 0, None
    for _ in range(count):
        failed_attempts, locked_until = record_failed_attempt(
            failed_attempts, locked_until, now
        )
    return failed_attempts, locked_until


# ---------------------------------------------------------------------------
# Property 14: Lockout state machine
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(
    pre_failures=st.integers(min_value=0, max_value=LOCKOUT_THRESHOLD - 1),
)
def test_below_threshold_never_locks(pre_failures: int) -> None:
    """Fewer than 5 consecutive failures never produces an active lock.

    Up to and including the 4th consecutive failure the account stays unlocked
    and ``locked_until`` is never set (R6.5 — only the 5th failure locks).

    **Validates: Requirements 6.5**
    """
    failed_attempts, locked_until = _apply_failures(pre_failures, _BASE_NOW)

    assert failed_attempts == pre_failures
    assert locked_until is None
    assert is_locked(failed_attempts, locked_until, _BASE_NOW) is False


@PBT_SETTINGS
@given(
    within=st.integers(min_value=0, max_value=_LOCK_SECONDS - 1),
)
def test_fifth_consecutive_failure_locks_for_fifteen_minutes(within: int) -> None:
    """The 5th consecutive failure locks for exactly 15 minutes (R6.5).

    ``locked_until`` is set to ``now + 15min`` and ``is_locked`` returns
    ``True`` for every instant strictly inside the window.

    **Validates: Requirements 6.5**
    """
    failed_attempts, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)

    # The 5th failure pushed the count to the threshold and armed the lock.
    assert failed_attempts == LOCKOUT_THRESHOLD
    assert locked_until == _BASE_NOW + timedelta(minutes=LOCKOUT_MINUTES)

    # Any instant strictly inside the window is reported as locked.
    instant = _BASE_NOW + timedelta(seconds=within)
    assert is_locked(failed_attempts, locked_until, instant) is True


@PBT_SETTINGS
@given(
    within=st.integers(min_value=0, max_value=_LOCK_SECONDS - 1),
)
def test_attempts_during_active_lock_do_not_change_state(within: int) -> None:
    """A failed attempt arriving during an active lock is a no-op (R6.5).

    The lock must not be extended and the count must not climb while locked —
    the state after the in-window attempt is identical to the state before it.

    **Validates: Requirements 6.5**
    """
    failed_attempts, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)

    instant = _BASE_NOW + timedelta(seconds=within)
    assert is_locked(failed_attempts, locked_until, instant) is True

    new_attempts, new_locked_until = record_failed_attempt(
        failed_attempts, locked_until, instant
    )

    assert new_attempts == failed_attempts
    assert new_locked_until == locked_until


@PBT_SETTINGS
@given(
    after=st.integers(min_value=0, max_value=7 * 24 * 60 * 60),
)
def test_count_resets_after_window_elapses(after: int) -> None:
    """Once the 15-minute window elapses the count resets and login resumes.

    At or after ``locked_until`` the lock is no longer active (R6.6); the next
    failed attempt starts a fresh streak from 1 rather than continuing the old
    count, and the account is accepted (not locked) again.

    **Validates: Requirements 6.6**
    """
    failed_attempts, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)

    # An instant at or after the window's end: the lock has elapsed.
    elapsed = _BASE_NOW + timedelta(seconds=_LOCK_SECONDS + after)
    assert is_locked(failed_attempts, locked_until, elapsed) is False

    # A new failure after the window starts a fresh streak from 1.
    next_attempts, next_locked_until = record_failed_attempt(
        failed_attempts, locked_until, elapsed
    )
    assert next_attempts == 1
    assert next_locked_until is None
    assert is_locked(next_attempts, next_locked_until, elapsed) is False


@PBT_SETTINGS
@given(
    failed_attempts=st.integers(min_value=0, max_value=50),
    locked_offset=st.integers(min_value=-_LOCK_SECONDS, max_value=_LOCK_SECONDS),
    locked_set=st.booleans(),
)
def test_reset_lockout_always_clears_state(
    failed_attempts: int, locked_offset: int, locked_set: bool
) -> None:
    """A successful login unconditionally clears the lockout state (R6.6).

    Regardless of the prior count or any ``locked_until`` (past or future),
    ``reset_lockout`` returns the cleared state ``(0, None)`` and the account
    is not locked thereafter.

    **Validates: Requirements 6.6**
    """
    locked_until = (
        _BASE_NOW + timedelta(seconds=locked_offset) if locked_set else None
    )

    new_attempts, new_locked_until = reset_lockout(
        failed_attempts, locked_until, _BASE_NOW
    )

    assert new_attempts == 0
    assert new_locked_until is None
    assert is_locked(new_attempts, new_locked_until, _BASE_NOW) is False


@PBT_SETTINGS
@given(
    n=st.integers(min_value=LOCKOUT_THRESHOLD, max_value=20),
    within=st.integers(min_value=0, max_value=_LOCK_SECONDS - 1),
)
def test_repeated_failures_keep_account_locked_without_extending(
    n: int, within: int
) -> None:
    """Failures beyond the 5th, while locked, leave the lock window unchanged.

    Hammering a locked account does not push ``locked_until`` further out: the
    window stays anchored to the instant of the 5th consecutive failure (R6.5).

    **Validates: Requirements 6.5**
    """
    # First lock the account with exactly THRESHOLD failures at the base time.
    failed_attempts, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)
    armed_until = locked_until

    # Now pile on extra failures within the same active window.
    instant = _BASE_NOW + timedelta(seconds=within)
    for _ in range(n - LOCKOUT_THRESHOLD):
        failed_attempts, locked_until = record_failed_attempt(
            failed_attempts, locked_until, instant
        )

    # The lock end is still the original armed instant — never extended.
    assert locked_until == armed_until
    assert is_locked(failed_attempts, locked_until, instant) is True


# ---------------------------------------------------------------------------
# Worked unit examples — concrete anchors for each branch of the machine.
# ---------------------------------------------------------------------------


def test_four_failures_then_success_resets() -> None:
    """Four failures then a success clears the streak (R6.6)."""
    failed_attempts, locked_until = _apply_failures(4, _BASE_NOW)
    assert failed_attempts == 4
    assert is_locked(failed_attempts, locked_until, _BASE_NOW) is False

    cleared = reset_lockout(failed_attempts, locked_until, _BASE_NOW)
    assert cleared == (0, None)


def test_exact_window_boundary_is_not_locked() -> None:
    """At exactly now + 15min the lock has elapsed (half-open window, R6.6)."""
    _, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)
    boundary = _BASE_NOW + timedelta(minutes=LOCKOUT_MINUTES)
    assert is_locked(LOCKOUT_THRESHOLD, locked_until, boundary) is False


def test_one_second_before_boundary_is_locked() -> None:
    """One second before the window end the account is still locked (R6.5)."""
    _, locked_until = _apply_failures(LOCKOUT_THRESHOLD, _BASE_NOW)
    almost = _BASE_NOW + timedelta(minutes=LOCKOUT_MINUTES) - timedelta(seconds=1)
    assert is_locked(LOCKOUT_THRESHOLD, locked_until, almost) is True
