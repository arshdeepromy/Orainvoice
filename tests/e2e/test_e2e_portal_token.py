"""E2E tests for portal token TTL and rotation.

Covers:
  - Valid portal token with future expiry → request passes through (not 401)
  - Expired portal token → returns 401 "Portal token has expired"
  - Token regeneration endpoint creates new token and resets expiry

The auth middleware checks portal_token_expires_at for portal paths
(/api/v1/portal/, /api/v2/portal/).  The database query that looks up the
customer by portal token is mocked.

Requirements: 19.1
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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
_TEST_EMAIL = "admin@example.com"
_TEST_CUSTOMER_ID = uuid.uuid4()
_TEST_PORTAL_TOKEN = uuid.uuid4()


def _make_access_token(role="global_admin"):
    """Create a valid JWT access token for admin requests."""
    return create_access_token(
        user_id=_TEST_USER_ID,
        org_id=_TEST_ORG_ID,
        role=role,
        email=_TEST_EMAIL,
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
# Helpers for mocking the portal token DB lookup
# ---------------------------------------------------------------------------


def _mock_session_factory(expires_at):
    """Return an async context manager that yields a mock session.

    The mock session's ``execute()`` returns a result whose ``first()``
    returns ``(expires_at,)`` — matching the query in
    ``AuthMiddleware._check_portal_token_expiry``.
    """
    row = (expires_at,) if expires_at is not None else None

    mock_result = MagicMock()
    mock_result.first.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    # async context manager protocol
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory


# ---------------------------------------------------------------------------
# 1. Valid portal token (future expiry) — passes through
# ---------------------------------------------------------------------------


class TestValidPortalToken:
    """Portal token with a future expiry should not be rejected by the middleware."""

    @pytest.mark.asyncio
    async def test_valid_portal_token_not_rejected(self, client):
        """A portal token with expiry in the future passes the TTL check.

        The downstream handler may still return 404 (no matching customer
        route), but the response must NOT be 401 "Portal token has expired".
        """
        future_expiry = datetime.now(timezone.utc) + timedelta(days=30)
        factory = _mock_session_factory(future_expiry)

        with patch(
            "app.core.database.async_session_factory",
            factory,
        ):
            resp = await client.get(
                f"/api/v1/portal/{_TEST_PORTAL_TOKEN}/invoices",
            )

        # Must NOT be the 401 portal-expired response
        assert resp.status_code != 401 or "Portal token has expired" not in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# 2. Expired portal token — returns 401
# ---------------------------------------------------------------------------


class TestExpiredPortalToken:
    """Portal token with a past expiry should be rejected with 401."""

    @pytest.mark.asyncio
    async def test_expired_portal_token_returns_401(self, client):
        """A portal token whose expiry is in the past returns 401."""
        past_expiry = datetime.now(timezone.utc) - timedelta(days=1)
        factory = _mock_session_factory(past_expiry)

        with patch(
            "app.core.database.async_session_factory",
            factory,
        ):
            resp = await client.get(
                f"/api/v1/portal/{_TEST_PORTAL_TOKEN}/invoices",
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Portal token has expired"

    @pytest.mark.asyncio
    async def test_expired_portal_token_v2_returns_401(self, client):
        """Expired portal token on /api/v2/portal/ also returns 401."""
        past_expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
        factory = _mock_session_factory(past_expiry)

        with patch(
            "app.core.database.async_session_factory",
            factory,
        ):
            resp = await client.get(
                f"/api/v2/portal/{_TEST_PORTAL_TOKEN}/invoices",
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Portal token has expired"


# ---------------------------------------------------------------------------
# 3. Token regeneration endpoint
# ---------------------------------------------------------------------------


class TestPortalTokenRegeneration:
    """Admin endpoint to regenerate a customer's portal token."""

    @pytest.mark.asyncio
    async def test_regenerate_portal_token_success(self, client, mock_db):
        """Regeneration creates a new token and resets expiry."""
        customer = MagicMock()
        customer.id = _TEST_CUSTOMER_ID
        customer.portal_token = _TEST_PORTAL_TOKEN
        customer.portal_token_expires_at = datetime.now(timezone.utc) - timedelta(days=10)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = customer
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = _make_access_token(role="global_admin")

        with (
            patch("app.core.audit.write_audit_log", new_callable=AsyncMock),
            patch(
                "app.core.redis.redis_pool",
                new_callable=lambda: type(
                    "FakeRedis",
                    (),
                    {"get": AsyncMock(return_value=str(_TEST_ORG_ID))},
                ),
            ),
        ):
            resp = await client.post(
                f"/api/v1/admin/customers/{_TEST_CUSTOMER_ID}/regenerate-portal-token",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["detail"] == "Portal token regenerated"
        assert body["customer_id"] == str(_TEST_CUSTOMER_ID)
        assert "portal_token" in body
        assert "portal_token_expires_at" in body
        # The new token should differ from the old one
        assert body["portal_token"] != str(_TEST_PORTAL_TOKEN)

    @pytest.mark.asyncio
    async def test_regenerate_portal_token_not_found(self, client, mock_db):
        """Regeneration for non-existent customer returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = _make_access_token(role="global_admin")
        fake_id = uuid.uuid4()

        with patch(
            "app.core.redis.redis_pool",
            new_callable=lambda: type(
                "FakeRedis",
                (),
                {"get": AsyncMock(return_value=str(_TEST_ORG_ID))},
            ),
        ):
            resp = await client.post(
                f"/api/v1/admin/customers/{fake_id}/regenerate-portal-token",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Customer not found"
