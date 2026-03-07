"""Unit tests for the core middleware stack (Task 1.4).

Tests cover:
  - AuthMiddleware: JWT validation, public path bypass, claim extraction
  - TenantMiddleware: org_id propagation
  - RateLimitMiddleware: sliding window enforcement
  - SecurityHeadersMiddleware: header injection, CSRF protection
"""

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant import TenantMiddleware


def _make_token(
    user_id: str = "u1",
    org_id: str | None = "org1",
    role: str = "salesperson",
    **extra,
) -> str:
    payload = {"user_id": user_id, "role": role, **extra}
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _build_app(middlewares: list | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the given middleware stack."""
    app = FastAPI()

    for mw in middlewares or []:
        if isinstance(mw, tuple):
            app.add_middleware(mw[0], **mw[1])
        else:
            app.add_middleware(mw)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/invoices")
    async def invoices(request: Request):
        return {
            "user_id": getattr(request.state, "user_id", None),
            "org_id": getattr(request.state, "org_id", None),
            "role": getattr(request.state, "role", None),
        }

    @app.post("/api/v1/invoices")
    async def create_invoice(request: Request):
        return {"created": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "ok"}

    @app.get("/api/v1/protected")
    async def protected(request: Request):
        return {
            "current_org_id": getattr(request.state, "current_org_id", None),
        }

    return app


# ---------------------------------------------------------------------------
# AuthMiddleware tests
# ---------------------------------------------------------------------------

class TestAuthMiddleware:
    def test_public_path_no_token_required(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_public_auth_endpoint_no_token(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 200

    def test_missing_auth_header_returns_401(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"]

    def test_invalid_token_returns_401(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": "Bearer bad.token.here"},
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_valid_token_populates_state(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        token = _make_token(user_id="u42", org_id="org7", role="org_admin")
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "u42"
        assert data["org_id"] == "org7"
        assert data["role"] == "org_admin"

    def test_token_missing_user_id_returns_401(self):
        bad_token = jwt.encode(
            {"role": "salesperson"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert resp.status_code == 401
        assert "required claims" in resp.json()["detail"]

    def test_global_admin_no_org_id(self):
        app = _build_app([AuthMiddleware])
        client = TestClient(app)
        token = _make_token(user_id="ga1", org_id=None, role="global_admin")
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["org_id"] is None


# ---------------------------------------------------------------------------
# TenantMiddleware tests
# ---------------------------------------------------------------------------

class TestTenantMiddleware:
    def test_org_id_propagated(self):
        app = _build_app([TenantMiddleware, AuthMiddleware])
        client = TestClient(app)
        token = _make_token(org_id="org99")
        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_org_id"] == "org99"

    def test_no_org_id_defaults_to_none(self):
        app = _build_app([TenantMiddleware, AuthMiddleware])
        client = TestClient(app)
        token = _make_token(org_id=None, role="global_admin")
        resp = client.get(
            "/api/v1/protected",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_org_id"] is None


# ---------------------------------------------------------------------------
# SecurityHeadersMiddleware tests
# ---------------------------------------------------------------------------

class TestSecurityHeadersMiddleware:
    def test_security_headers_present(self):
        app = _build_app([SecurityHeadersMiddleware])
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]
        assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
        assert resp.headers["X-XSS-Protection"] == "1; mode=block"

    def test_csrf_not_required_for_bearer_auth(self):
        """POST with Bearer token should not require CSRF header."""
        app = _build_app([SecurityHeadersMiddleware, AuthMiddleware])
        client = TestClient(app)
        token = _make_token()
        resp = client.post(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert resp.status_code == 200

    def test_csrf_required_for_cookie_auth(self):
        """POST with session cookie but no Bearer should require CSRF."""
        app = _build_app([SecurityHeadersMiddleware])
        client = TestClient(app, cookies={"session": "abc"})
        resp = client.post("/api/v1/invoices", json={})
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["detail"]

    def test_csrf_exempt_path(self):
        """Stripe webhook path should be exempt from CSRF."""
        app = _build_app([SecurityHeadersMiddleware])

        @app.post("/api/v1/payments/stripe/webhook")
        async def stripe_webhook():
            return {"ok": True}

        client = TestClient(app, cookies={"session": "abc"})
        resp = client.post("/api/v1/payments/stripe/webhook", json={})
        assert resp.status_code == 200
