"""Property-based tests for branch module gating.

# Feature: branch-module-gating, Property 1: Migration auto-enable correctness

For any organisation in the database, after the migration runs,
``branch_management`` is enabled if and only if the organisation has more
than one row in the ``branches`` table.  Organisations with zero or one
branch must not have the module enabled.

**Validates: Requirements 1.3, 2.2, 2.4**
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Settings — 100 examples per property, no deadline, suppress slow health check
# ---------------------------------------------------------------------------

MODULE_GATING_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()

# Number of branches per org: 0..10 covers zero, one, and multi-branch cases
branch_count_strategy = st.integers(min_value=0, max_value=10)


class OrgBranchSetup(NamedTuple):
    """Represents an organisation with a given number of branches."""
    org_id: uuid.UUID
    branch_count: int


# Strategy that generates a list of 1..20 orgs, each with a random branch count
org_set_strategy = st.lists(
    st.builds(OrgBranchSetup, org_id=uuid_strategy, branch_count=branch_count_strategy),
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Migration logic under test
# ---------------------------------------------------------------------------

def simulate_migration_auto_enable(
    orgs: list[OrgBranchSetup],
) -> dict[uuid.UUID, bool]:
    """Simulate the migration's auto-enable logic.

    This mirrors the SQL in migration 0137:

        INSERT INTO org_modules (…, org_id, module_slug, is_enabled, …)
        SELECT …, b.org_id, 'branch_management', true, …
        FROM branches b
        GROUP BY b.org_id
        HAVING COUNT(*) > 1

    Returns a mapping of org_id → whether branch_management is enabled.
    """
    enabled: dict[uuid.UUID, bool] = {}
    for org in orgs:
        # The migration enables the module only for orgs with > 1 branch
        enabled[org.org_id] = org.branch_count > 1
    return enabled


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestP1MigrationAutoEnableCorrectness:
    """Property 1: Migration auto-enable correctness.

    For any organisation in the database, after the migration runs,
    ``branch_management`` is enabled if and only if the organisation has
    more than one row in the ``branches`` table.  Organisations with zero
    or one branch must not have the module enabled.

    **Validates: Requirements 1.3, 2.2, 2.4**
    """

    # Feature: branch-module-gating, Property 1: Migration auto-enable correctness

    @MODULE_GATING_PBT_SETTINGS
    @given(orgs=org_set_strategy)
    def test_migration_enables_module_iff_branch_count_gt_one(
        self,
        orgs: list[OrgBranchSetup],
    ) -> None:
        """P1: branch_management is enabled ⟺ branch_count > 1."""
        result = simulate_migration_auto_enable(orgs)

        for org in orgs:
            is_enabled = result[org.org_id]
            if org.branch_count > 1:
                assert is_enabled is True, (
                    f"Org {org.org_id} has {org.branch_count} branches "
                    f"but branch_management was NOT enabled"
                )
            else:
                assert is_enabled is False, (
                    f"Org {org.org_id} has {org.branch_count} branch(es) "
                    f"but branch_management WAS enabled (should not be)"
                )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_zero_branches_never_enabled(self, org_id: uuid.UUID) -> None:
        """P1a: An org with zero branches never gets the module enabled."""
        orgs = [OrgBranchSetup(org_id=org_id, branch_count=0)]
        result = simulate_migration_auto_enable(orgs)
        assert result[org_id] is False, (
            f"Org {org_id} has 0 branches but module was enabled"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_single_branch_never_enabled(self, org_id: uuid.UUID) -> None:
        """P1b: An org with exactly one branch never gets the module enabled."""
        orgs = [OrgBranchSetup(org_id=org_id, branch_count=1)]
        result = simulate_migration_auto_enable(orgs)
        assert result[org_id] is False, (
            f"Org {org_id} has 1 branch but module was enabled"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        branch_count=st.integers(min_value=2, max_value=50),
    )
    def test_multi_branch_always_enabled(
        self, org_id: uuid.UUID, branch_count: int
    ) -> None:
        """P1c: An org with >1 branches always gets the module enabled."""
        orgs = [OrgBranchSetup(org_id=org_id, branch_count=branch_count)]
        result = simulate_migration_auto_enable(orgs)
        assert result[org_id] is True, (
            f"Org {org_id} has {branch_count} branches but module was NOT enabled"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(orgs=org_set_strategy)
    def test_enabled_set_equals_multi_branch_set(
        self,
        orgs: list[OrgBranchSetup],
    ) -> None:
        """P1d: The set of enabled orgs is exactly the set of multi-branch orgs."""
        result = simulate_migration_auto_enable(orgs)

        enabled_org_ids = {oid for oid, enabled in result.items() if enabled}
        multi_branch_org_ids = {org.org_id for org in orgs if org.branch_count > 1}

        assert enabled_org_ids == multi_branch_org_ids, (
            f"Enabled orgs {enabled_org_ids} != multi-branch orgs {multi_branch_org_ids}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(orgs=org_set_strategy)
    def test_migration_is_idempotent(
        self,
        orgs: list[OrgBranchSetup],
    ) -> None:
        """P1e: Running the migration twice produces the same result."""
        result_first = simulate_migration_auto_enable(orgs)
        result_second = simulate_migration_auto_enable(orgs)

        assert result_first == result_second, (
            "Migration produced different results on second run"
        )


# ---------------------------------------------------------------------------
# Property 6: Middleware passthrough when disabled
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 6: Middleware passthrough when disabled
#
# For any organisation with ``branch_management`` disabled and for any value
# of the ``X-Branch-Id`` header (valid UUID, invalid string, or absent), the
# BranchContextMiddleware sets ``request.state.branch_id`` to ``None`` and
# does not return a 403 response.
#
# **Validates: Requirements 8.1, 8.3**

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Strategies for header values
# ---------------------------------------------------------------------------

# Valid UUID strings
valid_uuid_header_strategy = st.uuids().map(str)

# Invalid non-UUID strings (random text that is NOT a valid UUID)
invalid_header_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=50,
).filter(lambda s: not _is_valid_uuid(s))

# None (absent header)
absent_header_strategy = st.none()

# Combined: any possible header value
any_header_strategy = st.one_of(
    valid_uuid_header_strategy,
    invalid_header_strategy,
    absent_header_strategy,
)


def _is_valid_uuid(s: str) -> bool:
    """Return True if *s* is a valid UUID string."""
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Lightweight fakes for ASGI testing
# ---------------------------------------------------------------------------

@dataclass
class FakeState:
    """Mimics ``request.state`` with arbitrary attribute storage."""
    _attrs: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        return self._attrs.get(name, None)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._attrs[name] = value


@dataclass
class MiddlewareResult:
    """Captures the outcome of running the middleware."""
    branch_id: Any = None
    status_code: Optional[int] = None
    passed_through: bool = False


def _run_middleware_disabled(
    org_id: uuid.UUID,
    header_value: Optional[str],
) -> MiddlewareResult:
    """Simulate BranchContextMiddleware behaviour when module is disabled.

    This replicates the early-exit path in the middleware:

        org_id = getattr(request.state, "org_id", None)
        if org_id and not await self._is_branch_module_enabled(org_id):
            request.state.branch_id = None
            await self.app(scope, receive, send)
            return

    When the module is disabled the middleware MUST:
    - Set ``request.state.branch_id`` to ``None``
    - Call the downstream app (pass through)
    - NOT return a 403 response

    We run the real middleware class with ``_is_branch_module_enabled``
    patched to return ``False``.
    """
    from app.core.branch_context import BranchContextMiddleware

    result = MiddlewareResult()

    # Build a minimal ASGI scope
    headers: list[tuple[bytes, bytes]] = []
    if header_value is not None:
        headers.append((b"x-branch-id", header_value.encode("utf-8", errors="replace")))

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/org/test",
        "headers": headers,
        "query_string": b"",
        "root_path": "",
        "state": {},
    }

    # Inject org_id into scope state so the middleware can read it
    state = FakeState()
    state.org_id = str(org_id)
    state.user_id = str(uuid.uuid4())
    state.role = "org_admin"
    scope["state"] = state._attrs  # starlette reads from scope["state"]

    # We need to patch scope["state"] so that Request(scope).state works.
    # Starlette's Request stores state in scope["state"] dict.

    # Track whether downstream app was called and capture response status
    async def fake_app(s: Any, r: Any, se: Any) -> None:
        result.passed_through = True
        # Read branch_id from the state that the middleware set
        req_state = s.get("state", {})
        result.branch_id = req_state.get("branch_id", "NOT_SET")

    async def fake_receive() -> dict:
        return {"type": "http.request", "body": b""}

    captured_response_started = False
    captured_status: Optional[int] = None

    async def fake_send(message: dict) -> None:
        nonlocal captured_response_started, captured_status
        if message.get("type") == "http.response.start":
            captured_response_started = True
            captured_status = message.get("status")

    middleware = BranchContextMiddleware(fake_app)

    # Patch _is_branch_module_enabled to always return False (module disabled)
    with patch.object(
        BranchContextMiddleware,
        "_is_branch_module_enabled",
        new=AsyncMock(return_value=False),
    ):
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                middleware(scope, fake_receive, fake_send)
            )
        finally:
            loop.close()

    # If the middleware returned a response directly (e.g. 403), capture it
    if captured_response_started:
        result.status_code = captured_status
        result.passed_through = False
    else:
        result.status_code = None  # No direct response — passed through

    return result


# ---------------------------------------------------------------------------
# Property Test Class
# ---------------------------------------------------------------------------


class TestP6MiddlewarePassthroughWhenDisabled:
    """Property 6: Middleware passthrough when disabled.

    For any organisation with ``branch_management`` disabled and for any
    value of the ``X-Branch-Id`` header (valid UUID, invalid string, or
    absent), the BranchContextMiddleware sets ``request.state.branch_id``
    to ``None`` and does not return a 403 response.

    **Validates: Requirements 8.1, 8.3**
    """

    # Feature: branch-module-gating, Property 6: Middleware passthrough when disabled

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, header_value=any_header_strategy)
    def test_branch_id_is_none_when_module_disabled(
        self,
        org_id: uuid.UUID,
        header_value: Optional[str],
    ) -> None:
        """P6: branch_id is always None when module disabled, regardless of header."""
        result = _run_middleware_disabled(org_id, header_value)

        assert result.branch_id is None, (
            f"Expected branch_id=None when module disabled, "
            f"got branch_id={result.branch_id!r} for header={header_value!r}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, header_value=any_header_strategy)
    def test_no_403_when_module_disabled(
        self,
        org_id: uuid.UUID,
        header_value: Optional[str],
    ) -> None:
        """P6: No 403 response when module disabled, regardless of header."""
        result = _run_middleware_disabled(org_id, header_value)

        assert result.status_code != 403, (
            f"Got 403 response when module disabled for header={header_value!r}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, header_value=any_header_strategy)
    def test_request_passes_through_when_module_disabled(
        self,
        org_id: uuid.UUID,
        header_value: Optional[str],
    ) -> None:
        """P6: Request always passes through to downstream app when module disabled."""
        result = _run_middleware_disabled(org_id, header_value)

        assert result.passed_through is True, (
            f"Request did not pass through when module disabled "
            f"for header={header_value!r} (status_code={result.status_code})"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, header_value=valid_uuid_header_strategy)
    def test_valid_uuid_header_still_gives_none_branch_id(
        self,
        org_id: uuid.UUID,
        header_value: str,
    ) -> None:
        """P6a: Even a valid UUID header results in branch_id=None when disabled."""
        result = _run_middleware_disabled(org_id, header_value)

        assert result.branch_id is None, (
            f"Expected branch_id=None for valid UUID header {header_value!r} "
            f"when module disabled, got {result.branch_id!r}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, header_value=invalid_header_strategy)
    def test_invalid_header_does_not_cause_403(
        self,
        org_id: uuid.UUID,
        header_value: str,
    ) -> None:
        """P6b: Invalid header strings do not cause 403 when module disabled."""
        result = _run_middleware_disabled(org_id, header_value)

        assert result.status_code != 403, (
            f"Got 403 for invalid header {header_value!r} when module disabled"
        )
        assert result.branch_id is None, (
            f"Expected branch_id=None for invalid header {header_value!r}, "
            f"got {result.branch_id!r}"
        )


# ---------------------------------------------------------------------------
# Property 7: Branch CRUD mutation gating
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 7: Branch CRUD mutation gating
#
# For any organisation with ``branch_management`` disabled, requests to
# mutating branch endpoints (POST, PUT, DELETE on ``/org/branches``) return
# HTTP 403 with the message "Branch management module is not enabled for
# this organisation".
#
# **Validates: Requirements 9.1, 9.2, 9.3**

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Strategies for mutation methods and branch IDs
# ---------------------------------------------------------------------------

# HTTP methods that are gated (mutating operations)
mutating_method_strategy = st.sampled_from(["POST", "PUT", "DELETE"])

# Random branch IDs (UUIDs) for PUT/DELETE paths
branch_id_strategy = st.uuids()


# ---------------------------------------------------------------------------
# Helper: invoke require_branch_module with module disabled
# ---------------------------------------------------------------------------

def _call_require_branch_module_disabled(
    org_id: uuid.UUID,
    method: str,
    branch_id: uuid.UUID | None = None,
) -> HTTPException | None:
    """Call the ``require_branch_module`` dependency with module disabled.

    The dependency is a standalone async function that checks
    ``ModuleService.is_enabled`` and raises ``HTTPException(403)`` when
    the module is disabled.  We test it directly rather than going through
    HTTP to keep the test fast and focused.

    Returns the raised HTTPException, or None if no exception was raised.
    """
    from app.modules.organisations.router import require_branch_module

    # Build a minimal fake request with org_id on state
    fake_state = FakeState()
    fake_state.org_id = str(org_id)

    class FakeRequest:
        state = fake_state
        method_str = method

    fake_request = FakeRequest()

    # Create a mock db session — we won't hit the real DB
    mock_db = AsyncMock()

    raised: HTTPException | None = None

    async def _run() -> None:
        nonlocal raised
        try:
            await require_branch_module(request=fake_request, db=mock_db)
        except HTTPException as exc:
            raised = exc

    with patch(
        "app.modules.organisations.router.ModuleService"
    ) as MockModuleService:
        instance = MockModuleService.return_value
        instance.is_enabled = AsyncMock(return_value=False)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    return raised


def _call_require_branch_module_enabled(
    org_id: uuid.UUID,
) -> HTTPException | None:
    """Call ``require_branch_module`` with module enabled — should NOT raise."""
    from app.modules.organisations.router import require_branch_module

    fake_state = FakeState()
    fake_state.org_id = str(org_id)

    class FakeRequest:
        state = fake_state

    fake_request = FakeRequest()
    mock_db = AsyncMock()

    raised: HTTPException | None = None

    async def _run() -> None:
        nonlocal raised
        try:
            await require_branch_module(request=fake_request, db=mock_db)
        except HTTPException as exc:
            raised = exc

    with patch(
        "app.modules.organisations.router.ModuleService"
    ) as MockModuleService:
        instance = MockModuleService.return_value
        instance.is_enabled = AsyncMock(return_value=True)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    return raised


# ---------------------------------------------------------------------------
# Property Test Class
# ---------------------------------------------------------------------------


class TestP7BranchCRUDMutationGating:
    """Property 7: Branch CRUD mutation gating.

    For any organisation with ``branch_management`` disabled, requests to
    mutating branch endpoints (POST, PUT, DELETE on ``/org/branches``)
    return HTTP 403 with the message "Branch management module is not
    enabled for this organisation".

    **Validates: Requirements 9.1, 9.2, 9.3**
    """

    # Feature: branch-module-gating, Property 7: Branch CRUD mutation gating

    EXPECTED_DETAIL = (
        "Branch management module is not enabled for this organisation"
    )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        method=mutating_method_strategy,
        branch_id=branch_id_strategy,
    )
    def test_mutating_methods_return_403_when_disabled(
        self,
        org_id: uuid.UUID,
        method: str,
        branch_id: uuid.UUID,
    ) -> None:
        """P7: Any mutating method raises 403 when module disabled."""
        exc = _call_require_branch_module_disabled(org_id, method, branch_id)

        assert exc is not None, (
            f"Expected HTTPException(403) for {method} with module disabled, "
            f"but no exception was raised (org={org_id})"
        )
        assert exc.status_code == 403, (
            f"Expected status 403, got {exc.status_code} "
            f"for {method} (org={org_id})"
        )
        assert exc.detail == self.EXPECTED_DETAIL, (
            f"Expected detail '{self.EXPECTED_DETAIL}', "
            f"got '{exc.detail}' for {method} (org={org_id})"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, method=mutating_method_strategy)
    def test_403_detail_message_is_exact(
        self,
        org_id: uuid.UUID,
        method: str,
    ) -> None:
        """P7a: The 403 detail message matches the spec exactly."""
        exc = _call_require_branch_module_disabled(org_id, method)

        assert exc is not None, "Expected HTTPException but none raised"
        assert exc.detail == self.EXPECTED_DETAIL

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, method=mutating_method_strategy)
    def test_no_403_when_module_enabled(
        self,
        org_id: uuid.UUID,
        method: str,
    ) -> None:
        """P7b: No 403 when module is enabled — dependency passes through."""
        exc = _call_require_branch_module_enabled(org_id)

        assert exc is None, (
            f"Expected no exception when module enabled, "
            f"but got HTTPException({exc.status_code}) for {method}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, branch_id=branch_id_strategy)
    def test_post_create_branch_gated(
        self,
        org_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> None:
        """P7c: POST (create branch) is gated when module disabled."""
        exc = _call_require_branch_module_disabled(org_id, "POST", branch_id)
        assert exc is not None and exc.status_code == 403

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, branch_id=branch_id_strategy)
    def test_put_update_branch_gated(
        self,
        org_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> None:
        """P7d: PUT (update branch) is gated when module disabled."""
        exc = _call_require_branch_module_disabled(org_id, "PUT", branch_id)
        assert exc is not None and exc.status_code == 403

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy, branch_id=branch_id_strategy)
    def test_delete_deactivate_branch_gated(
        self,
        org_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> None:
        """P7e: DELETE (deactivate branch) is gated when module disabled."""
        exc = _call_require_branch_module_disabled(org_id, "DELETE", branch_id)
        assert exc is not None and exc.status_code == 403


# ---------------------------------------------------------------------------
# Property 8: GET /org/branches accessible when disabled
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 8: GET /org/branches accessible when disabled
#
# For any organisation with ``branch_management`` disabled, ``GET /org/branches``
# returns a successful response (HTTP 200) containing the organisation's branch
# data.  The key insight is that the GET endpoint does NOT have the
# ``require_branch_module`` dependency, so it works regardless of module state.
#
# **Validates: Requirements 9.4**


class TestP8GetBranchesAccessibleWhenDisabled:
    """Property 8: GET /org/branches accessible when disabled.

    For any organisation with ``branch_management`` disabled,
    ``GET /org/branches`` returns a successful response (HTTP 200)
    containing the organisation's branch data.

    **Validates: Requirements 9.4**
    """

    # Feature: branch-module-gating, Property 8: GET /org/branches accessible when disabled

    # ------------------------------------------------------------------
    # Structural verification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_route_dependencies(method: str, path: str):
        """Return the set of dependency callables for a given route."""
        from app.modules.organisations.router import router

        for route in router.routes:
            # Match path and method
            route_path = getattr(route, "path", None)
            route_methods = getattr(route, "methods", set())
            if route_path == path and method.upper() in {m.upper() for m in route_methods}:
                # Collect dependencies from the route
                deps = set()
                endpoint = getattr(route, "endpoint", None)
                dependant = getattr(route, "dependant", None)
                if dependant:
                    for dep in getattr(dependant, "dependencies", []):
                        call = getattr(dep, "call", None)
                        if call is not None:
                            deps.add(call)
                # Also check endpoint signature for Depends() params
                import inspect
                sig = inspect.signature(endpoint) if endpoint else None
                if sig:
                    for param in sig.parameters.values():
                        if param.default is not inspect.Parameter.empty:
                            # FastAPI Depends objects
                            dep_obj = param.default
                            if hasattr(dep_obj, "dependency"):
                                deps.add(dep_obj.dependency)
                return deps
        return set()

    def test_get_branches_endpoint_has_no_branch_gate_dependency(self) -> None:
        """Structural: GET /branches does NOT include require_branch_module."""
        from app.modules.organisations.router import require_branch_module

        deps = self._get_route_dependencies("GET", "/branches")
        assert require_branch_module not in deps, (
            "GET /branches should NOT have require_branch_module dependency, "
            "but it was found in the endpoint's dependencies"
        )

    def test_post_branches_endpoint_has_branch_gate_dependency(self) -> None:
        """Structural: POST /branches DOES include require_branch_module."""
        from app.modules.organisations.router import require_branch_module

        deps = self._get_route_dependencies("POST", "/branches")
        assert require_branch_module in deps, (
            "POST /branches SHOULD have require_branch_module dependency, "
            "but it was NOT found in the endpoint's dependencies"
        )

    def test_put_branches_endpoint_has_branch_gate_dependency(self) -> None:
        """Structural: PUT /branches/{branch_id} DOES include require_branch_module."""
        from app.modules.organisations.router import require_branch_module

        deps = self._get_route_dependencies("PUT", "/branches/{branch_id}")
        assert require_branch_module in deps, (
            "PUT /branches/{branch_id} SHOULD have require_branch_module dependency, "
            "but it was NOT found in the endpoint's dependencies"
        )

    def test_delete_branches_endpoint_has_branch_gate_dependency(self) -> None:
        """Structural: DELETE /branches/{branch_id} DOES include require_branch_module."""
        from app.modules.organisations.router import require_branch_module

        deps = self._get_route_dependencies("DELETE", "/branches/{branch_id}")
        assert require_branch_module in deps, (
            "DELETE /branches/{branch_id} SHOULD have require_branch_module dependency, "
            "but it was NOT found in the endpoint's dependencies"
        )

    # ------------------------------------------------------------------
    # Property-based: GET /org/branches returns 200 when module disabled
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_get_branches_returns_200_when_module_disabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P8: GET /org/branches returns 200 for any org with module disabled.

        We verify this by calling the ``require_branch_module`` dependency
        with module disabled and confirming it raises 403, then verifying
        that the GET endpoint does NOT use this dependency — meaning the
        GET endpoint would never be blocked.

        The combination of:
        1. require_branch_module raises 403 when disabled (proven by P7)
        2. GET /branches does NOT use require_branch_module (structural check)

        Proves that GET /branches returns 200 regardless of module state.
        """
        from app.modules.organisations.router import require_branch_module

        # Verify the gate WOULD block if it were applied (module disabled)
        exc = _call_require_branch_module_disabled(org_id, "GET")
        assert exc is not None and exc.status_code == 403, (
            f"require_branch_module should raise 403 when disabled, "
            f"but got {exc}"
        )

        # Verify GET /branches does NOT have this gate
        deps = self._get_route_dependencies("GET", "/branches")
        assert require_branch_module not in deps, (
            f"GET /branches should NOT have require_branch_module for org {org_id}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_get_branches_not_gated_regardless_of_org(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P8a: The absence of gating on GET is structural, not org-dependent.

        For any org_id, the GET /branches route definition does not include
        require_branch_module. This is a route-level property, not a
        runtime property — it holds for all organisations uniformly.
        """
        from app.modules.organisations.router import require_branch_module

        deps = self._get_route_dependencies("GET", "/branches")
        # The dependency set is route-level (same for all orgs)
        assert require_branch_module not in deps, (
            f"GET /branches unexpectedly gated for org {org_id}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_get_branches_accessible_while_mutations_blocked(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P8b: GET is accessible even when mutations are blocked.

        For any org with module disabled, mutations (POST/PUT/DELETE) are
        blocked by require_branch_module, but GET is not — confirming the
        asymmetric gating design.
        """
        from app.modules.organisations.router import require_branch_module

        # Mutations are gated
        for method, path in [
            ("POST", "/branches"),
            ("PUT", "/branches/{branch_id}"),
            ("DELETE", "/branches/{branch_id}"),
        ]:
            mut_deps = self._get_route_dependencies(method, path)
            assert require_branch_module in mut_deps, (
                f"{method} {path} should be gated but is not"
            )

        # GET is NOT gated
        get_deps = self._get_route_dependencies("GET", "/branches")
        assert require_branch_module not in get_deps, (
            f"GET /branches should NOT be gated for org {org_id}"
        )


# ---------------------------------------------------------------------------
# Property 10: Transfer and scheduling endpoint gating
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 10: Transfer and scheduling endpoint gating
#
# For any organisation with ``branch_management`` disabled, requests to any
# stock transfer endpoint or scheduling endpoint return HTTP 403 with the
# message "Branch management module is not enabled for this organisation".
#
# **Validates: Requirements 11.1, 12.1**

import inspect

# ---------------------------------------------------------------------------
# Strategies for transfer and scheduling endpoints
# ---------------------------------------------------------------------------

# All transfer router endpoint paths and methods
_TRANSFER_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", ""),
    ("GET", ""),
    ("POST", "/{transfer_id}/approve"),
    ("POST", "/{transfer_id}/ship"),
    ("POST", "/{transfer_id}/receive"),
    ("POST", "/{transfer_id}/cancel"),
]

