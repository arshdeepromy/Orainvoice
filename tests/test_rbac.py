"""Unit tests for RBAC middleware and role enforcement (Task 4.9).

Tests cover:
  - Three roles enforced: global_admin, org_admin, salesperson
  - Role + org membership verification on every request
  - Salesperson denied org settings/billing/user management/catalogue
  - Org_Admin denied global admin endpoints
  - Global_Admin denied org customer/invoice data
  - require_role dependency factory
  - Path-based access control via RBACMiddleware

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.rbac import RBACMiddleware
from app.modules.auth.rbac import (
    ALL_ROLES,
    GLOBAL_ADMIN,
    GLOBAL_ADMIN_DENIED_PREFIXES,
    GLOBAL_ADMIN_ONLY_PREFIXES,
    ORG_ADMIN,
    SALESPERSON,
    SALESPERSON_DENIED_PREFIXES,
    check_role_path_access,
    require_role,
)


def _make_token(
    user_id: str = "u1",
    org_id: str | None = "org1",
    role: str = "salesperson",
) -> str:
    payload = {"user_id": user_id, "role": role}
    if org_id is not None:
        payload["org_id"] = org_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _build_rbac_app() -> FastAPI:
    """Create a FastAPI app with Auth + RBAC middleware and test routes."""
    app = FastAPI()

    # Middleware: RBAC runs after Auth (register RBAC first = innermost)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)

    # --- Org-level endpoints (salesperson + org_admin) ---
    @app.get("/api/v1/customers")
    async def list_customers(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/customers/{id}")
    async def get_customer(id: str, request: Request):
        return {"role": request.state.role, "id": id}

    @app.get("/api/v1/invoices")
    async def list_invoices(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v1/invoices")
    async def create_invoice(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/vehicles")
    async def list_vehicles(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/payments")
    async def list_payments(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/quotes")
    async def list_quotes(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/job-cards")
    async def list_job_cards(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/bookings")
    async def list_bookings(request: Request):
        return {"role": request.state.role}

    # --- Org admin only endpoints ---
    @app.get("/api/v1/org/settings")
    async def get_org_settings(request: Request):
        return {"role": request.state.role}

    @app.put("/api/v1/org/settings")
    async def update_org_settings(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/org/users")
    async def list_org_users(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v1/org/users/invite")
    async def invite_user(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/org/branches")
    async def list_branches(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/billing")
    async def billing_dashboard(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v1/billing/upgrade")
    async def upgrade_plan(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/catalogue/services")
    async def list_services(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v1/catalogue/services")
    async def create_service(request: Request):
        return {"role": request.state.role}

    # --- Global admin only endpoints ---
    @app.get("/api/v1/admin/organisations")
    async def list_orgs(request: Request):
        return {"role": request.state.role}

    @app.post("/api/v1/admin/organisations")
    async def create_org(request: Request):
        return {"role": request.state.role}

    @app.get("/api/v1/admin/errors")
    async def error_log(request: Request):
        return {"role": request.state.role}

    # --- Public paths ---
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "ok"}

    return app


@pytest.fixture
def client():
    app = _build_rbac_app()
    return TestClient(app)


def _auth_header(role: str, org_id: str | None = "org1") -> dict:
    token = _make_token(role=role, org_id=org_id)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Requirement 5.1: Three roles enforced
# ---------------------------------------------------------------------------

class TestThreeRolesEnforced:
    """Verify the system recognises all six roles."""

    def test_all_roles_defined(self):
        assert ALL_ROLES == {
            "global_admin", "franchise_admin", "org_admin",
            "location_manager", "salesperson", "staff_member",
        }

    def test_valid_roles_accepted(self, client):
        # Salesperson can access customers
        resp = client.get("/api/v1/customers", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

        # Org admin can access org settings
        resp = client.get("/api/v1/org/settings", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

        # Global admin can access admin endpoints
        resp = client.get(
            "/api/v1/admin/organisations",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Requirement 5.2: Verify role + org membership on every request
# ---------------------------------------------------------------------------

class TestRoleAndOrgVerification:
    """Verify role and org membership checked on every API request."""

    def test_unauthenticated_request_returns_401(self, client):
        resp = client.get("/api/v1/customers")
        assert resp.status_code == 401

    def test_org_admin_without_org_id_denied(self, client):
        resp = client.get(
            "/api/v1/org/settings",
            headers=_auth_header("org_admin", org_id=None),
        )
        assert resp.status_code == 403
        assert "Organisation membership" in resp.json()["detail"]

    def test_salesperson_without_org_id_denied(self, client):
        resp = client.get(
            "/api/v1/customers",
            headers=_auth_header("salesperson", org_id=None),
        )
        assert resp.status_code == 403
        assert "Organisation membership" in resp.json()["detail"]

    def test_public_paths_skip_rbac(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

        resp = client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Requirement 5.3: Salesperson denied org settings/billing/user management
# ---------------------------------------------------------------------------

class TestSalespersonRestrictions:
    """Salesperson cannot access org settings, billing, user management, catalogue."""

    def test_salesperson_allowed_org_settings_get(self, client):
        resp = client.get("/api/v1/org/settings", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_denied_org_settings_put(self, client):
        resp = client.put("/api/v1/org/settings", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_org_users(self, client):
        resp = client.get("/api/v1/org/users", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_user_invite(self, client):
        resp = client.post("/api/v1/org/users/invite", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_branches_write(self, client):
        resp = client.post("/api/v1/org/branches", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_allowed_branches_read(self, client):
        resp = client.get("/api/v1/org/branches", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_denied_billing(self, client):
        resp = client.get("/api/v1/billing", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_billing_upgrade(self, client):
        resp = client.post("/api/v1/billing/upgrade", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_catalogue(self, client):
        resp = client.get("/api/v1/catalogue/services", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_denied_admin(self, client):
        resp = client.get("/api/v1/admin/organisations", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_salesperson_allowed_customers(self, client):
        resp = client.get("/api/v1/customers", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_invoices(self, client):
        resp = client.get("/api/v1/invoices", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_vehicles(self, client):
        resp = client.get("/api/v1/vehicles", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_payments(self, client):
        resp = client.get("/api/v1/payments", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_quotes(self, client):
        resp = client.get("/api/v1/quotes", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_job_cards(self, client):
        resp = client.get("/api/v1/job-cards", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

    def test_salesperson_allowed_bookings(self, client):
        resp = client.get("/api/v1/bookings", headers=_auth_header("salesperson"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Requirement 5.4: Org_Admin gets all salesperson access + org management
# ---------------------------------------------------------------------------

class TestOrgAdminAccess:
    """Org_Admin can access everything a salesperson can, plus org management."""

    def test_org_admin_allowed_customers(self, client):
        resp = client.get("/api/v1/customers", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_invoices(self, client):
        resp = client.get("/api/v1/invoices", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_vehicles(self, client):
        resp = client.get("/api/v1/vehicles", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_payments(self, client):
        resp = client.get("/api/v1/payments", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_quotes(self, client):
        resp = client.get("/api/v1/quotes", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_job_cards(self, client):
        resp = client.get("/api/v1/job-cards", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_bookings(self, client):
        resp = client.get("/api/v1/bookings", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_org_settings(self, client):
        resp = client.get("/api/v1/org/settings", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_org_users(self, client):
        resp = client.get("/api/v1/org/users", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_billing(self, client):
        resp = client.get("/api/v1/billing", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_allowed_catalogue(self, client):
        resp = client.get("/api/v1/catalogue/services", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_org_admin_denied_admin_endpoints(self, client):
        resp = client.get("/api/v1/admin/organisations", headers=_auth_header("org_admin"))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Requirement 5.5: Global_Admin denied org customer/invoice data
# ---------------------------------------------------------------------------

class TestGlobalAdminRestrictions:
    """Global_Admin can access admin console but not org-level data."""

    def test_global_admin_allowed_admin_endpoints(self, client):
        resp = client.get(
            "/api/v1/admin/organisations",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 200

    def test_global_admin_allowed_admin_errors(self, client):
        resp = client.get(
            "/api/v1/admin/errors",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 200

    def test_global_admin_denied_customers(self, client):
        resp = client.get(
            "/api/v1/customers",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403
        assert "organisation-level" in resp.json()["detail"].lower()

    def test_global_admin_denied_customer_detail(self, client):
        resp = client.get(
            "/api/v1/customers/abc",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_invoices(self, client):
        resp = client.get(
            "/api/v1/invoices",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_invoice_create(self, client):
        resp = client.post(
            "/api/v1/invoices",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_vehicles(self, client):
        resp = client.get(
            "/api/v1/vehicles",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_payments(self, client):
        resp = client.get(
            "/api/v1/payments",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_quotes(self, client):
        resp = client.get(
            "/api/v1/quotes",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_job_cards(self, client):
        resp = client.get(
            "/api/v1/job-cards",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403

    def test_global_admin_denied_bookings(self, client):
        resp = client.get(
            "/api/v1/bookings",
            headers=_auth_header("global_admin", org_id=None),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Requirement 5.6: Tenant isolation (org membership check)
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    """Org-scoped roles must have org_id in their token."""

    def test_salesperson_with_org_id_allowed(self, client):
        resp = client.get("/api/v1/customers", headers=_auth_header("salesperson", "org1"))
        assert resp.status_code == 200

    def test_org_admin_with_org_id_allowed(self, client):
        resp = client.get("/api/v1/org/settings", headers=_auth_header("org_admin", "org1"))
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# check_role_path_access unit tests
# ---------------------------------------------------------------------------

class TestCheckRolePathAccess:
    """Direct unit tests for the path access checker function."""

    def test_global_admin_allowed_admin_path(self):
        assert check_role_path_access("global_admin", "/api/v1/admin/organisations") is None

    def test_global_admin_denied_customers(self):
        result = check_role_path_access("global_admin", "/api/v1/customers")
        assert result is not None
        assert "organisation" in result.lower()

    def test_global_admin_denied_invoices(self):
        result = check_role_path_access("global_admin", "/api/v1/invoices")
        assert result is not None

    def test_salesperson_denied_settings_write(self):
        result = check_role_path_access("salesperson", "/api/v1/org/settings", method="PUT")
        assert result is not None

    def test_salesperson_allowed_settings_read(self):
        result = check_role_path_access("salesperson", "/api/v1/org/settings", method="GET")
        assert result is None

    def test_salesperson_denied_billing(self):
        result = check_role_path_access("salesperson", "/api/v1/billing")
        assert result is not None

    def test_salesperson_denied_catalogue(self):
        result = check_role_path_access("salesperson", "/api/v1/catalogue/services")
        assert result is not None

    def test_salesperson_allowed_invoices(self):
        assert check_role_path_access("salesperson", "/api/v1/invoices") is None

    def test_org_admin_denied_admin(self):
        result = check_role_path_access("org_admin", "/api/v1/admin/organisations")
        assert result is not None

    def test_org_admin_allowed_settings(self):
        assert check_role_path_access("org_admin", "/api/v1/org/settings") is None

    def test_org_admin_allowed_customers(self):
        assert check_role_path_access("org_admin", "/api/v1/customers") is None

    def test_unknown_role_denied(self):
        result = check_role_path_access("hacker", "/api/v1/customers")
        assert result is not None
        assert "Unknown role" in result


# ---------------------------------------------------------------------------
# require_role dependency tests
# ---------------------------------------------------------------------------

class TestRequireRoleDependency:
    """Test the require_role FastAPI dependency factory."""

    def test_require_role_allows_matching_role(self):
        app = FastAPI()

        @app.get("/test", dependencies=[require_role("org_admin")])
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(AuthMiddleware)
        client = TestClient(app)
        resp = client.get("/test", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

    def test_require_role_denies_non_matching_role(self):
        app = FastAPI()

        @app.get("/test", dependencies=[require_role("global_admin")])
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(AuthMiddleware)
        client = TestClient(app)
        resp = client.get("/test", headers=_auth_header("salesperson"))
        assert resp.status_code == 403

    def test_require_role_multiple_roles(self):
        app = FastAPI()

        @app.get("/test", dependencies=[require_role("org_admin", "salesperson")])
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(AuthMiddleware)
        client = TestClient(app)

        resp = client.get("/test", headers=_auth_header("org_admin"))
        assert resp.status_code == 200

        resp = client.get("/test", headers=_auth_header("salesperson"))
        assert resp.status_code == 200

        resp = client.get("/test", headers=_auth_header("global_admin", org_id=None))
        assert resp.status_code == 403

    def test_require_role_unauthenticated(self):
        app = FastAPI()

        @app.get("/test", dependencies=[require_role("org_admin")])
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(AuthMiddleware)
        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 401
