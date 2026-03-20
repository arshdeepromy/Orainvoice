"""E2E tests for data export endpoints and audit logging.

Covers:
  - GET /api/v1/data/export/customers returns CSV and creates audit log
  - GET /api/v1/data/export/vehicles returns CSV and creates audit log
  - GET /api/v1/data/export/invoices returns CSV and creates audit log
  - Audit log entries include org_id, user_id, source IP, and export format

Uses httpx.AsyncClient with the FastAPI test client for full middleware stack
coverage.  External dependencies (Redis, database) are mocked.

Requirements: 19.2
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

from app.modules.auth.jwt import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_USER_ID = uuid.uuid4()
_TEST_ORG_ID = uuid.uuid4()
_TEST_EMAIL = "exporter@example.com"

_SAMPLE_CUSTOMERS_CSV = "id,first_name,last_name,email\n1,Jane,Doe,jane@example.com\n"
_SAMPLE_VEHICLES_CSV = "id,rego,make,model\n1,ABC123,Toyota,Corolla\n"
_SAMPLE_INVOICES_CSV = "id,invoice_number,status,total\n1,INV-001,issued,150.00\n"


def _make_access_token(user_id=None, org_id=None, role="org_admin", email=None):
    """Create a valid JWT access token for test requests."""
    return create_access_token(
        user_id=user_id or _TEST_USER_ID,
        org_id=org_id or _TEST_ORG_ID,
        role=role,
        email=email or _TEST_EMAIL,
    )


def _auth_headers(token: str | None = None) -> dict:
    """Return Authorization header dict."""
    t = token or _make_access_token()
    return {"Authorization": f"Bearer {t}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Provide a mock async database session."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def app(mock_db):
    """Create a fresh FastAPI app with rate limiter, RBAC, and DB bypassed."""
    import app.middleware.rate_limit as rl_mod
    import app.middleware.rbac as rbac_mod

    # Bypass rate limiter
    orig_rl_call = rl_mod.RateLimitMiddleware.__call__

    async def _rl_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rl_mod.RateLimitMiddleware.__call__ = _rl_passthrough

    # Bypass RBAC middleware
    orig_rbac_call = rbac_mod.RBACMiddleware.__call__

    async def _rbac_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rbac_mod.RBACMiddleware.__call__ = _rbac_passthrough

    from app.main import create_app
    application = create_app()

    # Override the database dependency with the mock
    from app.core.database import get_db_session

    async def _mock_db_session():
        yield mock_db

    application.dependency_overrides[get_db_session] = _mock_db_session

    yield application

    application.dependency_overrides.clear()
    rl_mod.RateLimitMiddleware.__call__ = orig_rl_call
    rbac_mod.RBACMiddleware.__call__ = orig_rbac_call


@pytest_asyncio.fixture
async def client(app):
    """Provide an httpx.AsyncClient wired to the FastAPI test app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 1. Export customers — CSV response + audit log
# ---------------------------------------------------------------------------


class TestExportCustomers:
    """E2E tests for GET /api/v1/data/export/customers."""

    @pytest.mark.asyncio
    async def test_export_customers_returns_csv(self, client):
        """Successful customer export returns CSV content."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_customers_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_CUSTOMERS_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.get(
                "/api/v1/data/export/customers",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "first_name" in resp.text
        assert "Jane" in resp.text

    @pytest.mark.asyncio
    async def test_export_customers_creates_audit_log(self, client):
        """Customer export writes audit log with correct action and metadata."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_customers_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_CUSTOMERS_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = await client.get(
                "/api/v1/data/export/customers",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "data_io.customers_exported"
        assert call_kwargs["entity_type"] == "export"
        assert call_kwargs["org_id"] is not None
        assert call_kwargs["user_id"] is not None
        assert call_kwargs["after_value"]["format"] == "csv"
        assert call_kwargs["after_value"]["ip_address"] is not None

    @pytest.mark.asyncio
    async def test_export_customers_requires_auth(self, client):
        """Export without auth token returns 401."""
        resp = await client.get("/api/v1/data/export/customers")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Export vehicles — CSV response + audit log
# ---------------------------------------------------------------------------


class TestExportVehicles:
    """E2E tests for GET /api/v1/data/export/vehicles."""

    @pytest.mark.asyncio
    async def test_export_vehicles_returns_csv(self, client):
        """Successful vehicle export returns CSV content."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_vehicles_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_VEHICLES_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.get(
                "/api/v1/data/export/vehicles",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "rego" in resp.text
        assert "ABC123" in resp.text

    @pytest.mark.asyncio
    async def test_export_vehicles_creates_audit_log(self, client):
        """Vehicle export writes audit log with correct action and metadata."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_vehicles_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_VEHICLES_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = await client.get(
                "/api/v1/data/export/vehicles",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "data_io.vehicles_exported"
        assert call_kwargs["entity_type"] == "export"
        assert call_kwargs["org_id"] is not None
        assert call_kwargs["user_id"] is not None
        assert call_kwargs["after_value"]["format"] == "csv"
        assert call_kwargs["after_value"]["ip_address"] is not None

    @pytest.mark.asyncio
    async def test_export_vehicles_requires_auth(self, client):
        """Export without auth token returns 401."""
        resp = await client.get("/api/v1/data/export/vehicles")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Export invoices — CSV response + audit log
# ---------------------------------------------------------------------------


class TestExportInvoices:
    """E2E tests for GET /api/v1/data/export/invoices."""

    @pytest.mark.asyncio
    async def test_export_invoices_returns_csv(self, client):
        """Successful invoice export returns CSV content."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_invoices_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_INVOICES_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            resp = await client.get(
                "/api/v1/data/export/invoices",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "invoice_number" in resp.text
        assert "INV-001" in resp.text

    @pytest.mark.asyncio
    async def test_export_invoices_creates_audit_log(self, client):
        """Invoice export writes audit log with correct action and metadata."""
        token = _make_access_token()

        with (
            patch(
                "app.modules.data_io.service.export_invoices_csv",
                new_callable=AsyncMock,
                return_value=_SAMPLE_INVOICES_CSV,
            ),
            patch(
                "app.modules.data_io.router.write_audit_log",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            resp = await client.get(
                "/api/v1/data/export/invoices",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "data_io.invoices_exported"
        assert call_kwargs["entity_type"] == "export"
        assert call_kwargs["org_id"] is not None
        assert call_kwargs["user_id"] is not None
        assert call_kwargs["after_value"]["format"] == "csv"
        assert call_kwargs["after_value"]["ip_address"] is not None

    @pytest.mark.asyncio
    async def test_export_invoices_requires_auth(self, client):
        """Export without auth token returns 401."""
        resp = await client.get("/api/v1/data/export/invoices")
        assert resp.status_code == 401
