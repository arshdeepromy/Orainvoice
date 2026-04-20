"""Unit tests for Task 4.2 — Organisation Detail Dashboard endpoint.

Tests cover:
  - GET /admin/organisations/{org_id}/detail: 404, 403, 200 response shape
  - Payment method masking (no stripe_payment_method_id in response)
  - Empty org returns zero counts
  - Audit log entry created on access
  - Requirements: 9.1, 9.2, 9.3, 9.6, 8.1, 8.4
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import app.modules.admin.models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.admin.schemas import (
    OrgDetailResponse,
    OrgDetailOverview,
    OrgDetailBilling,
    OrgDetailUsage,
    OrgDetailUserSection,
    OrgDetailSecurity,
    OrgDetailHealth,
)
from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(plan_id=None, name="Starter", storage_quota_gb=5, user_seats=5):
    """Create a mock SubscriptionPlan."""
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.name = name
    plan.monthly_price_nzd = 49.00
    plan.user_seats = user_seats
    plan.storage_quota_gb = storage_quota_gb
    plan.carjam_lookups_included = 100
    plan.sms_included_quota = 50
    plan.enabled_modules = []
    plan.is_public = True
    plan.is_archived = False
    return plan


def _make_org(org_id=None, name="Test Workshop", status="active", plan_id=None):
    """Create a mock Organisation."""
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.name = name
    org.plan_id = plan_id or uuid.uuid4()
    org.status = status
    org.billing_interval = "monthly"
    org.trial_ends_at = None
    org.next_billing_date = None
    org.storage_quota_gb = 5
    org.storage_used_bytes = 0
    org.carjam_lookups_this_month = 0
    org.sms_sent_this_month = 0
    org.business_type = "sole_trader"
    org.trade_category_id = None
    org.timezone = "Pacific/Auckland"
    org.locale = "en-NZ"
    org.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    org.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
    return org


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _build_full_detail_response(org_id=None, org_name="Test Workshop", plan_name="Starter"):
    """Build a complete detail response dict matching OrgDetailResponse schema."""
    oid = str(org_id or uuid.uuid4())
    return {
        "overview": {
            "id": oid,
            "name": org_name,
            "status": "active",
            "plan_name": plan_name,
            "plan_id": str(uuid.uuid4()),
            "signup_date": "2024-01-01T00:00:00+00:00",
            "business_type": "sole_trader",
            "trade_category_name": None,
            "billing_interval": "monthly",
            "trial_ends_at": None,
            "timezone": "Pacific/Auckland",
            "locale": "en-NZ",
        },
        "billing": {
            "plan_name": plan_name,
            "monthly_price_nzd": 49.00,
            "billing_interval": "monthly",
            "next_billing_date": None,
            "payment_method": None,
            "coupons": [],
            "storage_addon": None,
            "receipts_success_90d": 0,
            "receipts_failed_90d": 0,
            "last_failure_date": None,
        },
        "usage": {
            "invoice_count": 0,
            "quote_count": 0,
            "customer_count": 0,
            "vehicle_count": 0,
            "storage_used_bytes": 0,
            "storage_quota_gb": 5,
            "carjam_lookups_this_month": 0,
            "carjam_lookups_included": 100,
            "sms_sent_this_month": 0,
            "sms_included_quota": 50,
        },
        "users": {
            "users": [],
            "active_count": 0,
            "seat_limit": 5,
        },
        "security": {
            "login_attempts": [],
            "admin_actions": [],
            "mfa_enrolled_count": 0,
            "mfa_total_users": 0,
            "failed_payments_90d": 0,
        },
        "health": {
            "billing_ok": True,
            "storage_ok": True,
            "storage_warning": False,
            "seats_ok": True,
            "mfa_ok": True,
            "status_ok": True,
        },
    }


def _build_detail_response_with_payment_method(org_id=None):
    """Build a detail response dict that includes a masked payment method."""
    data = _build_full_detail_response(org_id=org_id)
    data["billing"]["payment_method"] = {
        "brand": "visa",
        "last4": "4242",
        "exp_month": 12,
        "exp_year": 2026,
    }
    return data


# ---------------------------------------------------------------------------
# Test: 404 for non-existent org UUID
# ---------------------------------------------------------------------------

class TestOrgDetail404:
    """GET /admin/organisations/{org_id}/detail returns 404 for missing org."""

    @pytest.mark.asyncio
    async def test_detail_404_for_missing_org(self):
        """Service returns None for non-existent org → endpoint should raise 404."""
        from app.modules.admin.service import get_org_detail

        db = _mock_db_session()
        missing_org_id = uuid.uuid4()

        # Mock the org query to return no result
        org_result = MagicMock()
        org_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=org_result)

        result = await get_org_detail(
            db,
            org_id=missing_org_id,
            admin_user_id=uuid.uuid4(),
            ip_address="127.0.0.1",
        )

        assert result is None, "get_org_detail should return None for non-existent org"


# ---------------------------------------------------------------------------
# Test: 403 for non-global-admin user
# ---------------------------------------------------------------------------

class TestOrgDetail403:
    """Endpoint requires global_admin role — non-admin users get 403."""

    def test_detail_endpoint_requires_global_admin_dependency(self):
        """Verify the endpoint is decorated with require_role('global_admin')."""
        from app.modules.admin.router import router

        # Find the route for GET /organisations/{org_id}/detail
        detail_route = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/organisations/{org_id}/detail":
                if "GET" in getattr(route, "methods", set()):
                    detail_route = route
                    break

        assert detail_route is not None, "Detail endpoint route not found"

        # require_role("global_admin") returns Depends(_check) where _check
        # is a closure that captures allowed = {"global_admin"}.
        # The route.dependencies list contains Depends objects whose .dependency
        # attribute is the inner _check function. We inspect the closure vars
        # to confirm "global_admin" is in the allowed set.
        found_global_admin = False
        for dep in detail_route.dependencies:
            dep_fn = dep.dependency
            # The closure created by require_role captures 'allowed' as a cell var
            closure_vars = getattr(dep_fn, "__closure__", None) or []
            for cell in closure_vars:
                try:
                    cell_val = cell.cell_contents
                    if isinstance(cell_val, set) and "global_admin" in cell_val:
                        found_global_admin = True
                        break
                except ValueError:
                    continue
            if found_global_admin:
                break

        assert found_global_admin, (
            "Detail endpoint must have require_role('global_admin') dependency"
        )


# ---------------------------------------------------------------------------
# Test: 200 with correct response shape for valid org
# ---------------------------------------------------------------------------

class TestOrgDetail200:
    """GET /admin/organisations/{org_id}/detail returns correct response shape."""

    @pytest.mark.asyncio
    async def test_detail_200_correct_response_shape(self):
        """Service returns a dict that validates against OrgDetailResponse schema."""
        from app.modules.admin.service import get_org_detail

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        admin_user_id = uuid.uuid4()

        org = _make_org(org_id=org_id, plan_id=plan_id)
        plan = _make_plan(plan_id=plan_id)

        db = _mock_db_session()

        # 1. Org + plan + trade_category query
        org_result = MagicMock()
        org_result.one_or_none.return_value = (org, plan, None)

        # 2. Payment method query
        pm_result = MagicMock()
        pm_result.one_or_none.return_value = None

        # 3. Aggregate counts query
        counts_row = MagicMock()
        counts_row.invoice_count = 5
        counts_row.quote_count = 3
        counts_row.customer_count = 10
        counts_row.vehicle_count = 7
        counts_result = MagicMock()
        counts_result.one.return_value = counts_row

        # 4. Users query
        users_result = MagicMock()
        users_result.all.return_value = []

        # 5. Billing receipts query
        receipts_row = MagicMock()
        receipts_row.success_count = 2
        receipts_row.failed_count = 0
        receipts_row.last_failure = None
        receipts_result = MagicMock()
        receipts_result.one.return_value = receipts_row

        # 6. Coupons query
        coupons_result = MagicMock()
        coupons_result.all.return_value = []

        # 7. Storage addon query
        addon_result = MagicMock()
        addon_result.one_or_none.return_value = None

        # 8. Login attempts query (iterable)
        login_result = MagicMock()
        login_result.__iter__ = MagicMock(return_value=iter([]))

        # 9. Admin actions query (iterable)
        admin_actions_result = MagicMock()
        admin_actions_result.__iter__ = MagicMock(return_value=iter([]))

        # 10. Audit log insert (returns nothing meaningful)
        audit_insert_result = MagicMock()

        db.execute = AsyncMock(side_effect=[
            org_result,       # 1. org + plan
            pm_result,        # 2. payment method
            counts_result,    # 3. aggregate counts
            users_result,     # 4. users
            receipts_result,  # 5. billing receipts
            coupons_result,   # 6. coupons
            addon_result,     # 7. storage addon
            login_result,     # 8. login attempts
            admin_actions_result,  # 9. admin actions
            audit_insert_result,   # 10. audit log insert
        ])

        result = await get_org_detail(
            db,
            org_id=org_id,
            admin_user_id=admin_user_id,
            ip_address="127.0.0.1",
            device_info="pytest",
        )

        assert result is not None, "get_org_detail should return data for valid org"

        # Validate the response matches the Pydantic schema
        response = OrgDetailResponse(**result)

        # Verify top-level sections exist
        assert response.overview is not None
        assert response.billing is not None
        assert response.usage is not None
        assert response.users is not None
        assert response.security is not None
        assert response.health is not None

        # Verify overview fields
        assert response.overview.id == str(org_id)
        assert response.overview.name == "Test Workshop"
        assert response.overview.status == "active"
        assert response.overview.plan_name == "Starter"

        # Verify usage counts
        assert response.usage.invoice_count == 5
        assert response.usage.quote_count == 3
        assert response.usage.customer_count == 10
        assert response.usage.vehicle_count == 7


# ---------------------------------------------------------------------------
# Test: Payment method masking (no stripe_payment_method_id in response)
# ---------------------------------------------------------------------------

class TestPaymentMethodMasking:
    """Payment method data must be masked — no stripe_payment_method_id."""

    @pytest.mark.asyncio
    async def test_payment_method_masking_no_stripe_id(self):
        """Response with payment method must not contain stripe_payment_method_id."""
        from app.modules.admin.service import get_org_detail

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        org = _make_org(org_id=org_id, plan_id=plan_id)
        plan = _make_plan(plan_id=plan_id)

        db = _mock_db_session()

        # 1. Org + plan + trade_category
        org_result = MagicMock()
        org_result.one_or_none.return_value = (org, plan, None)

        # 2. Payment method — present with masked data
        pm_row = MagicMock()
        pm_row.brand = "visa"
        pm_row.last4 = "4242"
        pm_row.exp_month = 12
        pm_row.exp_year = 2026
        pm_result = MagicMock()
        pm_result.one_or_none.return_value = pm_row

        # 3. Aggregate counts
        counts_row = MagicMock()
        counts_row.invoice_count = 0
        counts_row.quote_count = 0
        counts_row.customer_count = 0
        counts_row.vehicle_count = 0
        counts_result = MagicMock()
        counts_result.one.return_value = counts_row

        # 4. Users
        users_result = MagicMock()
        users_result.all.return_value = []

        # 5. Billing receipts
        receipts_row = MagicMock()
        receipts_row.success_count = 0
        receipts_row.failed_count = 0
        receipts_row.last_failure = None
        receipts_result = MagicMock()
        receipts_result.one.return_value = receipts_row

        # 6. Coupons
        coupons_result = MagicMock()
        coupons_result.all.return_value = []

        # 7. Storage addon
        addon_result = MagicMock()
        addon_result.one_or_none.return_value = None

        # 8. Login attempts
        login_result = MagicMock()
        login_result.__iter__ = MagicMock(return_value=iter([]))

        # 9. Admin actions
        admin_actions_result = MagicMock()
        admin_actions_result.__iter__ = MagicMock(return_value=iter([]))

        # 10. Audit log insert
        audit_insert_result = MagicMock()

        db.execute = AsyncMock(side_effect=[
            org_result,
            pm_result,
            counts_result,
            users_result,
            receipts_result,
            coupons_result,
            addon_result,
            login_result,
            admin_actions_result,
            audit_insert_result,
        ])

        result = await get_org_detail(
            db,
            org_id=org_id,
            admin_user_id=uuid.uuid4(),
            ip_address="127.0.0.1",
        )

        assert result is not None

        # Verify payment method is present and masked
        pm = result["billing"]["payment_method"]
        assert pm is not None
        assert pm["brand"] == "visa"
        assert pm["last4"] == "4242"
        assert pm["exp_month"] == 12
        assert pm["exp_year"] == 2026

        # Verify no stripe_payment_method_id anywhere in the response
        response_json = json.dumps(result)
        assert "stripe_payment_method_id" not in response_json, (
            "stripe_payment_method_id must never appear in the detail response"
        )

        # Verify the payment method dict has only the allowed keys
        assert set(pm.keys()) == {"brand", "last4", "exp_month", "exp_year"}, (
            "Payment method must contain only brand, last4, exp_month, exp_year"
        )


# ---------------------------------------------------------------------------
# Test: Empty org returns zero counts
# ---------------------------------------------------------------------------

class TestEmptyOrgZeroCounts:
    """An org with no data should return zero for all aggregate counts."""

    @pytest.mark.asyncio
    async def test_empty_org_returns_zero_counts(self):
        """Org with no invoices, quotes, customers, vehicles returns all zeros."""
        from app.modules.admin.service import get_org_detail

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()

        org = _make_org(org_id=org_id, plan_id=plan_id)
        plan = _make_plan(plan_id=plan_id)

        db = _mock_db_session()

        # 1. Org + plan
        org_result = MagicMock()
        org_result.one_or_none.return_value = (org, plan, None)

        # 2. No payment method
        pm_result = MagicMock()
        pm_result.one_or_none.return_value = None

        # 3. All counts zero
        counts_row = MagicMock()
        counts_row.invoice_count = 0
        counts_row.quote_count = 0
        counts_row.customer_count = 0
        counts_row.vehicle_count = 0
        counts_result = MagicMock()
        counts_result.one.return_value = counts_row

        # 4. No users
        users_result = MagicMock()
        users_result.all.return_value = []

        # 5. No billing receipts
        receipts_row = MagicMock()
        receipts_row.success_count = 0
        receipts_row.failed_count = 0
        receipts_row.last_failure = None
        receipts_result = MagicMock()
        receipts_result.one.return_value = receipts_row

        # 6. No coupons
        coupons_result = MagicMock()
        coupons_result.all.return_value = []

        # 7. No storage addon
        addon_result = MagicMock()
        addon_result.one_or_none.return_value = None

        # 8. No login attempts
        login_result = MagicMock()
        login_result.__iter__ = MagicMock(return_value=iter([]))

        # 9. No admin actions
        admin_actions_result = MagicMock()
        admin_actions_result.__iter__ = MagicMock(return_value=iter([]))

        # 10. Audit log insert
        audit_insert_result = MagicMock()

        db.execute = AsyncMock(side_effect=[
            org_result,
            pm_result,
            counts_result,
            users_result,
            receipts_result,
            coupons_result,
            addon_result,
            login_result,
            admin_actions_result,
            audit_insert_result,
        ])

        result = await get_org_detail(
            db,
            org_id=org_id,
            admin_user_id=uuid.uuid4(),
            ip_address="127.0.0.1",
        )

        assert result is not None

        # Verify all usage counts are zero
        usage = result["usage"]
        assert usage["invoice_count"] == 0
        assert usage["quote_count"] == 0
        assert usage["customer_count"] == 0
        assert usage["vehicle_count"] == 0
        assert usage["storage_used_bytes"] == 0

        # Verify billing counts are zero
        billing = result["billing"]
        assert billing["receipts_success_90d"] == 0
        assert billing["receipts_failed_90d"] == 0
        assert billing["last_failure_date"] is None
        assert billing["payment_method"] is None
        assert billing["coupons"] == []
        assert billing["storage_addon"] is None

        # Verify user section is empty
        users = result["users"]
        assert users["users"] == []
        assert users["active_count"] == 0

        # Verify security section is empty
        security = result["security"]
        assert security["login_attempts"] == []
        assert security["admin_actions"] == []
        assert security["mfa_enrolled_count"] == 0
        assert security["mfa_total_users"] == 0
        assert security["failed_payments_90d"] == 0


# ---------------------------------------------------------------------------
# Test: Audit log entry created on access
# ---------------------------------------------------------------------------

class TestAuditLogOnAccess:
    """Every call to get_org_detail must create an audit log entry."""

    @pytest.mark.asyncio
    async def test_audit_log_created_on_access(self):
        """Verify write_audit_log is called with org_detail_viewed action."""
        from app.modules.admin.service import get_org_detail

        org_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        admin_user_id = uuid.uuid4()

        org = _make_org(org_id=org_id, plan_id=plan_id)
        plan = _make_plan(plan_id=plan_id)

        db = _mock_db_session()

        # 1. Org + plan
        org_result = MagicMock()
        org_result.one_or_none.return_value = (org, plan, None)

        # 2. No payment method
        pm_result = MagicMock()
        pm_result.one_or_none.return_value = None

        # 3. Counts
        counts_row = MagicMock()
        counts_row.invoice_count = 0
        counts_row.quote_count = 0
        counts_row.customer_count = 0
        counts_row.vehicle_count = 0
        counts_result = MagicMock()
        counts_result.one.return_value = counts_row

        # 4. Users
        users_result = MagicMock()
        users_result.all.return_value = []

        # 5. Receipts
        receipts_row = MagicMock()
        receipts_row.success_count = 0
        receipts_row.failed_count = 0
        receipts_row.last_failure = None
        receipts_result = MagicMock()
        receipts_result.one.return_value = receipts_row

        # 6. Coupons
        coupons_result = MagicMock()
        coupons_result.all.return_value = []

        # 7. Storage addon
        addon_result = MagicMock()
        addon_result.one_or_none.return_value = None

        # 8. Login attempts
        login_result = MagicMock()
        login_result.__iter__ = MagicMock(return_value=iter([]))

        # 9. Admin actions
        admin_actions_result = MagicMock()
        admin_actions_result.__iter__ = MagicMock(return_value=iter([]))

        # 10. Audit log insert
        audit_insert_result = MagicMock()

        db.execute = AsyncMock(side_effect=[
            org_result,
            pm_result,
            counts_result,
            users_result,
            receipts_result,
            coupons_result,
            addon_result,
            login_result,
            admin_actions_result,
            audit_insert_result,
        ])

        with patch(
            "app.modules.admin.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await get_org_detail(
                db,
                org_id=org_id,
                admin_user_id=admin_user_id,
                ip_address="10.0.0.1",
                device_info="pytest-agent",
            )

        assert result is not None

        # Verify audit log was called exactly once
        mock_audit.assert_awaited_once()

        # Verify the audit log entry has the correct fields
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "org_detail_viewed"
        assert audit_kwargs["entity_type"] == "organisation"
        assert audit_kwargs["entity_id"] == org_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == admin_user_id
        assert audit_kwargs["ip_address"] == "10.0.0.1"
        assert audit_kwargs["device_info"] == "pytest-agent"

    @pytest.mark.asyncio
    async def test_no_audit_log_for_missing_org(self):
        """No audit log entry should be created when org doesn't exist."""
        from app.modules.admin.service import get_org_detail

        db = _mock_db_session()

        # Org not found
        org_result = MagicMock()
        org_result.one_or_none.return_value = None
        db.execute = AsyncMock(return_value=org_result)

        with patch(
            "app.modules.admin.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await get_org_detail(
                db,
                org_id=uuid.uuid4(),
                admin_user_id=uuid.uuid4(),
                ip_address="127.0.0.1",
            )

        assert result is None
        mock_audit.assert_not_awaited()
