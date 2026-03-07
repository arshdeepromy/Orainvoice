"""Integration test: flag evaluation falls back to default on Redis failure.

**Validates: Requirement 2.8** — If a feature flag evaluation fails due to a
Redis or database error, the platform falls back to the flag's configured
default value rather than blocking the request.

Uses unittest.mock to simulate Redis failures and verifies the service
gracefully degrades.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.core.feature_flags import OrgContext
from app.modules.feature_flags.service import FeatureFlagCRUDService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_flag(
    key: str = "test-flag",
    is_active: bool = True,
    default_value: bool = True,
    targeting_rules: list | None = None,
):
    """Create a mock FeatureFlag object."""
    flag = MagicMock()
    flag.id = uuid.uuid4()
    flag.key = key
    flag.display_name = "Test Flag"
    flag.description = None
    flag.is_active = is_active
    flag.default_value = default_value
    flag.targeting_rules = targeting_rules or []
    flag.created_by = None
    flag.created_at = datetime.now(timezone.utc)
    flag.updated_at = datetime.now(timezone.utc)
    return flag


class TestFlagFallbackOnRedisFailure:
    """Flag evaluation falls back to default_value when Redis is unavailable.

    **Validates: Requirements 2.8**
    """

    @pytest.mark.asyncio
    async def test_evaluate_returns_default_when_redis_get_fails(self):
        """When Redis.get raises an exception, the service should fall back
        to evaluating from the database and return the correct result."""
        org_context = OrgContext(org_id=str(uuid.uuid4()))
        flag = _make_fake_flag(default_value=True, is_active=True)

        # Mock DB session that returns our flag
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = flag
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock Redis: get raises, setex also raises (full Redis failure)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis down"))

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is True, "Should fall back to default_value=True when Redis fails"

    @pytest.mark.asyncio
    async def test_evaluate_returns_false_when_both_redis_and_db_fail(self):
        """When both Redis and DB fail, the service returns False (safe default)."""
        org_context = OrgContext(org_id=str(uuid.uuid4()))

        # Mock DB session that raises
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))

        # Mock Redis that raises
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is False, "Should return False when both Redis and DB fail"

    @pytest.mark.asyncio
    async def test_evaluate_returns_default_for_inactive_flag_on_redis_failure(self):
        """An inactive flag returns its default_value even when Redis fails."""
        org_context = OrgContext(org_id=str(uuid.uuid4()))
        flag = _make_fake_flag(default_value=False, is_active=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = flag
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis down"))

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is False, "Inactive flag should return default_value=False"

    @pytest.mark.asyncio
    async def test_evaluate_uses_cache_when_available(self):
        """When Redis has a cached value, the DB is not queried."""
        org_context = OrgContext(org_id=str(uuid.uuid4()))

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()  # Should NOT be called

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is True
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_caches_result_after_db_lookup(self):
        """After a DB lookup, the result is cached in Redis."""
        org_context = OrgContext(org_id=str(uuid.uuid4()))
        flag = _make_fake_flag(default_value=True, is_active=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = flag
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # Cache miss
        mock_redis.setex = AsyncMock()

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is True
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_evaluate_with_matching_rule_on_redis_failure(self):
        """When Redis fails but DB works, targeting rules are still evaluated."""
        org_id = str(uuid.uuid4())
        org_context = OrgContext(org_id=org_id, country_code="NZ")
        flag = _make_fake_flag(
            default_value=False,
            is_active=True,
            targeting_rules=[
                {"type": "country", "value": "NZ", "enabled": True},
            ],
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = flag
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("Redis down"))

        svc = FeatureFlagCRUDService(mock_db)

        with patch("app.modules.feature_flags.service.redis_pool", mock_redis):
            result = await svc.evaluate_single("test-flag", org_context)

        assert result is True, "Country=NZ rule should match and return enabled=True"
