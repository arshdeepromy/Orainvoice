"""E2E tests for admin operations.

Covers:
  - Integration backup with password re-confirmation (missing, wrong, correct)
  - Demo reset environment guard (non-development → 403, development → success)
  - SSRF validation on integration URL saving (reject private IPs, accept public)

Uses httpx.AsyncClient with the FastAPI test client for full middleware stack
coverage.  External dependencies (Redis, database) are mocked.

Requirements: 19.3
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
_TEST_EMAIL = "admin@example.com"
_TEST_PASSWORD = "Adm1nP@ssw0rd!"
_TEST_HASHED = "$2b$12$fakehashfortest"


def _make_user(**overrides):
    """Return a mock User ORM object with sensible defaults."""
    user = MagicMock()
    user.id = overrides.get("id", _TEST_USER_ID)
    user.org_id = overrides.get("org_id", _TEST_ORG_ID)
    user.email = overrides.get("email", _TEST_EMAIL)
    user.password_hash = overrides.get("password_hash", _TEST_HASHED)
    user.is_active = overrides.get("is_active", True)
    user.is_email_verified = overrides.get("is_email_verified", True)
    user.role = overrides.get("role", "global_admin")
    user.failed_login_count = overrides.get("failed_login_count", 0)
    user.locked_until = overrides.get("locked_until", None)
    user.last_login_at = overrides.get("last_login_at", None)
    return user


def _make_access_token(user_id=None, org_id=None, role="global_admin", email=None):
    """Create a valid JWT access token for test requests."""
    return create_access_token(
        user_id=user_id or _TEST_USER_ID,
        org_id=org_id or _TEST_ORG_ID,
        role=role,
        email=email or _TEST_EMAIL,
    )


def _auth_headers(token: str | None = None, extra: dict | None = None) -> dict:
    """Return Authorization header dict, optionally merged with extra headers."""
    t = token or _make_access_token()
    headers = {"Authorization": f"Bearer {t}"}
    if extra:
        headers.update(extra)
    return headers


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
# 1. Integration backup — password re-confirmation
# ---------------------------------------------------------------------------


class TestIntegrationBackup:
    """E2E tests for GET /api/v1/admin/integrations/backup."""

    @pytest.mark.asyncio
    async def test_backup_missing_password_header_returns_401(self, client):
        """Backup without x-confirm-password header returns 401."""
        token = _make_access_token()

        resp = await client.get(
            "/api/v1/admin/integrations/backup",
            headers=_auth_headers(token),
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Password confirmation required"

    @pytest.mark.asyncio
    async def test_backup_wrong_password_returns_400(self, client, mock_db):
        """Backup with incorrect password returns 400."""
        user = _make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = _make_access_token()

        with patch(
            "app.modules.auth.password.verify_password",
            return_value=False,
        ):
            resp = await client.get(
                "/api/v1/admin/integrations/backup",
                headers=_auth_headers(token, {"x-confirm-password": "wrong-password"}),
            )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Invalid password"

    @pytest.mark.asyncio
    async def test_backup_correct_password_returns_data(self, client, mock_db):
        """Backup with correct password returns integration settings JSON."""
        user = _make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute = AsyncMock(return_value=mock_result)

        backup_data = {
            "integrations": [
                {"name": "smtp", "provider": "brevo", "api_key": "***REDACTED***"},
            ]
        }
        token = _make_access_token()

        with (
            patch("app.modules.auth.password.verify_password", return_value=True),
            patch(
                "app.modules.admin.service.export_integration_settings",
                new_callable=AsyncMock,
                return_value=backup_data,
            ),
            patch("app.core.audit.write_audit_log", new_callable=AsyncMock),
        ):
            resp = await client.get(
                "/api/v1/admin/integrations/backup",
                headers=_auth_headers(token, {"x-confirm-password": _TEST_PASSWORD}),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "integrations" in body
        assert body["integrations"][0]["api_key"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# 2. Demo reset — environment guard
# ---------------------------------------------------------------------------


class TestDemoReset:
    """E2E tests for POST /api/v1/admin/demo/reset."""

    @pytest.mark.asyncio
    async def test_demo_reset_non_development_returns_403(self, client):
        """Demo reset in non-development environment returns 403."""
        token = _make_access_token()

        with patch("app.config.settings") as mock_settings:
            mock_settings.environment = "production"
            resp = await client.post(
                "/api/v1/admin/demo/reset",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 403
        assert "only available in development" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_demo_reset_staging_returns_403(self, client):
        """Demo reset in staging environment also returns 403."""
        token = _make_access_token()

        with patch("app.config.settings") as mock_settings:
            mock_settings.environment = "staging"
            resp = await client.post(
                "/api/v1/admin/demo/reset",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_demo_reset_development_succeeds(self, client, mock_db):
        """Demo reset in development environment proceeds (returns success or 404 for missing demo account)."""
        token = _make_access_token()

        # The demo reset queries for the demo user — return None to hit the 404 path
        # (simpler than mocking the entire reset flow)
        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.config.settings") as mock_settings:
            mock_settings.environment = "development"
            resp = await client.post(
                "/api/v1/admin/demo/reset",
                headers=_auth_headers(token),
            )

        # 404 means the environment guard passed — the endpoint is accessible
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Demo account not found"


# ---------------------------------------------------------------------------
# 3. SSRF validation — integration URL saving
# ---------------------------------------------------------------------------


class TestSsrfValidation:
    """E2E tests for SSRF protection on integration config endpoints."""

    @pytest.mark.asyncio
    async def test_smtp_config_rejects_private_ip_host(self, client):
        """SMTP config with a private IP host is rejected with 400."""
        token = _make_access_token()

        with patch(
            "app.core.url_validation.validate_url_for_ssrf",
            return_value=(False, "URL resolves to blocked IP range (10.0.0.0/8)"),
        ):
            resp = await client.put(
                "/api/v1/admin/integrations/smtp",
                json={
                    "provider": "smtp",
                    "host": "10.0.0.1",
                    "domain": "example.com",
                    "from_email": "noreply@example.com",
                    "from_name": "Test",
                },
                headers=_auth_headers(token),
            )

        assert resp.status_code == 400
        assert "blocked IP range" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_smtp_config_rejects_loopback_host(self, client):
        """SMTP config with loopback address is rejected."""
        token = _make_access_token()

        with patch(
            "app.core.url_validation.validate_url_for_ssrf",
            return_value=(False, "URL resolves to blocked IP range (127.0.0.0/8)"),
        ):
            resp = await client.put(
                "/api/v1/admin/integrations/smtp",
                json={
                    "provider": "smtp",
                    "host": "127.0.0.1",
                    "domain": "example.com",
                    "from_email": "noreply@example.com",
                    "from_name": "Test",
                },
                headers=_auth_headers(token),
            )

        assert resp.status_code == 400
        assert "blocked IP range" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_smtp_config_accepts_valid_public_host(self, client, mock_db):
        """SMTP config with a valid public host is accepted."""
        token = _make_access_token()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "app.core.url_validation.validate_url_for_ssrf",
                return_value=(True, ""),
            ),
            patch("app.core.encryption.envelope_encrypt", return_value=b"encrypted"),
            patch("app.core.audit.write_audit_log", new_callable=AsyncMock),
        ):
            resp = await client.put(
                "/api/v1/admin/integrations/smtp",
                json={
                    "provider": "smtp",
                    "host": "smtp.sendgrid.net",
                    "domain": "example.com",
                    "from_email": "noreply@example.com",
                    "from_name": "Test",
                },
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "SMTP configuration saved"
