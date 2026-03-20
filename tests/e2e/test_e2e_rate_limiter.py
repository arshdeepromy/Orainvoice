"""E2E tests for rate limiter behaviour.

Covers:
  - Auth endpoint (e.g., /api/v1/auth/login) returns 503 when Redis is unavailable
  - Non-auth endpoint (e.g., /api/v1/invoices) passes through when Redis is unavailable
  - Auth endpoint works normally when Redis is available

Uses the RateLimitMiddleware directly with mocked Redis.  The rate limiter
is NOT bypassed in these tests — it is the system under test.

Requirements: 19.5
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx


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
def app_redis_unavailable(mock_db):
    """Create a FastAPI app where the rate limiter sees Redis as unavailable.

    The rate limiter is active (NOT bypassed).  ``_get_redis`` is patched to
    always return ``None``, simulating a Redis outage.
    """
    import app.middleware.rate_limit as rl_mod
    import app.middleware.rbac as rbac_mod

    # Keep rate limiter active — only bypass RBAC so we can reach endpoints.
    orig_rbac_call = rbac_mod.RBACMiddleware.__call__

    async def _rbac_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rbac_mod.RBACMiddleware.__call__ = _rbac_passthrough

    # Patch _get_redis on the class to always return None (Redis unavailable).
    orig_get_redis = rl_mod.RateLimitMiddleware._get_redis

    async def _redis_unavailable(self):
        return None

    rl_mod.RateLimitMiddleware._get_redis = _redis_unavailable

    from app.main import create_app

    application = create_app()

    from app.core.database import get_db_session

    async def _mock_db_session():
        yield mock_db

    application.dependency_overrides[get_db_session] = _mock_db_session

    yield application

    application.dependency_overrides.clear()
    rbac_mod.RBACMiddleware.__call__ = orig_rbac_call
    rl_mod.RateLimitMiddleware._get_redis = orig_get_redis


@pytest.fixture
def app_redis_available(mock_db):
    """Create a FastAPI app where the rate limiter has a working mock Redis.

    The rate limiter is active.  A mock Redis is injected that always allows
    requests through (never rate-limited).
    """
    import app.middleware.rate_limit as rl_mod
    import app.middleware.rbac as rbac_mod

    # Bypass RBAC so we can reach endpoints.
    orig_rbac_call = rbac_mod.RBACMiddleware.__call__

    async def _rbac_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rbac_mod.RBACMiddleware.__call__ = _rbac_passthrough

    # Build a mock Redis that makes _check_rate_limit always allow.
    mock_redis = AsyncMock()

    def _make_pipeline():
        pipe = MagicMock()
        pipe.zremrangebyscore = MagicMock(return_value=pipe)
        pipe.zcard = MagicMock(return_value=pipe)
        pipe.zadd = MagicMock(return_value=pipe)
        pipe.expire = MagicMock(return_value=pipe)
        pipe.execute = AsyncMock(return_value=[0, 0])  # zremrangebyscore result, zcard=0
        return pipe

    mock_redis.pipeline = _make_pipeline
    mock_redis.ping = AsyncMock()

    orig_get_redis = rl_mod.RateLimitMiddleware._get_redis

    async def _redis_available(self):
        return mock_redis

    rl_mod.RateLimitMiddleware._get_redis = _redis_available

    from app.main import create_app

    application = create_app()

    from app.core.database import get_db_session

    async def _mock_db_session():
        yield mock_db

    application.dependency_overrides[get_db_session] = _mock_db_session

    yield application

    application.dependency_overrides.clear()
    rbac_mod.RBACMiddleware.__call__ = orig_rbac_call
    rl_mod.RateLimitMiddleware._get_redis = orig_get_redis


@pytest_asyncio.fixture
async def client_redis_down(app_redis_unavailable):
    """httpx client wired to the app with Redis unavailable."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_redis_unavailable),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def client_redis_up(app_redis_available):
    """httpx client wired to the app with Redis available."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_redis_available),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 1. Auth endpoint blocked when Redis is unavailable
# ---------------------------------------------------------------------------


class TestAuthEndpointRedisUnavailable:
    """Auth endpoints must return 503 when Redis is down (fail-closed)."""

    @pytest.mark.asyncio
    async def test_login_returns_503_when_redis_unavailable(self, client_redis_down):
        """POST /api/v1/auth/login returns 503 when Redis is unavailable."""
        resp = await client_redis_down.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "password"},
        )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service temporarily unavailable. Please try again shortly."

    @pytest.mark.asyncio
    async def test_mfa_verify_returns_503_when_redis_unavailable(self, client_redis_down):
        """POST /api/v1/auth/mfa/firebase-verify returns 503 when Redis is unavailable."""
        resp = await client_redis_down.post(
            "/api/v1/auth/mfa/firebase-verify",
            json={"mfa_token": "tok", "firebase_id_token": "fb-tok"},
        )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service temporarily unavailable. Please try again shortly."

    @pytest.mark.asyncio
    async def test_password_reset_returns_503_when_redis_unavailable(self, client_redis_down):
        """POST /api/v1/auth/password/reset-request returns 503 when Redis is unavailable."""
        resp = await client_redis_down.post(
            "/api/v1/auth/password/reset-request",
            json={"email": "user@example.com"},
        )

        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service temporarily unavailable. Please try again shortly."


# ---------------------------------------------------------------------------
# 2. Non-auth endpoint passes through when Redis is unavailable
# ---------------------------------------------------------------------------


class TestNonAuthEndpointRedisUnavailable:
    """Non-auth endpoints must pass through when Redis is down (fail-open)."""

    @pytest.mark.asyncio
    async def test_invoices_passes_through_when_redis_unavailable(self, client_redis_down):
        """GET /api/v1/invoices is NOT blocked when Redis is unavailable.

        The request reaches the application layer (which may return 401 because
        there is no auth token, but crucially it is NOT a 503 from the rate
        limiter).
        """
        resp = await client_redis_down.get("/api/v1/invoices")

        # Should NOT be 503 — the rate limiter must let it through.
        assert resp.status_code != 503

    @pytest.mark.asyncio
    async def test_customers_passes_through_when_redis_unavailable(self, client_redis_down):
        """GET /api/v1/customers is NOT blocked when Redis is unavailable."""
        resp = await client_redis_down.get("/api/v1/customers")

        assert resp.status_code != 503

    @pytest.mark.asyncio
    async def test_admin_passes_through_when_redis_unavailable(self, client_redis_down):
        """GET /api/v1/admin endpoint is NOT blocked when Redis is unavailable."""
        resp = await client_redis_down.get("/api/v1/admin/integrations")

        assert resp.status_code != 503


# ---------------------------------------------------------------------------
# 3. Auth endpoint works normally when Redis is available
# ---------------------------------------------------------------------------


class TestAuthEndpointRedisAvailable:
    """Auth endpoints work normally (not 503) when Redis is available."""

    @pytest.mark.asyncio
    async def test_login_not_blocked_when_redis_available(self, client_redis_up):
        """POST /api/v1/auth/login is not blocked by rate limiter when Redis is up.

        The request passes through the rate limiter and reaches the auth
        handler (which may return 401 for invalid credentials, but not 503).
        """
        with patch(
            "app.modules.auth.router.authenticate_user",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid credentials"),
        ):
            resp = await client_redis_up.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "wrong"},
            )

        # Should NOT be 503 — Redis is available.
        assert resp.status_code != 503
        # The request reached the handler and got a normal auth error.
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_password_reset_not_blocked_when_redis_available(self, client_redis_up):
        """POST /api/v1/auth/password/reset-request passes through when Redis is up."""
        with patch(
            "app.modules.auth.router.request_password_reset",
            new_callable=AsyncMock,
        ):
            resp = await client_redis_up.post(
                "/api/v1/auth/password/reset-request",
                json={"email": "user@example.com"},
            )

        assert resp.status_code != 503
        assert resp.status_code == 200
