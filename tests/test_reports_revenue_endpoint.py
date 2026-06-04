"""Integration tests for GET /reports/revenue (reports-remediation A1).

These exercise the HTTP endpoint end-to-end (router + response_model
serialisation) with a mocked DB session, asserting the additive
backward-compatible contract introduced by the reports-remediation spec:

  - ``monthly_breakdown`` is present and sorted in ascending month order (R1.1).
  - ``total_invoices`` equals ``invoice_count`` (R1.3).
  - With no ``export`` param the JSON response shape is otherwise unchanged —
    every pre-feature field is retained alongside the new additive fields (R18.5).

Requirements: 1.1, 1.3, 18.5
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

# Ensure ORM models are registered for relationship resolution
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.core.database import get_db_session
from app.modules.reports.router import router

# Pre-feature ("legacy") keys the Revenue response returned before this feature.
# With no `export` param these MUST all still be present (R18.5).
LEGACY_REVENUE_KEYS = {
    "total_revenue",
    "total_gst",
    "total_inclusive",
    "invoice_count",
    "average_invoice",
    "total_refunds",
    "refund_gst",
    "net_revenue",
    "net_gst",
    "period_start",
    "period_end",
}

# Additive fields introduced by reports-remediation A1.
NEW_REVENUE_KEYS = {"total_invoices", "monthly_breakdown"}


def _mock_row(**kwargs) -> MagicMock:
    """A mock SQLAlchemy result row exposing the given named attributes."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _build_revenue_db(
    *,
    invoice_count: int,
    total_revenue_nzd: Decimal,
    total_gst_nzd: Decimal,
    total_inclusive_nzd: Decimal,
    month_rows: list,
    cn_refunds: Decimal = Decimal("0"),
    pay_refunds: Decimal = Decimal("0"),
) -> AsyncMock:
    """Build a mock async DB whose execute() returns, in order, the four
    results get_revenue_summary consumes:

      1. invoice totals      -> .one()
      2. credit-note refunds -> .scalar()
      3. refund payments     -> .scalar()
      4. monthly breakdown   -> .all()
    """
    inv_result = MagicMock()
    inv_result.one.return_value = _mock_row(
        total_revenue_nzd=total_revenue_nzd,
        total_gst_nzd=total_gst_nzd,
        total_inclusive_nzd=total_inclusive_nzd,
        invoice_count=invoice_count,
    )

    cn_result = MagicMock()
    cn_result.scalar.return_value = cn_refunds

    pay_result = MagicMock()
    pay_result.scalar.return_value = pay_refunds

    month_result = MagicMock()
    month_result.all.return_value = month_rows

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[inv_result, cn_result, pay_result, month_result])
    return db


def _build_app(*, org_id: str, role: str, db: AsyncMock) -> FastAPI:
    """Minimal FastAPI app mounting the reports router with mocked auth + DB."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_context(request: Request, call_next):  # noqa: ANN001
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = org_id
        request.state.role = role
        return await call_next(request)

    async def _override_db():
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(router, prefix="/api/v1/reports")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRevenueEndpointMonthlyBreakdown:
    """GET /reports/revenue — monthly_breakdown + total_invoices contract."""

    @pytest.mark.asyncio
    async def test_monthly_breakdown_present_and_sorted_ascending(self):
        """monthly_breakdown is returned and ordered ascending by month (R1.1)."""
        org_id = str(uuid.uuid4())
        # DB returns rows in ascending month order (SQL ORDER BY month asc).
        month_rows = [
            _mock_row(month="2024-01", revenue=Decimal("300.00")),
            _mock_row(month="2024-02", revenue=Decimal("450.00")),
            _mock_row(month="2024-03", revenue=Decimal("400.00")),
        ]
        db = _build_revenue_db(
            invoice_count=7,
            total_revenue_nzd=Decimal("1000.00"),
            total_gst_nzd=Decimal("150.00"),
            total_inclusive_nzd=Decimal("1150.00"),
            month_rows=month_rows,
        )
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/reports/revenue",
                params={"start_date": "2024-01-01", "end_date": "2024-03-31"},
            )

        assert resp.status_code == 200
        data = resp.json()

        assert "monthly_breakdown" in data
        months = [point["month"] for point in data["monthly_breakdown"]]
        assert months == ["2024-01", "2024-02", "2024-03"]
        # Ascending order property: the returned sequence equals its sorted form.
        assert months == sorted(months)

    @pytest.mark.asyncio
    async def test_total_invoices_equals_invoice_count(self):
        """total_invoices mirrors invoice_count exactly (R1.3)."""
        org_id = str(uuid.uuid4())
        db = _build_revenue_db(
            invoice_count=42,
            total_revenue_nzd=Decimal("5000.00"),
            total_gst_nzd=Decimal("750.00"),
            total_inclusive_nzd=Decimal("5750.00"),
            month_rows=[_mock_row(month="2024-05", revenue=Decimal("5750.00"))],
        )
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/reports/revenue")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_invoices"] == data["invoice_count"]
        assert data["total_invoices"] == 42

    @pytest.mark.asyncio
    async def test_response_shape_unchanged_without_export(self):
        """With no export param, all legacy fields are retained and the new
        additive fields are present (R18.5, R18.2, R18.4)."""
        org_id = str(uuid.uuid4())
        db = _build_revenue_db(
            invoice_count=3,
            total_revenue_nzd=Decimal("900.00"),
            total_gst_nzd=Decimal("135.00"),
            total_inclusive_nzd=Decimal("1035.00"),
            month_rows=[_mock_row(month="2024-06", revenue=Decimal("1035.00"))],
        )
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/reports/revenue")

        assert resp.status_code == 200
        data = resp.json()

        # Every pre-feature field is still present (backward compatible).
        missing = LEGACY_REVENUE_KEYS - data.keys()
        assert not missing, f"legacy fields missing from response: {missing}"

        # New fields are added additively alongside the legacy ones.
        assert NEW_REVENUE_KEYS <= data.keys()

        # The legacy invoice_count alias is retained alongside total_invoices.
        assert data["invoice_count"] == 3
        assert data["total_invoices"] == 3

        # Period echo is unchanged in shape.
        assert data["period_start"] == "2024-06-01" or data["period_start"]  # present
        assert "period_end" in data

    @pytest.mark.asyncio
    async def test_empty_period_returns_empty_breakdown(self):
        """No invoices in range -> empty monthly_breakdown, total_invoices == 0."""
        org_id = str(uuid.uuid4())
        db = _build_revenue_db(
            invoice_count=0,
            total_revenue_nzd=Decimal("0"),
            total_gst_nzd=Decimal("0"),
            total_inclusive_nzd=Decimal("0"),
            month_rows=[],
        )
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/reports/revenue")

        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_breakdown"] == []
        assert data["total_invoices"] == data["invoice_count"] == 0