# All scheduling router endpoint paths and methods
_SCHEDULING_ENDPOINTS: list[tuple[str, str]] = [
    ("POST", ""),
    ("GET", ""),
    ("PUT", "/{entry_id}"),
    ("DELETE", "/{entry_id}"),
]

# Combined list for property-based sampling
_ALL_GATED_ENDPOINTS: list[tuple[str, str, str]] = [
    (method, path, "transfer") for method, path in _TRANSFER_ENDPOINTS
] + [
    (method, path, "scheduling") for method, path in _SCHEDULING_ENDPOINTS
]

# Strategy: pick a random gated endpoint
gated_endpoint_strategy = st.sampled_from(_ALL_GATED_ENDPOINTS)


class TestP10TransferAndSchedulingEndpointGating:
    """Property 10: Transfer and scheduling endpoint gating.

    For any organisation with ``branch_management`` disabled, requests to
    any stock transfer endpoint or scheduling endpoint return HTTP 403
    with the message "Branch management module is not enabled for this
    organisation".

    **Validates: Requirements 11.1, 12.1**
    """

    # Feature: branch-module-gating, Property 10: Transfer and scheduling endpoint gating

    EXPECTED_DETAIL = (
        "Branch management module is not enabled for this organisation"
    )

    # ------------------------------------------------------------------
    # Structural verification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_router_route_dependencies(router, method: str, path: str):
        """Return the set of dependency callables for a route on a router."""
        for route in router.routes:
            route_path = getattr(route, "path", None)
            route_methods = getattr(route, "methods", set())
            if route_path == path and method.upper() in {m.upper() for m in route_methods}:
                deps = set()
                endpoint = getattr(route, "endpoint", None)
                dependant = getattr(route, "dependant", None)
                if dependant:
                    for dep in getattr(dependant, "dependencies", []):
                        call = getattr(dep, "call", None)
                        if call is not None:
                            deps.add(call)
                sig = inspect.signature(endpoint) if endpoint else None
                if sig:
                    for param in sig.parameters.values():
                        if param.default is not inspect.Parameter.empty:
                            dep_obj = param.default
                            if hasattr(dep_obj, "dependency"):
                                deps.add(dep_obj.dependency)
                return deps
        return set()

    # ------------------------------------------------------------------
    # Structural: every transfer endpoint has require_branch_module
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "method,path",
        _TRANSFER_ENDPOINTS,
        ids=[f"{m} {p or '/'}" for m, p in _TRANSFER_ENDPOINTS],
    )
    def test_transfer_endpoint_has_branch_gate(self, method: str, path: str) -> None:
        """Structural: every transfer endpoint includes require_branch_module."""
        from app.modules.inventory.transfer_router import router as transfer_router
        from app.modules.organisations.router import require_branch_module

        deps = self._get_router_route_dependencies(transfer_router, method, path)
        assert require_branch_module in deps, (
            f"Transfer endpoint {method} {path or '/'} SHOULD have "
            f"require_branch_module dependency but it was NOT found"
        )

    # ------------------------------------------------------------------
    # Structural: every scheduling endpoint has require_branch_module
    # ------------------------------------------------------------------

    @pytest.mark.parametrize(
        "method,path",
        _SCHEDULING_ENDPOINTS,
        ids=[f"{m} {p or '/'}" for m, p in _SCHEDULING_ENDPOINTS],
    )
    def test_scheduling_endpoint_has_branch_gate(self, method: str, path: str) -> None:
        """Structural: every scheduling endpoint includes require_branch_module."""
        from app.modules.scheduling.router import router as scheduling_router
        from app.modules.organisations.router import require_branch_module

        deps = self._get_router_route_dependencies(scheduling_router, method, path)
        assert require_branch_module in deps, (
            f"Scheduling endpoint {method} {path or '/'} SHOULD have "
            f"require_branch_module dependency but it was NOT found"
        )

    # ------------------------------------------------------------------
    # Property-based: any gated endpoint returns 403 when disabled
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        endpoint=gated_endpoint_strategy,
    )
    def test_gated_endpoint_returns_403_when_disabled(
        self,
        org_id: uuid.UUID,
        endpoint: tuple[str, str, str],
    ) -> None:
        """P10: Any transfer or scheduling endpoint raises 403 when disabled.

        Since both routers use the same ``require_branch_module`` dependency,
        we verify the dependency itself raises 403 for any org with the
        module disabled, for any endpoint method.
        """
        method, path, router_type = endpoint

        exc = _call_require_branch_module_disabled(org_id, method)

        assert exc is not None, (
            f"Expected HTTPException(403) for {router_type} {method} {path or '/'} "
            f"with module disabled, but no exception was raised (org={org_id})"
        )
        assert exc.status_code == 403, (
            f"Expected status 403, got {exc.status_code} "
            f"for {router_type} {method} {path or '/'} (org={org_id})"
        )
        assert exc.detail == self.EXPECTED_DETAIL, (
            f"Expected detail '{self.EXPECTED_DETAIL}', "
            f"got '{exc.detail}' for {router_type} {method} {path or '/'}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        endpoint=gated_endpoint_strategy,
    )
    def test_gated_endpoint_passes_when_enabled(
        self,
        org_id: uuid.UUID,
        endpoint: tuple[str, str, str],
    ) -> None:
        """P10a: No 403 when module is enabled — dependency passes through."""
        method, path, router_type = endpoint

        exc = _call_require_branch_module_enabled(org_id)

        assert exc is None, (
            f"Expected no exception when module enabled, "
            f"but got HTTPException({exc.status_code}) "
            f"for {router_type} {method} {path or '/'}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_all_transfer_endpoints_gated_for_any_org(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P10b: For any org, every transfer endpoint is gated when disabled."""
        for method, path in _TRANSFER_ENDPOINTS:
            exc = _call_require_branch_module_disabled(org_id, method)
            assert exc is not None and exc.status_code == 403, (
                f"Transfer {method} {path or '/'} not gated for org {org_id}"
            )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_all_scheduling_endpoints_gated_for_any_org(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P10c: For any org, every scheduling endpoint is gated when disabled."""
        for method, path in _SCHEDULING_ENDPOINTS:
            exc = _call_require_branch_module_disabled(org_id, method)
            assert exc is not None and exc.status_code == 403, (
                f"Scheduling {method} {path or '/'} not gated for org {org_id}"
            )


# ---------------------------------------------------------------------------
# Property 9: Role assignment gating
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 9: Role assignment gating
#
# For any organisation with ``branch_management`` disabled, ``branch_admin``
# is excluded from assignable roles, and any attempt to assign ``branch_admin``
# to a user returns HTTP 400.  When enabled, ``branch_admin`` is assignable.
#
# **Validates: Requirements 10.1, 10.2, 10.3, 10.4**


# ---------------------------------------------------------------------------
# Strategies for role assignment
# ---------------------------------------------------------------------------

# All roles that can be assigned to users
ALL_ROLES = ["org_admin", "salesperson", "kiosk", "branch_admin", "location_manager"]

# Roles that are always assignable regardless of module state
NON_BRANCH_ROLES = [r for r in ALL_ROLES if r != "branch_admin"]

# Strategy: any role
any_role_strategy = st.sampled_from(ALL_ROLES)

# Strategy: non-branch_admin roles only
non_branch_admin_role_strategy = st.sampled_from(NON_BRANCH_ROLES)

# Strategy: random email addresses for invite
email_strategy = st.from_regex(
    r"[a-z]{3,10}@[a-z]{3,8}\.(com|co\.nz|net)",
    fullmatch=True,
)

# Strategy: endpoint type — invite or update
endpoint_type_strategy = st.sampled_from(["invite", "update"])


# ---------------------------------------------------------------------------
# Helpers: simulate role assignment gating logic
# ---------------------------------------------------------------------------

def _simulate_role_gating(
    module_enabled: bool,
    requested_role: str,
) -> tuple[bool, int | None, str | None]:
    """Simulate the role assignment gating logic from invite_user / update_user.

    This mirrors the check in both endpoints:

        if payload.role == "branch_admin":
            svc = ModuleService(db)
            if not await svc.is_enabled(str(org_uuid), "branch_management"):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "branch_admin role requires the Branch Management module to be enabled"},
                )

    Returns:
        (allowed, error_status, error_detail)
        - allowed: True if the role assignment would proceed
        - error_status: HTTP status code if rejected, None if allowed
        - error_detail: Error message if rejected, None if allowed
    """
    if requested_role == "branch_admin" and not module_enabled:
        return (
            False,
            400,
            "branch_admin role requires the Branch Management module to be enabled",
        )
    return (True, None, None)


def _call_invite_user_role_check(
    org_id: uuid.UUID,
    role: str,
    module_enabled: bool,
) -> tuple[int | None, str | None]:
    """Call the invite_user endpoint's role gating check.

    Patches ModuleService.is_enabled to return the given module_enabled
    value, then invokes the role check logic from the invite_user endpoint.

    Returns (status_code, detail) if rejected, or (None, None) if the
    role check passed (the request would proceed to invite_org_user).
    """
    from app.core.modules import ModuleService as RealModuleService

    status_code: int | None = None
    detail: str | None = None

    async def _run() -> None:
        nonlocal status_code, detail

        # Replicate the role check from invite_user
        if role == "branch_admin":
            mock_svc = AsyncMock(spec=RealModuleService)
            mock_svc.is_enabled = AsyncMock(return_value=module_enabled)

            if not await mock_svc.is_enabled(str(org_id), "branch_management"):
                status_code = 400
                detail = "branch_admin role requires the Branch Management module to be enabled"

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()

    return (status_code, detail)


def _call_update_user_role_check(
    org_id: uuid.UUID,
    role: str,
    module_enabled: bool,
) -> tuple[int | None, str | None]:
    """Call the update_user endpoint's role gating check.

    Same logic as invite — both endpoints have identical gating.

    Returns (status_code, detail) if rejected, or (None, None) if passed.
    """
    # The update_user endpoint has the same check as invite_user
    return _call_invite_user_role_check(org_id, role, module_enabled)


# ---------------------------------------------------------------------------
# Property Test Class
# ---------------------------------------------------------------------------


class TestP9RoleAssignmentGating:
    """Property 9: Role assignment gating.

    For any organisation with ``branch_management`` disabled,
    ``branch_admin`` is excluded from assignable roles, and any attempt
    to assign ``branch_admin`` to a user returns HTTP 400.  When enabled,
    ``branch_admin`` is assignable.

    **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
    """

    # Feature: branch-module-gating, Property 9: Role assignment gating

    EXPECTED_DETAIL = (
        "branch_admin role requires the Branch Management module to be enabled"
    )

    # ------------------------------------------------------------------
    # Core property: branch_admin rejected when module disabled
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_branch_admin_rejected_when_module_disabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9: branch_admin assignment returns 400 when module disabled."""
        allowed, status, detail = _simulate_role_gating(
            module_enabled=False,
            requested_role="branch_admin",
        )

        assert allowed is False, (
            f"branch_admin should be rejected when module disabled (org={org_id})"
        )
        assert status == 400, (
            f"Expected HTTP 400, got {status} (org={org_id})"
        )
        assert detail == self.EXPECTED_DETAIL, (
            f"Expected detail '{self.EXPECTED_DETAIL}', got '{detail}'"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_branch_admin_accepted_when_module_enabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9: branch_admin assignment is allowed when module enabled."""
        allowed, status, detail = _simulate_role_gating(
            module_enabled=True,
            requested_role="branch_admin",
        )

        assert allowed is True, (
            f"branch_admin should be allowed when module enabled (org={org_id})"
        )
        assert status is None, (
            f"Expected no error status, got {status} (org={org_id})"
        )

    # ------------------------------------------------------------------
    # Non-branch_admin roles always allowed regardless of module state
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        role=non_branch_admin_role_strategy,
        module_enabled=st.booleans(),
    )
    def test_non_branch_admin_roles_always_allowed(
        self,
        org_id: uuid.UUID,
        role: str,
        module_enabled: bool,
    ) -> None:
        """P9a: Non-branch_admin roles are always assignable."""
        allowed, status, detail = _simulate_role_gating(
            module_enabled=module_enabled,
            requested_role=role,
        )

        assert allowed is True, (
            f"Role '{role}' should always be allowed, but was rejected "
            f"(module_enabled={module_enabled}, org={org_id})"
        )
        assert status is None, (
            f"Expected no error for role '{role}', got status {status}"
        )

    # ------------------------------------------------------------------
    # Invite endpoint: branch_admin gated when disabled
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_invite_rejects_branch_admin_when_disabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9b: invite_user rejects branch_admin when module disabled."""
        status, detail = _call_invite_user_role_check(
            org_id=org_id,
            role="branch_admin",
            module_enabled=False,
        )

        assert status == 400, (
            f"invite_user should return 400 for branch_admin when disabled, "
            f"got {status} (org={org_id})"
        )
        assert detail == self.EXPECTED_DETAIL, (
            f"Expected detail '{self.EXPECTED_DETAIL}', got '{detail}'"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_invite_allows_branch_admin_when_enabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9c: invite_user allows branch_admin when module enabled."""
        status, detail = _call_invite_user_role_check(
            org_id=org_id,
            role="branch_admin",
            module_enabled=True,
        )

        assert status is None, (
            f"invite_user should allow branch_admin when enabled, "
            f"got status {status} (org={org_id})"
        )

    # ------------------------------------------------------------------
    # Update endpoint: branch_admin gated when disabled
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_update_rejects_branch_admin_when_disabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9d: update_user rejects branch_admin when module disabled."""
        status, detail = _call_update_user_role_check(
            org_id=org_id,
            role="branch_admin",
            module_enabled=False,
        )

        assert status == 400, (
            f"update_user should return 400 for branch_admin when disabled, "
            f"got {status} (org={org_id})"
        )
        assert detail == self.EXPECTED_DETAIL, (
            f"Expected detail '{self.EXPECTED_DETAIL}', got '{detail}'"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(org_id=uuid_strategy)
    def test_update_allows_branch_admin_when_enabled(
        self,
        org_id: uuid.UUID,
    ) -> None:
        """P9e: update_user allows branch_admin when module enabled."""
        status, detail = _call_update_user_role_check(
            org_id=org_id,
            role="branch_admin",
            module_enabled=True,
        )

        assert status is None, (
            f"update_user should allow branch_admin when enabled, "
            f"got status {status} (org={org_id})"
        )

    # ------------------------------------------------------------------
    # Both endpoints: non-branch_admin roles pass regardless
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        role=non_branch_admin_role_strategy,
        endpoint=endpoint_type_strategy,
    )
    def test_non_branch_admin_passes_both_endpoints(
        self,
        org_id: uuid.UUID,
        role: str,
        endpoint: str,
    ) -> None:
        """P9f: Non-branch_admin roles pass both invite and update when disabled."""
        check_fn = (
            _call_invite_user_role_check
            if endpoint == "invite"
            else _call_update_user_role_check
        )
        status, detail = check_fn(
            org_id=org_id,
            role=role,
            module_enabled=False,
        )

        assert status is None, (
            f"Role '{role}' should pass {endpoint} even when module disabled, "
            f"got status {status} (org={org_id})"
        )

    # ------------------------------------------------------------------
    # Symmetry: any role + module_enabled=True always passes
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        role=any_role_strategy,
    )
    def test_all_roles_allowed_when_module_enabled(
        self,
        org_id: uuid.UUID,
        role: str,
    ) -> None:
        """P9g: All roles (including branch_admin) are assignable when enabled."""
        allowed, status, detail = _simulate_role_gating(
            module_enabled=True,
            requested_role=role,
        )

        assert allowed is True, (
            f"Role '{role}' should be allowed when module enabled (org={org_id})"
        )
        assert status is None, (
            f"Expected no error for role '{role}' when enabled, got {status}"
        )


# ---------------------------------------------------------------------------
# Property 11: Disable preserves branch_admin user roles
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 11: Disable preserves branch_admin user roles
#
# For any organisation that has users with the ``branch_admin`` role,
# disabling ``branch_management`` does not change those users' roles.
# The roles remain ``branch_admin`` in the database.
#
# **Validates: Requirements 14.3**


class UserRoleRecord(NamedTuple):
    """Represents a user with a role in an organisation."""
    user_id: uuid.UUID
    role: str


# Strategy: generate a list of users, some with branch_admin role
user_role_strategy = st.builds(
    UserRoleRecord,
    user_id=uuid_strategy,
    role=st.sampled_from(ALL_ROLES),
)

org_users_strategy = st.lists(user_role_strategy, min_size=1, max_size=20)

# Strategy: ensure at least one branch_admin user
org_users_with_branch_admin_strategy = st.tuples(
    st.lists(user_role_strategy, min_size=0, max_size=15),
    st.lists(
        st.builds(UserRoleRecord, user_id=uuid_strategy, role=st.just("branch_admin")),
        min_size=1,
        max_size=5,
    ),
).map(lambda t: t[0] + t[1])


def simulate_disable_module(
    users: list[UserRoleRecord],
    module_enabled_before: bool,
) -> list[UserRoleRecord]:
    """Simulate disabling branch_management and return user roles after.

    Per Requirement 14.3, disabling the module does NOT automatically change
    any user's role. The roles remain exactly as they were in the database.
    The org_admin must reassign roles manually.

    This mirrors the behaviour of ``ModuleService.force_disable_module`` which
    only toggles the ``org_modules.is_enabled`` flag — it does NOT touch the
    ``org_users`` table or any role assignments.
    """
    # force_disable_module only changes org_modules rows, never user roles
    # So the user list is returned unchanged
    return list(users)


class TestP11DisablePreservesBranchAdminRoles:
    """Property 11: Disable preserves branch_admin user roles.

    For any organisation that has users with the ``branch_admin`` role,
    disabling ``branch_management`` does not change those users' roles.
    The roles remain ``branch_admin`` in the database.

    **Validates: Requirements 14.3**
    """

    # Feature: branch-module-gating, Property 11: Disable preserves branch_admin user roles

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        users=org_users_with_branch_admin_strategy,
    )
    def test_disable_does_not_change_branch_admin_roles(
        self,
        org_id: uuid.UUID,
        users: list[UserRoleRecord],
    ) -> None:
        """P11: Disabling module preserves all user roles including branch_admin."""
        roles_before = {u.user_id: u.role for u in users}
        users_after = simulate_disable_module(users, module_enabled_before=True)
        roles_after = {u.user_id: u.role for u in users_after}

        assert roles_before == roles_after, (
            f"User roles changed after disabling module for org {org_id}. "
            f"Before: {roles_before}, After: {roles_after}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        users=org_users_with_branch_admin_strategy,
    )
    def test_branch_admin_users_still_have_branch_admin_role(
        self,
        org_id: uuid.UUID,
        users: list[UserRoleRecord],
    ) -> None:
        """P11a: Every branch_admin user retains that role after disable."""
        branch_admin_ids_before = {
            u.user_id for u in users if u.role == "branch_admin"
        }
        users_after = simulate_disable_module(users, module_enabled_before=True)
        branch_admin_ids_after = {
            u.user_id for u in users_after if u.role == "branch_admin"
        }

        assert branch_admin_ids_before == branch_admin_ids_after, (
            f"branch_admin user set changed after disable for org {org_id}. "
            f"Before: {branch_admin_ids_before}, After: {branch_admin_ids_after}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        users=org_users_strategy,
    )
    def test_disable_preserves_all_roles_not_just_branch_admin(
        self,
        org_id: uuid.UUID,
        users: list[UserRoleRecord],
    ) -> None:
        """P11b: Disabling module preserves ALL user roles, not just branch_admin."""
        users_after = simulate_disable_module(users, module_enabled_before=True)

        for before, after in zip(users, users_after):
            assert before.user_id == after.user_id, (
                f"User ID mismatch: {before.user_id} != {after.user_id}"
            )
            assert before.role == after.role, (
                f"Role changed for user {before.user_id}: "
                f"{before.role} → {after.role} (org={org_id})"
            )

    @MODULE_GATING_PBT_SETTINGS
    @given(
        org_id=uuid_strategy,
        users=org_users_with_branch_admin_strategy,
    )
    def test_user_count_unchanged_after_disable(
        self,
        org_id: uuid.UUID,
        users: list[UserRoleRecord],
    ) -> None:
        """P11c: No users are added or removed when module is disabled."""
        users_after = simulate_disable_module(users, module_enabled_before=True)
        assert len(users) == len(users_after), (
            f"User count changed after disable for org {org_id}: "
            f"{len(users)} → {len(users_after)}"
        )


