"""Tenant context middleware — sets app.current_org_id on each DB session for RLS.

After the auth middleware has populated request.state.org_id, this middleware
ensures that every database session opened during the request has the
PostgreSQL session variable `app.current_org_id` set so that RLS policies
filter rows to the correct tenant.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.database import set_current_org_id


class TenantMiddleware(BaseHTTPMiddleware):
    """Propagate the authenticated org_id into a request-scoped context.

    The actual ``SET app.current_org_id`` SQL statement is executed by the
    database session factory (``core/database.py``) which reads the value
    stored here on ``request.state``.  This middleware simply guarantees
    the value is always present (defaulting to ``None`` for global admins
    or unauthenticated requests).
    """

    async def dispatch(self, request: Request, call_next):
        # org_id is set by AuthMiddleware; default to None when absent.
        org_id: str | None = getattr(request.state, "org_id", None)

        # Store in request.state for direct access by route handlers.
        request.state.current_org_id = org_id

        # Store in the context variable so the DB session factory can
        # read it when creating sessions during this request.
        set_current_org_id(org_id)

        response = await call_next(request)
        return response
