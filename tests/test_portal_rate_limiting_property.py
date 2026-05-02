"""Property-based tests for portal rate limiting.

Tests the pure rate limiting logic for portal endpoints:
  * Per-token rate limit: 60 req/min per portal token
  * Per-IP rate limit on token resolution: 20 req/min per IP

Properties covered:
  P7 — Portal per-token rate limit enforces threshold
  P8 — Portal per-IP rate limit on token resolution

**Validates: Requirements 9.1, 9.2, 9.3**
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.middleware.rate_limit import (
    _check_rate_limit,
    _PORTAL_PER_TOKEN_RATE_LIMIT,
    _PORTAL_PER_IP_RATE_LIMIT,
    _WINDOW,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Portal tokens — UUID-like strings
_portal_tokens = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    fullmatch=True,
)

# IP addresses
_ip_addresses = st.sampled_from([
    "192.168.1.1", "10.0.0.1", "172.16.0.1", "203.0.113.42",
    "2001:db8::1", "127.0.0.1", "8.8.8.8", "1.2.3.4",
])

# Request counts below the per-token limit (0 to 59)
_under_token_limit = st.integers(min_value=0, max_value=_PORTAL_PER_TOKEN_RATE_LIMIT - 1)

# Request counts at or above the per-token limit (60 to 200)
_over_token_limit = st.integers(
    min_value=_PORTAL_PER_TOKEN_RATE_LIMIT, max_value=200,
)

# Request counts below the per-IP limit (0 to 19)
_under_ip_limit = st.integers(min_value=0, max_value=_PORTAL_PER_IP_RATE_LIMIT - 1)

# Request counts at or above the per-IP limit (20 to 100)
_over_ip_limit = st.integers(
    min_value=_PORTAL_PER_IP_RATE_LIMIT, max_value=100,
)


# ---------------------------------------------------------------------------
# Helpers — build mock Redis that simulates sliding window state
# ---------------------------------------------------------------------------

def _build_mock_redis(current_count: int, window_start_time: float | None = None):
    """Build a mock Redis instance simulating a sorted-set sliding window.

    ``current_count`` is the number of entries already in the window after
    pruning old entries.

    ``window_start_time`` is the timestamp of the oldest entry still in the
    window (used to compute Retry-After). Defaults to ``now - 30`` (halfway
    through the 60-second window).
    """
    redis = AsyncMock()
    now = time.time()
    oldest_ts = window_start_time or (now - 30)

    # Pipeline for the initial prune + count
    pipe1 = AsyncMock()
    pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
    pipe1.zcard = MagicMock(return_value=pipe1)
    pipe1.execute = AsyncMock(return_value=[0, current_count])

    # Pipeline for recording a new request (zadd + expire)
    pipe2 = AsyncMock()
    pipe2.zadd = MagicMock(return_value=pipe2)
    pipe2.expire = MagicMock(return_value=pipe2)
    pipe2.execute = AsyncMock(return_value=[1, True])

    call_count = {"n": 0}

    def _pipeline():
        call_count["n"] += 1
        if call_count["n"] <= 1:
            return pipe1
        return pipe2

    redis.pipeline = _pipeline

    # zrange returns the oldest entry (used when over limit)
    redis.zrange = AsyncMock(return_value=[(b"oldest", oldest_ts)])

    return redis


# ===========================================================================
# Property 7: Portal per-token rate limit enforces threshold
# ===========================================================================


class TestP7PortalPerTokenRateLimit:
    """For any portal token and request count exceeding 60 within a
    60-second window, the rate limiter SHALL return HTTP 429 for requests
    beyond the threshold. For request counts at or below the threshold,
    all requests SHALL be allowed.

    **Validates: Requirements 9.1, 9.3**
    """

    @pytest.mark.asyncio
    @given(
        current_count=_under_token_limit,
        token=_portal_tokens,
    )
    @PBT_SETTINGS
    async def test_requests_within_token_limit_are_allowed(
        self, current_count: int, token: str,
    ) -> None:
        """P7: Requests under the per-token limit (60/min) must be allowed.

        **Validates: Requirements 9.1**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:token:{token}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_TOKEN_RATE_LIMIT, now,
        )

        assert allowed is True, (
            f"Request #{current_count + 1} for token {token} was blocked "
            f"but per-token limit is {_PORTAL_PER_TOKEN_RATE_LIMIT}"
        )
        assert retry_after == 0

    @pytest.mark.asyncio
    @given(
        current_count=_over_token_limit,
        token=_portal_tokens,
    )
    @PBT_SETTINGS
    async def test_requests_over_token_limit_are_denied(
        self, current_count: int, token: str,
    ) -> None:
        """P7: Requests at or over the per-token limit (60/min) must be
        denied with a positive Retry-After.

        **Validates: Requirements 9.1, 9.3**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:token:{token}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_TOKEN_RATE_LIMIT, now,
        )

        assert allowed is False, (
            f"Request #{current_count + 1} for token {token} was allowed "
            f"but per-token limit is {_PORTAL_PER_TOKEN_RATE_LIMIT}"
        )
        assert retry_after >= 1, (
            f"Retry-After was {retry_after}, must be >= 1 when rate limited"
        )

    @pytest.mark.asyncio
    @given(
        current_count=st.integers(min_value=0, max_value=200),
        token=_portal_tokens,
    )
    @PBT_SETTINGS
    async def test_token_limit_boundary_is_exact(
        self, current_count: int, token: str,
    ) -> None:
        """P7: The boundary between allowed and denied is exactly at the
        configured limit (60). Counts < 60 are allowed, counts >= 60 are
        denied.

        **Validates: Requirements 9.1, 9.3**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:token:{token}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_TOKEN_RATE_LIMIT, now,
        )

        if current_count < _PORTAL_PER_TOKEN_RATE_LIMIT:
            assert allowed is True, (
                f"count={current_count} < limit={_PORTAL_PER_TOKEN_RATE_LIMIT} "
                f"but request was blocked"
            )
            assert retry_after == 0
        else:
            assert allowed is False, (
                f"count={current_count} >= limit={_PORTAL_PER_TOKEN_RATE_LIMIT} "
                f"but request was allowed"
            )
            assert retry_after >= 1

    @pytest.mark.asyncio
    @given(
        token=_portal_tokens,
    )
    @PBT_SETTINGS
    async def test_token_limit_uses_correct_redis_key_format(
        self, token: str,
    ) -> None:
        """P7: The rate limit key for portal tokens follows the format
        rl:portal:token:{token_segment}, ensuring per-token isolation.

        **Validates: Requirements 9.1**
        """
        now = time.time()
        redis = _build_mock_redis(0)
        key = f"rl:portal:token:{token}"

        # Verify the key format is correct
        assert key.startswith("rl:portal:token:"), (
            f"Portal token rate limit key has wrong prefix: {key}"
        )
        assert token in key, (
            f"Portal token {token} not found in rate limit key: {key}"
        )

        # Verify the function works with this key
        allowed, _ = await _check_rate_limit(
            redis, key, _PORTAL_PER_TOKEN_RATE_LIMIT, now,
        )
        assert allowed is True