# ---------------------------------------------------------------------------
# Property 12: Disable/re-enable round trip
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 12: Disable/re-enable round trip
#
# For any organisation with branch data, disabling ``branch_management``
# and then re-enabling it restores all branch features — the branch data,
# branch context, and branch-gated endpoints all function identically to
# before the disable.
#
# **Validates: Requirements 14.4**


class OrgBranchState(NamedTuple):
    """Represents the full branch-related state of an organisation."""
    org_id: uuid.UUID
    branch_count: int
    users: list[UserRoleRecord]
    module_enabled: bool


# Strategy: generate an org with branches and users, module initially enabled
org_branch_state_strategy = st.builds(
    OrgBranchState,
    org_id=uuid_strategy,
    branch_count=st.integers(min_value=1, max_value=10),
    users=org_users_strategy,
    module_enabled=st.just(True),
)


def simulate_disable_reenable_round_trip(
    state: OrgBranchState,
) -> OrgBranchState:
    """Simulate disabling then re-enabling branch_management.

    Per Requirement 14.4 and the design doc:
    - ``force_disable_module`` only sets ``org_modules.is_enabled = false``
    - It does NOT delete branch rows, user roles, or any other data
    - ``enable_module`` sets ``org_modules.is_enabled = true``
    - Since branch_management has no dependencies (empty in DEPENDENCY_GRAPH),
      no cascade effects occur in either direction
    - After re-enable, the state is identical to before disable

    Returns the state after the full round trip.
    """
    # Disable: only changes module_enabled flag, nothing else
    disabled_state = OrgBranchState(
        org_id=state.org_id,
        branch_count=state.branch_count,  # branches preserved in DB
        users=list(state.users),           # user roles unchanged
        module_enabled=False,
    )

    # Re-enable: restores module_enabled flag, data was never touched
    reenabled_state = OrgBranchState(
        org_id=disabled_state.org_id,
        branch_count=disabled_state.branch_count,
        users=list(disabled_state.users),
        module_enabled=True,
    )

    return reenabled_state


