"""Integration tests for the org-wide Leave Balances endpoints.

Mounts the leave router on a tiny FastAPI app with a stubbed DB session and
injected ``request.state`` so the module gate (404 ``not_enabled``), the
``leave.balance_view`` RBAC gate (403), and the success path (200 ``{items,total}``)
can be asserted end-to-end through the router + middleware logic.

**Validates: Requirements 1.2, 1.3, 16.1, 16.2, 16.3, 15.1 (reference guide)**
"""

from __future__ import annotations

# Eagerly resolve mappers touched by the router's imports.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.leave.models  # noqa: F401
import app.modules.staff.models  # noqa: F401

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.database import get_db_session
from app.modules.leave.router import router as leave_router

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _build_app(*, role: str, custom_perms: list[str] | None = None) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        request.state.org_id = str(ORG_ID)
        request.state.user_id = str(USER_ID)
        request.state.role = role
        request.state.custom_role_permissions = custom_perms
        request.state.permission_overrides = None
        return await call_next(request)

    app.include_router(leave_router, prefix="/api/v2")
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return app


def _patch_module(enabled: bool):
    """Patch ModuleService so is_enabled returns the desired flag."""
    svc = AsyncMock()
    svc.is_enabled = AsyncMock(return_value=enabled)
    return patch("app.core.modules.ModuleService", return_value=svc)


def test_module_disabled_returns_404():
    app = _build_app(role="org_admin")
    with _patch_module(False):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/balances")
    assert resp.status_code == 404
    assert resp.json()["detail"]["detail"] == "not_enabled"


def test_missing_permission_returns_403():
    # A role without leave.balance_view and no custom grant.
    app = _build_app(role="salesperson", custom_perms=[])
    with _patch_module(True):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/balances")
    assert resp.status_code == 403


def test_org_admin_success_returns_envelope():
    app = _build_app(role="org_admin")
    with _patch_module(True), patch(
        "app.modules.leave.service.list_org_balances",
        new=AsyncMock(return_value=([], 0)),
    ):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/balances")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0}


def test_custom_permission_grant_allows_view():
    app = _build_app(role="salesperson", custom_perms=["leave.balance_view"])
    with _patch_module(True), patch(
        "app.modules.leave.service.list_org_balances",
        new=AsyncMock(return_value=([], 0)),
    ):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/balances")
    assert resp.status_code == 200


def test_reference_guide_returns_sections_when_enabled():
    app = _build_app(role="staff_member")
    with _patch_module(True):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/reference-guide")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rule_set_version"] == "holidays_act_2003"
    assert len(body["sections"]) >= 10
    # The parental-leave out-of-scope note must be present (R15.4).
    assert any("parental" in s["key"] for s in body["sections"])


def test_reference_guide_404_when_module_disabled():
    app = _build_app(role="org_admin")
    with _patch_module(False):
        client = TestClient(app)
        resp = client.get("/api/v2/leave/reference-guide")
    assert resp.status_code == 404


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
