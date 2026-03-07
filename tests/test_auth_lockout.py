"""Unit tests for Task 4.6 — account lockout, HIBP check, anomalous login detection.

Tests cover:
  - Account lockout: 5 failures → 15-min lock, 10 failures → permanent lock
  - Successful login resets failed count
  - Temporary lock expiry allows retry
  - HIBP k-anonymity password check
  - Anomalous login detection (new device, unusual time)
  - Session invalidation ("This wasn't me")
  - Password check endpoint schema
  - Session invalidation endpoint schema
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import Organisation model so SQLAlchemy can resolve relationships
import app.modules.admin.models  # noqa: F401

from app.modules.auth.password import hash_password
from app.modules.auth.schemas import (
    InvalidateAllSessionsResponse,
    LoginRequest,
    PasswordCheckRequest,
    PasswordCheckResponse,
)
from app.modules.auth.service import (
    PERMANENT_LOCK_THRESHOLD,
    TEMP_LOCK_MINUTES,
    TEMP_LOCK_THRESHOLD,
    authenticate_user,
    invalidate_all_sessions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    *,
    email: str = "user@example.com",
    password: str = "CorrectPassword1!",
    is_active: bool = True,
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
    mfa_methods: list | None = None,
    org_id: uuid.UUID | None = None,
):
    """Build a mock User object with lockout fields."""
    u = MagicMock()
    u.id = uuid.uuid4()
    u.org_id = org_id or uuid.uuid4()
    u.email = email
    u.password_hash = hash_password(password)
    u.role = "salesperson"
    u.is_active = is_active
    u.is_email_verified = True
    u.failed_login_count = failed_login_count
    u.locked_until = locked_until
    u.mfa_methods = mfa_methods or []
    u.last_login_at = None
    u.passkey_credentials = []
    return u


def _mock_scalar_one_or_none(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _login_request(email="user@example.com", password="CorrectPassword1!"):
    return LoginRequest(email=email, password=password)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPasswordCheckSchema:
    def test_valid_request(self):
        req = PasswordCheckRequest(password="test123")
        assert req.password == "test123"

    def test_response_compromised(self):
        resp = PasswordCheckResponse(compromised=True, message="found")
        assert resp.compromised is True

    def test_response_safe(self):
        resp = PasswordCheckResponse(compromised=False, message="safe")
        assert resp.compromised is False


class TestInvalidateAllSessionsSchema:
    def test_response(self):
        resp = InvalidateAllSessionsResponse(sessions_revoked=3, message="done")
        assert resp.sessions_revoked == 3


# ---------------------------------------------------------------------------
# Account lockout tests
# ---------------------------------------------------------------------------

class TestAccountLockout:
    """Tests for brute force protection in authenticate_user."""

    @pytest.mark.asyncio
    async def test_failed_login_increments_counter(self):
        """A wrong password should increment failed_login_count."""
        user = _make_user(password="RealPassword1!")
        db = AsyncMock()
        db.execute.return_value = _mock_scalar_one_or_none(user)

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Invalid credentials"):
                await authenticate_user(
                    db, _login_request(password="WrongPassword"), "1.2.3.4", "desktop", "Chrome"
                )

        assert user.failed_login_count == 1

    @pytest.mark.asyncio
    async def test_five_failures_triggers_temp_lock(self):
        """5 consecutive failures should set locked_until to 15 minutes from now."""
        user = _make_user(password="RealPassword1!", failed_login_count=4)
        db = AsyncMock()
        db.execute.return_value = _mock_scalar_one_or_none(user)

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Invalid credentials"):
                await authenticate_user(
                    db, _login_request(password="WrongPassword"), "1.2.3.4", "desktop", "Chrome"
                )

        assert user.failed_login_count == TEMP_LOCK_THRESHOLD
        assert user.locked_until is not None
        # Should be approximately 15 minutes from now
        expected_unlock = datetime.now(timezone.utc) + timedelta(minutes=TEMP_LOCK_MINUTES)
        assert abs((user.locked_until - expected_unlock).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_ten_failures_triggers_permanent_lock(self):
        """10 consecutive failures should deactivate the account."""
        user = _make_user(password="RealPassword1!", failed_login_count=9)
        db = AsyncMock()
        db.execute.return_value = _mock_scalar_one_or_none(user)

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_permanent_lockout_email", new_callable=AsyncMock) as mock_email,
        ):
            with pytest.raises(ValueError, match="Invalid credentials"):
                await authenticate_user(
                    db, _login_request(password="WrongPassword"), "1.2.3.4", "desktop", "Chrome"
                )

        assert user.failed_login_count == PERMANENT_LOCK_THRESHOLD
        assert user.is_active is False
        mock_email.assert_awaited_once_with("user@example.com")

    @pytest.mark.asyncio
    async def test_locked_account_rejects_login(self):
        """A temporarily locked account should reject login even with correct password."""
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        user = _make_user(password="RealPassword1!", locked_until=locked_until, failed_login_count=5)
        db = AsyncMock()
        db.execute.return_value = _mock_scalar_one_or_none(user)

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Account temporarily locked"):
                await authenticate_user(
                    db, _login_request(password="RealPassword1!"), "1.2.3.4", "desktop", "Chrome"
                )

    @pytest.mark.asyncio
    async def test_expired_lock_allows_login(self):
        """An expired temporary lock should allow login with correct password."""
        locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        user = _make_user(password="RealPassword1!", locked_until=locked_until, failed_login_count=5)
        db = AsyncMock()
        # First call: find user; Second call: previous sessions for anomaly check
        db.execute.side_effect = [
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([]),  # no previous sessions
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await authenticate_user(
                db, _login_request(password="RealPassword1!"), "1.2.3.4", "desktop", "Chrome"
            )

        assert result.access_token
        assert user.failed_login_count == 0
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_successful_login_resets_counter(self):
        """A successful login should reset failed_login_count to 0."""
        user = _make_user(password="RealPassword1!", failed_login_count=3)
        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([]),  # no previous sessions
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await authenticate_user(
                db, _login_request(password="RealPassword1!"), "1.2.3.4", "desktop", "Chrome"
            )

        assert result.access_token
        assert user.failed_login_count == 0


# ---------------------------------------------------------------------------
# HIBP integration tests
# ---------------------------------------------------------------------------

class TestHIBPCheck:
    """Tests for the HaveIBeenPwned k-anonymity password check."""

    @pytest.mark.asyncio
    async def test_compromised_password_detected(self):
        """A password whose hash suffix appears in the HIBP response should return True."""
        from app.integrations.hibp import is_password_compromised

        test_password = "password123"
        sha1 = hashlib.sha1(test_password.encode()).hexdigest().upper()
        suffix = sha1[5:]

        # Build a mock HIBP response containing the suffix
        mock_response = MagicMock()
        mock_response.text = f"{suffix}:42\nABCDE12345:10\n"
        mock_response.raise_for_status = MagicMock()

        with patch("app.integrations.hibp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await is_password_compromised(test_password)

        assert result is True

    @pytest.mark.asyncio
    async def test_safe_password_not_detected(self):
        """A password whose hash suffix is NOT in the HIBP response should return False."""
        from app.integrations.hibp import is_password_compromised

        mock_response = MagicMock()
        mock_response.text = "AAAAAAA:1\nBBBBBBB:2\nCCCCCCC:3\n"
        mock_response.raise_for_status = MagicMock()

        with patch("app.integrations.hibp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await is_password_compromised("super-unique-password-xyz-12345!")

        assert result is False

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self):
        """On network failure, should fail-open and return False."""
        from app.integrations.hibp import is_password_compromised
        import httpx

        with patch("app.integrations.hibp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await is_password_compromised("any-password")

        assert result is False

    @pytest.mark.asyncio
    async def test_k_anonymity_only_sends_prefix(self):
        """Only the first 5 chars of the SHA-1 hash should be sent to the API."""
        from app.integrations.hibp import is_password_compromised, HIBP_RANGE_URL

        test_password = "test-k-anonymity"
        sha1 = hashlib.sha1(test_password.encode()).hexdigest().upper()
        expected_prefix = sha1[:5]

        mock_response = MagicMock()
        mock_response.text = "AAAAAAA:1\n"
        mock_response.raise_for_status = MagicMock()

        with patch("app.integrations.hibp.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await is_password_compromised(test_password)

            # Verify the URL contains only the 5-char prefix
            call_args = mock_client.get.call_args
            url = call_args[0][0]
            assert url == f"{HIBP_RANGE_URL}{expected_prefix}"


# ---------------------------------------------------------------------------
# Anomalous login detection tests
# ---------------------------------------------------------------------------

class TestAnomalousLoginDetection:
    """Tests for anomalous login detection in authenticate_user."""

    @pytest.mark.asyncio
    async def test_new_device_triggers_alert(self):
        """Login from a never-seen device type should trigger an anomaly alert."""
        user = _make_user(password="RealPassword1!")

        # Create a previous session with "desktop" device
        prev_session = MagicMock()
        prev_session.device_type = "desktop"
        prev_session.created_at = datetime.now(timezone.utc) - timedelta(days=1)

        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([prev_session]),  # previous sessions
        ]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_anomalous_login_alert", new_callable=AsyncMock) as mock_alert,
        ):
            result = await authenticate_user(
                db, _login_request(password="RealPassword1!"), "1.2.3.4", "mobile", "Safari"
            )

        assert result.access_token
        mock_alert.assert_awaited_once()
        call_kwargs = mock_alert.call_args.kwargs
        assert any("new_device" in a for a in call_kwargs["anomalies"])

    @pytest.mark.asyncio
    async def test_known_device_no_alert(self):
        """Login from a known device type should not trigger an alert."""
        user = _make_user(password="RealPassword1!")

        prev_session = MagicMock()
        prev_session.device_type = "desktop"
        prev_session.created_at = datetime.now(timezone.utc) - timedelta(days=1)

        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalar_one_or_none(user),
            _mock_scalars_all([prev_session]),
        ]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_anomalous_login_alert", new_callable=AsyncMock) as mock_alert,
        ):
            result = await authenticate_user(
                db, _login_request(password="RealPassword1!"), "1.2.3.4", "desktop", "Chrome"
            )

        assert result.access_token
        mock_alert.assert_not_awaited()


# ---------------------------------------------------------------------------
# Session invalidation tests
# ---------------------------------------------------------------------------

class TestInvalidateAllSessions:
    """Tests for the 'This wasn't me' session invalidation."""

    @pytest.mark.asyncio
    async def test_revokes_all_active_sessions(self):
        """Should revoke all non-revoked sessions for the user."""
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        s1 = MagicMock()
        s1.is_revoked = False
        s2 = MagicMock()
        s2.is_revoked = False

        user_obj = MagicMock()
        user_obj.id = user_id
        user_obj.org_id = org_id

        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalars_all([s1, s2]),           # active sessions
            _mock_scalar_one_or_none(user_obj),    # load user for audit
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            count = await invalidate_all_sessions(db, user_id, ip_address="1.2.3.4")

        assert count == 2
        assert s1.is_revoked is True
        assert s2.is_revoked is True

    @pytest.mark.asyncio
    async def test_no_sessions_returns_zero(self):
        """Should return 0 when there are no active sessions."""
        user_id = uuid.uuid4()
        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalars_all([]),  # no active sessions
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            count = await invalidate_all_sessions(db, user_id)

        assert count == 0
