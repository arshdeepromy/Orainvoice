"""Unit tests for Task 6.1 — organisation provisioning.

Tests cover:
  - provision_organisation: org creation, plan assignment, admin user creation,
    invitation token generation, email dispatch, audit logging
  - Validation: invalid plan, archived plan, duplicate email, invalid status
  - Schema validation
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
from app.modules.admin.schemas import (
    ProvisionOrganisationRequest,
    ProvisionOrganisationResponse,
)
from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(
    plan_id=None,
    name="Starter",
    storage_quota_gb=5,
    is_archived=False,
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
    plan.is_public = True
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

class TestProvisionOrganisationSchemas:
    """Test Pydantic schema validation."""

    def test_valid_request(self):
        req = ProvisionOrganisationRequest(
            name="Test Workshop",
            plan_id=str(uuid.uuid4()),
            admin_email="admin@workshop.co.nz",
        )
        assert req.name == "Test Workshop"
        assert req.status == "active"

    def test_request_with_trial_status(self):
        req = ProvisionOrganisationRequest(
            name="Trial Workshop",
            plan_id=str(uuid.uuid4()),
            admin_email="admin@trial.co.nz",
            status="trial",
        )
        assert req.status == "trial"

    def test_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            ProvisionOrganisationRequest(
                name="",
                plan_id=str(uuid.uuid4()),
                admin_email="admin@test.co.nz",
            )

    def test_request_invalid_email_rejected(self):
        with pytest.raises(Exception):
            ProvisionOrganisationRequest(
                name="Test",
                plan_id=str(uuid.uuid4()),
                admin_email="not-an-email",
            )

    def test_response_model(self):
        resp = ProvisionOrganisationResponse(
            message="OK",
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test",
            plan_id=str(uuid.uuid4()),
            admin_user_id=str(uuid.uuid4()),
            admin_email="admin@test.co.nz",
            invitation_expires_at=datetime.now(timezone.utc),
        )
        assert resp.message == "OK"


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestProvisionOrganisation:
    """Test the provision_organisation service function."""

    @pytest.mark.asyncio
    async def test_successful_provisioning(self):
        """Happy path: valid plan, unique email → org + user created."""
        plan = _make_plan()
        db = _mock_db_session()

        # First execute: plan lookup → returns plan
        # Second execute: email uniqueness check → returns None
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with (
            patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock) as mock_audit,
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.admin.service._send_org_admin_invitation_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            from app.modules.admin.service import provision_organisation

            result = await provision_organisation(
                db,
                name="Test Workshop",
                plan_id=plan.id,
                admin_email="admin@workshop.co.nz",
                status="active",
                provisioned_by=uuid.uuid4(),
                ip_address="192.168.1.1",
            )

        assert result["organisation_name"] == "Test Workshop"
        assert result["admin_email"] == "admin@workshop.co.nz"
        assert result["plan_id"] == str(plan.id)
        assert "organisation_id" in result
        assert "admin_user_id" in result
        assert "invitation_expires_at" in result

        # Verify org and user were added to session
        assert db.add.call_count == 2
        assert db.flush.call_count == 2

        # Verify invitation email was sent
        mock_email.assert_awaited_once()
        email_args = mock_email.call_args
        assert email_args[0][0] == "admin@workshop.co.nz"
        assert email_args[0][2] == "Test Workshop"

        # Verify audit log was written (org provisioned + user invited)
        assert mock_audit.await_count == 2

        # Verify Redis token was stored
        mock_redis.setex.assert_awaited_once()
        redis_args = mock_redis.setex.call_args[0]
        assert redis_args[0].startswith("invite:")
        assert redis_args[1] == 48 * 3600

    @pytest.mark.asyncio
    async def test_plan_not_found(self):
        """Reject provisioning when plan doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        from app.modules.admin.service import provision_organisation

        with pytest.raises(ValueError, match="Subscription plan not found"):
            await provision_organisation(
                db,
                name="Test",
                plan_id=uuid.uuid4(),
                admin_email="admin@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_archived_plan_rejected(self):
        """Reject provisioning with an archived plan."""
        plan = _make_plan(is_archived=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        from app.modules.admin.service import provision_organisation

        with pytest.raises(ValueError, match="archived subscription plan"):
            await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="admin@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_duplicate_email_rejected(self):
        """Reject provisioning when admin email already exists."""
        plan = _make_plan()
        existing_user = MagicMock(spec=User)
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(existing_user),
            ]
        )

        from app.modules.admin.service import provision_organisation

        with pytest.raises(ValueError, match="email already exists"):
            await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="existing@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_invalid_status_rejected(self):
        """Reject provisioning with an invalid initial status."""
        plan = _make_plan()
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        from app.modules.admin.service import provision_organisation

        with pytest.raises(ValueError, match="Initial status must be"):
            await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="admin@test.co.nz",
                status="suspended",
                provisioned_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_trial_status_accepted(self):
        """Accept provisioning with trial status."""
        plan = _make_plan()
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with (
            patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.admin.service._send_org_admin_invitation_email",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.admin.service import provision_organisation

            result = await provision_organisation(
                db,
                name="Trial Workshop",
                plan_id=plan.id,
                admin_email="admin@trial.co.nz",
                status="trial",
                provisioned_by=uuid.uuid4(),
            )

        assert result["organisation_name"] == "Trial Workshop"

    @pytest.mark.asyncio
    async def test_storage_quota_from_plan(self):
        """Verify the org's storage quota is set from the plan."""
        plan = _make_plan(storage_quota_gb=10)
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        added_objects = []
        original_add = db.add

        def capture_add(obj):
            added_objects.append(obj)

        db.add = capture_add

        with (
            patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.admin.service._send_org_admin_invitation_email",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.admin.service import provision_organisation

            await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="admin@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )

        # First added object should be the Organisation
        org = added_objects[0]
        assert isinstance(org, Organisation)
        assert org.storage_quota_gb == 10

    @pytest.mark.asyncio
    async def test_admin_user_created_with_correct_role(self):
        """Verify the invited user has org_admin role."""
        plan = _make_plan()
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)

        db.add = capture_add

        with (
            patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.admin.service._send_org_admin_invitation_email",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.admin.service import provision_organisation

            await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="admin@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )

        # Second added object should be the User
        user = added_objects[1]
        assert isinstance(user, User)
        assert user.role == "org_admin"
        assert user.email == "admin@test.co.nz"
        assert user.is_email_verified is False
        assert user.password_hash is None

    @pytest.mark.asyncio
    async def test_invitation_token_expires_in_48_hours(self):
        """Verify the invitation expires approximately 48 hours from now."""
        plan = _make_plan()
        db = _mock_db_session()

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(plan),
                _mock_scalar_result(None),
            ]
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with (
            patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch(
                "app.modules.admin.service._send_org_admin_invitation_email",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.admin.service import provision_organisation

            before = datetime.now(timezone.utc)
            result = await provision_organisation(
                db,
                name="Test",
                plan_id=plan.id,
                admin_email="admin@test.co.nz",
                provisioned_by=uuid.uuid4(),
            )
            after = datetime.now(timezone.utc)

        expires = result["invitation_expires_at"]
        expected_min = before + timedelta(hours=47, minutes=59)
        expected_max = after + timedelta(hours=48, minutes=1)
        assert expected_min <= expires <= expected_max
