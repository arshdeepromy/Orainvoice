"""Unit tests for claims reports endpoints.

Tests all report endpoints with mocked service functions.

Requirements: 10.1-10.6
"""

from __future__ import annotations

import uuid
from datetime import date
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
from app.modules.claims.router import router as claims_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
BRANCH_ID = uuid.uuid4()

REPORTS_SVC = "app.modules.claims.reports_service"


def _fake_db():
    return AsyncMock()


def _make_test_app(role: str = "org_admin") -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db_session] = _fake_db

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(USER_ID)
        request.state.org_id = str(ORG_ID)
        request.state.role = role
        request.state.branch_id = None
        return await call_next(request)

    app.include_router(claims_router, prefix="/api/v1/claims", tags=["claims"])
    return app


# ---------------------------------------------------------------------------
# 9.1 GET /api/v1/claims/reports/by-period
# ---------------------------------------------------------------------------


class TestClaimsByPeriodReport:
    """Test GET /api/v1/claims/reports/by-period."""

    @patch(f"{REPORTS_SVC}.get_claims_by_period_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_by_period_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "periods": [
                {
                    "period": "2025-01-01T00:00:00",
                    "claim_count": 5,
                    "total_cost": Decimal("250.00"),
                    "average_resolution_hours": 48.5,
                },
                {
                    "period": "2025-02-01T00:00:00",
                    "claim_count": 3,
                    "total_cost": Decimal("120.00"),
                    "average_resolution_hours": 24.0,
                },
            ]
        }

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/by-period")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["periods"]) == 2
        assert data["periods"][0]["claim_count"] == 5
        assert float(data["periods"][0]["total_cost"]) == 250.00

    @patch(f"{REPORTS_SVC}.get_claims_by_period_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_by_period_with_date_filter(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"periods": []}

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/by-period",
            params={"date_from": "2025-01-01", "date_to": "2025-01-31"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["date_from"] == date(2025, 1, 1)
        assert call_kwargs["date_to"] == date(2025, 1, 31)

    @patch(f"{REPORTS_SVC}.get_claims_by_period_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_by_period_with_branch_filter(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"periods": []}

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/by-period",
            params={"branch_id": str(BRANCH_ID)},
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["branch_id"] == BRANCH_ID

    @patch(f"{REPORTS_SVC}.get_claims_by_period_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_by_period_empty_result(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"periods": []}

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/by-period")
        assert resp.status_code == 200
        assert resp.json()["periods"] == []


# ---------------------------------------------------------------------------
# 9.2 GET /api/v1/claims/reports/cost-overhead
# ---------------------------------------------------------------------------


class TestCostOverheadReport:
    """Test GET /api/v1/claims/reports/cost-overhead."""

    @patch(f"{REPORTS_SVC}.get_cost_overhead_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_cost_overhead_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "total_refunds": Decimal("500.00"),
            "total_credit_notes": Decimal("200.00"),
            "total_write_offs": Decimal("75.50"),
            "total_labour_cost": Decimal("150.00"),
        }

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/cost-overhead")
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["total_refunds"]) == 500.00
        assert float(data["total_credit_notes"]) == 200.00
        assert float(data["total_write_offs"]) == 75.50
        assert float(data["total_labour_cost"]) == 150.00

    @patch(f"{REPORTS_SVC}.get_cost_overhead_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_cost_overhead_with_date_filter(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "total_refunds": Decimal("0"),
            "total_credit_notes": Decimal("0"),
            "total_write_offs": Decimal("0"),
            "total_labour_cost": Decimal("0"),
        }

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/cost-overhead",
            params={"date_from": "2025-03-01", "date_to": "2025-03-31"},
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["date_from"] == date(2025, 3, 1)
        assert call_kwargs["date_to"] == date(2025, 3, 31)

    @patch(f"{REPORTS_SVC}.get_cost_overhead_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_cost_overhead_with_branch_filter(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {
            "total_refunds": Decimal("0"),
            "total_credit_notes": Decimal("0"),
            "total_write_offs": Decimal("0"),
            "total_labour_cost": Decimal("0"),
        }

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/cost-overhead",
            params={"branch_id": str(BRANCH_ID)},
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["branch_id"] == BRANCH_ID


# ---------------------------------------------------------------------------
# 9.3 GET /api/v1/claims/reports/supplier-quality
# ---------------------------------------------------------------------------


class TestSupplierQualityReport:
    """Test GET /api/v1/claims/reports/supplier-quality."""

    @patch(f"{REPORTS_SVC}.get_supplier_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_supplier_quality_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        product_id = uuid.uuid4()
        mock_svc.return_value = {
            "items": [
                {
                    "product_id": product_id,
                    "product_name": "Brake Pad Set",
                    "sku": "BP-001",
                    "return_count": 12,
                },
            ]
        }

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/supplier-quality")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "Brake Pad Set"
        assert data["items"][0]["return_count"] == 12

    @patch(f"{REPORTS_SVC}.get_supplier_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_supplier_quality_with_filters(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": []}

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/supplier-quality",
            params={
                "date_from": "2025-01-01",
                "date_to": "2025-06-30",
                "branch_id": str(BRANCH_ID),
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["date_from"] == date(2025, 1, 1)
        assert call_kwargs["date_to"] == date(2025, 6, 30)
        assert call_kwargs["branch_id"] == BRANCH_ID

    @patch(f"{REPORTS_SVC}.get_supplier_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_supplier_quality_empty(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": []}

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/supplier-quality")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# 9.4 GET /api/v1/claims/reports/service-quality
# ---------------------------------------------------------------------------


class TestServiceQualityReport:
    """Test GET /api/v1/claims/reports/service-quality."""

    @patch(f"{REPORTS_SVC}.get_service_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_service_quality_success(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        staff_id = uuid.uuid4()
        mock_svc.return_value = {
            "items": [
                {
                    "staff_id": staff_id,
                    "staff_name": "John Smith",
                    "redo_count": 5,
                },
            ]
        }

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/service-quality")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["staff_name"] == "John Smith"
        assert data["items"][0]["redo_count"] == 5

    @patch(f"{REPORTS_SVC}.get_service_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_service_quality_with_filters(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": []}

        client = TestClient(_make_test_app())
        resp = client.get(
            "/api/v1/claims/reports/service-quality",
            params={
                "date_from": "2025-02-01",
                "date_to": "2025-04-30",
                "branch_id": str(BRANCH_ID),
            },
        )
        assert resp.status_code == 200
        call_kwargs = mock_svc.call_args.kwargs
        assert call_kwargs["date_from"] == date(2025, 2, 1)
        assert call_kwargs["date_to"] == date(2025, 4, 30)
        assert call_kwargs["branch_id"] == BRANCH_ID

    @patch(f"{REPORTS_SVC}.get_service_quality_report", new_callable=AsyncMock)
    @patch("app.modules.auth.rbac._get_user_context")
    def test_service_quality_empty(self, mock_ctx, mock_svc):
        mock_ctx.return_value = (str(USER_ID), str(ORG_ID), "org_admin")
        mock_svc.return_value = {"items": []}

        client = TestClient(_make_test_app())
        resp = client.get("/api/v1/claims/reports/service-quality")
        assert resp.status_code == 200
        assert resp.json()["items"] == []
