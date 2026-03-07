"""Module enablement middleware.

Checks whether the requested API endpoint belongs to a module that is
disabled for the requesting organisation. Returns HTTP 403 if the module
is disabled.

Runs after AuthMiddleware (which populates request.state.org_id).

**Validates: Requirement 6.2, 6.6**
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.modules import ModuleService, CORE_MODULES
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)

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
}


def _resolve_module(path: str) -> str | None:
    """Return the module slug for a request path, or None if not gated."""
    for prefix, slug in MODULE_ENDPOINT_MAP.items():
        if path == prefix or path.startswith(prefix + "/"):
            return slug
    return None


class ModuleMiddleware(BaseHTTPMiddleware):
    """Return 403 for requests to endpoints of disabled modules."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        org_id = getattr(request.state, "org_id", None)

        # Only check module-gated paths for authenticated org requests
        if not org_id:
            return await call_next(request)

        module_slug = _resolve_module(path)
        if module_slug is None:
            return await call_next(request)

        # Core modules are always enabled
        if module_slug in CORE_MODULES:
            return await call_next(request)

        try:
            async with async_session_factory() as session:
                async with session.begin():
                    svc = ModuleService(session)
                    enabled = await svc.is_enabled(org_id, module_slug)
        except Exception:
            logger.exception("Module check failed for %s/%s", org_id, module_slug)
            # Fail open — don't block requests if the check itself fails
            return await call_next(request)

        if not enabled:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Module '{module_slug}' is not enabled for your organisation.",
                    "module": module_slug,
                },
            )

        return await call_next(request)
