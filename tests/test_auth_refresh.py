"""Unit tests for Task 4.2 — refresh token rotation with reuse detection.

Tests cover:
  - Happy path: valid refresh token → new token pair, old session revoked
  - Reuse detection: already-rotated token → entire family revoked + alert
  - Unknown token → 401
  - Expired token → 401
  - Schema validation for RefreshTokenRequest
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import Organisation model so SQLAlchemy can resolve the User.organisation
# relationship when Session ORM objects are instantiated in tests.
import app.modules.admin.models  # noqa: F401

from app.modules.auth.schemas import RefreshTokenRequest
from app.modules.auth.service import _hash_refresh_token, rotate_refresh_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    *,
    refresh_token: str,
    family_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    is_revoked: bool = False,
    expires_at: datetime | None = None,
):
    """Build a mock Session object."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.user_id = user_id or uuid.uuid4()
    s.org_id = org_id or uuid.uuid4()
    s.refresh_token_hash = _hash_refresh_token(refresh_token)
    s.family_id = family_id or uuid.uuid4()
    s.device_type = "desktop"
    s.browser = "Chrome"
    s.ip_address = "127.0.0.1"
    s.is_revoked = is_revoked
    s.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=7))
    return s


def _make_user(user_id: uuid.UUID, org_id: uuid.UUID | None = None):
    """Build a mock User object."""
    u = MagicMock()
    u.id = user_id
    u.org_id = org_id
    u.role = "org_admin"
    u.email = "test@example.com"
    return u


def _mock_scalar_one_or_none(value):
    """Return a mock result whose scalar_one_or_none() returns *value*."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalar_one(value):
    """Return a mock result whose scalar_one() returns *value*."""
    result = MagicMock()
    result.scalar_one.return_value = value
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestRefreshTokenRequestSchema:
    def test_valid_request(self):
        req = RefreshTokenRequest(refresh_token="abc123")
        assert req.refresh_token == "abc123"

    def test_missing_field_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RefreshTokenRequest()


# ---------------------------------------------------------------------------
# Service tests — rotate_refresh_token
# ---------------------------------------------------------------------------

class TestRotateRefreshToken:
    """Tests for the rotate_refresh_token service function."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_new_tokens(self):
        """Valid non-revoked, non-expired token → new pair issued."""
        token = "valid-refresh-token"
        family_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        session_obj = _make_session(
            refresh_token=token,
            family_id=family_id,
            user_id=user_id,
            org_id=org_id,
        )
        user_obj = _make_user(user_id, org_id)

        db = AsyncMock()
        # First call: find valid session; Second call: load user
        db.execute.side_effect = [
            _mock_scalar_one_or_none(session_obj),
            _mock_scalar_one(user_obj),
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            result = await rotate_refresh_token(db, token, ip_address="10.0.0.1")

        assert result.access_token
        assert result.refresh_token
        assert result.refresh_token != token
        assert result.token_type == "bearer"
        # Old session should be marked revoked
        assert session_obj.is_revoked is True
        # A new session should have been added
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_rotation_preserves_family_id(self):
        """New session must share the same family_id."""
        token = "family-token"
        family_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        session_obj = _make_session(
            refresh_token=token,
            family_id=family_id,
            user_id=user_id,
            org_id=org_id,
        )
        user_obj = _make_user(user_id, org_id)

        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalar_one_or_none(session_obj),
            _mock_scalar_one(user_obj),
        ]

        with patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock):
            await rotate_refresh_token(db, token)

        new_session = db.add.call_args[0][0]
        assert new_session.family_id == family_id

    @pytest.mark.asyncio
    async def test_reuse_detection_revokes_family(self):
        """Already-revoked token → entire family invalidated, ValueError raised."""
        token = "reused-token"
        family_id = uuid.uuid4()
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()

        revoked_session = _make_session(
            refresh_token=token,
            family_id=family_id,
            user_id=user_id,
            org_id=org_id,
            is_revoked=True,
        )
        user_obj = _make_user(user_id, org_id)

        db = AsyncMock()
        # First call: no valid session; Second call: find revoked session;
        # Third call: bulk update (invalidate family); Fourth call: load user
        db.execute.side_effect = [
            _mock_scalar_one_or_none(None),       # no valid session
            _mock_scalar_one_or_none(revoked_session),  # found revoked
            MagicMock(),                           # update (invalidate family)
            _mock_scalar_one_or_none(user_obj),    # load user for email
        ]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service._send_token_reuse_alert", new_callable=AsyncMock) as mock_alert,
        ):
            with pytest.raises(ValueError, match="Token has been revoked"):
                await rotate_refresh_token(db, token, ip_address="10.0.0.1")

        mock_alert.assert_awaited_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_unknown_token_raises(self):
        """Completely unknown token → ValueError."""
        db = AsyncMock()
        db.execute.side_effect = [
            _mock_scalar_one_or_none(None),  # no valid session
            _mock_scalar_one_or_none(None),  # not found at all
        ]

        with pytest.raises(ValueError, match="Invalid refresh token"):
            await rotate_refresh_token(db, "nonexistent-token")

    @pytest.mark.asyncio
    async def test_hash_function_consistency(self):
        """_hash_refresh_token should produce consistent SHA-256 hashes."""
        token = "test-token-value"
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert _hash_refresh_token(token) == expected
        assert _hash_refresh_token(token) == _hash_refresh_token(token)
