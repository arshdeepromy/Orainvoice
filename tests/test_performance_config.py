"""Unit tests for Task 38.3 — Performance optimisations.

Validates:
- Cache TTL configuration is correct for each data type
- Connection pool settings are appropriate for 500 concurrent users
- Performance target constants are defined
- Cache key generation works correctly
- ResponseTimer utility measures elapsed time

Requirements: 81.1, 81.2, 81.3, 81.4, 81.5
"""

from __future__ import annotations

import time

from app.core.cache import (
    CacheTTL,
    cache_key,
    cache_key_hash,
)
from app.core.performance import (
    API_RESPONSE_TARGET_MS,
    CONCURRENT_USERS_TARGET,
    CONCURRENCY_CONFIG,
    DB_POOL_CONFIG,
    PAGE_RENDER_TARGET_MS,
    REDIS_POOL_CONFIG,
    ResponseTimer,
)


# -----------------------------------------------------------------------
# Cache TTL configuration (Requirement 81.4)
# -----------------------------------------------------------------------


class TestCacheTTLConfiguration:
    """Verify TTL values match the documented caching strategy."""

    def test_vehicle_lookup_ttl_is_24_hours(self):
        assert CacheTTL.VEHICLE_LOOKUP == 86_400

    def test_service_catalogue_ttl_is_1_hour(self):
        assert CacheTTL.SERVICE_CATALOGUE == 3_600

    def test_session_data_ttl_is_30_minutes(self):
        assert CacheTTL.SESSION_DATA == 1_800

    def test_default_ttl_is_5_minutes(self):
        assert CacheTTL.DEFAULT == 300

    def test_vehicle_ttl_greater_than_catalogue(self):
        assert CacheTTL.VEHICLE_LOOKUP > CacheTTL.SERVICE_CATALOGUE

    def test_catalogue_ttl_greater_than_session(self):
        assert CacheTTL.SERVICE_CATALOGUE > CacheTTL.SESSION_DATA


# -----------------------------------------------------------------------
# Cache key generation
# -----------------------------------------------------------------------


class TestCacheKeyGeneration:
    """Verify cache key helpers produce correct, namespaced keys."""

    def test_simple_key(self):
        assert cache_key("vehicle", "ABC123") == "workshoppro:vehicle:ABC123"

    def test_key_with_multiple_parts(self):
        result = cache_key("catalogue", "org-1", "services")
        assert result == "workshoppro:catalogue:org-1:services"

    def test_key_namespace_only(self):
        assert cache_key("session") == "workshoppro:session"

    def test_hash_key_is_deterministic(self):
        k1 = cache_key_hash("vehicle", "ABC123")
        k2 = cache_key_hash("vehicle", "ABC123")
        assert k1 == k2

    def test_hash_key_differs_for_different_input(self):
        k1 = cache_key_hash("vehicle", "ABC123")
        k2 = cache_key_hash("vehicle", "XYZ789")
        assert k1 != k2

    def test_hash_key_has_correct_prefix(self):
        k = cache_key_hash("vehicle", "ABC123")
        assert k.startswith("workshoppro:vehicle:")

    def test_hash_key_length_is_bounded(self):
        # Even with very long input, the key stays short
        k = cache_key_hash("vehicle", "A" * 10_000)
        assert len(k) < 100


# -----------------------------------------------------------------------
# Database connection pool settings (Requirement 81.5)
# -----------------------------------------------------------------------


class TestDBPoolConfig:
    """Verify database pool settings are appropriate for 500 users."""

    def test_pool_size(self):
        assert DB_POOL_CONFIG.pool_size == 20

    def test_max_overflow(self):
        assert DB_POOL_CONFIG.max_overflow == 10

    def test_pool_pre_ping_enabled(self):
        assert DB_POOL_CONFIG.pool_pre_ping is True

    def test_pool_recycle_is_30_minutes(self):
        assert DB_POOL_CONFIG.pool_recycle_seconds == 1_800

    def test_pool_timeout_is_30_seconds(self):
        assert DB_POOL_CONFIG.pool_timeout_seconds == 30

    def test_total_connections_per_worker(self):
        total = DB_POOL_CONFIG.pool_size + DB_POOL_CONFIG.max_overflow
        assert total == 30

    def test_effective_connections_for_4_workers(self):
        per_worker = DB_POOL_CONFIG.pool_size + DB_POOL_CONFIG.max_overflow
        total = per_worker * CONCURRENCY_CONFIG.worker_count
        assert total == 120


# -----------------------------------------------------------------------
# Redis pool settings (Requirement 81.4)
# -----------------------------------------------------------------------


class TestRedisPoolConfig:
    """Verify Redis pool settings."""

    def test_max_connections(self):
        assert REDIS_POOL_CONFIG.max_connections == 50

    def test_socket_timeout(self):
        assert REDIS_POOL_CONFIG.socket_timeout_seconds == 5.0

    def test_connect_timeout(self):
        assert REDIS_POOL_CONFIG.socket_connect_timeout_seconds == 2.0


# -----------------------------------------------------------------------
# Performance target constants (Requirement 81.1, 81.2, 81.3)
# -----------------------------------------------------------------------


class TestPerformanceTargets:
    """Verify performance target constants are defined correctly."""

    def test_page_render_target_is_2_seconds(self):
        assert PAGE_RENDER_TARGET_MS == 2_000

    def test_api_response_target_is_200ms(self):
        assert API_RESPONSE_TARGET_MS == 200

    def test_concurrent_users_target_is_500(self):
        assert CONCURRENT_USERS_TARGET == 500


# -----------------------------------------------------------------------
# Concurrency configuration (Requirement 81.3)
# -----------------------------------------------------------------------


class TestConcurrencyConfig:
    """Verify concurrency settings support 500+ concurrent users."""

    def test_worker_count(self):
        assert CONCURRENCY_CONFIG.worker_count >= 2

    def test_worker_connections(self):
        assert CONCURRENCY_CONFIG.worker_connections >= 500

    def test_total_capacity_exceeds_target(self):
        capacity = (
            CONCURRENCY_CONFIG.worker_count
            * CONCURRENCY_CONFIG.worker_connections
        )
        assert capacity >= CONCURRENT_USERS_TARGET

    def test_keepalive_positive(self):
        assert CONCURRENCY_CONFIG.keepalive_seconds > 0

    def test_graceful_timeout_positive(self):
        assert CONCURRENCY_CONFIG.graceful_timeout_seconds > 0

    def test_max_requests_positive(self):
        assert CONCURRENCY_CONFIG.max_requests_per_worker > 0


# -----------------------------------------------------------------------
# ResponseTimer utility
# -----------------------------------------------------------------------


class TestResponseTimer:
    """Verify the response time measurement utility."""

    def test_elapsed_ms_is_positive(self):
        timer = ResponseTimer()
        with timer:
            time.sleep(0.01)
        assert timer.elapsed_ms > 0

    def test_within_target_for_fast_operation(self):
        timer = ResponseTimer()
        with timer:
            pass  # near-zero time
        assert timer.within_target(target_ms=1_000) is True

    def test_within_target_default_uses_api_target(self):
        timer = ResponseTimer()
        with timer:
            pass
        # Near-zero should be within 200ms
        assert timer.within_target() is True

    def test_slow_operation_exceeds_target(self):
        timer = ResponseTimer()
        with timer:
            time.sleep(0.05)
        # 50ms sleep should exceed a 10ms target
        assert timer.within_target(target_ms=10) is False
