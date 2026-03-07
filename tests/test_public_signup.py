"""Unit tests for Task 6.6 — public signup flow.

Tests cover:
  - public_signup service: org creation with trial status, 14-day trial,
    Stripe customer + SetupIntent creation, signup token generation, audit log
  - Validation: invalid plan, archived plan, non-public plan, duplicate email
  - Schema validation for PublicSignupRequest / PublicSignupResponse
  - Auth middleware registers /api/v1/auth/signup as a public path

Requirement 8.6.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships
import app.modules.admin.models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.organisations.schemas import (
    PublicSignupRequest,
    PublicSignupResponse,
)

# Rebuild models to resolve forward references caused by `from __future__ import annotations`
PublicSignupRequest.model_rebuild()
PublicSignupResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(
    plan_id=None,
    name="Starter",
    storage_quota_gb=5,
    is_archived=False,
    is_public=True,
):
    """Create a mock SubscriptionPlan."""
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.name = name
    plan.monthly_price_nzd = 49.00
    plan.user_seats = 5
    plan.storage_quota_gb = storage_quota_gb
    plan.carjam_lookups_included = 100
    plan.enabled_modules = []
    plan.is_public = is_public
    plan.is_archived = is_archived
    return plan


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPublicSignupSchemas:
    """Validate Pydantic request/response schemas."""

    def test_valid_request(self):
        req = PublicSignupRequest(
            org_name="Test Workshop",
            admin_email="admin@test.co.nz",
            admin_first_name="Jane",
            admin_last_name="Doe",
            plan_id=str(uuid.uuid4()),
        )
        assert req.org_name == "Test Workshop"
        assert req.admin_email == "admin@test.co.nz"

    def test_empty_org_name_rejected(self):
        with pytest.raises(Exception):
            PublicSignupRequest(
                org_name="",
                admin_email="admin@test.co.nz",
                admin_first_name="Jane",
                admin_last_name="Doe",
                plan_id=str(uuid.uuid4()),
            )

    def test_invalid_email_rejected(self):
        with pytest.raises(Exception):
            PublicSignupRequest(
                org_name="Workshop",
                admin_email="not-an-email",
                admin_first_name="Jane",
                admin_last_name="Doe",
                plan_id=str(uuid.uuid4()),
            )

    def test_empty_first_name_rejected(self):
        with pytest.raises(Exception):
            PublicSignupRequest(
                org_name="Workshop",
                admin_email="admin@test.co.nz",
                admin_first_name="",
                admin_last_name="Doe",
                plan_id=str(uuid.uuid4()),
            )

    def test_response_model(self):
        resp = PublicSignupResponse(
            message="Signup successful",
            organisation_id=str(uuid.uuid4()),
            organisation_name="Workshop",
            plan_id=str(uuid.uuid4()),
            admin_user_id=str(uuid.uuid4()),
            admin_email="admin@test.co.nz",
            trial_ends_at=datetime.now(timezone.utc),
            stripe_setup_intent_client_secret="seti_secret_123",
            signup_token="tok_abc",
        )
        assert resp.stripe_setup_intent_client_secret == "seti_secret_123"
        assert resp.signup_token == "tok_abc"


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestPublicSignup:
    """Test the public_signup service function."""

    @pytest.mark.asyncio
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_successful_signup(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()

        # First execute returns plan, second returns None (no existing user)
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])

        mock_stripe_customer.return_value = "cus_test_123"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_test_123",
            "client_secret": "seti_secret_test_123",
        }
        mock_redis.setex = AsyncMock()

        result = await public_signup(
            db,
            org_name="My Workshop",
            admin_email="owner@workshop.co.nz",
            admin_first_name="John",
            admin_last_name="Smith",
            plan_id=plan.id,
            ip_address="203.0.113.1",
        )

        assert result["organisation_name"] == "My Workshop"
        assert result["admin_email"] == "owner@workshop.co.nz"
        assert result["stripe_setup_intent_client_secret"] == "seti_secret_test_123"
        assert "signup_token" in result
        assert result["trial_ends_at"] is not None

        # Verify org was added to DB
        assert db.add.call_count >= 2  # org + user
        assert db.flush.call_count >= 3  # org, user, stripe_customer_id update

    @pytest.mark.asyncio
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_trial_ends_in_14_days(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_stripe_customer.return_value = "cus_test"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_test",
            "client_secret": "seti_secret",
        }
        mock_redis.setex = AsyncMock()

        before = datetime.now(timezone.utc)
        result = await public_signup(
            db,
            org_name="Workshop",
            admin_email="a@b.co.nz",
            admin_first_name="A",
            admin_last_name="B",
            plan_id=plan.id,
        )
        after = datetime.now(timezone.utc)

        trial_end = result["trial_ends_at"]
        assert trial_end >= before + timedelta(days=14)
        assert trial_end <= after + timedelta(days=14)

    @pytest.mark.asyncio
    async def test_plan_not_found(self):
        from app.modules.organisations.service import public_signup

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Subscription plan not found"):
            await public_signup(
                db,
                org_name="Workshop",
                admin_email="a@b.co.nz",
                admin_first_name="A",
                admin_last_name="B",
                plan_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_archived_plan_rejected(self):
        from app.modules.organisations.service import public_signup

        plan = _make_plan(is_archived=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="archived plan"):
            await public_signup(
                db,
                org_name="Workshop",
                admin_email="a@b.co.nz",
                admin_first_name="A",
                admin_last_name="B",
                plan_id=plan.id,
            )

    @pytest.mark.asyncio
    async def test_non_public_plan_rejected(self):
        from app.modules.organisations.service import public_signup

        plan = _make_plan(is_public=False)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="not available for public signup"):
            await public_signup(
                db,
                org_name="Workshop",
                admin_email="a@b.co.nz",
                admin_first_name="A",
                admin_last_name="B",
                plan_id=plan.id,
            )

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        existing_user = MagicMock(spec=User)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(existing_user),
        ])

        with pytest.raises(ValueError, match="already exists"):
            await public_signup(
                db,
                org_name="Workshop",
                admin_email="taken@test.co.nz",
                admin_first_name="A",
                admin_last_name="B",
                plan_id=plan.id,
            )

    @pytest.mark.asyncio
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_org_created_with_trial_status(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_stripe_customer.return_value = "cus_test"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_test",
            "client_secret": "seti_secret",
        }
        mock_redis.setex = AsyncMock()

        await public_signup(
            db,
            org_name="Trial Workshop",
            admin_email="trial@test.co.nz",
            admin_first_name="A",
            admin_last_name="B",
            plan_id=plan.id,
        )

        # Verify the org was added with trial status
        add_calls = db.add.call_args_list
        org_added = add_calls[0][0][0]
        assert isinstance(org_added, Organisation)
        assert org_added.status == "trial"
        assert org_added.trial_ends_at is not None

    @pytest.mark.asyncio
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_stripe_customer_and_setup_intent_created(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_stripe_customer.return_value = "cus_stripe_123"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_stripe_123",
            "client_secret": "seti_secret_stripe_123",
        }
        mock_redis.setex = AsyncMock()

        result = await public_signup(
            db,
            org_name="Workshop",
            admin_email="a@b.co.nz",
            admin_first_name="A",
            admin_last_name="B",
            plan_id=plan.id,
        )

        # Stripe customer created with correct args
        mock_stripe_customer.assert_called_once()
        call_kwargs = mock_stripe_customer.call_args[1]
        assert call_kwargs["email"] == "a@b.co.nz"
        assert call_kwargs["name"] == "Workshop"

        # SetupIntent created with the customer ID
        mock_setup_intent.assert_called_once()
        si_kwargs = mock_setup_intent.call_args[1]
        assert si_kwargs["customer_id"] == "cus_stripe_123"

        assert result["stripe_setup_intent_client_secret"] == "seti_secret_stripe_123"

    @pytest.mark.asyncio
    @patch("app.core.audit.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_signup_token_stored_in_redis(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_stripe_customer.return_value = "cus_test"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_test",
            "client_secret": "seti_secret",
        }
        mock_redis.setex = AsyncMock()

        result = await public_signup(
            db,
            org_name="Workshop",
            admin_email="a@b.co.nz",
            admin_first_name="A",
            admin_last_name="B",
            plan_id=plan.id,
        )

        # Token stored in Redis with signup: prefix and 48h TTL
        mock_redis.setex.assert_called_once()
        redis_args = mock_redis.setex.call_args[0]
        assert redis_args[0].startswith("signup:")
        assert redis_args[1] == 48 * 3600
        token_data = json.loads(redis_args[2])
        assert token_data["email"] == "a@b.co.nz"
        assert token_data["type"] == "signup"

        # Signup token returned in result
        assert len(result["signup_token"]) > 0

    @pytest.mark.asyncio
    @patch("app.modules.organisations.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_setup_intent", new_callable=AsyncMock)
    @patch("app.integrations.stripe_billing.create_stripe_customer", new_callable=AsyncMock)
    @patch("app.core.redis.redis_pool")
    async def test_audit_log_written(
        self, mock_redis, mock_stripe_customer, mock_setup_intent, mock_audit
    ):
        from app.modules.organisations.service import public_signup

        plan = _make_plan()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(plan),
            _mock_scalar_result(None),
        ])
        mock_stripe_customer.return_value = "cus_test"
        mock_setup_intent.return_value = {
            "setup_intent_id": "seti_test",
            "client_secret": "seti_secret",
        }
        mock_redis.setex = AsyncMock()

        await public_signup(
            db,
            org_name="Workshop",
            admin_email="a@b.co.nz",
            admin_first_name="A",
            admin_last_name="B",
            plan_id=plan.id,
            ip_address="203.0.113.1",
        )

        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args[1]
        assert audit_kwargs["action"] == "org.public_signup"
        assert audit_kwargs["after_value"]["status"] == "trial"
        assert audit_kwargs["ip_address"] == "203.0.113.1"


# ---------------------------------------------------------------------------
# Auth middleware public path test
# ---------------------------------------------------------------------------


class TestSignupPublicPath:
    """Verify /api/v1/auth/signup is registered as a public path."""

    def test_signup_in_public_paths(self):
        from app.middleware.auth import PUBLIC_PATHS

        assert "/api/v1/auth/signup" in PUBLIC_PATHS
