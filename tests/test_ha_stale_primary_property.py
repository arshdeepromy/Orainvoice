"""Property-based test: stale primary determination.

**Validates: Requirements 6.2, 6.3**

For all combinations of ``local_promoted_at`` (datetime or None) and
``peer_promoted_at`` (datetime or None):
- Antisymmetric: if A is stale relative to B, then B is not stale
  relative to A (when both have timestamps)
- Null is stale when peer has a timestamp
- The determination is consistent

Uses Hypothesis to verify the ``determine_stale_primary`` pure function
in ``app/modules/ha/utils.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.ha.utils import determine_stale_primary

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

# Aware datetimes in a realistic range (2020–2030)
aware_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Optional datetime (None or aware datetime)
optional_datetimes = st.one_of(st.none(), aware_datetimes)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestStalePrimaryDetermination:
    """Property 2: Stale Primary Determination.

    **Validates: Requirements 6.2, 6.3**
    """

    @given(local=optional_datetimes, peer=optional_datetimes)
    @PBT_SETTINGS
    def test_result_is_valid_value(self, local: datetime | None, peer: datetime | None):
        """Result is always one of the four valid values."""
        result = determine_stale_primary(local, peer)
        assert result in {"local", "peer", "neither", "both_null"}

    @given(local=aware_datetimes, peer=aware_datetimes)
    @PBT_SETTINGS
    def test_antisymmetric_when_both_have_timestamps(
        self, local: datetime, peer: datetime
    ):
        """If local is stale relative to peer, then peer is NOT stale
        relative to local (antisymmetry). When swapping arguments,
        'local' and 'peer' swap in the result."""
        assume(local != peer)
        result_forward = determine_stale_primary(local, peer)
        result_reverse = determine_stale_primary(peer, local)

        if result_forward == "local":
            assert result_reverse == "peer"
        elif result_forward == "peer":
            assert result_reverse == "local"

    @given(peer=aware_datetimes)
    @PBT_SETTINGS
    def test_null_local_is_stale_when_peer_has_timestamp(self, peer: datetime):
        """When local is None and peer has a timestamp, local is stale."""
        result = determine_stale_primary(None, peer)
        assert result == "local"

    @given(local=aware_datetimes)
    @PBT_SETTINGS
    def test_null_peer_is_stale_when_local_has_timestamp(self, local: datetime):
        """When peer is None and local has a timestamp, peer is stale."""
        result = determine_stale_primary(local, None)
        assert result == "peer"

    @PBT_SETTINGS
    @given(data=st.data())
    def test_both_null_returns_both_null(self, data):
        """When both are None, result is 'both_null'."""
        result = determine_stale_primary(None, None)
        assert result == "both_null"

    @given(ts=aware_datetimes)
    @PBT_SETTINGS
    def test_equal_timestamps_returns_neither(self, ts: datetime):
        """When both timestamps are equal, result is 'neither'."""
        result = determine_stale_primary(ts, ts)
        assert result == "neither"

    @given(local=aware_datetimes, peer=aware_datetimes)
    @PBT_SETTINGS
    def test_older_timestamp_is_stale(self, local: datetime, peer: datetime):
        """The node with the older timestamp is always the stale one."""
        assume(local != peer)
        result = determine_stale_primary(local, peer)
        if local < peer:
            assert result == "local"
        else:
            assert result == "peer"

    @given(local=optional_datetimes, peer=optional_datetimes)
    @PBT_SETTINGS
    def test_deterministic(self, local: datetime | None, peer: datetime | None):
        """Calling with the same inputs always produces the same result."""
        result1 = determine_stale_primary(local, peer)
        result2 = determine_stale_primary(local, peer)
        assert result1 == result2
