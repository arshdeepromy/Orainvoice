"""Unit tests for GET /admin/security-audit-log endpoint (Task 1.5).

Covers:
- Auth guard: unauthenticated → 401, org_admin → 403, global_admin → 200
- Filter parameters are passed through correctly to the service function

Validates: Requirements 7.1, 7.8
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import get_db_session
from app.modules.admin.router import router as admin_router
from app.modules.auth.security_settings_schemas import (
    AuditLogFilters,
    PlatformAuditLogPage,
)


# ---------------------------------------------------------------------------
# Test middleware — simulates auth by reading X-Test-* headers
# ---------------------------------------------------------------------------


class FakeAuthMiddleware(BaseHTTPMiddleware):
    """Set request.state auth fields from X-Test-* headers for testing."""

    async def dispatch(self, request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user-id")
        request.state.org_id = request.headers.get("x-test-org-id")
        request.state.role = request.headers.get("x-test-role")
        request.state.assigned_location_ids = []
        request.state.branch_ids = []
        request.state.franchise_group_id = None
        return await call_next(request)


# ---------------------------------------------------------------------------
# App fixture with dependency override for DB session
# ---------------------------------------------------------------------------

mock_db = AsyncMock()


async def _override_get_db_session():
    """Yield a mock DB session instead of a real one."""
    yield mock_db


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(FakeAuthMiddleware)
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db_session] = _override_get_db_session
    return app


app = _build_app()

ENDPOINT = "/api/v1/admin/security-audit-log"

# Reusable empty page response
EMPTY_PAGE = PlatformAuditLogPage(
    items=[], total=0, page=1, page_size=25, truncated=False
)


# ---------------------------------------------------------------------------
# Auth guard tests — Validates: Requirement 7.1, 7.8
# ---------------------------------------------------------------------------


class TestAuthGuard:
    """GET /admin/security-audit-log requires global_admin role."""

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self):
        """Request with no auth headers returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_org_admin_returns_403(self):
        """Authenticated as org_admin returns 403 (not global_admin)."""
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-org-id": str(uuid.uuid4()),
            "x-test-role": "org_admin",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(ENDPOINT, headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_global_admin_returns_200(self):
        """Authenticated as global_admin returns 200."""
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-role": "global_admin",
        }
        with patch(
            "app.modules.auth.security_audit_service.get_platform_security_audit_log",
            new_callable=AsyncMock,
            return_value=EMPTY_PAGE,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(ENDPOINT, headers=headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_salesperson_returns_403(self):
        """Authenticated as salesperson returns 403."""
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-org-id": str(uuid.uuid4()),
            "x-test-role": "salesperson",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(ENDPOINT, headers=headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Filter pass-through tests — Validates: Requirement 7.2, 7.8
# ---------------------------------------------------------------------------


class TestFilterPassthrough:
    """Filter query parameters are forwarded to the service function."""

    @pytest.mark.asyncio
    async def test_default_filters(self):
        """When no filters are provided, defaults are used."""
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-role": "global_admin",
        }
        captured_filters: list[AuditLogFilters] = []

        async def _capture_service(db, filters):
            captured_filters.append(filters)
            return EMPTY_PAGE

        with patch(
            "app.modules.auth.security_audit_service.get_platform_security_audit_log",
            side_effect=_capture_service,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(ENDPOINT, headers=headers)

        assert resp.status_code == 200
        assert len(captured_filters) == 1
        f = captured_filters[0]
        assert f.page == 1
        assert f.page_size == 25
        assert f.start_date is None
        assert f.end_date is None
        assert f.action is None
        assert f.user_id is None

    @pytest.mark.asyncio
    async def test_all_filters_passed_through(self):
        """All filter parameters are forwarded to the service."""
        user_id = uuid.uuid4()
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-role": "global_admin",
        }
        captured_filters: list[AuditLogFilters] = []

        async def _capture_service(db, filters):
            captured_filters.append(filters)
            return EMPTY_PAGE

        with patch(
            "app.modules.auth.security_audit_service.get_platform_security_audit_log",
            side_effect=_capture_service,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    ENDPOINT,
                    headers=headers,
                    params={
                        "start_date": "2024-01-01T00:00:00Z",
                        "end_date": "2024-12-31T23:59:59Z",
                        "action": "auth.login_success",
                        "user_id": str(user_id),
                        "page": 3,
                        "page_size": 50,
                    },
                )

        assert resp.status_code == 200
        assert len(captured_filters) == 1
        f = captured_filters[0]
        assert f.page == 3
        assert f.page_size == 50
        assert f.action == "auth.login_success"
        assert f.user_id == user_id
        assert f.start_date is not None
        assert f.end_date is not None

    @pytest.mark.asyncio
    async def test_response_body_matches_service_output(self):
        """The endpoint returns the PlatformAuditLogPage from the service."""
        headers = {
            "x-test-user-id": str(uuid.uuid4()),
            "x-test-role": "global_admin",
        }
        page = PlatformAuditLogPage(
            items=[], total=42, page=2, page_size=10, truncated=True
        )

        with patch(
            "app.modules.auth.security_audit_service.get_platform_security_audit_log",
            new_callable=AsyncMock,
            return_value=page,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    ENDPOINT,
                    headers=headers,
                    params={"page": 2, "page_size": 10},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 42
        assert body["page"] == 2
        assert body["page_size"] == 10
        assert body["truncated"] is True
        assert body["items"] == []
