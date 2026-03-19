"""Unit tests for Task 4.8 — password recovery.

Tests cover:
  - request_password_reset: uniform response for existing/non-existing emails,
    token generation and Redis storage, audit logging
  - complete_password_reset: token validation, HIBP check, password update,
    session invalidation, expired token handling
  - reset_via_backup_code: backup code verification and consumption,
    invalid code rejection, session invalidation
  - Schema validation
  - Router endpoint uniform response (Requirement 4.4)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.models import Session, User
from app.modules.auth.schemas import (
    PasswordResetBackupCodeSchema,
    PasswordResetCompleteSchema,
    PasswordResetRequestSchema,
    PasswordResetResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    user_id=None,
    org_id=None,
    email="user@example.com",
    is_active=True,
    password_hash="$2b$12$fakehash",
):
    """Create a mock User object."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = "org_admin"
    user.is_active = is_active
    user.password_hash = password_hash
    user.mfa_methods = []
    return user


# ---------------------------------------------------------------------------
# request_password_reset tests
# ---------------------------------------------------------------------------

class TestRequestPasswordReset:
    @pytest.mark.asyncio
    async def test_generates_token_for_existing_user(self):
        """A reset token is stored in Redis when the email exists."""
        from app.modules.auth.service import request_password_reset

        user = _make_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.return_value = mock_result

        mock_redis = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.modules.auth.service._send_password_reset_email", new_callable=AsyncMock) as mock_send,
        ):
            await request_password_reset(db=db, email=user.email, ip_address="1.2.3.4")

        # Token stored in Redis with 1-hour TTL
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0].startswith("password_reset:")
        assert call_args[0][1] == 3600  # 1 hour

        # Email sent
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_silent_return_for_nonexistent_email(self):
        """No token is generated and no email sent for unknown emails."""
        from app.modules.auth.service import request_password_reset

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        mock_redis = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.modules.auth.service._send_password_reset_email", new_callable=AsyncMock) as mock_send,
        ):
            # Should NOT raise — uniform response
            await request_password_reset(db=db, email="nobody@example.com", ip_address="1.2.3.4")

        # No Redis write, no email
        mock_redis.setex.assert_not_called()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_silent_return_for_inactive_user(self):
        """No token is generated for an inactive user account."""
        from app.modules.auth.service import request_password_reset

        user = _make_user(is_active=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.return_value = mock_result

        mock_redis = AsyncMock()

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.modules.auth.service._send_password_reset_email", new_callable=AsyncMock) as mock_send,
        ):
            await request_password_reset(db=db, email=user.email, ip_address="1.2.3.4")

        mock_redis.setex.assert_not_called()
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_log_written_regardless(self):
        """An audit entry is written whether the email exists or not."""
        from app.modules.auth.service import request_password_reset

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock) as mock_audit,
            patch("app.core.redis.redis_pool", AsyncMock()),
        ):
            await request_password_reset(db=db, email="any@example.com")

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs.kwargs["action"] == "auth.password_reset_requested"


# ---------------------------------------------------------------------------
# complete_password_reset tests
# ---------------------------------------------------------------------------

