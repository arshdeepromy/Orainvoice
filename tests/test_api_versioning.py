"""Tests for API versioning infrastructure (Task 3).

Validates:
  - /api/v1/ endpoints still work unchanged and include deprecation headers
  - /api/v2/ endpoints are accessible and return correct responses
  - After sunset date, /api/v1/ returns HTTP 410 Gone
"""

from datetime import date
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.middleware.api_version import (
    APIVersionMiddleware,
    SUNSET_DATE,
    _SUNSET_HTTP_DATE,
    _v2_equivalent,
)
from app.middleware.auth import AuthMiddleware


def _make_token(
    user_id: str = "u1",
    org_id: str | None = "org1",
    role: str = "salesperson",
) -> str:
    payload = {"user_id": user_id, "role": role}
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _build_app() -> FastAPI:
    """Minimal app with APIVersionMiddleware and AuthMiddleware."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(APIVersionMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/invoices")
    async def v1_invoices(request: Request):
        return {"version": "v1", "data": []}

    @app.post("/api/v1/auth/login")
    async def v1_login():
        return {"token": "ok"}

    @app.get("/api/v2/invoices")
    async def v2_invoices(request: Request):
        return {"version": "v2", "data": []}

    @app.get("/api/v2/auth/login")
    async def v2_login():
        return {"token": "ok"}

    return app


# ---------------------------------------------------------------------------
# Task 3.4 — V1 endpoints work unchanged with deprecation headers
# ---------------------------------------------------------------------------

class TestV1DeprecationHeaders:
    """Validates: Requirement 1.3 — V1 responses include Deprecation and Link headers."""

    def test_v1_endpoint_returns_200_with_deprecation_header(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"version": "v1", "data": []}
        assert "Deprecation" in resp.headers
        assert resp.headers["Deprecation"] == _SUNSET_HTTP_DATE

    def test_v1_endpoint_includes_sunset_header(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert "Sunset" in resp.headers
        assert resp.headers["Sunset"] == _SUNSET_HTTP_DATE

    def test_v1_endpoint_includes_link_header_to_v2(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert "Link" in resp.headers
        assert '</api/v2/invoices>; rel="successor-version"' in resp.headers["Link"]

    def test_v1_public_endpoint_also_gets_deprecation_headers(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 200
        assert "Deprecation" in resp.headers
        assert "Link" in resp.headers

    def test_v1_response_body_unchanged(self):
        """V1 response body must not be modified by the middleware."""
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v1/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json() == {"version": "v1", "data": []}

    def test_health_endpoint_no_deprecation_headers(self):
        """Non-API paths should not get deprecation headers."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "Deprecation" not in resp.headers
        assert "Link" not in resp.headers


class TestV1SunsetEnforcement:
    """Validates: Requirement 1.5 — After sunset, V1 returns HTTP 410."""

    def test_v1_returns_410_after_sunset(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        future_date = date(2028, 1, 1)
        with patch("app.middleware.api_version.date") as mock_date:
            mock_date.today.return_value = future_date
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            resp = client.get(
                "/api/v1/invoices",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 410
        body = resp.json()
        assert body["detail"] == "This API version has been retired."
        assert body["replacement"] == "/api/v2/invoices"

    def test_v2_unaffected_after_sunset(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        future_date = date(2028, 1, 1)
        with patch("app.middleware.api_version.date") as mock_date:
            mock_date.today.return_value = future_date
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            resp = client.get(
                "/api/v2/invoices",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Task 3.5 — V2 endpoints accessible and return correct responses
# ---------------------------------------------------------------------------

class TestV2Endpoints:
    """Validates: Requirement 1.2 — V2 endpoints serve new universal platform."""

    def test_v2_endpoint_returns_200(self):
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v2/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"version": "v2", "data": []}

    def test_v2_endpoint_no_deprecation_headers(self):
        """V2 responses must NOT include deprecation headers."""
        app = _build_app()
        client = TestClient(app)
        token = _make_token()
        resp = client.get(
            "/api/v2/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert "Deprecation" not in resp.headers
        assert "Sunset" not in resp.headers
        assert "Link" not in resp.headers

    def test_v2_auth_still_works(self):
        """V2 auth endpoints should be accessible without a token."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/api/v2/auth/login")
        assert resp.status_code == 200


class TestV2EquivalentMapping:
    """Unit tests for the path mapping helper."""

    def test_simple_path(self):
        assert _v2_equivalent("/api/v1/invoices") == "/api/v2/invoices"

    def test_nested_path(self):
        assert _v2_equivalent("/api/v1/org/accounting") == "/api/v2/org/accounting"

    def test_path_with_id(self):
        assert _v2_equivalent("/api/v1/invoices/123") == "/api/v2/invoices/123"
