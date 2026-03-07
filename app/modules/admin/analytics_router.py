"""Global Admin analytics router — platform-wide metrics endpoints.

All endpoints require the ``global_admin`` role.

**Validates: Requirement 39.1, 39.2, 39.3, 39.5**
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.admin.analytics_service import GlobalAnalyticsService, Period
from app.modules.auth.rbac import require_role

router = APIRouter(dependencies=[Depends(require_role("global_admin"))])


def _get_service(
    db: AsyncSession = Depends(get_db_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> GlobalAnalyticsService:
    """Build a GlobalAnalyticsService with DB session and Redis cache."""
    return GlobalAnalyticsService(db=db, redis_client=redis_client)


@router.get(
    "/overview",
    summary="Platform overview metrics",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_overview(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Total orgs, active orgs, MRR, and churn rate."""
    return await service.get_platform_overview()


@router.get(
    "/trade-distribution",
    summary="Organisation distribution by trade family/category",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_trade_distribution(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Org count per trade family and trade category."""
    return await service.get_trade_distribution()


@router.get(
    "/module-adoption",
    summary="Module adoption heatmap by trade family",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_module_adoption(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Module enablement rates per trade family."""
    return await service.get_module_adoption()


@router.get(
    "/geographic",
    summary="Geographic distribution of organisations",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_geographic(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Org count per country and data residency region."""
    return await service.get_geographic_distribution()


@router.get(
    "/revenue",
    summary="Revenue metrics by plan tier",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_revenue(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """MRR, ARR, ARPU, estimated LTV by plan tier."""
    return await service.get_revenue_metrics()


@router.get(
    "/conversion-funnel",
    summary="Conversion funnel metrics",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_conversion_funnel(
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Signup → wizard complete → first invoice → paid subscription."""
    return await service.get_conversion_funnel()


@router.get(
    "/time-series",
    summary="Time-series data for a metric",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def analytics_time_series(
    metric: str = Query(..., description="Metric name: signups, revenue, churn"),
    period: Period = Query("monthly", description="Aggregation period"),
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    service: GlobalAnalyticsService = Depends(_get_service),
):
    """Time-series aggregation with configurable periods."""
    return await service.get_time_series(
        metric=metric, period=period,
        start_date=start_date, end_date=end_date,
    )
