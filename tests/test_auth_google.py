"""Tests for Google OAuth login — Task 4.3."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.google_oauth import (
    GoogleOAuthError,
    GoogleUserInfo,
    exchange_code_for_user_info,
)
from app.modules.auth.schemas import GoogleLoginRequest
from app.modules.auth.service import authenticate_google


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestGoogleLoginRequestSchema:
    def test_valid_request(self):
        req = GoogleLoginRequest(code="auth-code-123", redirect_uri="http://localhost:5173/callback")
        assert req.code == "auth-code-123"
        assert req.redirect_uri == "http://localhost:5173/callback"

    def test_missing_code_raises(self):
        with pytest.raises(Exception):
            GoogleLoginRequest(redirect_uri="http://localhost:5173/callback")

    def test_missing_redirect_uri_raises(self):
        with pytest.raises(Exception):
            GoogleLoginRequest(code="auth-code-123")


# ---------------------------------------------------------------------------
# Google OAuth client tests
# ---------------------------------------------------------------------------

class TestExchangeCodeForUserInfo:
    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        """Happy path: code → tokens → user info."""
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "goog-access-token"}

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {
            "email": "user@example.com",
            "name": "Test User",
            "sub": "google-id-123",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_userinfo_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.google_oauth.httpx.AsyncClient", return_value=mock_client), \
             patch("app.integrations.google_oauth.settings") as mock_settings:
            mock_settings.google_client_id = "test-client-id"
            mock_settings.google_client_secret = "test-client-secret"

            result = await exchange_code_for_user_info("auth-code", "http://localhost/callback")

        assert result.email == "user@example.com"
        assert result.name == "Test User"
        assert result.google_id == "google-id-123"

    @pytest.mark.asyncio
    async def test_missing_config_raises(self):
        """Should raise when Google OAuth is not configured."""
        with patch("app.integrations.google_oauth.settings") as mock_settings:
            mock_settings.google_client_id = ""
            mock_settings.google_client_secret = ""

            with pytest.raises(GoogleOAuthError, match="not configured"):
                await exchange_code_for_user_info("code", "http://localhost/callback")

    @pytest.mark.asyncio
    async def test_token_exchange_failure(self):
        """Should raise when Google token endpoint returns error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.google_oauth.httpx.AsyncClient", return_value=mock_client), \
             patch("app.integrations.google_oauth.settings") as mock_settings:
            mock_settings.google_client_id = "id"
            mock_settings.google_client_secret = "secret"

            with pytest.raises(GoogleOAuthError, match="exchange"):
                await exchange_code_for_user_info("bad-code", "http://localhost/callback")

    @pytest.mark.asyncio
    async def test_userinfo_failure(self):
        """Should raise when Google userinfo endpoint returns error."""
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "tok"}

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 401
        mock_userinfo_resp.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_userinfo_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.google_oauth.httpx.AsyncClient", return_value=mock_client), \
             patch("app.integrations.google_oauth.settings") as mock_settings:
            mock_settings.google_client_id = "id"
            mock_settings.google_client_secret = "secret"

            with pytest.raises(GoogleOAuthError, match="user info"):
                await exchange_code_for_user_info("code", "http://localhost/callback")

    @pytest.mark.asyncio
    async def test_no_email_in_response(self):
        """Should raise when Google account has no email."""
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "tok"}

        mock_userinfo_resp = MagicMock()
        mock_userinfo_resp.status_code = 200
        mock_userinfo_resp.json.return_value = {"name": "No Email User", "sub": "123"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_userinfo_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.google_oauth.httpx.AsyncClient", return_value=mock_client), \
             patch("app.integrations.google_oauth.settings") as mock_settings:
            mock_settings.google_client_id = "id"
            mock_settings.google_client_secret = "secret"

            with pytest.raises(GoogleOAuthError, match="no email"):
                await exchange_code_for_user_info("code", "http://localhost/callback")


# ---------------------------------------------------------------------------
# Service-level tests for authenticate_google
# ---------------------------------------------------------------------------

def _make_mock_user(
    user_id=None,
    org_id=None,
    email="user@example.com",
    is_active=True,
    mfa_methods=None,
    google_oauth_id=None,
    role="salesperson",
):
    """Create a mock User object."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.is_active = is_active
    user.mfa_methods = mfa_methods or []
    user.google_oauth_id = google_oauth_id
    user.role = role
    user.last_login_at = None
    return user


class TestAuthenticateGoogle:
    @pytest.mark.asyncio
    async def test_existing_user_gets_tokens(self):
        """User exists by email → issue JWT pair."""
        user = _make_mock_user()
        google_info = GoogleUserInfo(email=user.email, name="Test", google_id="g-123")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.auth.service.Session") as MockSession:
            MockSession.return_value = MagicMock()
            result = await authenticate_google(
                db=mock_db,
                google_user_info=google_info,
                ip_address="127.0.0.1",
                device_type="desktop",
                browser="Chrome",
            )

        assert hasattr(result, "access_token")
        assert hasattr(result, "refresh_token")
        # Google ID should be linked
        assert user.google_oauth_id == "g-123"

    @pytest.mark.asyncio
    async def test_no_account_raises(self):
        """No user with that email → ValueError."""
        google_info = GoogleUserInfo(email="nobody@example.com", name="Nobody", google_id="g-999")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="must be invited"):
                await authenticate_google(
                    db=mock_db,
                    google_user_info=google_info,
                    ip_address="127.0.0.1",
                    device_type="desktop",
                    browser="Chrome",
                )

    @pytest.mark.asyncio
    async def test_inactive_user_raises(self):
        """Inactive user → ValueError."""
        user = _make_mock_user(is_active=False)
        google_info = GoogleUserInfo(email=user.email, name="Test", google_id="g-123")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="inactive"):
                await authenticate_google(
                    db=mock_db,
                    google_user_info=google_info,
                    ip_address="127.0.0.1",
                    device_type="desktop",
                    browser="Chrome",
                )

    @pytest.mark.asyncio
    async def test_mfa_user_gets_challenge(self):
        """User with MFA → MFARequiredResponse."""
        user = _make_mock_user(mfa_methods=[{"type": "totp"}])
        google_info = GoogleUserInfo(email=user.email, name="Test", google_id="g-123")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await authenticate_google(
                db=mock_db,
                google_user_info=google_info,
                ip_address="127.0.0.1",
                device_type="desktop",
                browser="Chrome",
            )

        assert result.mfa_required is True
        assert "totp" in result.mfa_methods

    @pytest.mark.asyncio
    async def test_existing_google_id_not_overwritten(self):
        """If google_oauth_id already set, don't overwrite it."""
        user = _make_mock_user(google_oauth_id="existing-id")
        google_info = GoogleUserInfo(email=user.email, name="Test", google_id="new-id")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.auth.service.Session") as MockSession:
            MockSession.return_value = MagicMock()
            await authenticate_google(
                db=mock_db,
                google_user_info=google_info,
                ip_address="127.0.0.1",
                device_type="desktop",
                browser="Chrome",
            )

        # Should keep the existing ID
        assert user.google_oauth_id == "existing-id"
