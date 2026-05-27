"""Tests for the legacy /admin/integrations/smtp endpoints — 410 Gone.

Phase 7 of the email-provider-unification spec replaced the bodies of
``PUT /api/v1/admin/integrations/smtp`` and ``POST
/api/v1/admin/integrations/smtp/test`` with HTTP 410 Gone stubs. The
route registrations are kept so old clients see a clear deprecation
signal (and emit a ``legacy_smtp_endpoint_hit`` log line we can grep for
in production access logs) instead of a 404. Phase 9 will eventually
remove the registrations entirely once telemetry confirms zero callers
remain.

Validates: Requirements 14.1, 14.2.
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Ensure SQLAlchemy can resolve all relationships (the admin router
# transitively imports models from many other modules)
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.core.database import get_db_session
from app.modules.admin.router import router as admin_router


USER_ID = uuid.uuid4()


def _fake_db():
    return AsyncMock()


def _make_app(role: str = "global_admin", user_id: uuid.UUID | None = USER_ID) -> FastAPI:
    """Stand up a minimal FastAPI app exposing the admin router only.

    The DB dependency is mocked (the 410 stubs do not touch it) and the
    auth state is injected via middleware so ``require_role`` can
    evaluate the request without going through the real auth middleware.
    """
    app = FastAPI()
    app.dependency_overrides[get_db_session] = _fake_db

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(user_id) if user_id else None
        request.state.org_id = None
        request.state.role = role
        request.state.email = "admin@example.com"
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    app.include_router(admin_router, prefix="/api/v1/admin")
    return app


# ---------------------------------------------------------------------------
# 410 Gone behaviour (Requirement 14.1)
# ---------------------------------------------------------------------------


class TestLegacySmtpEndpoints410:
    def test_put_smtp_returns_410_with_location_header(self):
        app = _make_app()
        client = TestClient(app)

        resp = client.put(
            "/api/v1/admin/integrations/smtp",
            json={
                "provider": "brevo",
                "domain": "example.com",
                "from_email": "noreply@example.com",
                "from_name": "Example",
            },
        )

        assert resp.status_code == 410
        assert resp.headers.get("location") == "/api/v2/admin/email-providers"
        body = resp.json()
        assert body["detail"] == (
            "This endpoint is deprecated. Configure email via /api/v2/admin/email-providers."
        )

    def test_put_smtp_with_empty_body_still_returns_410(self):
        """The 410 stub must not require a valid SmtpConfigRequest body."""
        app = _make_app()
        client = TestClient(app)

        resp = client.put("/api/v1/admin/integrations/smtp", json={})

        assert resp.status_code == 410
        assert resp.headers.get("location") == "/api/v2/admin/email-providers"

    def test_post_smtp_test_returns_410_with_location_header(self):
        app = _make_app()
        client = TestClient(app)

        resp = client.post("/api/v1/admin/integrations/smtp/test")

        assert resp.status_code == 410
        assert resp.headers.get("location") == "/api/v2/admin/email-providers"
        body = resp.json()
        assert body["detail"] == (
            "This endpoint is deprecated. Configure email via /api/v2/admin/email-providers."
        )

    def test_endpoints_still_enforce_global_admin_role(self):
        """Role guard runs before the 410 — non-admins still see 403.

        This keeps the legacy endpoints from leaking the deprecation
        message to anonymous or under-privileged callers; the role gate
        sits in front of the body so behaviour mirrors the old endpoint.
        """
        app = _make_app(role="org_admin")
        client = TestClient(app)

        put_resp = client.put("/api/v1/admin/integrations/smtp", json={})
        post_resp = client.post("/api/v1/admin/integrations/smtp/test")

        assert put_resp.status_code == 403
        assert post_resp.status_code == 403


# ---------------------------------------------------------------------------
# Telemetry log line (Requirement 14.2)
# ---------------------------------------------------------------------------


class TestLegacySmtpEndpointTelemetry:
    """Each 410 must emit a structured log line tagged
    ``legacy_smtp_endpoint_hit`` so a single grep over production access
    logs counts the remaining callers, gating the Phase 9 removal.
    """

    @pytest.fixture
    def caplog_warning(self, caplog):
        caplog.set_level(logging.WARNING, logger="app.modules.admin.router")
        return caplog

    def test_put_smtp_emits_telemetry_log(self, caplog_warning):
        app = _make_app()
        client = TestClient(app)

        client.put("/api/v1/admin/integrations/smtp", json={})

        matched = [
            r for r in caplog_warning.records
            if "legacy_smtp_endpoint_hit" in r.getMessage()
        ]
        assert matched, (
            "Expected at least one log record tagged 'legacy_smtp_endpoint_hit' "
            f"on PUT /admin/integrations/smtp. Got: {[r.getMessage() for r in caplog_warning.records]}"
        )
        # Path and remote-ip placeholders included for grep parsing
        msg = matched[0].getMessage()
        assert "path=/api/v1/admin/integrations/smtp" in msg
        assert "remote=" in msg

    def test_post_smtp_test_emits_telemetry_log(self, caplog_warning):
        app = _make_app()
        client = TestClient(app)

        client.post("/api/v1/admin/integrations/smtp/test")

        matched = [
            r for r in caplog_warning.records
            if "legacy_smtp_endpoint_hit" in r.getMessage()
        ]
        assert matched
        msg = matched[0].getMessage()
        assert "path=/api/v1/admin/integrations/smtp/test" in msg
        assert "remote=" in msg
