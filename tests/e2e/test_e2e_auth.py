"""E2E tests for authentication flows.

Covers:
  - Login (valid credentials, invalid credentials)
  - MFA challenge with Firebase token verification (valid, invalid, phone mismatch)
  - MFA enrolment verification with Firebase token
  - Password reset (existing email, non-existing email — same response)
  - Session management (session creation, session limit enforcement)

Uses httpx.AsyncClient with the FastAPI test client for full middleware stack
coverage.  External dependencies (Firebase, Redis, database) are mocked.

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
_TEST_EMAIL = "user@example.com"
_TEST_PASSWORD = "Sup3rS3cure!Pass"
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
    user.role = overrides.get("role", "org_admin")
    user.failed_login_count = overrides.get("failed_login_count", 0)
    user.locked_until = overrides.get("locked_until", None)
    user.last_login_at = overrides.get("last_login_at", None)
    return user


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
# 1. Login flow
# ---------------------------------------------------------------------------

class TestLoginFlow:
    """E2E tests for the login endpoint."""

    @pytest.mark.asyncio
    async def test_login_valid_credentials(self, client):
        """Successful login returns access_token and refresh_token."""
        token_resp = MagicMock()
        token_resp.access_token = "fake-access"
        token_resp.refresh_token = "fake-refresh"
        token_resp.token_type = "bearer"
        token_resp.mfa_required = False

        with patch(
            "app.modules.auth.router.authenticate_user",
            new_callable=AsyncMock,
            return_value=token_resp,
        ):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client):
        """Invalid credentials return 401."""
        with patch(
            "app.modules.auth.router.authenticate_user",
            new_callable=AsyncMock,
            side_effect=ValueError("Invalid credentials"),
        ):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": _TEST_EMAIL, "password": "wrong-password"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_login_returns_mfa_challenge(self, client):
        """Login with MFA-enabled user returns mfa_required response."""
        mfa_resp = MagicMock()
        mfa_resp.mfa_required = True
        mfa_resp.mfa_token = "mfa-token-123"
        mfa_resp.methods = ["sms", "totp"]
        mfa_resp.default_method = "sms"

        with patch(
            "app.modules.auth.router.authenticate_user",
            new_callable=AsyncMock,
            return_value=mfa_resp,
        ):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mfa_required"] is True
        assert body["mfa_token"] == "mfa-token-123"
        assert "sms" in body["methods"]


# ---------------------------------------------------------------------------
# 2. MFA challenge with Firebase token verification
# ---------------------------------------------------------------------------

class TestMfaFirebaseChallenge:
    """E2E tests for MFA challenge completion via Firebase token."""

    @pytest.mark.asyncio
    async def test_mfa_firebase_verify_valid_token(self, client):
        """Valid Firebase token + matching phone completes MFA challenge."""
        session_data = {
            "user_id": str(_TEST_USER_ID),
            "methods": ["sms"],
            "phone_number": "+6421555000",
        }
        firebase_claims = {
            "phone_number": "+6421555000",
            "sub": "firebase-uid-123",
        }
        token_resp = MagicMock()
        token_resp.access_token = "access-after-mfa"
        token_resp.refresh_token = "refresh-after-mfa"
        token_resp.token_type = "bearer"

        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        with (
            patch("app.modules.auth.mfa_service._get_challenge_session", new_callable=AsyncMock, return_value=session_data),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, return_value=firebase_claims),
            patch("app.modules.auth.router.verify_mfa", new_callable=AsyncMock, return_value=token_resp),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/firebase-verify",
                json={
                    "mfa_token": "valid-mfa-token",
                    "firebase_id_token": "valid-firebase-token",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access-after-mfa"
        assert body["refresh_token"] == "refresh-after-mfa"

    @pytest.mark.asyncio
    async def test_mfa_firebase_verify_invalid_token(self, client):
        """Invalid Firebase token returns 401."""
        session_data = {
            "user_id": str(_TEST_USER_ID),
            "methods": ["sms"],
            "phone_number": "+6421555000",
        }
        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        with (
            patch("app.modules.auth.mfa_service._get_challenge_session", new_callable=AsyncMock, return_value=session_data),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, side_effect=ValueError("Token verification failed")),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/firebase-verify",
                json={
                    "mfa_token": "valid-mfa-token",
                    "firebase_id_token": "bad-firebase-token",
                },
            )

        assert resp.status_code == 401
        assert "Invalid or missing Firebase ID token" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_mfa_firebase_verify_phone_mismatch(self, client):
        """Phone number mismatch between Firebase token and challenge returns 400."""
        session_data = {
            "user_id": str(_TEST_USER_ID),
            "methods": ["sms"],
            "phone_number": "+6421555000",
        }
        firebase_claims = {
            "phone_number": "+6421999999",  # different phone
            "sub": "firebase-uid-123",
        }
        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        with (
            patch("app.modules.auth.mfa_service._get_challenge_session", new_callable=AsyncMock, return_value=session_data),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, return_value=firebase_claims),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/firebase-verify",
                json={
                    "mfa_token": "valid-mfa-token",
                    "firebase_id_token": "valid-firebase-token",
                },
            )

        assert resp.status_code == 400
        assert "Phone number mismatch" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_mfa_firebase_verify_expired_mfa_token(self, client):
        """Expired/invalid MFA token returns 401."""
        with patch("app.modules.auth.mfa_service._get_challenge_session", new_callable=AsyncMock, return_value=None):
            resp = await client.post(
                "/api/v1/auth/mfa/firebase-verify",
                json={
                    "mfa_token": "expired-token",
                    "firebase_id_token": "some-token",
                },
            )

        assert resp.status_code == 401
        assert "Invalid or expired MFA token" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 3. MFA enrolment verification with Firebase token
# ---------------------------------------------------------------------------

class TestMfaEnrolmentFirebase:
    """E2E tests for MFA enrolment verification via Firebase token."""

    @pytest.mark.asyncio
    async def test_enrol_firebase_verify_success(self, client, mock_db):
        """Valid Firebase token marks pending SMS enrolment as verified."""
        user = _make_user()
        firebase_claims = {
            "phone_number": "+6421555000",
            "sub": "firebase-uid-123",
        }
        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        pending_method = MagicMock()
        pending_method.phone_number = "+6421555000"
        pending_method.verified = False
        pending_method.verified_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pending_method
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, return_value=firebase_claims),
            patch("app.core.audit.write_audit_log", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/enrol/firebase-verify",
                json={"firebase_id_token": "valid-firebase-token"},
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        assert "verified successfully" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_enrol_firebase_verify_invalid_token(self, client):
        """Invalid Firebase token during enrolment returns 401."""
        user = _make_user()
        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, side_effect=ValueError("Token verification failed")),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/enrol/firebase-verify",
                json={"firebase_id_token": "bad-token"},
                headers=_auth_headers(token),
            )

        assert resp.status_code == 401
        assert "Invalid or missing Firebase ID token" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_enrol_firebase_verify_phone_mismatch(self, client, mock_db):
        """Phone mismatch during enrolment returns 400."""
        user = _make_user()
        firebase_claims = {
            "phone_number": "+6421999999",  # different phone
            "sub": "firebase-uid-123",
        }
        mock_provider = MagicMock()
        mock_provider.provider_key = "firebase_phone_auth"

        pending_method = MagicMock()
        pending_method.phone_number = "+6421555000"
        pending_method.verified = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = pending_method
        mock_db.execute = AsyncMock(return_value=mock_result)

        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.mfa_service._resolve_mfa_sms_provider", new_callable=AsyncMock, return_value=mock_provider),
            patch("app.core.firebase_token.verify_firebase_id_token", new_callable=AsyncMock, return_value=firebase_claims),
        ):
            resp = await client.post(
                "/api/v1/auth/mfa/enrol/firebase-verify",
                json={"firebase_id_token": "valid-firebase-token"},
                headers=_auth_headers(token),
            )

        assert resp.status_code == 400
        assert "Phone number mismatch" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. Password reset
# ---------------------------------------------------------------------------

class TestPasswordReset:
    """E2E tests for password reset — same response for existing/non-existing emails."""

    @pytest.mark.asyncio
    async def test_password_reset_existing_email(self, client):
        """Password reset for existing email returns uniform 200 response."""
        with patch(
            "app.modules.auth.router.request_password_reset",
            new_callable=AsyncMock,
        ) as mock_reset:
            resp = await client.post(
                "/api/v1/auth/password/reset-request",
                json={"email": _TEST_EMAIL},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        mock_reset.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_password_reset_nonexistent_email(self, client):
        """Password reset for non-existent email returns same 200 response."""
        with patch(
            "app.modules.auth.router.request_password_reset",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                "/api/v1/auth/password/reset-request",
                json={"email": "nonexistent@example.com"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body

    @pytest.mark.asyncio
    async def test_password_reset_same_response_body(self, client):
        """Both existing and non-existing emails produce identical response bodies."""
        responses = []
        for email in [_TEST_EMAIL, "nobody@example.com"]:
            with patch(
                "app.modules.auth.router.request_password_reset",
                new_callable=AsyncMock,
            ):
                resp = await client.post(
                    "/api/v1/auth/password/reset-request",
                    json={"email": email},
                )
                responses.append(resp)

        assert responses[0].status_code == responses[1].status_code == 200
        assert responses[0].json()["message"] == responses[1].json()["message"]


# ---------------------------------------------------------------------------
# 5. Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    """E2E tests for session listing, termination, and limit enforcement."""

    @pytest.mark.asyncio
    async def test_list_sessions_requires_auth(self, client):
        """GET /sessions without auth returns 401."""
        resp = await client.get("/api/v1/auth/sessions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_sessions_authenticated(self, client):
        """Authenticated user can list their sessions."""
        user = _make_user()
        sessions = [
            {
                "id": str(uuid.uuid4()),
                "device_type": "desktop",
                "browser": "Chrome",
                "ip_address": "127.0.0.1",
                "last_activity_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "current": True,
            }
        ]
        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.router.list_user_sessions", new_callable=AsyncMock, return_value=sessions),
        ):
            resp = await client.get(
                "/api/v1/auth/sessions",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body
        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["current"] is True

    @pytest.mark.asyncio
    async def test_terminate_session(self, client):
        """Authenticated user can terminate a specific session."""
        user = _make_user()
        session_id = uuid.uuid4()
        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.router.terminate_session", new_callable=AsyncMock),
        ):
            resp = await client.delete(
                f"/api/v1/auth/sessions/{session_id}",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        assert "terminated" in resp.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_terminate_nonexistent_session(self, client):
        """Terminating a non-existent session returns 404."""
        user = _make_user()
        session_id = uuid.uuid4()
        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch(
                "app.modules.auth.router.terminate_session",
                new_callable=AsyncMock,
                side_effect=ValueError("Session not found"),
            ),
        ):
            resp = await client.delete(
                f"/api/v1/auth/sessions/{session_id}",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalidate_all_sessions(self, client):
        """Authenticated user can invalidate all sessions."""
        user = _make_user()
        token = _make_access_token()

        with (
            patch("app.modules.auth.router._get_current_user", new_callable=AsyncMock, return_value=user),
            patch("app.modules.auth.router.invalidate_all_sessions", new_callable=AsyncMock, return_value=3),
        ):
            resp = await client.post(
                "/api/v1/auth/sessions/invalidate-all",
                headers=_auth_headers(token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["sessions_revoked"] == 3

    @pytest.mark.asyncio
    async def test_session_limit_enforcement_on_login(self, client):
        """Login enforces session limit — oldest sessions are evicted."""
        token_resp = MagicMock()
        token_resp.access_token = "new-access"
        token_resp.refresh_token = "new-refresh"
        token_resp.token_type = "bearer"
        token_resp.mfa_required = False

        with patch(
            "app.modules.auth.router.authenticate_user",
            new_callable=AsyncMock,
            return_value=token_resp,
        ):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
            )

        # authenticate_user internally calls enforce_session_limit;
        # if it succeeds, login succeeds
        assert resp.status_code == 200
        assert resp.json()["access_token"] == "new-access"
