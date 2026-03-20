"""E2E tests for Swagger UI disable by environment.

Covers:
  - In production: /docs, /redoc, /openapi.json return 404
  - In development: /docs, /redoc, /openapi.json return 200

The FastAPI app gates docs_url, redoc_url, and openapi_url based on
``settings.environment`` at app creation time.  We patch the setting
*before* calling ``create_app()`` so the conditional takes effect.

Requirements: 19.6
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
import httpx

import app.middleware.rate_limit as rl_mod
import app.middleware.rbac as rbac_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_app_with_env(environment: str):
    """Create a FastAPI app with the given environment setting.

    Patches ``settings.environment`` before ``create_app()`` so the
    docs_url / redoc_url / openapi_url conditional is evaluated with
    the desired value.  Rate limiter and RBAC are bypassed.
    """
    orig_rl_call = rl_mod.RateLimitMiddleware.__call__

    async def _rl_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rl_mod.RateLimitMiddleware.__call__ = _rl_passthrough

    orig_rbac_call = rbac_mod.RBACMiddleware.__call__

    async def _rbac_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rbac_mod.RBACMiddleware.__call__ = _rbac_passthrough

    with patch("app.config.settings.environment", environment):
        from app.main import create_app
        application = create_app()

    # Restore middleware after app creation
    rl_mod.RateLimitMiddleware.__call__ = orig_rl_call
    rbac_mod.RBACMiddleware.__call__ = orig_rbac_call

    return application


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_production():
    """FastAPI app created with environment='production'."""
    return _create_app_with_env("production")


@pytest.fixture
def app_development():
    """FastAPI app created with environment='development'."""
    return _create_app_with_env("development")


@pytest_asyncio.fixture
async def client_production(app_production):
    """httpx client wired to the production app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_production),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def client_development(app_development):
    """httpx client wired to the development app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_development),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 1. Production environment — docs disabled (404)
# ---------------------------------------------------------------------------


class TestSwaggerDisabledInProduction:
    """Swagger UI, ReDoc, and OpenAPI schema must return 404 in production."""

    @pytest.mark.asyncio
    async def test_docs_returns_404_in_production(self, client_production):
        """GET /docs returns 404 when environment is 'production'."""
        resp = await client_production.get("/docs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_redoc_returns_404_in_production(self, client_production):
        """GET /redoc returns 404 when environment is 'production'."""
        resp = await client_production.get("/redoc")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_openapi_json_returns_404_in_production(self, client_production):
        """GET /openapi.json returns 404 when environment is 'production'."""
        resp = await client_production.get("/openapi.json")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 2. Development environment — docs enabled (200)
# ---------------------------------------------------------------------------


class TestSwaggerEnabledInDevelopment:
    """Swagger UI, ReDoc, and OpenAPI schema must return 200 in development."""

    @pytest.mark.asyncio
    async def test_docs_returns_200_in_development(self, client_development):
        """GET /docs returns 200 when environment is 'development'."""
        resp = await client_development.get("/docs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_redoc_returns_200_in_development(self, client_development):
        """GET /redoc returns 200 when environment is 'development'."""
        resp = await client_development.get("/redoc")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_json_returns_200_in_development(self, client_development):
        """GET /openapi.json returns 200 when environment is 'development'."""
        resp = await client_development.get("/openapi.json")
        assert resp.status_code == 200
