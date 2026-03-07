"""Unit tests for Task 6.7 — consolidated organisation module tests.

Covers:
  - Onboarding wizard step saving and skipping (Requirements 8.2, 8.4)
  - GST number validation in IRD format (Requirement 9.3)
  - Seat limit enforcement on user invitations (Requirement 10.4)

These tests exercise the service layer with mocked database sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.organisations.schemas import (
    OnboardingStepRequest,
    validate_ird_gst_number,
)
from app.modules.organisations.service import (
    ALL_ONBOARDING_FIELDS,
    SeatLimitExceeded,
    invite_org_user,
    save_onboarding_step,
    update_org_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_org(org_id=None, plan_id=None, name="Test Workshop", settings=None):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.plan_id = plan_id or uuid.uuid4()
    org.name = name
    org.settings = settings if settings is not None else {}
    return org


def _make_plan(plan_id=None, user_seats=5):
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.user_seats = user_seats
    return plan


def _make_user(user_id=None, org_id=None, email="user@test.com", role="salesperson"):
    user = MagicMock(spec=User)
    user.id = user_id or uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.email = email
    user.role = role
    user.is_active = True
    user.is_email_verified = True
    user.last_login_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return user


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalar_count(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ===========================================================================
# 1. Onboarding wizard step saving and skipping (Requirements 8.2, 8.4)
# ===========================================================================


class TestOnboardingStepSaving:
    """Requirement 8.2: step-by-step onboarding wizard saves fields."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_save_single_field_updates_settings(self, mock_audit):
        """Saving one field should update only that field in settings."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db, org_id=org.id, user_id=uuid.uuid4(), gst_number="12-345-678"
        )

        assert "gst_number" in result["updated_fields"]
        assert result["skipped"] is False
        assert org.settings["gst_number"] == "12-345-678"

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_save_multiple_fields_in_one_step(self, mock_audit):
        """Multiple fields can be saved in a single step."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db,
            org_id=org.id,
            user_id=uuid.uuid4(),
            invoice_prefix="INV-",
            invoice_start_number=1000,
        )

        assert "invoice_prefix" in result["updated_fields"]
        assert "invoice_start_number" in result["updated_fields"]
        assert org.settings["invoice_prefix"] == "INV-"
        assert org.settings["invoice_start_number"] == 1000

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_save_tracks_completed_fields_cumulatively(self, mock_audit):
        """Completed fields accumulate across multiple save calls."""
        org = _make_org(settings={"onboarding_completed_fields": ["org_name"]})
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db, org_id=org.id, user_id=uuid.uuid4(), gst_number="12-345-678"
        )

        completed = org.settings["onboarding_completed_fields"]
        assert "org_name" in completed
        assert "gst_number" in completed


class TestOnboardingStepSkipping:
    """Requirement 8.4: any onboarding step can be skipped."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_skip_step_returns_skipped_true(self, mock_audit):
        """Calling save with no fields marks the step as skipped."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db, org_id=org.id, user_id=uuid.uuid4()
        )

        assert result["skipped"] is True
        assert result["updated_fields"] == []

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_skip_does_not_write_audit_log(self, mock_audit):
        """Skipping a step should not produce an audit log entry."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        await save_onboarding_step(db, org_id=org.id, user_id=uuid.uuid4())

        mock_audit.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_skip_does_not_alter_existing_settings(self, mock_audit):
        """Skipping should leave existing settings untouched."""
        original_settings = {"gst_number": "12-345-678", "gst_percentage": 15.0}
        org = _make_org(settings=dict(original_settings))
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        await save_onboarding_step(db, org_id=org.id, user_id=uuid.uuid4())

        assert org.settings["gst_number"] == "12-345-678"
        assert org.settings["gst_percentage"] == 15.0

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_workspace_usable_after_partial_onboarding(self, mock_audit):
        """Workspace is usable (onboarding_complete can be False) after partial steps."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db, org_id=org.id, user_id=uuid.uuid4(), org_name="My Workshop"
        )

        # Only one field completed — onboarding is not complete but workspace is usable
        assert result["onboarding_complete"] is False
        assert result["skipped"] is False

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_onboarding_complete_when_all_fields_provided(self, mock_audit):
        """Onboarding is complete only when ALL_ONBOARDING_FIELDS are covered."""
        # Pre-fill all fields except org_name
        completed = sorted(ALL_ONBOARDING_FIELDS - {"org_name"})
        org = _make_org(settings={"onboarding_completed_fields": completed})
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await save_onboarding_step(
            db, org_id=org.id, user_id=uuid.uuid4(), org_name="Final Step"
        )

        assert result["onboarding_complete"] is True

    def test_schema_allows_all_none_fields(self):
        """OnboardingStepRequest accepts an empty body (all fields None)."""
        req = OnboardingStepRequest()
        assert req.org_name is None
        assert req.gst_number is None
        assert req.invoice_prefix is None


# ===========================================================================
# 2. GST number validation — IRD format (Requirement 9.3)
# ===========================================================================


