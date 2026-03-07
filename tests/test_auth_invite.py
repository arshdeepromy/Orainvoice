"""Unit tests for Task 4.11 — email verification for new accounts.

Tests cover:
  - create_invitation: user creation, token storage in Redis, email dispatch,
    duplicate email rejection, role validation, audit logging
  - verify_email_and_set_password: token validation, email verification,
    password setting, HIBP check, JWT issuance, already-verified rejection
  - resend_invitation: fresh token generation, org mismatch rejection,
    already-verified rejection, non-existent user rejection
  - Schema validation
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import Organisation model so SQLAlchemy can resolve the User.organisation
# relationship when ORM objects are instantiated in tests.
import app.modules.admin.models  # noqa: F401

from app.modules.auth.models import Session, User
from app.modules.auth.schemas import (
    InviteUserRequest,
    InviteUserResponse,
    ResendInviteRequest,
    ResendInviteResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    user_id=None,
    org_id=None,
    email="admin@example.com",
    role="org_admin",
    is_active=True,
    is_email_verified=True,
):
    """Create a mock User object."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = role
    user.is_active = is_active
    user.is_email_verified = is_email_verified
    user.password_hash = "$2b$12$fakehash"
    user.mfa_methods = []
    return user


def _make_invited_user(
    user_id=None,
    org_id=None,
    email="invited@example.com",
    role="salesperson",
    is_email_verified=False,
):
    """Create a mock User representing an invited (unverified) user."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = role
    user.is_active = True
    user.is_email_verified = is_email_verified
    user.password_hash = None
    user.mfa_methods = []
    user.last_login_at = None
    return user


# ---------------------------------------------------------------------------
# create_invitation tests
# ---------------------------------------------------------------------------

class TestCreateInvitation:
    @pytest.mark.asyncio
    async def test_creates_user_and_stores_token(self):
        """Invitation creates a user record and stores token in Redis."""
        from app.modules.auth.service import create_invitation

        admin = _make_user()
        mock_redis = AsyncMock()

        # Mock DB: no existing user found, then flush succeeds
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.auth.service._send_invitation_email",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            result = await create_invitation(
                db=db,
                inviter_user_id=admin.id,
                org_id=admin.org_id,
                email="newuser@example.com",
                role="salesperson",
                ip_address="1.2.3.4",
            )

        assert "user_id" in result
        assert "invitation_expires_at" in result

        # Token stored in Redis with 48-hour TTL
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0].startswith("invite:")
        assert call_args[0][1] == 48 * 3600

        # Email sent
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "newuser@example.com"

    @pytest.mark.asyncio
    async def test_rejects_duplicate_email(self):
        """Invitation fails if email is already registered."""
        from app.modules.auth.service import create_invitation

        admin = _make_user()
        existing = _make_user(email="existing@example.com")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already exists"):
            await create_invitation(
                db=db,
                inviter_user_id=admin.id,
                org_id=admin.org_id,
                email="existing@example.com",
                role="salesperson",
            )

    @pytest.mark.asyncio
    async def test_rejects_invalid_role(self):
        """Invitation fails for invalid role values."""
        from app.modules.auth.service import create_invitation

        admin = _make_user()
        db = AsyncMock()

        with pytest.raises(ValueError, match="Role must be"):
            await create_invitation(
                db=db,
                inviter_user_id=admin.id,
                org_id=admin.org_id,
                email="newuser@example.com",
                role="global_admin",
            )

    @pytest.mark.asyncio
    async def test_token_expiry_is_48_hours(self):
        """Invitation token expires in 48 hours."""
        from app.modules.auth.service import create_invitation

        admin = _make_user()
        mock_redis = AsyncMock()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.auth.service._send_invitation_email",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_invitation(
                db=db,
                inviter_user_id=admin.id,
                org_id=admin.org_id,
                email="newuser@example.com",
                role="org_admin",
            )

        expires_at = result["invitation_expires_at"]
        now = datetime.now(timezone.utc)
        # Should be approximately 48 hours from now (within 5 seconds tolerance)
        delta = expires_at - now
        assert timedelta(hours=47, minutes=59) < delta < timedelta(hours=48, seconds=5)


# ---------------------------------------------------------------------------
# verify_email_and_set_password tests
# ---------------------------------------------------------------------------

class TestVerifyEmailAndSetPassword:
    @pytest.mark.asyncio
    async def test_verifies_email_and_sets_password(self):
        """Valid token verifies email, sets password, and returns JWT pair."""
        from app.modules.auth.service import verify_email_and_set_password

        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        invited = _make_invited_user(user_id=user_id, org_id=org_id)

        mock_redis = AsyncMock()
        token_data = json.dumps({
            "user_id": str(user_id),
            "email": invited.email,
            "org_id": str(org_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mock_redis.get.return_value = token_data

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invited
        db.execute.return_value = mock_result

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.integrations.hibp.is_password_compromised",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.modules.auth.password.hash_password", return_value="$2b$12$newhash"),
        ):
            result = await verify_email_and_set_password(
                db=db,
                token="valid-token-string",
                new_password="SecurePassword123!",
                ip_address="1.2.3.4",
            )

        assert "access_token" in result
        assert "refresh_token" in result

        # Email marked as verified
        assert invited.is_email_verified is True

        # Password set
        assert invited.password_hash == "$2b$12$newhash"

        # Token consumed from Redis
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_expired_token(self):
        """Expired or invalid token raises ValueError."""
        from app.modules.auth.service import verify_email_and_set_password

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # Token not found / expired

        db = AsyncMock()

        with (
            patch("app.core.redis.redis_pool", mock_redis),
            pytest.raises(ValueError, match="Invalid or expired"),
        ):
            await verify_email_and_set_password(
                db=db,
                token="expired-token",
                new_password="SecurePassword123!",
            )

    @pytest.mark.asyncio
    async def test_rejects_already_verified_email(self):
        """Already-verified user raises ValueError."""
        from app.modules.auth.service import verify_email_and_set_password

        user_id = uuid.uuid4()
        verified_user = _make_invited_user(user_id=user_id, is_email_verified=True)

        mock_redis = AsyncMock()
        token_data = json.dumps({
            "user_id": str(user_id),
            "email": verified_user.email,
            "org_id": str(verified_user.org_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mock_redis.get.return_value = token_data

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = verified_user
        db.execute.return_value = mock_result

        with (
            patch("app.core.redis.redis_pool", mock_redis),
            pytest.raises(ValueError, match="already been verified"),
        ):
            await verify_email_and_set_password(
                db=db,
                token="valid-token",
                new_password="SecurePassword123!",
            )

    @pytest.mark.asyncio
    async def test_rejects_compromised_password(self):
        """Compromised password (HIBP) raises ValueError."""
        from app.modules.auth.service import verify_email_and_set_password

        user_id = uuid.uuid4()
        invited = _make_invited_user(user_id=user_id)

        mock_redis = AsyncMock()
        token_data = json.dumps({
            "user_id": str(user_id),
            "email": invited.email,
            "org_id": str(invited.org_id),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        mock_redis.get.return_value = token_data

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invited
        db.execute.return_value = mock_result

        with (
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.integrations.hibp.is_password_compromised",
                new_callable=AsyncMock,
                return_value=True,
            ),
            pytest.raises(ValueError, match="data breach"),
        ):
            await verify_email_and_set_password(
                db=db,
                token="valid-token",
                new_password="password123",
            )


# ---------------------------------------------------------------------------
# resend_invitation tests
# ---------------------------------------------------------------------------

class TestResendInvitation:
    @pytest.mark.asyncio
    async def test_resends_with_fresh_token(self):
        """Resend generates a new token and sends email."""
        from app.modules.auth.service import resend_invitation

        admin = _make_user()
        invited = _make_invited_user(org_id=admin.org_id)

        mock_redis = AsyncMock()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invited
        db.execute.return_value = mock_result

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.auth.service._send_invitation_email",
                new_callable=AsyncMock,
            ) as mock_send,
        ):
            result = await resend_invitation(
                db=db,
                resender_user_id=admin.id,
                org_id=admin.org_id,
                email=invited.email,
                ip_address="1.2.3.4",
            )

        assert "invitation_expires_at" in result

        # New token stored in Redis
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0].startswith("invite:")
        assert call_args[0][1] == 48 * 3600

        # Email sent
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_user(self):
        """Resend fails for unknown email."""
        from app.modules.auth.service import resend_invitation

        admin = _make_user()

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No pending invitation"):
            await resend_invitation(
                db=db,
                resender_user_id=admin.id,
                org_id=admin.org_id,
                email="unknown@example.com",
            )

    @pytest.mark.asyncio
    async def test_rejects_different_org(self):
        """Resend fails if user belongs to a different org."""
        from app.modules.auth.service import resend_invitation

        admin = _make_user()
        other_org_user = _make_invited_user(org_id=uuid.uuid4())

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = other_org_user
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="No pending invitation"):
            await resend_invitation(
                db=db,
                resender_user_id=admin.id,
                org_id=admin.org_id,
                email=other_org_user.email,
            )

    @pytest.mark.asyncio
    async def test_rejects_already_verified(self):
        """Resend fails if user has already verified their email."""
        from app.modules.auth.service import resend_invitation

        admin = _make_user()
        verified = _make_invited_user(
            org_id=admin.org_id,
            is_email_verified=True,
        )

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = verified
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="already verified"):
            await resend_invitation(
                db=db,
                resender_user_id=admin.id,
                org_id=admin.org_id,
                email=verified.email,
            )


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestInvitationSchemas:
    def test_invite_user_request(self):
        req = InviteUserRequest(email="test@example.com", role="salesperson")
        assert req.email == "test@example.com"
        assert req.role == "salesperson"

    def test_invite_user_request_default_role(self):
        req = InviteUserRequest(email="test@example.com")
        assert req.role == "salesperson"

    def test_verify_email_request(self):
        req = VerifyEmailRequest(token="abc123", password="SecurePass123!")
        assert req.token == "abc123"
        assert req.password == "SecurePass123!"

    def test_resend_invite_request(self):
        req = ResendInviteRequest(email="test@example.com")
        assert req.email == "test@example.com"

    def test_invite_response(self):
        resp = InviteUserResponse(
            message="Invitation sent",
            user_id="some-uuid",
            invitation_expires_at=datetime.now(timezone.utc),
        )
        assert resp.message == "Invitation sent"

    def test_verify_email_response(self):
        resp = VerifyEmailResponse(
            message="Verified",
            access_token="at",
            refresh_token="rt",
        )
        assert resp.token_type == "bearer"

    def test_resend_invite_response(self):
        resp = ResendInviteResponse(
            message="Resent",
            invitation_expires_at=datetime.now(timezone.utc),
        )
        assert resp.message == "Resent"
