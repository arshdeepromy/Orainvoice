"""Unit tests for claims API router.

Tests all endpoints with mocked service functions.

Requirements: 1.1-1.8, 2.1-2.7, 3.1-3.8, 6.1-6.5, 7.1-7.5, 8.1-8.4, 9.1-9.3, 11.1-11.4, 12.1-12.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401

from app.core.database import get_db_session
from app.modules.claims.router import router as claims_router, customer_claims_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CLAIM_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)

# Patch prefix for service functions (lazy-imported inside router endpoints)
SVC = "app.modules.claims.service"


def _fake_db():
    """Return a mock AsyncSession to override get_db_session."""
    return AsyncMock()


def _make_test_app(role: str = "org_admin", branch_id: str | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the claims router, auth bypass, and DB override."""
    app = FastAPI()

    # Override DB dependency so no real connection is attempted
    app.dependency_overrides[get_db_session] = _fake_db

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(USER_ID)
        request.state.org_id = str(ORG_ID)
        request.state.role = role
        request.state.branch_id = branch_id
        return await call_next(request)

    app.include_router(claims_router, prefix="/api/v1/claims", tags=["claims"])
    app.include_router(customer_claims_router, prefix="/api/v1/customers", tags=["customer-claims"])
    return app


def _sample_claim_dict(**overrides) -> dict:
    """Return a sample claim dict as returned by the service layer."""
    base = {
        "id": CLAIM_ID,
        "org_id": ORG_ID,
        "branch_id": None,
        "customer_id": CUSTOMER_ID,
        "customer": None,
        "invoice_id": INVOICE_ID,
        "invoice": None,
        "job_card_id": None,
        "job_card": None,
        "line_item_ids": [],
        "claim_type": "warranty",
        "status": "open",
        "description": "Faulty brake pads",
        "resolution_type": None,
        "resolution_amount": None,
        "resolution_notes": None,
        "resolved_at": None,
        "resolved_by": None,
        "refund_id": None,
        "credit_note_id": None,
        "return_movement_ids": [],
        "warranty_job_id": None,
        "cost_to_business": Decimal("0"),
        "cost_breakdown": {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0},
        "created_by": USER_ID,
        "created_at": NOW,
        "updated_at": NOW,
        "actions": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 8.1 POST /api/v1/claims
# ---------------------------------------------------------------------------


class TestCreateClaimEndpoint:
    """Test POST /api/v1/claims."""

    @patch(f"{SVC}.create_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_create_claim_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = _sample_claim_dict()

        client = TestClient(_make_test_app())
        resp = client.post(
            "/api/v1/claims",
            json={
                "customer_id": str(CUSTOMER_ID),
                "claim_type": "warranty",
                "description": "Faulty brake pads",
                "invoice_id": str(INVOICE_ID),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "open"
        assert data["claim_type"] == "warranty"

    @patch(f"{SVC}.create_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_create_claim_validation_error(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.side_effect = ValueError("Invoice not found in this organisation")

        client = TestClient(_make_test_app())
        resp = client.post(
            "/api/v1/claims",
            json={
                "customer_id": str(CUSTOMER_ID),
                "claim_type": "warranty",
                "description": "Faulty brake pads",
                "invoice_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 400
        assert "Invoice not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8.2 GET /api/v1/claims
# ---------------------------------------------------------------------------


class TestListClaimsEndpoint:
    """Test GET /api/v1/claims."""

    @patch(f"{SVC}.list_claims", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_list_claims_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "items": [
                {
                    "id": CLAIM_ID,
                    "customer_id": CUSTOMER_ID,
                    "customer_name": "John Doe",
                    "claim_type": "warranty",
                    "status": "open",
                    "description": "Faulty brake pads",
                    "cost_to_business": Decimal("0"),
                    "branch_id": None,
                    "created_at": NOW,
                },
            ],
            "total": 1,
        }

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    @patch(f"{SVC}.list_claims", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_list_claims_with_filters(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": [], "total": 0}

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims",
            params={"status": "open", "claim_type": "warranty", "limit": 10, "offset": 0},
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["status"] == "open"
        assert call_kwargs["claim_type"] == "warranty"
        assert call_kwargs["limit"] == 10


# ---------------------------------------------------------------------------
# 8.3 GET /api/v1/claims/{id}
# ---------------------------------------------------------------------------


class TestGetClaimEndpoint:
    """Test GET /api/v1/claims/{id}."""

    @patch(f"{SVC}.get_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_get_claim_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = _sample_claim_dict()

        client = TestClient(_make_test_app())
        resp = client.get(f"/api/v1/claims/{CLAIM_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(CLAIM_ID)
        assert data["status"] == "open"

    @patch(f"{SVC}.get_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_get_claim_not_found(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.side_effect = ValueError("Claim not found in this organisation")

        client = TestClient(_make_test_app())
        resp = client.get(f"/api/v1/claims/{uuid.uuid4()}")
        assert resp.status_code == 400
        assert "Claim not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8.4 PATCH /api/v1/claims/{id}/status
# ---------------------------------------------------------------------------


class TestUpdateClaimStatusEndpoint:
    """Test PATCH /api/v1/claims/{id}/status."""

    @patch(f"{SVC}.update_claim_status", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_update_status_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = _sample_claim_dict(status="investigating")

        client = TestClient(_make_test_app())
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/status",
            json={"new_status": "investigating"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    @patch(f"{SVC}.update_claim_status", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_update_status_invalid_transition(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.side_effect = ValueError(
            "Cannot transition from 'open' to 'approved'. Allowed: ['investigating']"
        )

        client = TestClient(_make_test_app())
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/status",
            json={"new_status": "approved"},
        )
        assert resp.status_code == 400
        assert "Cannot transition" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8.5 POST /api/v1/claims/{id}/resolve
# ---------------------------------------------------------------------------


class TestResolveClaimEndpoint:
    """Test POST /api/v1/claims/{id}/resolve."""

    @patch(f"{SVC}.resolve_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_resolve_claim_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = _sample_claim_dict(
            status="resolved",
            resolution_type="full_refund",
            refund_id=uuid.uuid4(),
            resolved_at=NOW,
            resolved_by=USER_ID,
        )

        client = TestClient(_make_test_app())
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/resolve",
            json={"resolution_type": "full_refund"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolution_type"] == "full_refund"

    @patch(f"{SVC}.resolve_claim", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_resolve_claim_not_approved(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.side_effect = ValueError("Claim must be in 'approved' status before resolution")

        client = TestClient(_make_test_app())
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/resolve",
            json={"resolution_type": "full_refund"},
        )
        assert resp.status_code == 400
        assert "approved" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8.6 POST /api/v1/claims/{id}/notes
# ---------------------------------------------------------------------------


class TestAddClaimNoteEndpoint:
    """Test POST /api/v1/claims/{id}/notes."""

    @patch(f"{SVC}.add_claim_note", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_add_note_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = _sample_claim_dict()

        client = TestClient(_make_test_app())
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/notes",
            json={"notes": "Customer called to follow up"},
        )
        assert resp.status_code == 201

    @patch(f"{SVC}.add_claim_note", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_add_note_claim_not_found(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.side_effect = ValueError("Claim not found in this organisation")

        client = TestClient(_make_test_app())
        resp = client.post(
            f"/api/v1/claims/{uuid.uuid4()}/notes",
            json={"notes": "Some note"},
        )
        assert resp.status_code == 400
        assert "Claim not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8.7 GET /api/v1/customers/{id}/claims
# ---------------------------------------------------------------------------


class TestCustomerClaimsEndpoint:
    """Test GET /api/v1/customers/{id}/claims."""

    @patch(f"{SVC}.get_customer_claims_summary", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_customer_claims_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "total_claims": 2,
            "open_claims": 1,
            "total_cost_to_business": Decimal("150.00"),
            "claims": [
                {
                    "id": CLAIM_ID,
                    "customer_id": CUSTOMER_ID,
                    "customer_name": None,
                    "claim_type": "warranty",
                    "status": "open",
                    "description": "Faulty brake pads",
                    "cost_to_business": Decimal("0"),
                    "branch_id": None,
                    "created_at": NOW,
                },
            ],
        }

        client = TestClient(_make_test_app())
        resp = client.get(f"/api/v1/customers/{CUSTOMER_ID}/claims")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_claims"] == 2
        assert data["open_claims"] == 1


# ---------------------------------------------------------------------------
# Branch scoping tests (Req 11.2, 11.3)
# ---------------------------------------------------------------------------


class TestBranchScoping:
    """Test branch context filtering for non-admin users."""

    @patch(f"{SVC}.list_claims", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_non_admin_gets_branch_scoped(self, mock_ctx, mock_svc):
        """Non-admin users should have branch_id injected from request state."""
        branch_id = uuid.uuid4()
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "salesperson")
        mock_svc.return_value = {"items": [], "total": 0}

        client = TestClient(_make_test_app(role="salesperson", branch_id=str(branch_id)))
        resp = client.get("/api/v1/claims")
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["branch_id"] == branch_id

    @patch(f"{SVC}.list_claims", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_admin_sees_all_branches(self, mock_ctx, mock_svc):
        """Org admin should see claims across all branches (no branch filter injected)."""
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": [], "total": 0}

        client = TestClient(_make_test_app(role="org_admin"))
        resp = client.get("/api/v1/claims")
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["branch_id"] is None