class TestGSTNumberValidation:
    """Requirement 9.3: GST number validated against IRD format."""

    # --- Valid formats ---

    def test_valid_8_digit_hyphenated(self):
        assert validate_ird_gst_number("12-345-678") == "12-345-678"

    def test_valid_9_digit_hyphenated(self):
        assert validate_ird_gst_number("123-456-789") == "123-456-789"

    def test_valid_8_digit_plain(self):
        assert validate_ird_gst_number("12345678") == "12345678"

    def test_valid_9_digit_plain(self):
        assert validate_ird_gst_number("123456789") == "123456789"

    # --- Invalid formats ---

    def test_rejects_too_few_digits(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("1234567")

    def test_rejects_too_many_digits(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("1234567890")

    def test_rejects_alphabetic_characters(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("AB-CDE-FGH")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="8 or 9 digits"):
            validate_ird_gst_number("")

    def test_rejects_wrong_hyphen_placement(self):
        """Hyphens in non-standard positions should be rejected."""
        with pytest.raises(ValueError):
            validate_ird_gst_number("1-2345-678")

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_settings_validates_gst_number(self, mock_audit):
        """update_org_settings should reject an invalid GST number."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="8 or 9 digits"):
            await update_org_settings(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                gst_number="INVALID",
            )

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_settings_accepts_valid_gst_number(self, mock_audit):
        """update_org_settings should accept a valid IRD GST number."""
        org = _make_org()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await update_org_settings(
            db,
            org_id=org.id,
            user_id=uuid.uuid4(),
            gst_number="123-456-789",
        )

        assert "gst_number" in result["updated_fields"]
        assert org.settings["gst_number"] == "123-456-789"


# ===========================================================================
# 3. Seat limit enforcement (Requirement 10.4)
# ===========================================================================


class TestSeatLimitEnforcement:
    """Requirement 10.4: enforce user seat limits based on subscription plan."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_invite_blocked_when_at_seat_limit(self, mock_audit):
        """Inviting a user when at the seat limit raises SeatLimitExceeded."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=3)
        org = _make_org(org_id=org_id, plan_id=plan.id)

        db = _mock_db()
        # First call: org lookup, second: plan lookup, third: count query
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(plan),
                _mock_scalar_count(3),  # 3 active users == 3 seat limit
            ]
        )

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

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.auth.service.create_invitation", new_callable=AsyncMock)
    async def test_invite_allowed_below_seat_limit(self, mock_create, mock_audit):
        """Inviting a user below the seat limit should succeed."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=5)
        org = _make_org(org_id=org_id, plan_id=plan.id)
        new_user = _make_user(org_id=org_id, email="new@test.com")

        mock_create.return_value = {"user_id": str(new_user.id)}

        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),      # org lookup
                _mock_scalar_result(plan),     # plan lookup
                _mock_scalar_count(2),         # 2 active users < 5 seat limit
                _mock_scalar_result(new_user), # fetch created user
            ]
        )

        result = await invite_org_user(
            db,
            org_id=org_id,
            inviter_user_id=uuid.uuid4(),
            email="new@test.com",
            role="salesperson",
        )

        assert result["email"] == "new@test.com"
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    async def test_invite_blocked_when_over_seat_limit(self, mock_audit):
        """Inviting when already over the limit (e.g. plan downgrade) still blocks."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=2)
        org = _make_org(org_id=org_id, plan_id=plan.id)

        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(plan),
                _mock_scalar_count(5),  # 5 active users > 2 seat limit
            ]
        )

        with pytest.raises(SeatLimitExceeded) as exc_info:
            await invite_org_user(
                db,
                org_id=org_id,
                inviter_user_id=uuid.uuid4(),
                email="new@test.com",
                role="salesperson",
            )

        assert exc_info.value.seat_limit == 2
        assert exc_info.value.current_users == 5

    def test_seat_limit_exceeded_message_includes_upgrade_prompt(self):
        """SeatLimitExceeded message should direct user to upgrade."""
        exc = SeatLimitExceeded(current_users=5, seat_limit=5)
        assert "upgrade" in str(exc).lower()
        assert "5/5" in str(exc)

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.auth.service.create_invitation", new_callable=AsyncMock)
    async def test_zero_seat_limit_means_unlimited(self, mock_create, mock_audit):
        """A seat limit of 0 should mean unlimited (no enforcement)."""
        org_id = uuid.uuid4()
        plan = _make_plan(user_seats=0)
        org = _make_org(org_id=org_id, plan_id=plan.id)
        new_user = _make_user(org_id=org_id, email="new@test.com")

        mock_create.return_value = {"user_id": str(new_user.id)}

        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(plan),
                _mock_scalar_count(100),       # 100 users but limit is 0 (unlimited)
                _mock_scalar_result(new_user),
            ]
        )

        result = await invite_org_user(
            db,
            org_id=org_id,
            inviter_user_id=uuid.uuid4(),
            email="new@test.com",
            role="salesperson",
        )

        assert result["email"] == "new@test.com"