class TestCompletePasswordReset:
    @pytest.mark.asyncio
    async def test_resets_password_and_invalidates_sessions(self):
        """Valid token resets password and revokes all sessions."""
        from app.modules.auth.service import complete_password_reset

        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id)

        token_data = json.dumps({
            "user_id": str(user_id),
            "email": user.email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.return_value = mock_user_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = token_data

        with (
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.integrations.hibp.is_password_compromised", new_callable=AsyncMock, return_value=False),
            patch("app.modules.auth.password.hash_password", return_value="$2b$12$newhash"),
            patch("app.modules.auth.service.invalidate_all_sessions", new_callable=AsyncMock, return_value=2) as mock_invalidate,
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            await complete_password_reset(
                db=db, token="valid-token", new_password="NewSecureP@ss123", ip_address="1.2.3.4"
            )

        # Password updated
        assert user.password_hash == "$2b$12$newhash"
        # Token deleted from Redis
        mock_redis.delete.assert_called_once()
        # Sessions invalidated
        mock_invalidate.assert_called_once_with(db=db, user_id=user_id, ip_address="1.2.3.4")

    @pytest.mark.asyncio
    async def test_rejects_expired_or_invalid_token(self):
        """Raises ValueError when the token is not found in Redis (expired)."""
        from app.modules.auth.service import complete_password_reset

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        db = AsyncMock()

        with (
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(ValueError, match="Invalid or expired reset token"):
                await complete_password_reset(
                    db=db, token="expired-token", new_password="NewP@ss123"
                )

    @pytest.mark.asyncio
    async def test_rejects_compromised_password(self):
        """Raises ValueError when the new password is found in HIBP."""
        from app.modules.auth.service import complete_password_reset

        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id)

        token_data = json.dumps({
            "user_id": str(user_id),
            "email": user.email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.return_value = mock_user_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = token_data

        with (
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.integrations.hibp.is_password_compromised", new_callable=AsyncMock, return_value=True),
        ):
            with pytest.raises(ValueError, match="data breach"):
                await complete_password_reset(
                    db=db, token="valid-token", new_password="compromised123"
                )

    @pytest.mark.asyncio
    async def test_rejects_inactive_user(self):
        """Raises ValueError when the user is inactive."""
        from app.modules.auth.service import complete_password_reset

        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id, is_active=False)

        token_data = json.dumps({
            "user_id": str(user_id),
            "email": user.email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        db = AsyncMock()
        db.execute.return_value = mock_user_result

        mock_redis = AsyncMock()
        mock_redis.get.return_value = token_data

        with (
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(ValueError, match="Invalid or expired reset token"):
                await complete_password_reset(
                    db=db, token="valid-token", new_password="NewP@ss123"
                )


# ---------------------------------------------------------------------------
# reset_via_backup_code tests
# ---------------------------------------------------------------------------

class TestResetViaBackupCode:
    @pytest.mark.asyncio
    async def test_resets_with_valid_backup_code(self):
        """Valid backup code resets password and invalidates sessions."""
        from app.modules.auth.service import reset_via_backup_code
        from app.modules.auth.models import UserBackupCode
        import bcrypt as bcrypt_lib

        user_id = uuid.uuid4()
        plain_code = "ABCD1234"
        hashed = bcrypt_lib.hashpw(plain_code.encode(), bcrypt_lib.gensalt()).decode()

        user = _make_user(user_id=user_id)

        # Create a mock UserBackupCode record
        mock_bc = MagicMock(spec=UserBackupCode)
        mock_bc.code_hash = hashed
        mock_bc.used = False
        mock_bc.used_at = None

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        mock_bc_result = MagicMock()
        mock_bc_scalars = MagicMock()
        mock_bc_scalars.all.return_value = [mock_bc]
        mock_bc_result.scalars.return_value = mock_bc_scalars

        db = AsyncMock()
        db.execute.side_effect = [mock_user_result, mock_bc_result]

        with (
            patch("app.integrations.hibp.is_password_compromised", new_callable=AsyncMock, return_value=False),
            patch("app.modules.auth.password.hash_password", return_value="$2b$12$newhash"),
            patch("app.modules.auth.service.invalidate_all_sessions", new_callable=AsyncMock, return_value=1) as mock_invalidate,
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            await reset_via_backup_code(
                db=db,
                email=user.email,
                backup_code=plain_code,
                new_password="NewSecureP@ss123",
                ip_address="1.2.3.4",
            )

        # Password updated
        assert user.password_hash == "$2b$12$newhash"
        # Backup code marked as used
        assert mock_bc.used is True
        assert mock_bc.used_at is not None
        # Sessions invalidated
        mock_invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_backup_code(self):
        """Raises ValueError for an incorrect backup code."""
        from app.modules.auth.service import reset_via_backup_code
        from app.modules.auth.models import UserBackupCode
        import bcrypt as bcrypt_lib

        hashed = bcrypt_lib.hashpw(b"REALCODE", bcrypt_lib.gensalt()).decode()
        user = _make_user()

        mock_bc = MagicMock(spec=UserBackupCode)
        mock_bc.code_hash = hashed
        mock_bc.used = False

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        mock_bc_result = MagicMock()
        mock_bc_scalars = MagicMock()
        mock_bc_scalars.all.return_value = [mock_bc]
        mock_bc_result.scalars.return_value = mock_bc_scalars

        db = AsyncMock()
        db.execute.side_effect = [mock_user_result, mock_bc_result]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="Invalid backup code"):
                await reset_via_backup_code(
                    db=db,
                    email=user.email,
                    backup_code="WRONGCODE",
                    new_password="NewP@ss123",
                )

    @pytest.mark.asyncio
    async def test_rejects_already_used_backup_code(self):
        """Raises ValueError when the backup code has already been used."""
        from app.modules.auth.service import reset_via_backup_code

        plain_code = "USEDCODE"
        user = _make_user()

        # No unused backup codes returned (all used)
        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        mock_bc_result = MagicMock()
        mock_bc_scalars = MagicMock()
        mock_bc_scalars.all.return_value = []  # No unused codes
        mock_bc_result.scalars.return_value = mock_bc_scalars

        db = AsyncMock()
        db.execute.side_effect = [mock_user_result, mock_bc_result]

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="Invalid backup code"):
                await reset_via_backup_code(
                    db=db,
                    email=user.email,
                    backup_code=plain_code,
                    new_password="NewP@ss123",
                )

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_email(self):
        """Raises ValueError for an unknown email address."""
        from app.modules.auth.service import reset_via_backup_code

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invalid credentials"):
            await reset_via_backup_code(
                db=db,
                email="nobody@example.com",
                backup_code="ANYCODE",
                new_password="NewP@ss123",
            )

    @pytest.mark.asyncio
    async def test_rejects_compromised_password_via_backup(self):
        """Raises ValueError when new password is compromised (HIBP)."""
        from app.modules.auth.service import reset_via_backup_code
        from app.modules.auth.models import UserBackupCode
        import bcrypt as bcrypt_lib

        plain_code = "VALIDCODE"
        hashed = bcrypt_lib.hashpw(plain_code.encode(), bcrypt_lib.gensalt()).decode()
        user = _make_user()

        mock_bc = MagicMock(spec=UserBackupCode)
        mock_bc.code_hash = hashed
        mock_bc.used = False
        mock_bc.used_at = None

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = user

        mock_bc_result = MagicMock()
        mock_bc_scalars = MagicMock()
        mock_bc_scalars.all.return_value = [mock_bc]
        mock_bc_result.scalars.return_value = mock_bc_scalars

        db = AsyncMock()
        db.execute.side_effect = [mock_user_result, mock_bc_result]

        with (
            patch("app.integrations.hibp.is_password_compromised", new_callable=AsyncMock, return_value=True),
        ):
            with pytest.raises(ValueError, match="data breach"):
                await reset_via_backup_code(
                    db=db,
                    email=user.email,
                    backup_code=plain_code,
                    new_password="compromised123",
                )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPasswordResetSchemas:
    def test_reset_request_schema(self):
        schema = PasswordResetRequestSchema(email="user@example.com")
        assert schema.email == "user@example.com"

    def test_reset_complete_schema(self):
        schema = PasswordResetCompleteSchema(token="abc123", new_password="NewP@ss")
        assert schema.token == "abc123"
        assert schema.new_password == "NewP@ss"

    def test_backup_code_schema(self):
        schema = PasswordResetBackupCodeSchema(
            email="user@example.com",
            backup_code="ABCD1234",
            new_password="NewP@ss",
        )
        assert schema.email == "user@example.com"
        assert schema.backup_code == "ABCD1234"

    def test_reset_response_schema(self):
        resp = PasswordResetResponse(message="Reset link sent.")
        assert resp.message == "Reset link sent."


# ---------------------------------------------------------------------------
# Router uniform response test
# ---------------------------------------------------------------------------

class TestRouterUniformResponse:
    def test_uniform_message_constant(self):
        """The uniform message is consistent for account enumeration prevention."""
        from app.modules.auth.router import _RESET_UNIFORM_MESSAGE

        assert "If an account" in _RESET_UNIFORM_MESSAGE
        assert "reset link" in _RESET_UNIFORM_MESSAGE
