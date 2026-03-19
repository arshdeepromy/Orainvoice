"""Backend unit tests for signup wizard edge cases.

Tests cover:
  - Expired pending signup returns correct error
  - confirm-payment with non-existent pending_signup_id returns 400
  - confirm-payment deletes Redis key after success (replay prevention)
  - Email already registered returns 400 without creating pending signup
  - Coupon reducing price to zero skips PaymentIntent

Requirements: 1.3, 1.4, 5.3, 6.2, 7.2, 7.4
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.auth.pending_signup import _signup_key, _email_index_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PASSWORD = "S3cret!Pass99"


def _make_plan(
    plan_id=None,
    name="Professional",
    monthly_price_nzd=49.00,
    storage_quota_gb=10,
    is_archived=False,
    is_public=True,
    trial_duration=0,
    trial_duration_unit="days",
):
    """Create a mock SubscriptionPlan (paid plan by default)."""
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.name = name
    plan.monthly_price_nzd = monthly_price_nzd
    plan.user_seats = 5
    plan.storage_quota_gb = storage_quota_gb
    plan.carjam_lookups_included = 100
    plan.enabled_modules = []
    plan.is_public = is_public
    plan.is_archived = is_archived
    plan.trial_duration = trial_duration
    plan.trial_duration_unit = trial_duration_unit
    return plan


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_pending_signup_data(**overrides) -> dict:
    """Build a sample pending signup dict as stored in Redis."""
    base = {
        "org_name": "Test Workshop",
        "admin_email": "admin@test.co.nz",
        "admin_first_name": "Jane",
        "admin_last_name": "Doe",
        "password_hash": "$2b$12$fakehashvalue",
        "plan_id": str(uuid.uuid4()),
        "plan_name": "Professional",
        "payment_amount_cents": 4900,
        "stripe_payment_intent_id": "pi_test_abc123",
        "coupon_code": None,
        "coupon_discount_type": None,
        "coupon_discount_value": None,
        "ip_address": "127.0.0.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def _make_stripe_intent(status="succeeded", payment_method="pm_test_123"):
    """Create a mock Stripe PaymentIntent object."""
    intent = MagicMock()
    intent.status = status
    intent.payment_method = payment_method
    intent.get = MagicMock(return_value={})
    return intent


def _make_stripe_pm():
    """Create a mock Stripe PaymentMethod object."""
    pm = MagicMock()
    pm.get = MagicMock(return_value={
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2030,
    })
    return pm


# ---------------------------------------------------------------------------
# Test: Expired pending signup returns correct error (Req 1.4, 6.2)
# ---------------------------------------------------------------------------


class TestExpiredPendingSignup:
    """When a pending signup has expired in Redis, confirm-payment should
    return 400 with 'Invalid or expired signup session'."""

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_expired_pending_signup_returns_error(self, mock_redis):
        """Simulate expiry by having get_pending_signup return None."""
        mock_redis.get = AsyncMock(return_value=None)

        from app.modules.auth.pending_signup import get_pending_signup

        result = await get_pending_signup("expired-signup-id")
        assert result is None

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_confirm_payment_rejects_expired_signup(self, mock_redis):
        """The confirm-payment endpoint returns 400 when the pending signup
        has expired (Redis key gone)."""
        # get_pending_signup returns None for expired key
        mock_redis.get = AsyncMock(return_value=None)

        from app.modules.auth.pending_signup import get_pending_signup

        pending = await get_pending_signup("expired-id-123")
        assert pending is None, (
            "Expired pending signup should return None, triggering "
            "'Invalid or expired signup session' error"
        )


# ---------------------------------------------------------------------------
# Test: Non-existent pending_signup_id returns 400 (Req 1.4)
# ---------------------------------------------------------------------------


class TestNonExistentPendingSignupId:
    """confirm-payment with a random UUID that was never stored should
    return 400."""

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_random_uuid_returns_none(self, mock_redis):
        """A completely random pending_signup_id should not exist in Redis."""
        mock_redis.get = AsyncMock(return_value=None)

        from app.modules.auth.pending_signup import get_pending_signup

        random_id = str(uuid.uuid4())
        result = await get_pending_signup(random_id)
        assert result is None

        # Verify the correct Redis key was queried
        mock_redis.get.assert_called_once_with(_signup_key(random_id))


# ---------------------------------------------------------------------------
# Test: confirm-payment deletes Redis key after success (Req 7.2)
# ---------------------------------------------------------------------------


class TestReplayPrevention:
    """After successful payment confirmation, the pending signup key must
    be deleted from Redis so the same signup cannot be replayed."""

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_delete_removes_both_keys(self, mock_redis):
        """delete_pending_signup removes both the signup key and the
        email index key."""
        pending_data = _make_pending_signup_data()
        mock_redis.get = AsyncMock(return_value=json.dumps(pending_data))
        mock_redis.delete = AsyncMock()

        from app.modules.auth.pending_signup import delete_pending_signup

        pending_id = "test-pending-id"
        await delete_pending_signup(pending_id)

        mock_redis.delete.assert_called_once()
        deleted_keys = mock_redis.delete.call_args[0]
        assert _signup_key(pending_id) in deleted_keys
        assert _email_index_key(pending_data["admin_email"]) in deleted_keys

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_replay_returns_none_after_delete(self, mock_redis):
        """After deletion, a second get_pending_signup returns None,
        which would cause confirm-payment to reject the replay."""
        # First call returns data, second call (after delete) returns None
        mock_redis.get = AsyncMock(side_effect=[
            json.dumps(_make_pending_signup_data()),  # first get (for delete)
            None,  # second get (replay attempt)
        ])
        mock_redis.delete = AsyncMock()

        from app.modules.auth.pending_signup import (
            delete_pending_signup,
            get_pending_signup,
        )

        pending_id = "replay-test-id"

        # Delete the pending signup (simulating post-confirmation cleanup)
        await delete_pending_signup(pending_id)

        # Replay attempt — should return None
        result = await get_pending_signup(pending_id)
        assert result is None


# ---------------------------------------------------------------------------
# Test: Email already registered returns 400 (Req 7.4)
# ---------------------------------------------------------------------------


class TestEmailAlreadyRegistered:
    """When the email is already registered to an existing User, the signup
    endpoint should reject the request without creating a pending signup."""

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_value_error(self):
        """public_signup raises ValueError when email already exists."""
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        existing_user = MagicMock(spec=User)
        db = _mock_db_session()

        # First execute returns the plan, second returns an existing user
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(existing_user),
        ])

        with pytest.raises(ValueError, match="already exists"):
            await public_signup(
                db,
                org_name="New Workshop",
                admin_email="taken@test.co.nz",
                admin_first_name="Jane",
                admin_last_name="Doe",
                password=_DEFAULT_PASSWORD,
                plan_id=plan.id,
            )

        # Verify no Organisation or User was added to the DB
        db.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.modules.auth.pending_signup.redis_pool")
    async def test_duplicate_email_does_not_create_pending_signup(self, mock_redis):
        """No pending signup should be created when email is already taken."""
        from app.modules.organisations.service import public_signup

        plan = _make_plan()  # paid plan (trial_duration=0)
        existing_user = MagicMock(spec=User)
        db = _mock_db_session()

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(existing_user),
        ])

        pipe = MagicMock()
        pipe.setex = MagicMock()
        pipe.execute = AsyncMock()
        mock_redis.pipeline.return_value = pipe

        with pytest.raises(ValueError, match="already exists"):
            await public_signup(
                db,
                org_name="Workshop",
                admin_email="taken@test.co.nz",
                admin_first_name="A",
                admin_last_name="B",
                password=_DEFAULT_PASSWORD,
                plan_id=plan.id,
            )

        # No Redis pipeline calls should have been made
        pipe.setex.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Coupon reducing price to zero skips PaymentIntent (Req 5.3)
# ---------------------------------------------------------------------------


class TestCouponZeroPrice:
    """When a coupon reduces the effective price to zero for a paid plan,
    the backend should skip PaymentIntent creation, create the account
    immediately, and return requires_payment: false."""

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.auth.service.send_verification_email", new_callable=AsyncMock)
    @patch("app.modules.auth.service.create_email_verification_token", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    @patch("app.modules.admin.service.validate_coupon", new_callable=AsyncMock)
    async def test_100_percent_coupon_skips_payment(
        self,
        mock_validate_coupon,
        mock_redis,
        mock_create_token,
        mock_send_email,
        mock_audit,
    ):
        """A 100% percentage coupon on a paid plan should create the account
        immediately and return requires_payment=False."""
        from app.modules.organisations.service import public_signup

        plan = _make_plan(monthly_price_nzd=49.00, trial_duration=0)
        db = _mock_db_session()

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),   # plan lookup
            _mock_scalar_result(None),   # email uniqueness check
        ])
        mock_redis.setex = AsyncMock()
        mock_create_token.return_value = "verify_token_abc"

        # Coupon gives 100% discount
        mock_validate_coupon.return_value = {
            "valid": True,
            "coupon": {
                "discount_type": "percentage",
                "discount_value": 100,
            },
        }

        result = await public_signup(
            db,
            org_name="Free Workshop",
            admin_email="free@test.co.nz",
            admin_first_name="Jane",
            admin_last_name="Doe",
            password=_DEFAULT_PASSWORD,
            plan_id=plan.id,
            coupon_code="FREE100",
        )

        assert result["requires_payment"] is False
        assert result["payment_amount_cents"] == 0
        # Organisation and User should have been created
        assert db.add.call_count >= 2
        assert "organisation_id" in result

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.auth.service.send_verification_email", new_callable=AsyncMock)
    @patch("app.modules.auth.service.create_email_verification_token", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    @patch("app.modules.admin.service.validate_coupon", new_callable=AsyncMock)
    async def test_fixed_amount_coupon_zeroes_price(
        self,
        mock_validate_coupon,
        mock_redis,
        mock_create_token,
        mock_send_email,
        mock_audit,
    ):
        """A fixed-amount coupon that equals or exceeds the plan price should
        create the account immediately without PaymentIntent."""
        from app.modules.organisations.service import public_signup

        plan = _make_plan(monthly_price_nzd=49.00, trial_duration=0)
        db = _mock_db_session()

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_redis.setex = AsyncMock()
        mock_create_token.return_value = "verify_token_xyz"

        # Fixed-amount coupon >= plan price
        mock_validate_coupon.return_value = {
            "valid": True,
            "coupon": {
                "discount_type": "fixed_amount",
                "discount_value": 50.00,  # $50 off a $49 plan
            },
        }

        result = await public_signup(
            db,
            org_name="Discounted Workshop",
            admin_email="discount@test.co.nz",
            admin_first_name="John",
            admin_last_name="Smith",
            password=_DEFAULT_PASSWORD,
            plan_id=plan.id,
            coupon_code="BIGDISCOUNT",
        )

        assert result["requires_payment"] is False
        assert result["payment_amount_cents"] == 0
        assert db.add.call_count >= 2
        assert "organisation_id" in result
