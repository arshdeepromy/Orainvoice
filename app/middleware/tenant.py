"""Tenant context middleware — sets app.current_org_id on each DB session for RLS.

After the auth middleware has populated request.state.org_id, this middleware
ensures that every database session opened during the request has the
PostgreSQL session variable `app.current_org_id` set so that RLS policies
filter rows to the correct tenant.
"""

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.database import set_current_org_id


class TenantMiddleware:
    """Propagate the authenticated org_id into a request-scoped context.

    The actual ``SET app.current_org_id`` SQL statement is executed by the
    database session factory (``core/database.py``) which reads the value
    stored here on ``request.state``.  This middleware simply guarantees
    the value is always present (defaulting to ``None`` for global admins
    or unauthenticated requests).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        org_id: str | None = getattr(request.state, "org_id", None)
        request.state.current_org_id = org_id
        set_current_org_id(org_id)

        await self.app(scope, receive, send)
