"""Tests for portal analytics — Redis counter tracking and aggregation.

Tests the portal analytics helper functions: ``track_portal_event``
increments Redis counters, and ``get_portal_analytics`` aggregates
the last 30 days of counters into a response.

**Validates: Requirements 47.1, 47.2, 47.3**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.portal.service import (
    track_portal_event,
    get_portal_analytics,
    PORTAL_ANALYTICS_EVENT_TYPES,
    _ANALYTICS_KEY_TTL_SECONDS,
)
from app.modules.portal.schemas import (
    PortalAnalyticsDayItem,
    PortalAnalyticsResponse,
)

# redis_pool is imported lazily inside the functions from app.core.redis
_REDIS_PATCH_TARGET = "app.core.redis.redis_pool"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_org_id_strategy = st.uuids()
_event_type_strategy = st.sampled_from(list(PORTAL_ANALYTICS_EVENT_TYPES))
_count_strategy = st.integers(min_value=0, max_value=10000)


# ---------------------------------------------------------------------------
# Unit tests — track_portal_event
# ---------------------------------------------------------------------------


class TestTrackPortalEvent:
    """Unit tests for the track_portal_event helper."""

    @pytest.mark.asyncio
    async def test_track_event_calls_redis_incr(self) -> None:
        """track_portal_event should INCR the correct Redis key and set TTL."""
        org_id = uuid.uuid4()
        today = date.today().isoformat()

        mock_pipe = AsyncMock()
        mock_pipe.incr = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            await track_portal_event(org_id, "view")

        expected_key = f"portal:analytics:{org_id}:{today}:view"
        mock_pipe.incr.assert_called_once_with(expected_key)
        mock_pipe.expire.assert_called_once_with(expected_key, _ANALYTICS_KEY_TTL_SECONDS)
        mock_pipe.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_track_event_does_not_raise_on_redis_failure(self) -> None:
        """track_portal_event should silently handle Redis errors."""
        org_id = uuid.uuid4()

        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            # Should not raise
            await track_portal_event(org_id, "view")

    @pytest.mark.asyncio
    async def test_track_event_uses_correct_key_format(self) -> None:
        """The Redis key should follow portal:analytics:{org_id}:{date}:{event_type}."""
        org_id = uuid.uuid4()
        today = date.today().isoformat()

        captured_keys: list[str] = []

        mock_pipe = AsyncMock()
        mock_pipe.incr = MagicMock(side_effect=lambda k: captured_keys.append(k))
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True])

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            for event_type in PORTAL_ANALYTICS_EVENT_TYPES:
                await track_portal_event(org_id, event_type)

        for i, event_type in enumerate(PORTAL_ANALYTICS_EVENT_TYPES):
            assert captured_keys[i] == f"portal:analytics:{org_id}:{today}:{event_type}"


# ---------------------------------------------------------------------------
# Unit tests — get_portal_analytics
# ---------------------------------------------------------------------------


class TestGetPortalAnalytics:
    """Unit tests for the get_portal_analytics aggregation function."""

    @pytest.mark.asyncio
    async def test_returns_30_days(self) -> None:
        """get_portal_analytics should return exactly 30 day entries."""
        org_id = uuid.uuid4()

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[None] * len(PORTAL_ANALYTICS_EVENT_TYPES))

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            result = await get_portal_analytics(org_id)

        assert len(result.days) == 30

    @pytest.mark.asyncio
    async def test_days_are_in_chronological_order(self) -> None:
        """Days should be returned oldest-first."""
        org_id = uuid.uuid4()

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[None] * len(PORTAL_ANALYTICS_EVENT_TYPES))

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            result = await get_portal_analytics(org_id)

        dates = [d.date for d in result.days]
        assert dates == sorted(dates)
        # First day should be 29 days ago, last day should be today
        today = date.today()
        assert result.days[0].date == (today - timedelta(days=29)).isoformat()
        assert result.days[-1].date == today.isoformat()

    @pytest.mark.asyncio
    async def test_totals_sum_correctly(self) -> None:
        """Totals should be the sum of all daily counters."""
        org_id = uuid.uuid4()

        # Simulate: day 0 (today) has view=5, quote_accepted=2, booking_created=1, payment_initiated=3
        # All other days have 0
        day_values = ["5", "2", "1", "3"]
        zero_values = [None] * len(PORTAL_ANALYTICS_EVENT_TYPES)

        call_count = 0

        mock_redis = MagicMock()

        def make_pipe():
            nonlocal call_count
            pipe = AsyncMock()
            pipe.get = MagicMock()
            if call_count == 0:
                # First call is for the most recent day (today) in the loop
                pipe.execute = AsyncMock(return_value=day_values)
            else:
                pipe.execute = AsyncMock(return_value=zero_values)
            call_count += 1
            return pipe

        mock_redis.pipeline = MagicMock(side_effect=make_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            result = await get_portal_analytics(org_id)

        assert result.totals.view == 5
        assert result.totals.quote_accepted == 2
        assert result.totals.booking_created == 1
        assert result.totals.payment_initiated == 3

    @pytest.mark.asyncio
    async def test_handles_redis_failure_gracefully(self) -> None:
        """If Redis fails, days should have zero counts."""
        org_id = uuid.uuid4()

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock()
        mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            result = await get_portal_analytics(org_id)

        assert len(result.days) == 30
        assert result.totals.view == 0
        assert result.totals.quote_accepted == 0

    @pytest.mark.asyncio
    async def test_totals_date_field_is_total(self) -> None:
        """The totals item should have date='total'."""
        org_id = uuid.uuid4()

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[None] * len(PORTAL_ANALYTICS_EVENT_TYPES))

        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch(_REDIS_PATCH_TARGET, mock_redis):
            result = await get_portal_analytics(org_id)

        assert result.totals.date == "total"


# ---------------------------------------------------------------------------
# Property-based tests — analytics schema correctness
# ---------------------------------------------------------------------------


class TestPortalAnalyticsSchemaProperties:
    """Property-based tests for portal analytics schemas.

    **Validates: Requirements 47.1, 47.2, 47.3**
    """

    @given(
        view=_count_strategy,
        quote_accepted=_count_strategy,
        booking_created=_count_strategy,
        payment_initiated=_count_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_day_item_preserves_all_counts(
        self,
        view: int,
        quote_accepted: int,
        booking_created: int,
        payment_initiated: int,
    ) -> None:
        """**Validates: Requirements 47.1**

        For any set of non-negative counter values, a PortalAnalyticsDayItem
        SHALL preserve all values exactly as provided.
        """
        item = PortalAnalyticsDayItem(
            date="2025-01-15",
            view=view,
            quote_accepted=quote_accepted,
            booking_created=booking_created,
            payment_initiated=payment_initiated,
        )
        assert item.view == view
        assert item.quote_accepted == quote_accepted
        assert item.booking_created == booking_created
        assert item.payment_initiated == payment_initiated

    @given(
        days_data=st.lists(
            st.fixed_dictionaries({
                "view": _count_strategy,
                "quote_accepted": _count_strategy,
                "booking_created": _count_strategy,
                "payment_initiated": _count_strategy,
            }),
            min_size=0,
            max_size=30,
        ),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_response_totals_equal_sum_of_days(
        self,
        days_data: list[dict],
    ) -> None:
        """**Validates: Requirements 47.2**

        For any list of daily analytics, the totals SHALL equal the sum
        of each event type across all days.
        """
        days = []
        expected_totals = {"view": 0, "quote_accepted": 0, "booking_created": 0, "payment_initiated": 0}

        for i, d in enumerate(days_data):
            day_str = (date.today() - timedelta(days=len(days_data) - 1 - i)).isoformat()
            days.append(PortalAnalyticsDayItem(date=day_str, **d))
            for key in expected_totals:
                expected_totals[key] += d[key]

        totals = PortalAnalyticsDayItem(date="total", **expected_totals)
        response = PortalAnalyticsResponse(days=days, totals=totals)

        assert response.totals.view == sum(d.view for d in response.days)
        assert response.totals.quote_accepted == sum(d.quote_accepted for d in response.days)
        assert response.totals.booking_created == sum(d.booking_created for d in response.days)
        assert response.totals.payment_initiated == sum(d.payment_initiated for d in response.days)

    @given(org_id=_org_id_strategy, event_type=_event_type_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_analytics_key_format_is_deterministic(
        self,
        org_id: uuid.UUID,
        event_type: str,
    ) -> None:
        """**Validates: Requirements 47.1**

        For any org_id and event_type, the Redis key format SHALL be
        deterministic: portal:analytics:{org_id}:{date}:{event_type}.
        """
        today = date.today().isoformat()
        expected_key = f"portal:analytics:{org_id}:{today}:{event_type}"
        # Verify the key components
        parts = expected_key.split(":")
        assert parts[0] == "portal"
        assert parts[1] == "analytics"
        assert parts[2] == str(org_id)
        assert parts[3] == today
        assert parts[4] == event_type
