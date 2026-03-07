"""Unit tests for Task 6.5 — organisation user management.

Tests cover:
  - list_org_users: listing users with seat limit info
  - invite_org_user: invitation with seat limit enforcement
  - update_org_user: role change, deactivation with session invalidation
  - deactivate_org_user: deactivation, self-deactivation prevention
  - update_mfa_policy: optional/mandatory policy setting
  - SeatLimitExceeded: seat limit error when limit reached
  - Schema validation

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import Session, User
from app.modules.organisations.schemas import (
    MFAPolicyUpdateRequest,
    OrgUserResponse,
    SeatLimitResponse,
    UserInviteRequest,
    UserListResponse,
    UserUpdateRequest,
)
from app.modules.organisations.service import (
    SeatLimitExceeded,
    deactivate_org_user,
    invite_org_user,
    list_org_users,
    update_mfa_policy,
    update_org_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(plan_id=None, user_seats=5):
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.user_seats = user_seats
    return plan


def _make_org(org_id=None, plan_id=None, settings=None):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.plan_id = plan_id or uuid.uuid4()
    org.settings = settings if settings is not None else {}
    org.name = "Test Workshop"
    return org


def _make_user(user_id=None, org_id=None, email="admin@test.com", role="org_admin", is_active=True):
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = role
    user.is_active = is_active
    user.is_email_verified = True
    user.last_login_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return user


def _make_session(user_id, is_revoked=False):
    sess = MagicMock(spec=Session)
    sess.id = uuid.uuid4()
    sess.user_id = user_id
    sess.is_revoked = is_revoked
    return sess


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_scalar_count(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestUserManagementSchemas:
    def test_invite_request_defaults(self):
        req = UserInviteRequest(email="user@test.com")
        assert req.role == "salesperson"

    def test_invite_request_org_admin(self):
        req = UserInviteRequest(email="admin@test.com", role="org_admin")
        assert req.role == "org_admin"

    def test_user_list_response(self):
        resp = UserListResponse(
            users=[],
            total=0,
            seat_limit=5,
        )
        assert resp.seat_limit == 5

    def test_update_request_role_only(self):
        req = UserUpdateRequest(role="org_admin")
        assert req.role == "org_admin"
        assert req.is_active is None

    def test_update_request_deactivate(self):
        req = UserUpdateRequest(is_active=False)
        assert req.is_active is False
        assert req.role is None

    def test_mfa_policy_request(self):
        req = MFAPolicyUpdateRequest(mfa_policy="mandatory")
        assert req.mfa_policy == "mandatory"

    def test_seat_limit_response(self):
        resp = SeatLimitResponse(
            detail="Seat limit reached",
            current_users=5,
            seat_limit=5,
        )
        assert resp.upgrade_required is True

    def test_org_user_response(self):
        resp = OrgUserResponse(
            id=str(uuid.uuid4()),
            email="user@test.com",
            role="salesperson",
            is_active=True,
            is_email_verified=True,
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.last_login_at is None


# ---------------------------------------------------------------------------
# list_org_users tests
# ---------------------------------------------------------------------------

class TestListOrgUsers:
    @pytest.mark.asyncio
    async def test_returns_users_with_seat_limit(self):
        """Lists users and includes seat limit from subscription plan."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=10)
        org = _make_org(org_id=org_id, plan_id=plan.id)
        users = [
            _make_user(org_id=org_id, email="user1@test.com"),
            _make_user(org_id=org_id, email="user2@test.com", role="salesperson"),
        ]

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalars_result(users),   # users query
            _mock_scalar_result(org),       # org query
            _mock_scalar_result(plan),      # plan query
        ])

        result = await list_org_users(db, org_id=org_id)

        assert result["total"] == 2
        assert result["seat_limit"] == 10
        assert len(result["users"]) == 2
        assert result["users"][0]["email"] == "user1@test.com"

    @pytest.mark.asyncio
    async def test_empty_org_returns_zero(self):
        """Returns empty list for org with no users."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=5)
        org = _make_org(org_id=org_id, plan_id=plan.id)

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalars_result([]),
            _mock_scalar_result(org),
            _mock_scalar_result(plan),
        ])

        result = await list_org_users(db, org_id=org_id)

        assert result["total"] == 0
        assert result["seat_limit"] == 5


# ---------------------------------------------------------------------------
# invite_org_user tests
# ---------------------------------------------------------------------------

class TestInviteOrgUser:
    @pytest.mark.asyncio
    async def test_invite_creates_user(self):
        """Inviting a user delegates to create_invitation and returns user data."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=5)
        org = _make_org(org_id=org_id, plan_id=plan.id)
        admin = _make_user(org_id=org_id)
        new_user = _make_user(
            org_id=org_id, email="new@test.com", role="salesperson",
            is_active=True,
        )
        new_user.is_email_verified = False
        new_user_id = str(new_user.id)

        db = _mock_db()
        # Calls: _get_seat_limit_and_count (org, plan, count), create_invitation, fetch user
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(org),       # org for seat check
            _mock_scalar_result(plan),      # plan for seat limit
            _mock_scalar_count(2),          # active user count
            _mock_scalar_result(new_user),  # fetch created user
        ])

        with patch(
            "app.modules.auth.service.create_invitation",
            new_callable=AsyncMock,
            return_value={"user_id": new_user_id, "invitation_expires_at": "2024-01-03T00:00:00+00:00"},
        ):
            result = await invite_org_user(
                db,
                org_id=org_id,
                inviter_user_id=admin.id,
                email="new@test.com",
                role="salesperson",
            )

        assert result["email"] == "new@test.com"
        assert result["role"] == "salesperson"

    @pytest.mark.asyncio
    async def test_invite_blocked_at_seat_limit(self):
        """Invitation fails when seat limit is reached (Requirement 10.4, 10.5)."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=3)
        org = _make_org(org_id=org_id, plan_id=plan.id)

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(org),
            _mock_scalar_result(plan),
            _mock_scalar_count(3),  # already at limit
        ])

        with pytest.raises(SeatLimitExceeded) as exc_info:
            await invite_org_user(
                db,
                org_id=org_id,
                inviter_user_id=uuid.uuid4(),
                email="new@test.com",
                role="salesperson",
            )

        assert exc_info.value.current_users == 3
        assert exc_info.value.seat_limit == 3
        assert "upgrade" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_invite_allowed_below_seat_limit(self):
        """Invitation succeeds when below seat limit."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=5)
        org = _make_org(org_id=org_id, plan_id=plan.id)
        new_user = _make_user(org_id=org_id, email="new@test.com", role="salesperson")
        new_user.is_email_verified = False

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(org),
            _mock_scalar_result(plan),
            _mock_scalar_count(2),          # below limit
            _mock_scalar_result(new_user),  # fetch created user
        ])

        with patch(
            "app.modules.auth.service.create_invitation",
            new_callable=AsyncMock,
            return_value={"user_id": str(new_user.id), "invitation_expires_at": "2024-01-03T00:00:00+00:00"},
        ):
            result = await invite_org_user(
                db, org_id=org_id, inviter_user_id=uuid.uuid4(),
                email="new@test.com", role="salesperson",
            )

        assert result["email"] == "new@test.com"


