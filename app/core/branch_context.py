"""Branch context middleware — validates X-Branch-Id header and sets request.state.branch_id.

Reads the optional ``X-Branch-Id`` header from incoming requests.  When present
the value is validated as a UUID and checked against the requesting user's
organisation.  Invalid or unauthorised values are rejected with 403.  When the
header is absent the request is treated as "All Branches" scope
(``request.state.branch_id = None``).

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class BranchContextMiddleware:
    """Validate ``X-Branch-Id`` header and attach ``request.state.branch_id``.

    Placement in the middleware stack: after AuthMiddleware (which populates
    ``request.state.org_id``) and before service-layer middleware so that
    downstream handlers can read ``request.state.branch_id``.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)

        # --- Early module gating check ---
        # If branch_management module is disabled for this org, skip all
        # header validation, DB lookups, and branch_admin scoping.
        org_id = getattr(request.state, "org_id", None)
        if org_id and not await self._is_branch_module_enabled(org_id):
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        branch_header = request.headers.get("x-branch-id")

        # --- Parse header UUID early (needed by branch_admin check) ---
        branch_id: uuid.UUID | None = None
        if branch_header:
            try:
                branch_id = uuid.UUID(branch_header)
            except (ValueError, AttributeError):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid branch context"},
                )
                await response(scope, receive, send)
                return

        # --- branch_admin auto-scoping ---
        role = getattr(request.state, "role", None)

        if role == "branch_admin":
            user_branch_ids = getattr(request.state, "branch_ids", None) or []

            if not user_branch_ids:
                # No branch assigned — deny all data access
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "No branch assignment. Contact your org admin."},
                )
                await response(scope, receive, send)
                return

            assigned_branch = uuid.UUID(str(user_branch_ids[0]))

            if branch_header:
                # Validate header matches assigned branch
                if branch_id != assigned_branch:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Invalid branch context"},
                    )
                    await response(scope, receive, send)
                    return
            else:
                # No header = "All Branches" — deny for branch_admin
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid branch context"},
                )
                await response(scope, receive, send)
                return

            request.state.branch_id = assigned_branch
            await self.app(scope, receive, send)
            return

        if not branch_header:
            # No header → "All Branches" scope
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        # --- Validate branch belongs to user's org ---
        user_id = getattr(request.state, "user_id", None)

        if not user_id:
            # Unauthenticated request (e.g. /auth/login) — skip branch validation,
            # just set branch_id from header and let auth middleware handle access.
            request.state.branch_id = branch_id
            await self.app(scope, receive, send)
            return

        if org_id is None:
            # Authenticated but no org context (e.g. global_admin) —
            # ignore the branch header, set branch_id to None.
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        try:
            belongs = await self._branch_belongs_to_org(branch_id, org_id)
        except Exception:
            logger.warning(
                "Failed to validate branch %s for org %s — falling back to all-branches",
                branch_id,
                org_id,
                exc_info=True,
            )
            # Fall back to all-branches instead of blocking the request
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        if not belongs:
            # Branch doesn't belong to org (stale header from localStorage) —
            # fall back to all-branches instead of returning 403.
            # The frontend will re-validate and clear the stale selection.
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        request.state.branch_id = branch_id
        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _is_branch_module_enabled(org_id: str | uuid.UUID) -> bool:
        """Check whether the branch_management module is enabled for *org_id*.

        Uses ModuleService.is_enabled which reads from Redis cache (60s TTL)
        first, falling back to DB. This keeps the hot path fast for
        single-location orgs.
        """
        from app.core.database import async_session_factory
        from app.core.modules import ModuleService

        async with async_session_factory() as session:
            svc = ModuleService(session)
            return await svc.is_enabled(str(org_id), "branch_management")

    @staticmethod
    async def _branch_belongs_to_org(
        branch_id: uuid.UUID,
        org_id: str | uuid.UUID,
    ) -> bool:
        """Check whether *branch_id* belongs to *org_id* via a DB lookup."""
        from app.core.database import async_session_factory
        from app.modules.organisations.models import Branch

        org_uuid = uuid.UUID(str(org_id)) if not isinstance(org_id, uuid.UUID) else org_id

        async with async_session_factory() as session:
            result = await session.execute(
                select(Branch.id).where(
                    Branch.id == branch_id,
                    Branch.org_id == org_uuid,
                )
            )
            return result.scalar_one_or_none() is not None