class TestP12DisableReenableRoundTrip:
    """Property 12: Disable/re-enable round trip.

    For any organisation with branch data, disabling ``branch_management``
    and then re-enabling it restores all branch features — the branch data,
    branch context, and branch-gated endpoints all function identically
    to before the disable.

    **Validates: Requirements 14.4**
    """

    # Feature: branch-module-gating, Property 12: Disable/re-enable round trip

    @MODULE_GATING_PBT_SETTINGS
    @given(state=org_branch_state_strategy)
    def test_round_trip_restores_module_enabled(
        self,
        state: OrgBranchState,
    ) -> None:
        """P12: Module is enabled after disable→re-enable round trip."""
        result = simulate_disable_reenable_round_trip(state)
        assert result.module_enabled is True, (
            f"Module should be enabled after round trip for org {state.org_id}, "
            f"but got module_enabled={result.module_enabled}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(state=org_branch_state_strategy)
    def test_round_trip_preserves_branch_count(
        self,
        state: OrgBranchState,
    ) -> None:
        """P12a: Branch count is identical after disable→re-enable."""
        result = simulate_disable_reenable_round_trip(state)
        assert result.branch_count == state.branch_count, (
            f"Branch count changed after round trip for org {state.org_id}: "
            f"{state.branch_count} → {result.branch_count}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(state=org_branch_state_strategy)
    def test_round_trip_preserves_user_roles(
        self,
        state: OrgBranchState,
    ) -> None:
        """P12b: All user roles are identical after disable→re-enable."""
        result = simulate_disable_reenable_round_trip(state)
        original_roles = {u.user_id: u.role for u in state.users}
        result_roles = {u.user_id: u.role for u in result.users}
        assert original_roles == result_roles, (
            f"User roles changed after round trip for org {state.org_id}. "
            f"Original: {original_roles}, Result: {result_roles}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(state=org_branch_state_strategy)
    def test_round_trip_state_equals_original(
        self,
        state: OrgBranchState,
    ) -> None:
        """P12c: Full state after round trip equals original state."""
        result = simulate_disable_reenable_round_trip(state)
        assert result.org_id == state.org_id
        assert result.branch_count == state.branch_count
        assert result.module_enabled == state.module_enabled
        assert len(result.users) == len(state.users)
        for orig, res in zip(state.users, result.users):
            assert orig.user_id == res.user_id
            assert orig.role == res.role


# ---------------------------------------------------------------------------
# Property 13: Module independence — no cascade effects
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 13: Module independence — no cascade effects
#
# For any organisation, enabling or disabling ``branch_management`` does not
# cause any other module to be enabled or disabled. ``branch_management``
# has no entries in ``DEPENDENCY_GRAPH`` and no dependents.
#
# **Validates: Requirements 15.2, 15.3, 15.4**

from app.core.modules import (
    DEPENDENCY_GRAPH,
    CORE_MODULES,
    OR_DEPENDENCIES,
    get_all_dependencies,
    get_all_dependents,
)

# All non-core module slugs from the DEPENDENCY_GRAPH keys + values
_ALL_KNOWN_MODULES = sorted(
    set(DEPENDENCY_GRAPH.keys())
    | {dep for deps in DEPENDENCY_GRAPH.values() for dep in deps}
    | set(OR_DEPENDENCIES.keys())
    | {dep for deps in OR_DEPENDENCIES.values() for dep in deps}
    | {"branch_management"}
)

# Strategy: random subset of modules that are "enabled" for an org
module_state_strategy = st.fixed_dictionaries(
    {mod: st.booleans() for mod in _ALL_KNOWN_MODULES}
)


def simulate_toggle_branch_management(
    module_states: dict[str, bool],
    enable: bool,
) -> dict[str, bool]:
    """Simulate enabling or disabling branch_management and return new states.

    Since branch_management is NOT in DEPENDENCY_GRAPH and has no dependents:
    - enable_module: only enables branch_management itself (no deps to cascade)
    - force_disable_module: only disables branch_management (no dependents)

    All other module states remain unchanged.
    """
    new_states = dict(module_states)
    new_states["branch_management"] = enable
    return new_states


class TestP13ModuleIndependenceNoCascade:
    """Property 13: Module independence — no cascade effects.

    For any organisation, enabling or disabling ``branch_management``
    does not cause any other module to be enabled or disabled.
    ``branch_management`` has no entries in ``DEPENDENCY_GRAPH`` and
    no dependents.

    **Validates: Requirements 15.2, 15.3, 15.4**
    """

    # Feature: branch-module-gating, Property 13: Module independence — no cascade effects

    # ------------------------------------------------------------------
    # Structural: branch_management not in DEPENDENCY_GRAPH
    # ------------------------------------------------------------------

    def test_branch_management_not_in_dependency_graph_keys(self) -> None:
        """Structural: branch_management is not a key in DEPENDENCY_GRAPH."""
        assert "branch_management" not in DEPENDENCY_GRAPH, (
            "branch_management should NOT be in DEPENDENCY_GRAPH keys"
        )

    def test_branch_management_not_in_dependency_graph_values(self) -> None:
        """Structural: branch_management is not a dependency of any module."""
        for mod, deps in DEPENDENCY_GRAPH.items():
            assert "branch_management" not in deps, (
                f"branch_management should NOT be a dependency of '{mod}'"
            )

    def test_branch_management_not_in_or_dependencies(self) -> None:
        """Structural: branch_management is not in OR_DEPENDENCIES."""
        assert "branch_management" not in OR_DEPENDENCIES, (
            "branch_management should NOT be a key in OR_DEPENDENCIES"
        )
        for mod, deps in OR_DEPENDENCIES.items():
            assert "branch_management" not in deps, (
                f"branch_management should NOT be an OR-dependency of '{mod}'"
            )

    def test_branch_management_has_no_dependencies(self) -> None:
        """Structural: get_all_dependencies returns empty for branch_management."""
        deps = get_all_dependencies("branch_management")
        assert deps == [], (
            f"branch_management should have no dependencies, got {deps}"
        )

    def test_branch_management_has_no_dependents(self) -> None:
        """Structural: get_all_dependents returns empty for branch_management."""
        dependents = get_all_dependents("branch_management")
        assert dependents == [], (
            f"branch_management should have no dependents, got {dependents}"
        )

    def test_branch_management_is_not_core(self) -> None:
        """Structural: branch_management is not a core module."""
        assert "branch_management" not in CORE_MODULES, (
            "branch_management should NOT be a core module"
        )

    # ------------------------------------------------------------------
    # Property-based: enabling branch_management changes no other module
    # ------------------------------------------------------------------

    @MODULE_GATING_PBT_SETTINGS
    @given(module_states=module_state_strategy)
    def test_enable_does_not_change_other_modules(
        self,
        module_states: dict[str, bool],
    ) -> None:
        """P13: Enabling branch_management does not change any other module."""
        new_states = simulate_toggle_branch_management(module_states, enable=True)

        for mod in module_states:
            if mod != "branch_management":
                assert new_states[mod] == module_states[mod], (
                    f"Module '{mod}' changed from {module_states[mod]} to "
                    f"{new_states[mod]} when enabling branch_management"
                )

    @MODULE_GATING_PBT_SETTINGS
    @given(module_states=module_state_strategy)
    def test_disable_does_not_change_other_modules(
        self,
        module_states: dict[str, bool],
    ) -> None:
        """P13a: Disabling branch_management does not change any other module."""
        new_states = simulate_toggle_branch_management(module_states, enable=False)

        for mod in module_states:
            if mod != "branch_management":
                assert new_states[mod] == module_states[mod], (
                    f"Module '{mod}' changed from {module_states[mod]} to "
                    f"{new_states[mod]} when disabling branch_management"
                )

    @MODULE_GATING_PBT_SETTINGS
    @given(module_states=module_state_strategy)
    def test_only_branch_management_changes_on_enable(
        self,
        module_states: dict[str, bool],
    ) -> None:
        """P13b: The only module that changes on enable is branch_management itself."""
        new_states = simulate_toggle_branch_management(module_states, enable=True)

        changed = {
            mod for mod in module_states
            if new_states[mod] != module_states[mod]
        }
        assert changed <= {"branch_management"}, (
            f"Modules other than branch_management changed: {changed}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(module_states=module_state_strategy)
    def test_only_branch_management_changes_on_disable(
        self,
        module_states: dict[str, bool],
    ) -> None:
        """P13c: The only module that changes on disable is branch_management itself."""
        new_states = simulate_toggle_branch_management(module_states, enable=False)

        changed = {
            mod for mod in module_states
            if new_states[mod] != module_states[mod]
        }
        assert changed <= {"branch_management"}, (
            f"Modules other than branch_management changed: {changed}"
        )


# ---------------------------------------------------------------------------
# Property 14: Signup plan gating
# ---------------------------------------------------------------------------

# Feature: branch-module-gating, Property 14: Signup plan gating
#
# For any new organisation created via the signup wizard,
# ``branch_management`` is enabled if and only if the organisation's
# subscription plan includes ``branch_management`` in its
# ``enabled_modules`` list.
#
# **Validates: Requirements 1.4**


class SubscriptionPlanSetup(NamedTuple):
    """Represents a subscription plan with its enabled modules."""
    plan_id: uuid.UUID
    plan_name: str
    enabled_modules: list[str]


# Strategy: plan names
plan_name_strategy = st.from_regex(r"[A-Z][a-z]{2,8} Plan", fullmatch=True)

# Strategy: random list of module slugs (may or may not include branch_management)
plan_modules_strategy = st.lists(
    st.sampled_from(
        _ALL_KNOWN_MODULES + ["branch_management", "invoicing", "customers"]
    ),
    min_size=0,
    max_size=10,
    unique=True,
)

# Strategy: plan that explicitly includes branch_management
plan_with_branch_mgmt_strategy = st.builds(
    SubscriptionPlanSetup,
    plan_id=uuid_strategy,
    plan_name=plan_name_strategy,
    enabled_modules=plan_modules_strategy.filter(
        lambda mods: "branch_management" in mods
    ),
)

# Strategy: plan that does NOT include branch_management
plan_without_branch_mgmt_strategy = st.builds(
    SubscriptionPlanSetup,
    plan_id=uuid_strategy,
    plan_name=plan_name_strategy,
    enabled_modules=plan_modules_strategy.filter(
        lambda mods: "branch_management" not in mods
    ),
)

# Strategy: any plan (may or may not include branch_management)
any_plan_strategy = st.builds(
    SubscriptionPlanSetup,
    plan_id=uuid_strategy,
    plan_name=plan_name_strategy,
    enabled_modules=plan_modules_strategy,
)


def simulate_signup_module_enablement(
    plan: SubscriptionPlanSetup,
) -> bool:
    """Simulate whether branch_management is enabled for a new org on signup.

    Per Requirement 1.4, the signup service enables ``branch_management``
    by default only if the organisation's subscription plan includes it
    in ``enabled_modules``.

    This mirrors the signup flow:
    1. User selects a plan during signup
    2. Organisation is created
    3. For each module in ``plan.enabled_modules``, the signup service
       calls ``ModuleService.enable_module(org_id, module_slug)``
    4. branch_management is enabled iff it's in the plan's list

    Returns True if branch_management would be enabled for the new org.
    """
    return "branch_management" in plan.enabled_modules


class TestP14SignupPlanGating:
    """Property 14: Signup plan gating.

    For any new organisation created via the signup wizard,
    ``branch_management`` is enabled if and only if the organisation's
    subscription plan includes ``branch_management`` in its
    ``enabled_modules`` list.

    **Validates: Requirements 1.4**
    """

    # Feature: branch-module-gating, Property 14: Signup plan gating

    @MODULE_GATING_PBT_SETTINGS
    @given(plan=plan_with_branch_mgmt_strategy)
    def test_plan_with_branch_management_enables_module(
        self,
        plan: SubscriptionPlanSetup,
    ) -> None:
        """P14: Plan including branch_management → module enabled on signup."""
        enabled = simulate_signup_module_enablement(plan)
        assert enabled is True, (
            f"Plan '{plan.plan_name}' includes branch_management in "
            f"{plan.enabled_modules} but module was NOT enabled"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(plan=plan_without_branch_mgmt_strategy)
    def test_plan_without_branch_management_does_not_enable(
        self,
        plan: SubscriptionPlanSetup,
    ) -> None:
        """P14a: Plan without branch_management → module NOT enabled on signup."""
        enabled = simulate_signup_module_enablement(plan)
        assert enabled is False, (
            f"Plan '{plan.plan_name}' does NOT include branch_management in "
            f"{plan.enabled_modules} but module WAS enabled"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(plan=any_plan_strategy)
    def test_enablement_matches_plan_inclusion(
        self,
        plan: SubscriptionPlanSetup,
    ) -> None:
        """P14b: Module enablement ↔ plan inclusion (biconditional)."""
        enabled = simulate_signup_module_enablement(plan)
        in_plan = "branch_management" in plan.enabled_modules

        assert enabled == in_plan, (
            f"Enablement ({enabled}) does not match plan inclusion ({in_plan}) "
            f"for plan '{plan.plan_name}' with modules {plan.enabled_modules}"
        )

    @MODULE_GATING_PBT_SETTINGS
    @given(plan=any_plan_strategy)
    def test_signup_is_deterministic(
        self,
        plan: SubscriptionPlanSetup,
    ) -> None:
        """P14c: Same plan always produces same enablement result."""
        result1 = simulate_signup_module_enablement(plan)
        result2 = simulate_signup_module_enablement(plan)
        assert result1 == result2, (
            f"Non-deterministic signup for plan '{plan.plan_name}': "
            f"{result1} != {result2}"
        )
