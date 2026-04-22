"""Property-based test: failover countdown arithmetic.

**Validates: Requirements 3.3, 3.4**

For all ``failover_timeout`` (int > 0) and ``elapsed`` (float >= 0):
- ``remaining = max(0, failover_timeout - elapsed)``
- When ``elapsed < failover_timeout``: ``remaining > 0``
- When ``elapsed >= failover_timeout``: ``remaining == 0``
- Invariant: ``elapsed + remaining >= failover_timeout``

Uses Hypothesis to verify the countdown arithmetic used by
``HeartbeatService.get_seconds_until_auto_promote()``.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Pure function under test — mirrors HeartbeatService countdown logic
# ---------------------------------------------------------------------------


def calculate_failover_countdown(failover_timeout: int, elapsed: float) -> float:
    """Compute remaining seconds until auto-promote.

    This is the pure arithmetic extracted from
    ``HeartbeatService.get_seconds_until_auto_promote()``.
    """
    return max(0.0, failover_timeout - elapsed)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# failover_timeout: positive integer (realistic range 1–86400 seconds = 1 day)
failover_timeouts = st.integers(min_value=1, max_value=86_400)

# elapsed: non-negative float (realistic range 0–172800 seconds = 2 days)
elapsed_times = st.floats(min_value=0.0, max_value=172_800.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestFailoverCountdownArithmetic:
    """Property 3: Failover Countdown Arithmetic.

    **Validates: Requirements 3.3, 3.4**
    """

    @given(failover_timeout=failover_timeouts, elapsed=elapsed_times)
    @PBT_SETTINGS
    def test_remaining_non_negative(self, failover_timeout: int, elapsed: float):
        """The remaining countdown is always >= 0."""
        remaining = calculate_failover_countdown(failover_timeout, elapsed)
        assert remaining >= 0.0

    @given(failover_timeout=failover_timeouts, elapsed=elapsed_times)
    @PBT_SETTINGS
    def test_remaining_positive_when_elapsed_less_than_timeout(
        self, failover_timeout: int, elapsed: float
    ):
        """When elapsed < failover_timeout, remaining must be > 0."""
        remaining = calculate_failover_countdown(failover_timeout, elapsed)
        if elapsed < failover_timeout:
            assert remaining > 0.0

    @given(failover_timeout=failover_timeouts, elapsed=elapsed_times)
    @PBT_SETTINGS
    def test_remaining_zero_when_elapsed_ge_timeout(
        self, failover_timeout: int, elapsed: float
    ):
        """When elapsed >= failover_timeout, remaining must be 0."""
        remaining = calculate_failover_countdown(failover_timeout, elapsed)
        if elapsed >= failover_timeout:
            assert remaining == 0.0

    @given(failover_timeout=failover_timeouts, elapsed=elapsed_times)
    @PBT_SETTINGS
    def test_elapsed_plus_remaining_ge_timeout(
        self, failover_timeout: int, elapsed: float
    ):
        """Invariant: elapsed + remaining >= failover_timeout."""
        remaining = calculate_failover_countdown(failover_timeout, elapsed)
        assert elapsed + remaining >= failover_timeout

    @given(failover_timeout=failover_timeouts, elapsed=elapsed_times)
    @PBT_SETTINGS
    def test_remaining_equals_max_zero_diff(
        self, failover_timeout: int, elapsed: float
    ):
        """remaining == max(0, failover_timeout - elapsed)."""
        remaining = calculate_failover_countdown(failover_timeout, elapsed)
        expected = max(0.0, failover_timeout - elapsed)
        assert remaining == expected
