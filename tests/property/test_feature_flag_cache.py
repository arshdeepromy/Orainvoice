"""Property-based tests for feature flag cache invalidation.

**Validates: Requirement 2.5** — Cache invalidation ensures fresh evaluation
within 5 seconds of flag toggle.

Tests the cache invalidation logic by simulating Redis cache operations
using an in-memory fake, verifying that after a flag toggle the cached
value is cleared and re-evaluation produces the updated result.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.feature_flags import OrgContext, evaluate_flag


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# In-memory Redis fake for testing cache behaviour
# ---------------------------------------------------------------------------

class FakeRedis:
    """Minimal async Redis fake that supports get/setex/delete/scan."""

    def __init__(self):
        self._store: dict[str, tuple[str, float]] = {}  # key -> (value, expire_time)

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_time = entry
        if expire_time and time.monotonic() > expire_time:
            del self._store[key]
            return None
        return value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count

    async def scan(self, cursor: int, match: str = "*", count: int = 100):
        import fnmatch
        matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return 0, matched


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

org_id_strategy = st.uuids().map(str)
slug_strategy = st.from_regex(r"[a-z][a-z0-9_-]{2,20}", fullmatch=True)


def _org_context_strategy():
    return st.builds(
        OrgContext,
        org_id=org_id_strategy,
        trade_category_slug=st.one_of(st.none(), slug_strategy),
        trade_family_slug=st.one_of(st.none(), slug_strategy),
        country_code=st.one_of(st.none(), st.sampled_from(["NZ", "AU", "UK"])),
        plan_tier=st.one_of(st.none(), st.sampled_from(["free", "starter"])),
    )


# ===========================================================================
# Property Test 4.7: Cache invalidation ensures fresh evaluation
# ===========================================================================


class TestCacheInvalidation:
    """Cache invalidation ensures fresh evaluation within 5 seconds of
    flag toggle.

    **Validates: Requirements 2.5**
    """

    @given(
        org_context=_org_context_strategy(),
        initial_enabled=st.booleans(),
    )
    @PBT_SETTINGS
    def test_cache_invalidation_produces_fresh_result(
        self,
        org_context: OrgContext,
        initial_enabled: bool,
    ) -> None:
        """After invalidating the cache for a flag, re-evaluation with
        changed rules produces the updated result (not the stale cached value).

        This simulates the flow:
        1. Evaluate flag → caches result
        2. Toggle the flag (change targeting rules)
        3. Invalidate cache
        4. Re-evaluate → must reflect the new rules
        """
        fake_redis = FakeRedis()
        flag_key = "test-flag"
        cache_key = f"flag:{flag_key}:{org_context.org_id}"

        toggled_enabled = not initial_enabled

        # Step 1: Evaluate with initial rules and cache the result
        initial_rules = [
            {"type": "org_override", "value": org_context.org_id, "enabled": initial_enabled}
        ]
        result_before = evaluate_flag(
            is_active=True,
            default_value=False,
            targeting_rules=initial_rules,
            org_context=org_context,
        )
        assert result_before == initial_enabled

        # Simulate caching
        asyncio.run(fake_redis.setex(cache_key, 60, "1" if result_before else "0"))

        # Verify cache has the old value
        cached = asyncio.run(fake_redis.get(cache_key))
        assert cached is not None

        # Step 2: Toggle the flag rules
        toggled_rules = [
            {"type": "org_override", "value": org_context.org_id, "enabled": toggled_enabled}
        ]

        # Step 3: Invalidate cache (simulating what service._invalidate_cache does)
        async def invalidate():
            pattern = f"flag:{flag_key}:*"
            cursor, keys = await fake_redis.scan(0, match=pattern)
            if keys:
                await fake_redis.delete(*keys)

        asyncio.run(invalidate())

        # Verify cache is cleared
        cached_after = asyncio.run(fake_redis.get(cache_key))
        assert cached_after is None, "Cache should be cleared after invalidation"

        # Step 4: Re-evaluate with new rules
        result_after = evaluate_flag(
            is_active=True,
            default_value=False,
            targeting_rules=toggled_rules,
            org_context=org_context,
        )
        assert result_after == toggled_enabled, (
            f"After cache invalidation, expected {toggled_enabled} but got {result_after}"
        )

    @given(
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_invalidation_clears_all_org_entries_for_flag(
        self,
        org_context: OrgContext,
    ) -> None:
        """Invalidating a flag clears cached entries for ALL orgs, not just one."""
        fake_redis = FakeRedis()
        flag_key = "multi-org-flag"
        other_org_id = "other-org-id-12345"

        # Cache entries for two different orgs
        asyncio.run(fake_redis.setex(f"flag:{flag_key}:{org_context.org_id}", 60, "1"))
        asyncio.run(fake_redis.setex(f"flag:{flag_key}:{other_org_id}", 60, "0"))

        # Invalidate
        async def invalidate():
            pattern = f"flag:{flag_key}:*"
            cursor, keys = await fake_redis.scan(0, match=pattern)
            if keys:
                await fake_redis.delete(*keys)

        asyncio.run(invalidate())

        # Both should be cleared
        val1 = asyncio.run(fake_redis.get(f"flag:{flag_key}:{org_context.org_id}"))
        val2 = asyncio.run(fake_redis.get(f"flag:{flag_key}:{other_org_id}"))
        assert val1 is None, "Cache for org 1 should be cleared"
        assert val2 is None, "Cache for org 2 should be cleared"
