"""Tests for Global Admin analytics dashboard (Task 47).

Covers:
- 47.5: analytics overview returns correct counts matching database state
- 47.6: module adoption heatmap correctly calculates percentages per trade category
- 47.7: conversion funnel correctly tracks each stage

Requirements: 39.1, 39.2, 39.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.analytics_service import (
    GlobalAnalyticsService,
    _HISTORICAL_TTL,
    _OVERVIEW_TTL,
    _cache_key,
    _get_cached,
    _set_cached,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(*values):
    """Create a mock row that supports index access."""
    return values


def _scalar_result(value):
    """Create a mock execute result that returns a scalar."""
    mock = MagicMock()
    mock.scalar.return_value = value
    return mock


def _fetchall_result(rows):
    """Create a mock execute result that returns fetchall rows."""
    mock = MagicMock()
    mock.fetchall.return_value = rows
    return mock


# ---------------------------------------------------------------------------
# 47.5: Analytics overview returns correct counts
# ---------------------------------------------------------------------------


class TestAnalyticsOverview:
    """Validates: Requirement 39.1 — platform overview metrics."""

    @pytest.mark.asyncio
    async def test_overview_returns_correct_counts(self):
        """Overview returns total_orgs, active_orgs, mrr, churn_rate
        matching the database state."""
        db = AsyncMock()

        # total orgs = 100
        # active orgs = 80
        # MRR = 5000.0
        # churned in last 30 days = 5
        # churn_rate = 5 / (80 + 5) * 100 = 5.88
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(100),   # total orgs
                _scalar_result(80),    # active orgs
                _scalar_result(5000.0),  # MRR
                _scalar_result(5),     # churned
            ]
        )

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_platform_overview()

        assert result["total_orgs"] == 100
        assert result["active_orgs"] == 80
        assert result["mrr"] == 5000.0
        assert result["churn_rate"] == pytest.approx(5.88, abs=0.01)

    @pytest.mark.asyncio
    async def test_overview_zero_active_orgs_no_division_error(self):
        """When no active orgs, churn_rate should be 0 (no division by zero)."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(0),   # total orgs
                _scalar_result(0),   # active orgs
                _scalar_result(0),   # MRR
                _scalar_result(0),   # churned
            ]
        )

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_platform_overview()

        assert result["total_orgs"] == 0
        assert result["active_orgs"] == 0
        assert result["mrr"] == 0.0
        assert result["churn_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_overview_uses_cache_when_available(self):
        """Overview returns cached data when Redis has it."""
        db = AsyncMock()
        redis = AsyncMock()
        cached_data = '{"total_orgs": 50, "active_orgs": 40, "mrr": 2500.0, "churn_rate": 3.0}'
        redis.get = AsyncMock(return_value=cached_data)

        service = GlobalAnalyticsService(db=db, redis_client=redis)
        result = await service.get_platform_overview()

        assert result["total_orgs"] == 50
        assert result["active_orgs"] == 40
        # DB should not have been called
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_overview_caches_result_with_5min_ttl(self):
        """Overview stores result in Redis with 5-minute TTL."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(10),
                _scalar_result(8),
                _scalar_result(400.0),
                _scalar_result(1),
            ]
        )
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        service = GlobalAnalyticsService(db=db, redis_client=redis)
        await service.get_platform_overview()

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args.kwargs.get("ex") == _OVERVIEW_TTL


# ---------------------------------------------------------------------------
# 47.6: Module adoption heatmap correctly calculates percentages
# ---------------------------------------------------------------------------


class TestModuleAdoption:
    """Validates: Requirement 39.2 — module adoption heatmap."""

    @pytest.mark.asyncio
    async def test_adoption_heatmap_calculates_percentages(self):
        """Heatmap returns correct adoption_pct per trade family + module."""
        db = AsyncMock()

        # Simulate: Automotive family has 10 orgs, 7 use invoicing, 3 use POS
        heatmap_rows = [
            _row("automotive", "Automotive & Transport", "invoicing", 7, 10, 70.0),
            _row("automotive", "Automotive & Transport", "pos", 3, 10, 30.0),
            _row("construction", "Building & Construction", "invoicing", 5, 5, 100.0),
            _row("construction", "Building & Construction", "pos", 0, 5, 0.0),
        ]
        db.execute = AsyncMock(return_value=_fetchall_result(heatmap_rows))

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_module_adoption()

        heatmap = result["heatmap"]
        assert len(heatmap) == 4

        # Automotive invoicing: 70%
        auto_inv = next(h for h in heatmap if h["family_slug"] == "automotive" and h["module_slug"] == "invoicing")
        assert auto_inv["adoption_pct"] == 70.0
        assert auto_inv["enabled_count"] == 7
        assert auto_inv["total_orgs"] == 10

        # Construction invoicing: 100%
        const_inv = next(h for h in heatmap if h["family_slug"] == "construction" and h["module_slug"] == "invoicing")
        assert const_inv["adoption_pct"] == 100.0

        # Construction POS: 0%
        const_pos = next(h for h in heatmap if h["family_slug"] == "construction" and h["module_slug"] == "pos")
        assert const_pos["adoption_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_adoption_empty_when_no_orgs(self):
        """Heatmap returns empty list when no organisations exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result([]))

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_module_adoption()

        assert result["heatmap"] == []

    @pytest.mark.asyncio
    async def test_adoption_caches_with_1hour_ttl(self):
        """Module adoption data is cached with 1-hour TTL."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_fetchall_result([]))
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        service = GlobalAnalyticsService(db=db, redis_client=redis)
        await service.get_module_adoption()

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args.kwargs.get("ex") == _HISTORICAL_TTL


# ---------------------------------------------------------------------------
# 47.7: Conversion funnel correctly tracks each stage
# ---------------------------------------------------------------------------


class TestConversionFunnel:
    """Validates: Requirement 39.3 — conversion funnel metrics."""

    @pytest.mark.asyncio
    async def test_funnel_tracks_all_stages(self):
        """Funnel returns 4 stages with correct counts and rates."""
        db = AsyncMock()

        # 100 signups → 80 wizard complete → 50 first invoice → 30 paid
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(100),  # signups
                _scalar_result(80),   # wizard complete
                _scalar_result(50),   # first invoice
                _scalar_result(30),   # paid
            ]
        )

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_conversion_funnel()

        stages = result["stages"]
        assert len(stages) == 4

        assert stages[0]["stage"] == "signup"
        assert stages[0]["count"] == 100
        assert stages[0]["rate"] == 100.0

        assert stages[1]["stage"] == "wizard_complete"
        assert stages[1]["count"] == 80
        assert stages[1]["rate"] == 80.0  # 80/100

        assert stages[2]["stage"] == "first_invoice"
        assert stages[2]["count"] == 50
        assert stages[2]["rate"] == 62.5  # 50/80

        assert stages[3]["stage"] == "paid_subscription"
        assert stages[3]["count"] == 30
        assert stages[3]["rate"] == 60.0  # 30/50

    @pytest.mark.asyncio
    async def test_funnel_handles_zero_signups(self):
        """Funnel handles zero signups without division errors."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(0),
                _scalar_result(0),
                _scalar_result(0),
                _scalar_result(0),
            ]
        )

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_conversion_funnel()

        stages = result["stages"]
        assert all(s["count"] == 0 for s in stages)
        # No division by zero — rates should be safe
        assert stages[0]["rate"] == 100.0  # signup rate is always 100%
        assert stages[1]["rate"] == 0.0

    @pytest.mark.asyncio
    async def test_funnel_decreasing_counts(self):
        """Each funnel stage should have count <= previous stage."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_result(200),
                _scalar_result(150),
                _scalar_result(100),
                _scalar_result(60),
            ]
        )

        service = GlobalAnalyticsService(db=db, redis_client=None)
        result = await service.get_conversion_funnel()

        stages = result["stages"]
        for i in range(1, len(stages)):
            assert stages[i]["count"] <= stages[i - 1]["count"]


# ---------------------------------------------------------------------------
# Cache helper tests
# ---------------------------------------------------------------------------


class TestCacheHelpers:
    """Test Redis cache helper functions."""

    def test_cache_key_generation(self):
        key = _cache_key("overview")
        assert key == "analytics:overview"

        key = _cache_key("timeseries", metric="signups", period="monthly")
        assert "metric=signups" in key
        assert "period=monthly" in key

    @pytest.mark.asyncio
    async def test_get_cached_returns_none_without_redis(self):
        result = await _get_cached(None, "test_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_cached_noop_without_redis(self):
        # Should not raise
        await _set_cached(None, "test_key", {"data": 1}, 300)

    @pytest.mark.asyncio
    async def test_get_cached_returns_data_from_redis(self):
        redis = AsyncMock()
        redis.get = AsyncMock(return_value='{"total_orgs": 42}')
        result = await _get_cached(redis, "test_key")
        assert result == {"total_orgs": 42}

    @pytest.mark.asyncio
    async def test_get_cached_handles_redis_error(self):
        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis down"))
        result = await _get_cached(redis, "test_key")
        assert result is None
