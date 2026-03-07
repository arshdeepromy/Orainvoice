"""Unit tests for extended RBAC roles (Task 9.7, 9.8, 9.9).

Tests cover:
  - franchise_admin: read-only access to aggregate metrics only
  - staff_member: access only assigned jobs, own time entries
  - permission overrides: recorded in audit log

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.7**
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.rbac import RBACMiddleware
from app.modules.auth.rbac import (
    ALL_ROLES,
    FRANCHISE_ADMIN,
    LOCATION_MANAGER,
    STAFF_MEMBER,
    check_role_path_access,
    has_permission,
    ROLE_PERMISSIONS,
)


def _make_token(
    user_id: str = "u1",
    org_id: str | None = "org1",
    role: str = "salesperson",
    assigned_location_ids: list[str] | None = None,
    franchise_group_id: str | None = None,
) -> str:
    payload = {"user_id": user_id, "role": role}
    if org_id is not None:
        payload["org_id"] = org_id
    if assigned_location_ids is not None:
        payload["assigned_location_ids"] = assigned_location_ids
    if franchise_group_id is not None:
        payload["franchise_group_id"] = franchise_group_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _build_extended_rbac_app() -> FastAPI:
    """Create a FastAPI app with Auth + RBAC middleware and test routes."""
    app = FastAPI()

    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    # --- Franchise/reports endpoints ---
    @app.get("/api/v2/franchise/dashboard")
    async def franchise_dashboard(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v2/reports/aggregate")
    async def reports_aggregate(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v2/franchise/settings")
    async def franchise_settings_write(request: Request):
        return {"role": request.state.role}

    # --- Job/time-tracking endpoints ---
    @app.get("/api/v2/jobs/my-jobs")
    async def my_jobs(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v2/time-tracking/entries")
    async def time_entries(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v2/schedule/mine")
    async def my_schedule(request: Request):
        return {"role": request.state.role}

    # --- Endpoints staff_member should NOT access ---
    @app.get("/api/v1/customers")
    async def list_customers(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/invoices")
    async def list_invoices(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v2/inventory/products")
    async def list_products(request: Request):
        return {"role": request.state.role}

    # --- Admin endpoints ---
    @app.get("/api/v2/admin/organisations")
    async def admin_orgs(request: Request):
        return {"role": request.state.role}

    # --- Public paths ---
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client():
    app = _build_extended_rbac_app()
    return TestClient(app)


def _auth_header(
    role: str,
    org_id: str | None = "org1",
    assigned_location_ids: list[str] | None = None,
    franchise_group_id: str | None = None,
) -> dict:
    token = _make_token(
        role=role,
        org_id=org_id,
        assigned_location_ids=assigned_location_ids,
        franchise_group_id=franchise_group_id,
    )
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Task 9.7: franchise_admin has read-only access to aggregate metrics only
# ===========================================================================


class TestFranchiseAdminAccess:
    """Verify franchise_admin can only read aggregate reports.

    **Validates: Requirements 8.1, 8.3**
    """

    def test_franchise_admin_in_all_roles(self):
        """franchise_admin is a recognized role."""
        assert FRANCHISE_ADMIN in ALL_ROLES

    def test_franchise_admin_allowed_franchise_dashboard_get(self, client):
        """franchise_admin can GET franchise dashboard."""
        resp = client.get(
            "/api/v2/franchise/dashboard",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 200

    def test_franchise_admin_allowed_reports_get(self, client):
        """franchise_admin can GET aggregate reports."""
        resp = client.get(
            "/api/v2/reports/aggregate",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 200

    def test_franchise_admin_denied_franchise_write(self, client):
        """franchise_admin cannot POST to franchise endpoints (read-only)."""
        resp = client.post(
            "/api/v2/franchise/settings",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_franchise_admin_denied_customers(self, client):
        """franchise_admin cannot access customer data."""
        resp = client.get(
            "/api/v1/customers",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_franchise_admin_denied_invoices(self, client):
        """franchise_admin cannot access invoice data."""
        resp = client.get(
            "/api/v1/invoices",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_franchise_admin_denied_inventory(self, client):
        """franchise_admin cannot access inventory."""
        resp = client.get(
            "/api/v2/inventory/products",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_franchise_admin_denied_admin(self, client):
        """franchise_admin cannot access admin endpoints."""
        resp = client.get(
            "/api/v2/admin/organisations",
            headers=_auth_header("franchise_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_franchise_admin_permissions_are_read_only(self):
        """All franchise_admin permissions end with .read."""
        perms = ROLE_PERMISSIONS["franchise_admin"]
        for perm in perms:
            assert perm.endswith(".read"), f"franchise_admin has non-read permission: {perm}"

    def test_franchise_admin_has_permission_franchise_read(self):
        """franchise_admin has franchise.read permission."""
        assert has_permission("franchise_admin", "franchise.read")

    def test_franchise_admin_has_permission_reports_read(self):
        """franchise_admin has reports.read permission."""
        assert has_permission("franchise_admin", "reports.read")

    def test_franchise_admin_lacks_invoices_permission(self):
        """franchise_admin does not have invoices.read permission."""
        assert not has_permission("franchise_admin", "invoices.read")

    def test_franchise_admin_lacks_customers_permission(self):
        """franchise_admin does not have customers.read permission."""
        assert not has_permission("franchise_admin", "customers.read")


# ===========================================================================
# Task 9.8: staff_member can only access assigned jobs and own time entries
# ===========================================================================


class TestStaffMemberAccess:
    """Verify staff_member can only access assigned jobs, own time entries,
    own schedule, and job attachment uploads.

    **Validates: Requirements 8.1, 8.4**
    """

    def test_staff_member_in_all_roles(self):
        """staff_member is a recognized role."""
        assert STAFF_MEMBER in ALL_ROLES

    def test_staff_member_allowed_jobs(self, client):
        """staff_member can access jobs endpoint."""
        resp = client.get(
            "/api/v2/jobs/my-jobs",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 200

    def test_staff_member_allowed_time_tracking(self, client):
        """staff_member can access time tracking endpoint."""
        resp = client.get(
            "/api/v2/time-tracking/entries",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 200

    def test_staff_member_allowed_schedule(self, client):
        """staff_member can access schedule endpoint."""
        resp = client.get(
            "/api/v2/schedule/mine",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 200

    def test_staff_member_denied_customers(self, client):
        """staff_member cannot access customer data."""
        resp = client.get(
            "/api/v1/customers",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_denied_invoices(self, client):
        """staff_member cannot access invoices."""
        resp = client.get(
            "/api/v1/invoices",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_denied_inventory(self, client):
        """staff_member cannot access inventory."""
        resp = client.get(
            "/api/v2/inventory/products",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_denied_admin(self, client):
        """staff_member cannot access admin endpoints."""
        resp = client.get(
            "/api/v2/admin/organisations",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_denied_franchise(self, client):
        """staff_member cannot access franchise endpoints."""
        resp = client.get(
            "/api/v2/franchise/dashboard",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_denied_reports(self, client):
        """staff_member cannot access reports."""
        resp = client.get(
            "/api/v2/reports/aggregate",
            headers=_auth_header("staff_member"),
        )
        assert resp.status_code == 403

    def test_staff_member_has_jobs_read_assigned(self):
        """staff_member has jobs.read_assigned permission."""
        assert has_permission("staff_member", "jobs.read_assigned")

    def test_staff_member_has_time_entries_own(self):
        """staff_member has time_entries.own permission."""
        assert has_permission("staff_member", "time_entries.own")

    def test_staff_member_has_schedule_own(self):
        """staff_member has schedule.own permission."""
        assert has_permission("staff_member", "schedule.own")

    def test_staff_member_has_job_attachments_upload(self):
        """staff_member has job_attachments.upload permission."""
        assert has_permission("staff_member", "job_attachments.upload")

    def test_staff_member_lacks_invoices_create(self):
        """staff_member does not have invoices.create permission."""
        assert not has_permission("staff_member", "invoices.create")

    def test_staff_member_lacks_customers_read(self):
        """staff_member does not have customers.read permission."""
        assert not has_permission("staff_member", "customers.read")

    def test_staff_member_requires_org_id(self, client):
        """staff_member without org_id is denied."""
        resp = client.get(
            "/api/v2/jobs/my-jobs",
            headers=_auth_header("staff_member", org_id=None),
        )
        assert resp.status_code == 403


# ===========================================================================
# Task 9.9: permission overrides are recorded in audit log
# ===========================================================================

import uuid
from unittest.mock import AsyncMock, patch, MagicMock


class TestPermissionOverridesAuditLog:
    """Verify that creating/updating/deleting permission overrides
    writes entries to the audit log.

    **Validates: Requirements 8.5, 8.7**
    """

    @pytest.mark.asyncio
    async def test_create_override_writes_audit_log(self):
        """Creating a new permission override records it in the audit log."""
        from app.modules.auth.permission_overrides import create_or_update_permission_override

        user_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        org_id = uuid.uuid4()

        mock_session = AsyncMock()
        # Simulate no existing override
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("app.core.audit.write_audit_log", new_callable=AsyncMock) as mock_audit:
            override = await create_or_update_permission_override(
                mock_session,
                user_id=user_id,
                permission_key="inventory.read",
                is_granted=True,
                granted_by=admin_id,
                org_id=org_id,
            )

            # Verify audit log was called
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs[1]["action"] == "permission_override.created"
            assert call_kwargs[1]["entity_type"] == "user_permission_override"
            assert call_kwargs[1]["entity_id"] == user_id
            assert call_kwargs[1]["user_id"] == admin_id
            assert call_kwargs[1]["org_id"] == org_id
            assert call_kwargs[1]["after_value"] == {
                "permission_key": "inventory.read",
                "is_granted": True,
            }
            assert call_kwargs[1]["before_value"] is None

    @pytest.mark.asyncio
    async def test_update_override_writes_audit_log_with_before_value(self):
        """Updating an existing permission override records before and after values."""
        from app.modules.auth.permission_overrides import (
            create_or_update_permission_override,
            UserPermissionOverride,
        )

        user_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        org_id = uuid.uuid4()

        # Simulate existing override
        existing = MagicMock(spec=UserPermissionOverride)
        existing.permission_key = "inventory.read"
        existing.is_granted = True
        existing.user_id = user_id

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        with patch("app.core.audit.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await create_or_update_permission_override(
                mock_session,
                user_id=user_id,
                permission_key="inventory.read",
                is_granted=False,
                granted_by=admin_id,
                org_id=org_id,
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs[1]["action"] == "permission_override.updated"
            assert call_kwargs[1]["before_value"] == {
                "permission_key": "inventory.read",
                "is_granted": True,
            }
            assert call_kwargs[1]["after_value"] == {
                "permission_key": "inventory.read",
                "is_granted": False,
            }

    @pytest.mark.asyncio
    async def test_delete_override_writes_audit_log(self):
        """Deleting a permission override records it in the audit log."""
        from app.modules.auth.permission_overrides import (
            delete_permission_override,
            UserPermissionOverride,
        )

        user_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        org_id = uuid.uuid4()

        existing = MagicMock(spec=UserPermissionOverride)
        existing.permission_key = "inventory.read"
        existing.is_granted = True

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_session.execute.return_value = mock_result

        with patch("app.core.audit.write_audit_log", new_callable=AsyncMock) as mock_audit:
            deleted = await delete_permission_override(
                mock_session,
                user_id=user_id,
                permission_key="inventory.read",
                deleted_by=admin_id,
                org_id=org_id,
            )

            assert deleted is True
            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs[1]["action"] == "permission_override.deleted"
            assert call_kwargs[1]["before_value"] == {
                "permission_key": "inventory.read",
                "is_granted": True,
            }
            assert call_kwargs[1]["after_value"] is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_override_no_audit(self):
        """Deleting a non-existent override does not write to audit log."""
        from app.modules.auth.permission_overrides import delete_permission_override

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("app.core.audit.write_audit_log", new_callable=AsyncMock) as mock_audit:
            deleted = await delete_permission_override(
                mock_session,
                user_id=uuid.uuid4(),
                permission_key="nonexistent.perm",
                deleted_by=uuid.uuid4(),
            )

            assert deleted is False
            mock_audit.assert_not_called()

    def test_has_permission_with_override_grant(self):
        """Permission override can grant a permission not in base role."""
        overrides = [{"permission_key": "inventory.read", "is_granted": True}]
        assert has_permission("salesperson", "inventory.read", overrides=overrides)

    def test_has_permission_with_override_revoke(self):
        """Permission override can revoke a permission from base role."""
        overrides = [{"permission_key": "invoices.create", "is_granted": False}]
        assert not has_permission("salesperson", "invoices.create", overrides=overrides)

    def test_has_permission_override_takes_precedence(self):
        """Override takes precedence over base role permission."""
        # org_admin has org.* which includes org.read
        assert has_permission("org_admin", "org.read")
        # But override can revoke it
        overrides = [{"permission_key": "org.read", "is_granted": False}]
        assert not has_permission("org_admin", "org.read", overrides=overrides)
