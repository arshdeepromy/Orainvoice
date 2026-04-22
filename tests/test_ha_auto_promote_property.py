"""Property-based test: should_auto_promote decision consistency.

**Validates: Requirements 3.4, 4.1**

For all combinations of ``auto_promote_enabled`` (bool),
``peer_unreachable_seconds`` (float >= 0), and ``failover_timeout`` (int > 0):
- ``should_auto_promote(enabled, seconds, timeout)`` returns True
  if and only if ``enabled`` is True AND ``seconds > timeout``.

Uses Hypothesis to verify the ``should_auto_promote`` pure function
in ``app/modules/ha/utils.py``.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.ha.utils import should_auto_promote

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# auto_promote_enabled: boolean
enabled_flags = st.booleans()

# peer_unreachable_seconds: non-negative float (realistic range 0–172800 = 2 days)
unreachable_seconds = st.floats(
    min_value=0.0, max_value=172_800.0, allow_nan=False, allow_infinity=False
)

# failover_timeout: positive integer (realistic range 1–86400 = 1 day)
failover_timeouts = st.integers(min_value=1, max_value=86_400)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestShouldAutoPromoteDecisionConsistency:
    """Property 1: Auto-Promote Decision Consistency.

    **Validates: Requirements 3.4, 4.1**
    """

    @given(
        enabled=enabled_flags,
        seconds=unreachable_seconds,
        timeout=failover_timeouts,
    )
    @PBT_SETTINGS
    def test_true_iff_enabled_and_seconds_exceeds_timeout(
        self, enabled: bool, seconds: float, timeout: int
    ):
        """should_auto_promote returns True iff enabled=True AND seconds > timeout."""
        result = should_auto_promote(enabled, seconds, timeout)
        expected = enabled and seconds > timeout
        assert result == expected

    @given(seconds=unreachable_seconds, timeout=failover_timeouts)
    @PBT_SETTINGS
    def test_disabled_always_returns_false(self, seconds: float, timeout: int):
        """When auto_promote_enabled is False, result is always False."""
        result = should_auto_promote(False, seconds, timeout)
        assert result is False

    @given(enabled=enabled_flags, timeout=failover_timeouts)
    @PBT_SETTINGS
    def test_zero_seconds_never_promotes(self, enabled: bool, timeout: int):
        """When peer_unreachable_seconds is 0, result is always False
        (0 is never > any positive timeout)."""
        result = should_auto_promote(enabled, 0.0, timeout)
        assert result is False

    @given(timeout=failover_timeouts)
    @PBT_SETTINGS
    def test_exactly_at_timeout_does_not_promote(self, timeout: int):
        """When seconds == timeout exactly, result is False (must exceed, not equal)."""
        result = should_auto_promote(True, float(timeout), timeout)
        assert result is False

    @given(timeout=failover_timeouts)
    @PBT_SETTINGS
    def test_just_above_timeout_promotes_when_enabled(self, timeout: int):
        """When enabled and seconds is just above timeout, result is True."""
        seconds = float(timeout) + 0.001
        result = should_auto_promote(True, seconds, timeout)
        assert result is True
