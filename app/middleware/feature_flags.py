"""Feature flag middleware — gates API endpoints by feature flag evaluation.

Intercepts authenticated API requests and returns HTTP 403 when the
corresponding feature flag is disabled for the requesting organisation.
Core flags (invoicing, customers, notifications) always pass through.

Evaluated flags are cached per-org in Redis with a configurable TTL
(default 30 seconds). On any error (Redis, DB, evaluation), the middleware
fails open and allows the request to proceed.

Runs after RBAC middleware (which populates request.state.org_id) and
before Module middleware.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7**
"""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cache TTL (seconds). Override via settings if available.
# ---------------------------------------------------------------------------
DEFAULT_CACHE_TTL = 30

# ---------------------------------------------------------------------------
# URL path prefix → feature flag key mapping.
# Only /api/v2/ paths listed here are gated by feature flags.
# ---------------------------------------------------------------------------
FLAG_ENDPOINT_MAP: dict[str, str] = {
    "/api/v2/quotes": "quotes",
    "/api/v2/jobs": "jobs",
    "/api/v2/projects": "projects",
    "/api/v2/time-entries": "time_tracking",
    "/api/v2/expenses": "expenses",
    "/api/v2/products": "inventory",
    "/api/v2/stock": "inventory",
    "/api/v2/purchase-orders": "purchase_orders",
    "/api/v2/pos": "pos",
    "/api/v2/tips": "tipping",
    "/api/v2/tables": "tables",
    "/api/v2/kitchen": "kitchen_display",
    "/api/v2/schedule": "scheduling",
    "/api/v2/staff": "staff",
    "/api/v2/bookings": "bookings",
    "/api/v2/progress-claims": "progress_claims",
    "/api/v2/retentions": "retentions",
    "/api/v2/variations": "variations",
    "/api/v2/compliance-docs": "compliance_docs",
    "/api/v2/currencies": "multi_currency",
    "/api/v2/recurring": "recurring",
    "/api/v2/loyalty": "loyalty",
    "/api/v2/franchise": "franchise",
    "/api/v2/ecommerce": "ecommerce",
    "/api/v2/admin/branding": "branding",
    "/api/v2/assets": "assets",
    "/api/v2/reports": "reports",
    "/api/v2/portal": "portal",
    "/api/v2/admin/analytics": "analytics",
    "/api/v2/i18n": "i18n",
    "/api/v2/admin/migrations": "migration_tool",
    "/api/v2/printers": "receipt_printer",
}

# ---------------------------------------------------------------------------
# Core flags — always allowed regardless of evaluation result.
# ---------------------------------------------------------------------------
CORE_FLAGS: set[str] = {"invoicing", "customers", "notifications"}

# ---------------------------------------------------------------------------
# Redis cache key prefix for per-org evaluated flag maps.
# ---------------------------------------------------------------------------
_CACHE_KEY_PREFIX = "ff:"


def _get_cache_ttl() -> int:
    """Return the feature flag cache TTL in seconds."""
    try:
        from app.config import settings
        return int(getattr(settings, "feature_flag_cache_ttl", DEFAULT_CACHE_TTL))
    except Exception:
        return DEFAULT_CACHE_TTL


def _resolve_flag_key(path: str) -> str | None:
    """Return the feature flag key for a request path, or None if not gated."""
    for prefix, flag_key in FLAG_ENDPOINT_MAP.items():
        if path == prefix or path.startswith(prefix + "/"):
            return flag_key
    return None


class FeatureFlagMiddleware:
    """Gate API endpoints by feature flag evaluation.

    For each authenticated request to a mapped path prefix, the middleware:
    1. Resolves the path to a flag key via ``FLAG_ENDPOINT_MAP``
    2. Skips core flags (always allowed)
    3. Checks Redis cache (``ff:{org_id}``) for the org's evaluated flags
    4. On cache miss, evaluates via the service and caches the result
    5. Returns 403 if the flag evaluates to ``False``
    6. Fails open on any error
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        org_id = getattr(request.state, "org_id", None)

        # Skip unauthenticated requests (no org context)
        if not org_id:
            await self.app(scope, receive, send)
            return

        # Resolve path to flag key
        flag_key = _resolve_flag_key(path)
        if flag_key is None:
            await self.app(scope, receive, send)
            return

        # Core flags always pass through
        if flag_key in CORE_FLAGS:
            await self.app(scope, receive, send)
            return

        # Evaluate the flag (cache-first, fail-open)
        try:
            flag_value = await self._evaluate_flag(org_id, flag_key)
        except Exception:
            logger.exception(
                "Feature flag evaluation failed for org=%s flag=%s, failing open",
                org_id,
                flag_key,
            )
            await self.app(scope, receive, send)
            return

        if not flag_value:
            response = JSONResponse(
                status_code=403,
                content={
                    "detail": f"Feature '{flag_key}' is disabled for your organisation.",
                    "flag_key": flag_key,
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    async def _evaluate_flag(self, org_id: str, flag_key: str) -> bool:
        """Evaluate a flag for an org, using Redis cache with fallback to DB.

        Returns ``True`` (allow) on any error (fail-open behaviour).
        """
        cache_key = f"{_CACHE_KEY_PREFIX}{org_id}"

        # 1. Try Redis cache — stored as a JSON dict of {flag_key: bool}
        try:
            cached_raw = await redis_pool.get(cache_key)
            if cached_raw is not None:
                cached_flags: dict[str, bool] = json.loads(cached_raw)
                if flag_key in cached_flags:
                    return cached_flags[flag_key]
        except Exception as exc:
            logger.warning(
                "Redis read failed for ff cache org=%s: %s", org_id, exc
            )

        # 2. Cache miss — evaluate all flags via the service and cache
        try:
            from app.core.database import async_session_factory
            from app.modules.feature_flags.service import FeatureFlagCRUDService

            async with async_session_factory() as session:
                async with session.begin():
                    svc = FeatureFlagCRUDService(session)
                    evaluations = await svc.evaluate_all_for_org(str(org_id))

            # Build the flag map
            flag_map: dict[str, bool] = {e.key: e.enabled for e in evaluations}
        except Exception as exc:
            logger.warning(
                "Flag evaluation from DB failed for org=%s: %s, failing open",
                org_id,
                exc,
            )
            return True  # fail-open

        # 3. Cache the full flag map in Redis
        try:
            ttl = _get_cache_ttl()
            await redis_pool.setex(cache_key, ttl, json.dumps(flag_map))
        except Exception as exc:
            logger.warning("Redis write failed for ff cache org=%s: %s", org_id, exc)

        # 4. Return the evaluated value (default True = fail-open if key missing)
        return flag_map.get(flag_key, True)
