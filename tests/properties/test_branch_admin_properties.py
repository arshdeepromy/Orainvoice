"""Property-based tests for branch_admin role.

# Feature: branch-admin-role, Property 1: branch_admin granted permissions are correct

For any permission key in the granted set, calling
``has_permission("branch_admin", perm)`` should return ``True``.

**Validates: Requirements 1.3, 9.1**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.auth.rbac import has_permission


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

BRANCH_ADMIN_GRANTED_PERMISSIONS = [
    "invoices.*",
    "customers.*",
    "vehicles.*",
    "quotes.*",
    "jobs.*",
    "bookings.*",
    "inventory.*",
    "catalogue.*",
    "expenses.*",
    "purchase_orders.*",
    "scheduling.*",
    "pos.*",
    "staff.*",
    "projects.*",
    "time_tracking.*",
    "claims.*",
    "notifications.*",
    "data_io.*",
    "reports.*",
]

granted_permission_strategy = st.sampled_from(BRANCH_ADMIN_GRANTED_PERMISSIONS)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestP1BranchAdminGrantedPermissions:
    """Property 1: branch_admin granted permissions are correct.

    For any permission key in the granted set, calling
    ``has_permission("branch_admin", perm)`` should return ``True``.

    **Validates: Requirements 1.3, 9.1**
    """

    # Feature: branch-admin-role, Property 1: branch_admin granted permissions are correct

    @settings(max_examples=100)
    @given(perm=granted_permission_strategy)
    def test_branch_admin_has_granted_permission(self, perm: str) -> None:
        """P1: has_permission('branch_admin', perm) returns True for every granted permission."""
        assert has_permission("branch_admin", perm) is True, (
            f"Expected has_permission('branch_admin', '{perm}') to be True"
        )


# ---------------------------------------------------------------------------
# Property 2: branch_admin denied permissions
# ---------------------------------------------------------------------------

BRANCH_ADMIN_DENIED_PERMISSIONS = [
    "billing.*",
    "modules.*",
    "settings.write",
    "users.role_assign",
    "branches.create",
    "branches.delete",
    "org.*",
]

denied_permission_strategy = st.sampled_from(BRANCH_ADMIN_DENIED_PERMISSIONS)


class TestP2BranchAdminDeniedPermissions:
    """Property 2: branch_admin denied permissions are correct.

    For any permission key in the denied set, calling
    ``has_permission("branch_admin", perm)`` should return ``False``.

    **Validates: Requirements 1.4, 9.2**
    """

    # Feature: branch-admin-role, Property 2: branch_admin denied permissions are correct

    @settings(max_examples=100)
    @given(perm=denied_permission_strategy)
    def test_branch_admin_denied_permission(self, perm: str) -> None:
        """P2: has_permission('branch_admin', perm) returns False for every denied permission."""
        assert has_permission("branch_admin", perm) is False, (
            f"Expected has_permission('branch_admin', '{perm}') to be False"
        )


# ---------------------------------------------------------------------------
# Property 3: branch_admin denied org-level paths
# ---------------------------------------------------------------------------

from app.modules.auth.rbac import check_role_path_access

BRANCH_ADMIN_DENIED_PATH_PREFIXES = [
    "/api/v1/billing/",
    "/api/v1/admin/",
    "/api/v1/org/users",
    "/api/v1/org/branches",
]

ALL_HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
WRITE_HTTP_METHODS = ["POST", "PUT", "DELETE", "PATCH"]

denied_prefix_strategy = st.sampled_from(BRANCH_ADMIN_DENIED_PATH_PREFIXES)
http_method_strategy = st.sampled_from(ALL_HTTP_METHODS)
write_method_strategy = st.sampled_from(WRITE_HTTP_METHODS)
path_suffix_strategy = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_/"),
    min_size=0,
    max_size=30,
)


class TestP3BranchAdminDeniedPaths:
    """Property 3: branch_admin denied org-level paths.

    For any HTTP method and any path that starts with a denied prefix,
    ``check_role_path_access("branch_admin", path, method)`` should return
    a non-None denial message. Additionally, write methods on
    ``/api/v1/org/settings`` should return a denial message.

    **Validates: Requirements 1.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
    """

    # Feature: branch-admin-role, Property 3: branch_admin denied org-level paths

    @settings(max_examples=100)
    @given(
        prefix=denied_prefix_strategy,
        suffix=path_suffix_strategy,
        method=http_method_strategy,
    )
    def test_branch_admin_denied_prefix_paths(self, prefix: str, suffix: str, method: str) -> None:
        """P3a: branch_admin is denied access to all paths under denied prefixes."""
        path = prefix + suffix
        result = check_role_path_access("branch_admin", path, method)
        assert result is not None, (
            f"Expected denial for branch_admin on {method} {path}, got None"
        )

    @settings(max_examples=100)
    @given(
        suffix=path_suffix_strategy,
        method=write_method_strategy,
    )
    def test_branch_admin_denied_write_org_settings(self, suffix: str, method: str) -> None:
        """P3b: branch_admin is denied write access to /api/v1/org/settings."""
        path = "/api/v1/org/settings" + suffix
        result = check_role_path_access("branch_admin", path, method)
        assert result is not None, (
            f"Expected denial for branch_admin on {method} {path}, got None"
        )


# ---------------------------------------------------------------------------
# Property 4, 5, 6: BranchContextMiddleware tests for branch_admin
# ---------------------------------------------------------------------------

import uuid
import asyncio
from unittest.mock import patch, AsyncMock

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.branch_context import BranchContextMiddleware

uuid_strategy = st.uuids()


def _build_branch_admin_test_app(
    *,
    role: str = "branch_admin",
    branch_ids: list[str] | None = None,
    org_id: uuid.UUID | None = None,
    captured: dict | None = None,
):
    """Build a minimal Starlette app with BranchContextMiddleware for branch_admin testing.

    Injects role, branch_ids, and org_id into request.state before the
    BranchContextMiddleware runs, simulating what AuthMiddleware would do.
    """

    async def _test_endpoint(request):
        if captured is not None:
            captured["branch_id"] = getattr(request.state, "branch_id", "MISSING")
        return StarletteJSONResponse({"ok": True})

    async def _inject_auth_state(request, call_next):
        request.state.role = role
        request.state.branch_ids = branch_ids or []
        request.state.org_id = str(org_id) if org_id else None
        response = await call_next(request)
        return response

    app = Starlette(
        routes=[Route("/test", _test_endpoint)],
        middleware=[
            Middleware(BaseHTTPMiddleware, dispatch=_inject_auth_state),
            Middleware(BranchContextMiddleware),
        ],
    )
    return app


class TestP4BranchAdminAutoScopedToAssignedBranch:
    """Property 4: branch_admin auto-scoped to assigned branch.

    For any branch_admin user with a non-empty branch_ids list, when the
    middleware processes a request with X-Branch-Id matching branch_ids[0],
    the middleware should set request.state.branch_id to that branch UUID
    and allow the request to proceed.

    **Validates: Requirements 2.1**
    """

    # Feature: branch-admin-role, Property 4: branch_admin auto-scoped to assigned branch

    @settings(max_examples=100)
    @given(branch_id=uuid_strategy)
    def test_branch_admin_auto_scoped_to_assigned_branch(self, branch_id: uuid.UUID) -> None:
        """P4: branch_admin with matching X-Branch-Id header is allowed and branch_id is set."""
        captured: dict = {}
        app = _build_branch_admin_test_app(
            role="branch_admin",
            branch_ids=[str(branch_id)],
            org_id=uuid.uuid4(),
            captured=captured,
        )

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test", headers={"X-Branch-Id": str(branch_id)})

        assert resp.status_code == 200, (
            f"Expected 200 for branch_admin with matching header, got {resp.status_code}: {resp.text}"
        )
        assert captured.get("branch_id") == branch_id, (
            f"Expected branch_id={branch_id}, got {captured.get('branch_id')}"
        )


class TestP5BranchAdminCrossBranchRejection:
    """Property 5: branch_admin cross-branch rejection.

    For any branch_admin user with branch_ids = [B] and any UUID X where X != B,
    when the middleware processes a request with X-Branch-Id = X, the middleware
    should reject the request with HTTP 403.

    **Validates: Requirements 2.2, 3.2, 3.3**
    """

    # Feature: branch-admin-role, Property 5: branch_admin cross-branch rejection

    @settings(max_examples=100)
    @given(
        assigned_branch=uuid_strategy,
        requested_branch=uuid_strategy,
    )
    def test_branch_admin_cross_branch_rejected(
        self, assigned_branch: uuid.UUID, requested_branch: uuid.UUID
    ) -> None:
        """P5: branch_admin requesting a different branch gets 403."""
        from hypothesis import assume

        assume(assigned_branch != requested_branch)

        app = _build_branch_admin_test_app(
            role="branch_admin",
            branch_ids=[str(assigned_branch)],
            org_id=uuid.uuid4(),
        )

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test", headers={"X-Branch-Id": str(requested_branch)})

        assert resp.status_code == 403, (
            f"Expected 403 for cross-branch request (assigned={assigned_branch}, "
            f"requested={requested_branch}), got {resp.status_code}"
        )
        assert resp.json()["detail"] == "Invalid branch context"


class TestP6BranchAdminAllBranchesScopeRejection:
    """Property 6: branch_admin all-branches scope rejection.

    For any branch_admin user (regardless of branch_ids content), when the
    middleware processes a request with no X-Branch-Id header, the middleware
    should reject the request with HTTP 403.

    **Validates: Requirements 2.3**
    """

    # Feature: branch-admin-role, Property 6: branch_admin all-branches scope rejection

    @settings(max_examples=100)
    @given(branch_id=uuid_strategy)
    def test_branch_admin_no_header_rejected(self, branch_id: uuid.UUID) -> None:
        """P6: branch_admin with no X-Branch-Id header gets 403."""
        app = _build_branch_admin_test_app(
            role="branch_admin",
            branch_ids=[str(branch_id)],
            org_id=uuid.uuid4(),
        )

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test")  # No X-Branch-Id header

        assert resp.status_code == 403, (
            f"Expected 403 for branch_admin with no header, got {resp.status_code}"
        )
        assert resp.json()["detail"] == "Invalid branch context"