# ---------------------------------------------------------------------------
# update_org_user tests
# ---------------------------------------------------------------------------

class TestUpdateOrgUser:
    @pytest.mark.asyncio
    async def test_update_role(self):
        """Updating role changes the user's role."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id, role="salesperson")

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(user))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id, role="org_admin",
            )

        assert user.role == "org_admin"
        assert result["role"] == "org_admin"

    @pytest.mark.asyncio
    async def test_deactivate_invalidates_sessions(self):
        """Deactivating a user invalidates all their sessions (Requirement 10.2)."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)
        sessions = [_make_session(user.id), _make_session(user.id)]

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(user),       # fetch user
            _mock_scalars_result(sessions),  # fetch sessions to invalidate
        ])

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id, is_active=False,
            )

        assert user.is_active is False
        assert result["sessions_invalidated"] == 2
        for sess in sessions:
            assert sess.is_revoked is True

    @pytest.mark.asyncio
    async def test_invalid_role_rejected(self):
        """Invalid role value raises ValueError."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(user))

        with pytest.raises(ValueError, match="Role must be"):
            await update_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id, role="superadmin",
            )

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        """Raises ValueError when user not found in org."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="User not found"):
            await update_org_user(
                db, org_id=uuid.uuid4(), acting_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(), role="salesperson",
            )

    @pytest.mark.asyncio
    async def test_audit_log_written_on_update(self):
        """Audit log is written when user is updated."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id, role="salesperson")

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(user))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id, role="org_admin",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.user_updated"
        assert call_kwargs["entity_type"] == "user"


# ---------------------------------------------------------------------------
# deactivate_org_user tests
# ---------------------------------------------------------------------------

class TestDeactivateOrgUser:
    @pytest.mark.asyncio
    async def test_deactivate_user(self):
        """Deactivating a user sets is_active=False and invalidates sessions."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)
        sessions = [_make_session(user.id)]

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(user),
            _mock_scalars_result(sessions),
        ])

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await deactivate_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
            )

        assert user.is_active is False
        assert result["sessions_invalidated"] == 1

    @pytest.mark.asyncio
    async def test_cannot_deactivate_self(self):
        """Cannot deactivate your own account."""
        user_id = uuid.uuid4()

        db = _mock_db()

        with pytest.raises(ValueError, match="Cannot deactivate your own account"):
            await deactivate_org_user(
                db, org_id=uuid.uuid4(), acting_user_id=user_id,
                target_user_id=user_id,
            )

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        """Raises ValueError when user not found."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="User not found"):
            await deactivate_org_user(
                db, org_id=uuid.uuid4(), acting_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_audit_log_on_deactivation(self):
        """Audit log records deactivation with session count."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)

        db = _mock_db()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(user),
            _mock_scalars_result([]),  # no sessions
        ])

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await deactivate_org_user(
                db, org_id=org_id, acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.user_deactivated"
        assert call_kwargs["after_value"]["sessions_invalidated"] == 0


# ---------------------------------------------------------------------------
# update_mfa_policy tests
# ---------------------------------------------------------------------------

class TestUpdateMFAPolicy:
    @pytest.mark.asyncio
    async def test_set_mandatory(self):
        """Setting MFA policy to mandatory updates org settings."""
        org = _make_org(settings={"mfa_policy": "optional"})

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_mfa_policy(
                db, org_id=org.id, user_id=uuid.uuid4(),
                mfa_policy="mandatory",
            )

        assert result["mfa_policy"] == "mandatory"
        assert org.settings["mfa_policy"] == "mandatory"

    @pytest.mark.asyncio
    async def test_set_optional(self):
        """Setting MFA policy to optional updates org settings."""
        org = _make_org(settings={"mfa_policy": "mandatory"})

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_mfa_policy(
                db, org_id=org.id, user_id=uuid.uuid4(),
                mfa_policy="optional",
            )

        assert result["mfa_policy"] == "optional"

    @pytest.mark.asyncio
    async def test_invalid_policy_rejected(self):
        """Invalid MFA policy value raises ValueError."""
        db = _mock_db()

        with pytest.raises(ValueError, match="MFA policy must be"):
            await update_mfa_policy(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                mfa_policy="disabled",
            )

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Raises ValueError when org not found."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await update_mfa_policy(
                db, org_id=uuid.uuid4(), user_id=uuid.uuid4(),
                mfa_policy="mandatory",
            )

    @pytest.mark.asyncio
    async def test_audit_log_on_policy_change(self):
        """Audit log records MFA policy change."""
        org = _make_org(settings={"mfa_policy": "optional"})

        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_mfa_policy(
                db, org_id=org.id, user_id=uuid.uuid4(),
                mfa_policy="mandatory",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.mfa_policy_updated"
        assert call_kwargs["before_value"]["mfa_policy"] == "optional"
        assert call_kwargs["after_value"]["mfa_policy"] == "mandatory"


# ---------------------------------------------------------------------------
# SeatLimitExceeded tests
# ---------------------------------------------------------------------------

class TestSeatLimitExceeded:
    def test_exception_message(self):
        exc = SeatLimitExceeded(current_users=5, seat_limit=5)
        assert exc.current_users == 5
        assert exc.seat_limit == 5
        assert "upgrade" in str(exc).lower()
        assert "5/5" in str(exc)

    def test_exception_is_exception(self):
        exc = SeatLimitExceeded(current_users=3, seat_limit=3)
        assert isinstance(exc, Exception)