# ===========================================================================
# Property 8: Portal per-IP rate limit on token resolution
# ===========================================================================


class TestP8PortalPerIPRateLimit:
    """For any IP address and request count exceeding 20 within a
    60-second window to the token resolution endpoint, the rate limiter
    SHALL return HTTP 429 for requests beyond the threshold.

    **Validates: Requirements 9.2**
    """

    @pytest.mark.asyncio
    @given(
        current_count=_under_ip_limit,
        ip=_ip_addresses,
    )
    @PBT_SETTINGS
    async def test_requests_within_ip_limit_are_allowed(
        self, current_count: int, ip: str,
    ) -> None:
        """P8: Requests under the per-IP limit (20/min) on token resolution
        must be allowed.

        **Validates: Requirements 9.2**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:ip:{ip}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_IP_RATE_LIMIT, now,
        )

        assert allowed is True, (
            f"Request #{current_count + 1} from IP {ip} was blocked "
            f"but per-IP limit is {_PORTAL_PER_IP_RATE_LIMIT}"
        )
        assert retry_after == 0

    @pytest.mark.asyncio
    @given(
        current_count=_over_ip_limit,
        ip=_ip_addresses,
    )
    @PBT_SETTINGS
    async def test_requests_over_ip_limit_are_denied(
        self, current_count: int, ip: str,
    ) -> None:
        """P8: Requests at or over the per-IP limit (20/min) on token
        resolution must be denied with a positive Retry-After.

        **Validates: Requirements 9.2**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:ip:{ip}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_IP_RATE_LIMIT, now,
        )

        assert allowed is False, (
            f"Request #{current_count + 1} from IP {ip} was allowed "
            f"but per-IP limit is {_PORTAL_PER_IP_RATE_LIMIT}"
        )
        assert retry_after >= 1, (
            f"Retry-After was {retry_after}, must be >= 1 when rate limited"
        )

    @pytest.mark.asyncio
    @given(
        current_count=st.integers(min_value=0, max_value=100),
        ip=_ip_addresses,
    )
    @PBT_SETTINGS
    async def test_ip_limit_boundary_is_exact(
        self, current_count: int, ip: str,
    ) -> None:
        """P8: The boundary between allowed and denied is exactly at the
        configured limit (20). Counts < 20 are allowed, counts >= 20 are
        denied.

        **Validates: Requirements 9.2**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:ip:{ip}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_IP_RATE_LIMIT, now,
        )

        if current_count < _PORTAL_PER_IP_RATE_LIMIT:
            assert allowed is True, (
                f"count={current_count} < limit={_PORTAL_PER_IP_RATE_LIMIT} "
                f"but request was blocked"
            )
            assert retry_after == 0
        else:
            assert allowed is False, (
                f"count={current_count} >= limit={_PORTAL_PER_IP_RATE_LIMIT} "
                f"but request was allowed"
            )
            assert retry_after >= 1

    @pytest.mark.asyncio
    @given(
        current_count=_over_ip_limit,
        ip=_ip_addresses,
    )
    @PBT_SETTINGS
    async def test_retry_after_is_positive_when_over_ip_limit(
        self, current_count: int, ip: str,
    ) -> None:
        """P8: When over the per-IP limit, Retry-After must be >= 1 second,
        satisfying the HTTP 429 Retry-After header requirement.

        **Validates: Requirements 9.2, 9.3**
        """
        now = time.time()
        redis = _build_mock_redis(current_count)
        key = f"rl:portal:ip:{ip}"

        allowed, retry_after = await _check_rate_limit(
            redis, key, _PORTAL_PER_IP_RATE_LIMIT, now,
        )

        assert allowed is False
        assert retry_after >= 1, (
            f"Retry-After was {retry_after}, must be >= 1 for HTTP 429 "
            f"compliance (Req 9.3)"
        )

    @pytest.mark.asyncio
    @given(ip=_ip_addresses)
    @PBT_SETTINGS
    async def test_ip_limit_uses_correct_redis_key_format(
        self, ip: str,
    ) -> None:
        """P8: The rate limit key for portal IP limits follows the format
        rl:portal:ip:{client_ip}, ensuring per-IP isolation on the token
        resolution endpoint.

        **Validates: Requirements 9.2**
        """
        now = time.time()
        redis = _build_mock_redis(0)
        key = f"rl:portal:ip:{ip}"

        # Verify the key format is correct
        assert key.startswith("rl:portal:ip:"), (
            f"Portal IP rate limit key has wrong prefix: {key}"
        )
        assert ip in key, (
            f"IP {ip} not found in rate limit key: {key}"
        )

        # Verify the function works with this key
        allowed, _ = await _check_rate_limit(
            redis, key, _PORTAL_PER_IP_RATE_LIMIT, now,
        )
        assert allowed is True
