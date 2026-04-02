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
        branch_header = request.headers.get("x-branch-id")

        if not branch_header:
            # No header → "All Branches" scope
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

        # --- Validate UUID format ---
        try:
            branch_id = uuid.UUID(branch_header)
        except (ValueError, AttributeError):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Invalid branch context"},
            )
            await response(scope, receive, send)
            return

        # --- Validate branch belongs to user's org ---
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            # No org context (e.g. unauthenticated or global admin without
            # org context) — cannot validate ownership, reject.
            response = JSONResponse(
                status_code=403,
                content={"detail": "Invalid branch context"},
            )
            await response(scope, receive, send)
            return

        try:
            belongs = await self._branch_belongs_to_org(branch_id, org_id)
        except Exception:
            logger.warning(
                "Failed to validate branch %s for org %s",
                branch_id,
                org_id,
                exc_info=True,
            )
            response = JSONResponse(
                status_code=403,
                content={"detail": "Invalid branch context"},
            )
            await response(scope, receive, send)
            return

        if not belongs:
            response = JSONResponse(
                status_code=403,
                content={"detail": "Invalid branch context"},
            )
            await response(scope, receive, send)
            return

        request.state.branch_id = branch_id
        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
