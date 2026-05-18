"""Unit tests for reset_kiosk_user_password() service function.

Covers:
  - Successful password reset: hash updated, sessions invalidated, audit log written
  - Validation failures: user not found, wrong role, inactive, different org
  - Requirements: 5.1–5.6, 6.1, 6.2, 7.1, 8.1
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.models import User
from app.modules.organisations.service import reset_kiosk_user_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kiosk_user(
    user_id=None,
    org_id=None,
    email="kiosk@workshop.test",
    role="kiosk",
    is_active=True,
):
    """Create a mock User with kiosk defaults."""
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = role
    user.is_active = is_active
    user.password_hash = "$2b$12$oldhasholdhasholdhasholdhasholdhasholdhasholdha"
    return user


def _mock_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ===========================================================================
# Successful reset
# ===========================================================================


class TestResetKioskUserPasswordSuccess:
    """Requirement 5.1–5.6, 6.1, 6.2, 7.1, 8.1: successful password reset."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch(
        "app.modules.organisations.service._invalidate_user_sessions",
        new_callable=AsyncMock,
    )
    @patch("app.modules.auth.password.hash_password")
    async def test_successful_reset_updates_password_hash(
        self, mock_hash, mock_invalidate, mock_audit
    ):
        """6.1, 6.2: password_hash is updated with bcrypt hash of new password."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()
        user = _make_kiosk_user(user_id=target_user_id, org_id=org_id)

        mock_hash.return_value = "$2b$12$newhashnewhashnewhashnewhashnewhashnewhashne"
        mock_invalidate.return_value = 3

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        result = await reset_kiosk_user_password(
            db,
            org_id=org_id,
            acting_user_id=acting_user_id,
            target_user_id=target_user_id,
            new_password="NewSecurePass123",
        )

        # Verify password hash was updated
        assert user.password_hash == "$2b$12$newhashnewhashnewhashnewhashnewhashnewhashne"
        assert result["user_id"] == str(target_user_id)

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch(
        "app.modules.organisations.service._invalidate_user_sessions",
        new_callable=AsyncMock,
    )
    @patch("app.modules.auth.password.hash_password")
    async def test_successful_reset_invalidates_sessions(
        self, mock_hash, mock_invalidate, mock_audit
    ):
        """7.1: all sessions for target user are invalidated."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()
        user = _make_kiosk_user(user_id=target_user_id, org_id=org_id)

        mock_hash.return_value = "$2b$12$somehash"
        mock_invalidate.return_value = 5

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        result = await reset_kiosk_user_password(
            db,
            org_id=org_id,
            acting_user_id=acting_user_id,
            target_user_id=target_user_id,
            new_password="NewSecurePass123",
        )

        mock_invalidate.assert_called_once_with(db, user_id=target_user_id)
        assert result["sessions_invalidated"] == 5

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch(
        "app.modules.organisations.service._invalidate_user_sessions",
        new_callable=AsyncMock,
    )
    @patch("app.modules.auth.password.hash_password")
    async def test_successful_reset_writes_audit_log(
        self, mock_hash, mock_invalidate, mock_audit
    ):
        """8.1: audit log entry is written with correct parameters."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()
        user = _make_kiosk_user(
            user_id=target_user_id, org_id=org_id, email="tablet1@shop.test"
        )

        mock_hash.return_value = "$2b$12$somehash"
        mock_invalidate.return_value = 2

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        await reset_kiosk_user_password(
            db,
            org_id=org_id,
            acting_user_id=acting_user_id,
            target_user_id=target_user_id,
            new_password="NewSecurePass123",
            ip_address="192.168.1.50",
        )

        mock_audit.assert_called_once_with(
            session=db,
            org_id=org_id,
            user_id=acting_user_id,
            action="auth.kiosk_password_reset",
            entity_type="user",
            entity_id=target_user_id,
            after_value={
                "target_email": "tablet1@shop.test",
                "sessions_invalidated": 2,
            },
            ip_address="192.168.1.50",
        )

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch(
        "app.modules.organisations.service._invalidate_user_sessions",
        new_callable=AsyncMock,
    )
    @patch("app.modules.auth.password.hash_password")
    async def test_successful_reset_returns_correct_dict(
        self, mock_hash, mock_invalidate, mock_audit
    ):
        """5.1: returns dict with user_id and sessions_invalidated."""
        org_id = uuid.uuid4()
        acting_user_id = uuid.uuid4()
        target_user_id = uuid.uuid4()
        user = _make_kiosk_user(user_id=target_user_id, org_id=org_id)

        mock_hash.return_value = "$2b$12$somehash"
        mock_invalidate.return_value = 0

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        result = await reset_kiosk_user_password(
            db,
            org_id=org_id,
            acting_user_id=acting_user_id,
            target_user_id=target_user_id,
            new_password="NewSecurePass123",
        )

        assert result == {
            "user_id": str(target_user_id),
            "sessions_invalidated": 0,
        }


# ===========================================================================
# Validation failures
# ===========================================================================


class TestResetKioskUserPasswordValidation:
    """Requirements 5.1–5.6: validation failures raise ValueError."""

    @pytest.mark.asyncio
    async def test_target_not_found_raises_value_error(self):
        """5.1, 5.2: user not found in org raises ValueError."""
        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(None)

        with pytest.raises(ValueError, match="User not found"):
            await reset_kiosk_user_password(
                db,
                org_id=uuid.uuid4(),
                acting_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                new_password="SomePassword123",
            )

    @pytest.mark.asyncio
    async def test_target_in_different_org_raises_value_error(self):
        """5.1, 5.2: user in different org (query returns None) raises ValueError."""
        # The query filters by org_id, so a user in a different org returns None
        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(None)

        caller_org_id = uuid.uuid4()
        target_user_id = uuid.uuid4()

        with pytest.raises(ValueError, match="User not found"):
            await reset_kiosk_user_password(
                db,
                org_id=caller_org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=target_user_id,
                new_password="SomePassword123",
            )

    @pytest.mark.asyncio
    async def test_target_not_kiosk_role_raises_value_error(self):
        """5.3, 5.4: non-kiosk user raises ValueError."""
        org_id = uuid.uuid4()
        user = _make_kiosk_user(org_id=org_id, role="org_admin")

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        with pytest.raises(
            ValueError, match="Password reset is only allowed for kiosk users"
        ):
            await reset_kiosk_user_password(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                new_password="SomePassword123",
            )

    @pytest.mark.asyncio
    async def test_target_inactive_raises_value_error(self):
        """5.5, 5.6: inactive kiosk user raises ValueError."""
        org_id = uuid.uuid4()
        user = _make_kiosk_user(org_id=org_id, role="kiosk", is_active=False)

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        with pytest.raises(
            ValueError, match="Cannot reset password for inactive user"
        ):
            await reset_kiosk_user_password(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                new_password="SomePassword123",
            )

    @pytest.mark.asyncio
    async def test_salesperson_role_raises_value_error(self):
        """5.3, 5.4: salesperson role raises ValueError."""
        org_id = uuid.uuid4()
        user = _make_kiosk_user(org_id=org_id, role="salesperson")

        db = _mock_db()
        db.execute.return_value = _mock_scalar_result(user)

        with pytest.raises(
            ValueError, match="Password reset is only allowed for kiosk users"
        ):
            await reset_kiosk_user_password(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                new_password="SomePassword123",
            )
