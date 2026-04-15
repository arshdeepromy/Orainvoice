"""Module enablement middleware.

Checks whether the requested API endpoint belongs to a module that is
disabled for the requesting organisation. Returns HTTP 403 if the module
is disabled. Results are cached in Redis per-org for 60 seconds.

Runs after AuthMiddleware (which populates request.state.org_id).

**Validates: Requirement 6.2, 6.6**
"""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.modules import ModuleService, CORE_MODULES
from app.core.database import async_session_factory
from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# Cache module enablement per-org for 60 seconds
_MODULE_CACHE_TTL = 60
_MODULE_CACHE_PREFIX = "mod:"

# ---------------------------------------------------------------------------
# URL path prefix → module slug mapping
# Only /api/v2/ paths are gated by module enablement.
# ---------------------------------------------------------------------------

MODULE_ENDPOINT_MAP: dict[str, str] = {
    "/api/v2/inventory": "inventory",
    "/api/v2/products": "inventory",
    "/api/v2/stock": "inventory",
    "/api/v2/pos": "pos",
    "/api/v2/jobs": "jobs",
    "/api/v2/quotes": "quotes",
    "/api/v2/time-tracking": "time_tracking",
    "/api/v2/projects": "projects",
    "/api/v2/expenses": "expenses",
    "/api/v2/purchase-orders": "purchase_orders",
    "/api/v2/staff": "staff",
    "/api/v2/schedule": "scheduling",
    "/api/v2/bookings": "bookings",
    "/api/v2/tables": "tables",
    "/api/v2/kitchen": "kitchen_display",
    "/api/v2/tipping": "tipping",
    "/api/v2/recurring": "recurring",
    "/api/v2/progress-claims": "progress_claims",
    "/api/v2/retentions": "retentions",
    "/api/v2/variations": "variations",
    "/api/v2/compliance-docs": "compliance_docs",
    "/api/v2/multi-currency": "multi_currency",
    "/api/v2/loyalty": "loyalty",
    "/api/v2/franchise": "franchise",
    "/api/v2/ecommerce": "ecommerce",
    "/api/v1/vehicles": "vehicles",
    "/api/v1/ledger": "accounting",
    "/api/v1/gst": "accounting",
    "/api/v1/banking": "accounting",
    "/api/v1/tax-wallets": "accounting",
    "/api/v1/ird": "accounting",
}


def _resolve_module(path: str) -> str | None:
    """Return the module slug for a request path, or None if not gated."""
    for prefix, slug in MODULE_ENDPOINT_MAP.items():
        if path == prefix or path.startswith(prefix + "/"):
            return slug
    return None


class ModuleMiddleware:
    """Return 403 for requests to endpoints of disabled modules."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        path = request.url.path
        org_id = getattr(request.state, "org_id", None)

        # Only check module-gated paths for authenticated org requests
        if not org_id:
            await self.app(scope, receive, send)
            return

        module_slug = _resolve_module(path)
        if module_slug is None:
            await self.app(scope, receive, send)
            return

        # Core modules are always enabled
        if module_slug in CORE_MODULES:
            await self.app(scope, receive, send)
            return

        try:
            enabled = await self._is_module_enabled_cached(str(org_id), module_slug)
        except Exception:
            logger.exception("Module check failed for %s/%s", org_id, module_slug)
            # Fail open — don't block requests if the check itself fails
            await self.app(scope, receive, send)
            return

        if not enabled:
            response = JSONResponse(
                status_code=403,
                content={
                    "detail": f"Module '{module_slug}' is not enabled for your organisation.",
                    "module": module_slug,
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _is_module_enabled_cached(org_id: str, module_slug: str) -> bool:
        """Check module enablement with Redis cache."""
        cache_key = f"{_MODULE_CACHE_PREFIX}{org_id}"

        # Try Redis cache — stored as JSON dict {slug: bool}
        try:
            cached = await redis_pool.get(cache_key)
            if cached is not None:
                module_map = json.loads(cached)
                if module_slug in module_map:
                    return module_map[module_slug]
        except Exception:
            pass  # Fall through to DB

        # Cache miss — load all modules for this org and cache
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    svc = ModuleService(session)
                    enabled = await svc.is_enabled(org_id, module_slug)
        except Exception:
            raise

        # We only cache the single result here; the full map gets built over time
        try:
            # Merge with existing cache if present
            existing = {}
            raw = await redis_pool.get(cache_key)
            if raw:
                existing = json.loads(raw)
            existing[module_slug] = enabled
            await redis_pool.setex(cache_key, _MODULE_CACHE_TTL, json.dumps(existing))
        except Exception:
            pass

        return enabled
