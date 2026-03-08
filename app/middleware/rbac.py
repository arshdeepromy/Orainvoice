"""RBAC middleware — enforces role-based path access on every request.

Runs after AuthMiddleware (which populates request.state.role, .user_id,
.org_id) and before route handlers. Checks the user's role against the
requested path and returns 403 if the role is not permitted.

Also loads user permission overrides from the database and attaches them
to request.state for downstream use.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.5, 8.7
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.modules.auth.rbac import (
    check_role_path_access,
    ORG_ADMIN,
    SALESPERSON,
    LOCATION_MANAGER,
    STAFF_MEMBER,
    FRANCHISE_ADMIN,
)
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


class RBACMiddleware:
    """Enforce role-based access control on every authenticated request.

    After path-based checks, loads any user permission overrides from the
    ``user_permission_overrides`` table and attaches them to
    ``request.state.permission_overrides`` for downstream handlers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        user_id = getattr(request.state, "user_id", None)
        role = getattr(request.state, "role", None)
        org_id = getattr(request.state, "org_id", None)

        # Default: no overrides
        request.state.permission_overrides = []

        # Skip for unauthenticated requests (public paths already handled)
        if not user_id or not role:
            await self.app(scope, receive, send)
            return

        path = request.url.path

        # Org-scoped roles must have org membership
        if role in (ORG_ADMIN, SALESPERSON, LOCATION_MANAGER, STAFF_MEMBER) and not org_id:
            response = JSONResponse(
                status_code=403,
                content={"detail": "Organisation membership required"},
            )
            await response(scope, receive, send)
            return

        # Check path-based role access
        denial_reason = check_role_path_access(role, path, method=request.method)
        if denial_reason:
            response = JSONResponse(
                status_code=403,
                content={"detail": denial_reason},
            )
            await response(scope, receive, send)
            return

        # Load permission overrides for the user
        try:
            overrides = await self._load_permission_overrides(user_id)
            request.state.permission_overrides = overrides
        except Exception:
            logger.exception("Failed to load permission overrides for user %s", user_id)
            # Fail open — use base role permissions only
            request.state.permission_overrides = []

        await self.app(scope, receive, send)

    @staticmethod
    async def _load_permission_overrides(user_id: str) -> list[dict]:
        """Load permission overrides from the database for a user."""
        from app.modules.auth.permission_overrides import UserPermissionOverride

        try:
            async with async_session_factory() as session:
                async with session.begin():
                    result = await session.execute(
                        select(
                            UserPermissionOverride.permission_key,
                            UserPermissionOverride.is_granted,
                        ).where(UserPermissionOverride.user_id == user_id)
                    )
                    rows = result.all()
                    return [
                        {"permission_key": row.permission_key, "is_granted": row.is_granted}
                        for row in rows
                    ]
        except Exception:
            logger.exception("Error querying permission overrides")
            return []
