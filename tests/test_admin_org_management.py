"""Unit tests for Task 23.1 — organisation management in admin console.

Tests cover:
  - GET /api/v1/admin/organisations: list, search, filter, sort, pagination
  - PUT /api/v1/admin/organisations/{id}: suspend, reinstate, delete_request, move_plan
  - DELETE /api/v1/admin/organisations/{id}: multi-step confirmation delete
  - Audit logging for suspend/delete
  - Reason required for suspend/delete
  - Optional email notification to Org_Admin
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

import app.modules.admin.models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.admin.schemas import (
    OrgDeleteRequest,
    OrgDeleteRequestResponse,
    OrgDeleteResponse,
    OrgListItem,
    OrgListResponse,
    OrgUpdateRequest,
    OrgUpdateResponse,
)
from app.modules.admin.service import (
    delete_organisation,
    list_organisations,
    update_organisation,
)
from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(plan_id=None, name="Starter", storage_quota_gb=5, is_archived=False):
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


def _make_org(org_id=None, name="Test Workshop", status="active", plan_id=None):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.name = name
    org.plan_id = plan_id or uuid.uuid4()
    org.status = status
    org.storage_quota_gb = 5
    org.storage_used_bytes = 1024
    org.carjam_lookups_this_month = 10
    org.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    org.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
    return org


def _mock_db_session():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_redis():
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestOrgManagementSchemas:
    """Test Pydantic schema validation for org management."""

    def test_update_request_suspend(self):
        req = OrgUpdateRequest(
            action="suspend",
            reason="Non-payment",
            notify_org_admin=True,
        )
        assert req.action == "suspend"
        assert req.reason == "Non-payment"
        assert req.notify_org_admin is True

    def test_update_request_reinstate(self):
        req = OrgUpdateRequest(action="reinstate")
        assert req.action == "reinstate"
        assert req.reason is None

    def test_update_request_move_plan(self):
        plan_id = str(uuid.uuid4())
        req = OrgUpdateRequest(action="move_plan", new_plan_id=plan_id)
        assert req.action == "move_plan"
        assert req.new_plan_id == plan_id

    def test_delete_request_schema(self):
        req = OrgDeleteRequest(
            reason="Org requested closure",
            confirmation_token="abc123",
            notify_org_admin=True,
        )
        assert req.reason == "Org requested closure"
        assert req.confirmation_token == "abc123"

    def test_delete_request_requires_reason(self):
        with pytest.raises(Exception):
            OrgDeleteRequest(
                reason="",
                confirmation_token="abc123",
            )

    def test_org_list_item(self):
        item = OrgListItem(
            id=str(uuid.uuid4()),
            name="Workshop",
            plan_id=str(uuid.uuid4()),
            plan_name="Starter",
            status="active",
            storage_quota_gb=5,
            storage_used_bytes=0,
            carjam_lookups_this_month=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert item.name == "Workshop"

    def test_org_list_response(self):
        resp = OrgListResponse(organisations=[], total=0, page=1, page_size=25)
        assert resp.total == 0

    def test_update_response(self):
        resp = OrgUpdateResponse(
            message="Suspended",
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test",
            status="suspended",
            previous_status="active",
        )
        assert resp.status == "suspended"

    def test_delete_response(self):
        resp = OrgDeleteResponse(
            message="Deleted",
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test",
        )
        assert resp.message == "Deleted"


# ---------------------------------------------------------------------------
# Service: list_organisations
# ---------------------------------------------------------------------------

class TestListOrganisations:
    """Test list_organisations service function."""

    @pytest.mark.asyncio
    async def test_list_returns_organisations(self):
        db = _mock_db_session()
        org = _make_org()

        # Mock the count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # Mock the main query
        main_result = MagicMock()
        main_result.all.return_value = [(org, "Starter")]

        db.execute = AsyncMock(side_effect=[count_result, main_result])

        result = await list_organisations(db)

        assert result["total"] == 1
        assert len(result["organisations"]) == 1
        assert result["organisations"][0]["name"] == "Test Workshop"
        assert result["page"] == 1
        assert result["page_size"] == 25

    @pytest.mark.asyncio
    async def test_list_empty(self):
        db = _mock_db_session()

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        main_result = MagicMock()
        main_result.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, main_result])

        result = await list_organisations(db)

        assert result["total"] == 0
        assert result["organisations"] == []

    @pytest.mark.asyncio
    async def test_list_with_search(self):
        db = _mock_db_session()

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        main_result = MagicMock()
        main_result.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, main_result])

        result = await list_organisations(db, search="workshop")

        assert result["total"] == 0
        # Verify execute was called (search filter applied)
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self):
        db = _mock_db_session()

        count_result = MagicMock()
        count_result.scalar.return_value = 50

        main_result = MagicMock()
        main_result.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, main_result])

        result = await list_organisations(db, page=2, page_size=10)

        assert result["total"] == 50
        assert result["page"] == 2
        assert result["page_size"] == 10


# ---------------------------------------------------------------------------
# Service: update_organisation — suspend
# ---------------------------------------------------------------------------

class TestSuspendOrganisation:
    """Test suspend action in update_organisation."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_suspend_success(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await update_organisation(
            db,
            org_id=org.id,
            action="suspend",
            reason="Non-payment",
            updated_by=uuid.uuid4(),
        )

        assert result["status"] == "suspended"
        assert result["previous_status"] == "active"
        assert org.status == "suspended"
        mock_audit.assert_called_once()
        audit_kwargs = mock_audit.call_args
        assert audit_kwargs.kwargs["action"] == "org.suspended"

    @pytest.mark.asyncio
    async def test_suspend_requires_reason(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Reason is required"):
            await update_organisation(
                db,
                org_id=org.id,
                action="suspend",
                reason=None,
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_suspend_already_suspended(self):
        db = _mock_db_session()
        org = _make_org(status="suspended")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="already suspended"):
            await update_organisation(
                db,
                org_id=org.id,
                action="suspend",
                reason="Test",
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_suspend_deleted_org(self):
        db = _mock_db_session()
        org = _make_org(status="deleted")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Cannot suspend a deleted"):
            await update_organisation(
                db,
                org_id=org.id,
                action="suspend",
                reason="Test",
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_suspend_with_notification(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        await update_organisation(
            db,
            org_id=org.id,
            action="suspend",
            reason="Non-payment",
            notify_org_admin=True,
            updated_by=uuid.uuid4(),
        )

        mock_notify.assert_called_once()


# ---------------------------------------------------------------------------
# Service: update_organisation — reinstate
# ---------------------------------------------------------------------------

class TestReinstateOrganisation:
    """Test reinstate action in update_organisation."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_reinstate_success(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="suspended")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        result = await update_organisation(
            db,
            org_id=org.id,
            action="reinstate",
            updated_by=uuid.uuid4(),
        )

        assert result["status"] == "active"
        assert result["previous_status"] == "suspended"
        assert org.status == "active"
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_reinstate_non_suspended(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Only suspended"):
            await update_organisation(
                db,
                org_id=org.id,
                action="reinstate",
                updated_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Service: update_organisation — move_plan
# ---------------------------------------------------------------------------

class TestMovePlan:
    """Test move_plan action in update_organisation."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_move_plan_success(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        new_plan = _make_plan(name="Pro", storage_quota_gb=20)

        # First call returns org, second returns new plan
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(new_plan),
            ]
        )

        result = await update_organisation(
            db,
            org_id=org.id,
            action="move_plan",
            new_plan_id=new_plan.id,
            updated_by=uuid.uuid4(),
        )

        assert "Pro" in result["message"]
        assert result["new_plan_id"] == str(new_plan.id)
        assert org.plan_id == new_plan.id
        assert org.storage_quota_gb == 20

    @pytest.mark.asyncio
    async def test_move_plan_requires_plan_id(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="new_plan_id is required"):
            await update_organisation(
                db,
                org_id=org.id,
                action="move_plan",
                new_plan_id=None,
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_move_plan_not_found(self):
        db = _mock_db_session()
        org = _make_org(status="active")

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(None),
            ]
        )

        with pytest.raises(ValueError, match="Target subscription plan not found"):
            await update_organisation(
                db,
                org_id=org.id,
                action="move_plan",
                new_plan_id=uuid.uuid4(),
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_move_plan_archived(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        archived_plan = _make_plan(is_archived=True)

        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(org),
                _mock_scalar_result(archived_plan),
            ]
        )

        with pytest.raises(ValueError, match="archived plan"):
            await update_organisation(
                db,
                org_id=org.id,
                action="move_plan",
                new_plan_id=archived_plan.id,
                updated_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Service: update_organisation — delete_request
# ---------------------------------------------------------------------------

class TestDeleteRequest:
    """Test delete_request action (step 1 of multi-step delete)."""

    @pytest.mark.asyncio
    async def test_delete_request_returns_token(self):
        mock_redis = _mock_redis()
        with patch("app.core.redis.redis_pool", mock_redis):
            db = _mock_db_session()
            org = _make_org(status="active")
            db.execute = AsyncMock(return_value=_mock_scalar_result(org))

            result = await update_organisation(
                db,
                org_id=org.id,
                action="delete_request",
                reason="Org requested closure",
                updated_by=uuid.uuid4(),
            )

            assert "confirmation_token" in result
            assert result["expires_in_seconds"] == 300
            mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_request_requires_reason(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Reason is required"):
            await update_organisation(
                db,
                org_id=org.id,
                action="delete_request",
                reason=None,
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_delete_request_already_deleted(self):
        db = _mock_db_session()
        org = _make_org(status="deleted")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="already deleted"):
            await update_organisation(
                db,
                org_id=org.id,
                action="delete_request",
                reason="Test",
                updated_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Service: delete_organisation (step 2)
# ---------------------------------------------------------------------------

class TestDeleteOrganisation:
    """Test delete_organisation service function (multi-step confirmation)."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_delete_success(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        org_id = org.id
        token = "valid-token"

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "org_id": str(org_id),
            "reason": "Closure",
            "requested_by": str(uuid.uuid4()),
        }))

        with patch("app.core.redis.redis_pool", mock_redis):
            db.execute = AsyncMock(return_value=_mock_scalar_result(org))

            result = await delete_organisation(
                db,
                org_id=org_id,
                reason="Closure",
                confirmation_token=token,
                deleted_by=uuid.uuid4(),
            )

            assert result["message"] == "Organisation permanently deleted"
            assert org.status == "deleted"
            mock_redis.delete.assert_called_once()
            mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_invalid_token(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.core.redis.redis_pool", mock_redis):
            with pytest.raises(ValueError, match="Invalid or expired confirmation token"):
                await delete_organisation(
                    db,
                    org_id=org_id,
                    reason="Test",
                    confirmation_token="bad-token",
                    deleted_by=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_delete_token_org_mismatch(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "org_id": str(other_org_id),
            "reason": "Test",
        }))

        with patch("app.core.redis.redis_pool", mock_redis):
            with pytest.raises(ValueError, match="does not match"):
                await delete_organisation(
                    db,
                    org_id=org_id,
                    reason="Test",
                    confirmation_token="token",
                    deleted_by=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_delete_with_notification(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        org_id = org.id

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "org_id": str(org_id),
            "reason": "Closure",
        }))

        with patch("app.core.redis.redis_pool", mock_redis):
            db.execute = AsyncMock(return_value=_mock_scalar_result(org))

            await delete_organisation(
                db,
                org_id=org_id,
                reason="Closure",
                confirmation_token="token",
                notify_org_admin=True,
                deleted_by=uuid.uuid4(),
            )

            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_delete_already_deleted(self, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="deleted")
        org_id = org.id

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "org_id": str(org_id),
            "reason": "Test",
        }))

        with patch("app.core.redis.redis_pool", mock_redis):
            db.execute = AsyncMock(return_value=_mock_scalar_result(org))

            with pytest.raises(ValueError, match="already deleted"):
                await delete_organisation(
                    db,
                    org_id=org_id,
                    reason="Test",
                    confirmation_token="token",
                    deleted_by=uuid.uuid4(),
                )


# ---------------------------------------------------------------------------
# Service: update_organisation — invalid action
# ---------------------------------------------------------------------------

class TestInvalidAction:
    """Test invalid action handling."""

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with pytest.raises(ValueError, match="Invalid action"):
            await update_organisation(
                db,
                org_id=org.id,
                action="invalid_action",
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_org_not_found(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await update_organisation(
                db,
                org_id=uuid.uuid4(),
                action="suspend",
                reason="Test",
                updated_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Service: audit log entries
# ---------------------------------------------------------------------------

class TestAuditLogging:
    """Test that audit log entries are created for org management actions."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_suspend_creates_audit_with_reason(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="active")
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        await update_organisation(
            db,
            org_id=org.id,
            action="suspend",
            reason="Violation of terms",
            updated_by=uuid.uuid4(),
            ip_address="10.0.0.1",
        )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.suspended"
        assert call_kwargs["after_value"]["reason"] == "Violation of terms"
        assert call_kwargs["ip_address"] == "10.0.0.1"

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._notify_org_admin_status_change", new_callable=AsyncMock)
    async def test_delete_creates_audit_with_reason(self, mock_notify, mock_audit):
        db = _mock_db_session()
        org = _make_org(status="suspended")
        org_id = org.id

        mock_redis = _mock_redis()
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "org_id": str(org_id),
            "reason": "Permanent closure",
        }))

        with patch("app.core.redis.redis_pool", mock_redis):
            db.execute = AsyncMock(return_value=_mock_scalar_result(org))

            await delete_organisation(
                db,
                org_id=org_id,
                reason="Permanent closure",
                confirmation_token="token",
                deleted_by=uuid.uuid4(),
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args.kwargs
            assert call_kwargs["action"] == "org.deleted"
            assert call_kwargs["after_value"]["reason"] == "Permanent closure"
