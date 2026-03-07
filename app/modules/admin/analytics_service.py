"""Global Admin analytics service for platform-wide metrics.

Provides aggregated analytics across all organisations segmented by
trade category, country, module adoption, and revenue.

**Validates: Requirement 39.1, 39.2, 39.3, 39.5**
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Period = Literal["daily", "weekly", "monthly"]


# ---------------------------------------------------------------------------
# Cache helpers (Redis)
# ---------------------------------------------------------------------------

_OVERVIEW_TTL = 300  # 5 minutes
_HISTORICAL_TTL = 3600  # 1 hour


def _cache_key(name: str, **kwargs: Any) -> str:
    parts = [f"analytics:{name}"]
    for k, v in sorted(kwargs.items()):
        parts.append(f"{k}={v}")
    return ":".join(parts)


async def _get_cached(redis_client: Any | None, key: str) -> dict | None:
    if redis_client is None:
        return None
    try:
        raw = await redis_client.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def _set_cached(redis_client: Any | None, key: str, data: dict, ttl: int) -> None:
    if redis_client is None:
        return
    try:
        await redis_client.set(key, json.dumps(data, default=str), ex=ttl)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GlobalAnalyticsService
# ---------------------------------------------------------------------------


class GlobalAnalyticsService:
    """Platform-wide analytics queries for the Global Admin dashboard."""

    def __init__(self, db: AsyncSession, redis_client: Any | None = None):
        self.db = db
        self.redis = redis_client

    # ------------------------------------------------------------------
    # get_platform_overview
    # ------------------------------------------------------------------

    async def get_platform_overview(self) -> dict:
        """Return high-level platform metrics.

        Returns dict with: total_orgs, active_orgs, mrr, churn_rate.
        """
        cache_key = _cache_key("overview")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        # Total organisations
        total_q = await self.db.execute(
            text("SELECT COUNT(*) FROM organisations")
        )
        total_orgs = total_q.scalar() or 0

        # Active organisations (status = 'active')
        active_q = await self.db.execute(
            text("SELECT COUNT(*) FROM organisations WHERE status = 'active'")
        )
        active_orgs = active_q.scalar() or 0

        # MRR: sum of monthly_price_nzd for active orgs with plans
        mrr_q = await self.db.execute(
            text(
                "SELECT COALESCE(SUM(sp.monthly_price_nzd), 0) "
                "FROM organisations o "
                "JOIN subscription_plans sp ON o.plan_id = sp.id "
                "WHERE o.status = 'active'"
            )
        )
        mrr = float(mrr_q.scalar() or 0)

        # Churn rate: orgs cancelled in last 30 days / total active at start
        churn_q = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM organisations "
                "WHERE status IN ('cancelled', 'suspended') "
                "AND updated_at >= NOW() - INTERVAL '30 days'"
            )
        )
        churned = churn_q.scalar() or 0
        churn_rate = round((churned / max(active_orgs + churned, 1)) * 100, 2)

        result = {
            "total_orgs": total_orgs,
            "active_orgs": active_orgs,
            "mrr": mrr,
            "churn_rate": churn_rate,
        }
        await _set_cached(self.redis, cache_key, result, _OVERVIEW_TTL)
        return result

    # ------------------------------------------------------------------
    # get_trade_distribution
    # ------------------------------------------------------------------

    async def get_trade_distribution(self) -> dict:
        """Return org count per trade family and trade category."""
        cache_key = _cache_key("trade_distribution")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        # By trade family
        family_q = await self.db.execute(
            text(
                "SELECT tf.slug, tf.display_name, COUNT(o.id) AS org_count "
                "FROM trade_families tf "
                "LEFT JOIN trade_categories tc ON tc.family_id = tf.id "
                "LEFT JOIN organisations o ON o.trade_category_id = tc.id "
                "GROUP BY tf.slug, tf.display_name "
                "ORDER BY org_count DESC"
            )
        )
        by_family = [
            {"slug": r[0], "display_name": r[1], "org_count": r[2]}
            for r in family_q.fetchall()
        ]

        # By trade category
        category_q = await self.db.execute(
            text(
                "SELECT tc.slug, tc.display_name, tf.slug AS family_slug, "
                "COUNT(o.id) AS org_count "
                "FROM trade_categories tc "
                "JOIN trade_families tf ON tf.id = tc.family_id "
                "LEFT JOIN organisations o ON o.trade_category_id = tc.id "
                "GROUP BY tc.slug, tc.display_name, tf.slug "
                "ORDER BY org_count DESC"
            )
        )
        by_category = [
            {
                "slug": r[0],
                "display_name": r[1],
                "family_slug": r[2],
                "org_count": r[3],
            }
            for r in category_q.fetchall()
        ]

        result = {"by_family": by_family, "by_category": by_category}
        await _set_cached(self.redis, cache_key, result, _HISTORICAL_TTL)
        return result

    # ------------------------------------------------------------------
    # get_module_adoption
    # ------------------------------------------------------------------

    async def get_module_adoption(self) -> dict:
        """Return module enablement rates per trade family as a heatmap."""
        cache_key = _cache_key("module_adoption")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        heatmap_q = await self.db.execute(
            text(
                "SELECT tf.slug AS family_slug, tf.display_name AS family_name, "
                "om.module_slug, "
                "COUNT(DISTINCT om.org_id) AS enabled_count, "
                "COUNT(DISTINCT o.id) AS total_orgs, "
                "CASE WHEN COUNT(DISTINCT o.id) > 0 "
                "  THEN ROUND(COUNT(DISTINCT om.org_id)::numeric / "
                "       COUNT(DISTINCT o.id) * 100, 1) "
                "  ELSE 0 END AS adoption_pct "
                "FROM trade_families tf "
                "JOIN trade_categories tc ON tc.family_id = tf.id "
                "JOIN organisations o ON o.trade_category_id = tc.id "
                "LEFT JOIN org_modules om ON om.org_id = o.id AND om.is_enabled = true "
                "GROUP BY tf.slug, tf.display_name, om.module_slug "
                "ORDER BY tf.slug, om.module_slug"
            )
        )
        rows = heatmap_q.fetchall()

        heatmap: list[dict] = []
        for r in rows:
            heatmap.append({
                "family_slug": r[0],
                "family_name": r[1],
                "module_slug": r[2],
                "enabled_count": r[3],
                "total_orgs": r[4],
                "adoption_pct": float(r[5]) if r[5] else 0.0,
            })

        result = {"heatmap": heatmap}
        await _set_cached(self.redis, cache_key, result, _HISTORICAL_TTL)
        return result

    # ------------------------------------------------------------------
    # get_geographic_distribution
    # ------------------------------------------------------------------

    async def get_geographic_distribution(self) -> dict:
        """Return org count per country/region."""
        cache_key = _cache_key("geographic")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        country_q = await self.db.execute(
            text(
                "SELECT COALESCE(country_code, 'unknown') AS country, "
                "COUNT(*) AS org_count "
                "FROM organisations "
                "GROUP BY country_code "
                "ORDER BY org_count DESC"
            )
        )
        by_country = [
            {"country_code": r[0], "org_count": r[1]}
            for r in country_q.fetchall()
        ]

        region_q = await self.db.execute(
            text(
                "SELECT COALESCE(data_residency_region, 'nz-au') AS region, "
                "COUNT(*) AS org_count "
                "FROM organisations "
                "GROUP BY data_residency_region "
                "ORDER BY org_count DESC"
            )
        )
        by_region = [
            {"region": r[0], "org_count": r[1]}
            for r in region_q.fetchall()
        ]

        result = {"by_country": by_country, "by_region": by_region}
        await _set_cached(self.redis, cache_key, result, _HISTORICAL_TTL)
        return result

    # ------------------------------------------------------------------
    # get_revenue_metrics
    # ------------------------------------------------------------------

    async def get_revenue_metrics(self) -> dict:
        """Return MRR, ARR, ARPU, LTV by plan tier."""
        cache_key = _cache_key("revenue")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        metrics_q = await self.db.execute(
            text(
                "SELECT sp.name AS plan_name, "
                "COUNT(o.id) AS org_count, "
                "COALESCE(SUM(sp.monthly_price_nzd), 0) AS plan_mrr, "
                "COALESCE(SUM(sp.monthly_price_nzd) * 12, 0) AS plan_arr, "
                "CASE WHEN COUNT(o.id) > 0 "
                "  THEN ROUND(SUM(sp.monthly_price_nzd) / COUNT(o.id), 2) "
                "  ELSE 0 END AS arpu, "
                "CASE WHEN COUNT(o.id) > 0 "
                "  THEN ROUND(SUM(sp.monthly_price_nzd) / COUNT(o.id) * 24, 2) "
                "  ELSE 0 END AS estimated_ltv "
                "FROM subscription_plans sp "
                "LEFT JOIN organisations o ON o.plan_id = sp.id "
                "  AND o.status = 'active' "
                "GROUP BY sp.name "
                "ORDER BY plan_mrr DESC"
            )
        )
        by_plan = [
            {
                "plan_name": r[0],
                "org_count": r[1],
                "mrr": float(r[2]),
                "arr": float(r[3]),
                "arpu": float(r[4]),
                "estimated_ltv": float(r[5]),
            }
            for r in metrics_q.fetchall()
        ]

        # Totals
        total_mrr = sum(p["mrr"] for p in by_plan)
        total_arr = total_mrr * 12
        total_orgs = sum(p["org_count"] for p in by_plan)
        overall_arpu = round(total_mrr / max(total_orgs, 1), 2)

        result = {
            "by_plan": by_plan,
            "total_mrr": total_mrr,
            "total_arr": total_arr,
            "total_orgs": total_orgs,
            "overall_arpu": overall_arpu,
        }
        await _set_cached(self.redis, cache_key, result, _OVERVIEW_TTL)
        return result

    # ------------------------------------------------------------------
    # get_conversion_funnel
    # ------------------------------------------------------------------

    async def get_conversion_funnel(self) -> dict:
        """Return conversion funnel: signup → wizard complete → first invoice → paid.

        Each stage returns a count and conversion rate from previous stage.
        """
        cache_key = _cache_key("conversion_funnel")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        # Stage 1: Total signups (all orgs)
        signup_q = await self.db.execute(
            text("SELECT COUNT(*) FROM organisations")
        )
        signups = signup_q.scalar() or 0

        # Stage 2: Wizard completed
        wizard_q = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM setup_wizard_progress "
                "WHERE wizard_completed = true"
            )
        )
        wizard_complete = wizard_q.scalar() or 0

        # Stage 3: First invoice created
        invoice_q = await self.db.execute(
            text(
                "SELECT COUNT(DISTINCT org_id) FROM invoices"
            )
        )
        first_invoice = invoice_q.scalar() or 0

        # Stage 4: Paid subscription (active, non-trial)
        paid_q = await self.db.execute(
            text(
                "SELECT COUNT(*) FROM organisations "
                "WHERE status = 'active' AND billing_status != 'trial'"
            )
        )
        paid = paid_q.scalar() or 0

        def _rate(current: int, previous: int) -> float:
            return round((current / max(previous, 1)) * 100, 1)

        stages = [
            {"stage": "signup", "count": signups, "rate": 100.0},
            {"stage": "wizard_complete", "count": wizard_complete, "rate": _rate(wizard_complete, signups)},
            {"stage": "first_invoice", "count": first_invoice, "rate": _rate(first_invoice, wizard_complete)},
            {"stage": "paid_subscription", "count": paid, "rate": _rate(paid, first_invoice)},
        ]

        result = {"stages": stages}
        await _set_cached(self.redis, cache_key, result, _OVERVIEW_TTL)
        return result

    # ------------------------------------------------------------------
    # Time-series aggregation (Task 47.3)
    # ------------------------------------------------------------------

    async def get_time_series(
        self,
        metric: str,
        period: Period = "monthly",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """Return time-series data for a metric using date_trunc.

        Supported metrics: signups, revenue, churn.
        """
        cache_key = _cache_key("timeseries", metric=metric, period=period,
                               start=start_date or "", end=end_date or "")
        cached = await _get_cached(self.redis, cache_key)
        if cached is not None:
            return cached

        date_filter = ""
        params: dict[str, Any] = {}
        if start_date:
            date_filter += " AND created_at >= :start_date"
            params["start_date"] = start_date
        if end_date:
            date_filter += " AND created_at <= :end_date"
            params["end_date"] = end_date

        if metric == "signups":
            query = text(
                f"SELECT date_trunc(:period, created_at) AS bucket, "
                f"COUNT(*) AS value "
                f"FROM organisations "
                f"WHERE 1=1 {date_filter} "
                f"GROUP BY bucket ORDER BY bucket"
            )
        elif metric == "revenue":
            query = text(
                f"SELECT date_trunc(:period, o.created_at) AS bucket, "
                f"COALESCE(SUM(sp.monthly_price_nzd), 0) AS value "
                f"FROM organisations o "
                f"JOIN subscription_plans sp ON o.plan_id = sp.id "
                f"WHERE o.status = 'active' {date_filter.replace('created_at', 'o.created_at')} "
                f"GROUP BY bucket ORDER BY bucket"
            )
        elif metric == "churn":
            churn_filter = date_filter.replace("created_at", "updated_at")
            query = text(
                f"SELECT date_trunc(:period, updated_at) AS bucket, "
                f"COUNT(*) AS value "
                f"FROM organisations "
                f"WHERE status IN ('cancelled', 'suspended') {churn_filter} "
                f"GROUP BY bucket ORDER BY bucket"
            )
        else:
            return {"error": f"Unknown metric: {metric}", "data": []}

        params["period"] = period
        result_q = await self.db.execute(query, params)
        data = [
            {"period": r[0].isoformat() if r[0] else None, "value": float(r[1])}
            for r in result_q.fetchall()
        ]

        result = {"metric": metric, "period": period, "data": data}
        await _set_cached(self.redis, cache_key, result, _HISTORICAL_TTL)
        return result
