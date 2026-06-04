"""Integration tests for the reports export layer (reports-remediation C1, task 6.5).

These exercise the export wiring end-to-end through the HTTP endpoints
(router ``_maybe_export`` + ``app/modules/reports/export.py``) with a mocked DB
session, asserting the export contract introduced by the reports-remediation
spec:

  - ``?export=csv``  -> ``text/csv`` body + ``Content-Disposition`` attachment
    filename of the form ``{report_key}_{YYYY-MM-DD}.csv`` (R10.3).
  - ``?export=pdf``  -> ``application/pdf`` body + matching ``.pdf`` filename
    (R10.4).
  - The CSV body is golden-file checked: a representative revenue export starts
    with the ``Month,Revenue (NZD)`` header and ends with a ``TOTAL,<amount>``
    row matching the mocked ``total_inclusive`` to two decimal places (R10.5).
  - Regression (R18.5): with no ``export`` param the revenue endpoint still
    returns JSON.

The date in every filename is computed dynamically from
``date.today().isoformat()`` so the test never hard-codes a calendar date.

PDF approach: WeasyPrint is installed in the container, so the PDF tests use the
REAL renderer (no monkeypatching) and assert the body starts with ``b"%PDF"``.

Requirements: 10.3, 10.4
"""

from __future__ import annotations

import csv
import io
import types
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

# Ensure ORM models are registered for relationship resolution.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.core.database import get_db_session
from app.modules.reports.router import router

TODAY = date.today().isoformat()


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_reports_revenue_endpoint.py)
# ---------------------------------------------------------------------------


def _mock_row(**kwargs) -> MagicMock:
    """A mock SQLAlchemy result row exposing the given named attributes."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _build_revenue_results(
    *,
    invoice_count: int,
    total_revenue_nzd: Decimal,
    total_gst_nzd: Decimal,
    total_inclusive_nzd: Decimal,
    month_rows: list,
    cn_refunds: Decimal = Decimal("0"),
    pay_refunds: Decimal = Decimal("0"),
) -> list:
    """Return the four execute() results get_revenue_summary consumes, in order:

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

    return [inv_result, cn_result, pay_result, month_result]


def _build_db(side_effect: list) -> AsyncMock:
    """Build a mock async DB whose execute() returns the given sequence."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=side_effect)
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
# Revenue export — CSV
# ---------------------------------------------------------------------------


class TestRevenueCsvExport:
    """GET /reports/revenue?export=csv — text/csv + filename + golden CSV body."""

    @pytest.mark.asyncio
    async def test_revenue_csv_headers_and_golden_body(self):
        org_id = str(uuid.uuid4())
        month_rows = [
            _mock_row(month="2024-01", revenue=Decimal("300.00")),
            _mock_row(month="2024-02", revenue=Decimal("450.00")),
            _mock_row(month="2024-03", revenue=Decimal("400.00")),
        ]
        side_effect = _build_revenue_results(
            invoice_count=7,
            total_revenue_nzd=Decimal("1000.00"),
            total_gst_nzd=Decimal("150.00"),
            total_inclusive_nzd=Decimal("1150.00"),
            month_rows=month_rows,
        )
        db = _build_db(side_effect)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/reports/revenue",
                params={
                    "start_date": "2024-01-01",
                    "end_date": "2024-03-31",
                    "export": "csv",
                },
            )

        assert resp.status_code == 200

        # content-type starts with text/csv (starlette appends '; charset=utf-8').
        assert resp.headers["content-type"].startswith("text/csv")

        # Content-Disposition filename: revenue_<today>.csv (today computed live).
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="revenue_{TODAY}.csv"'
        )

        body = resp.content.decode("utf-8")

        # Golden-file check: header line is exactly the revenue CSV header.
        assert body.startswith("Month,Revenue (NZD)")

        # Parse the CSV robustly (csv.writer emits \r\n line terminators).
        rows = list(csv.reader(io.StringIO(body)))
        assert rows[0] == ["Month", "Revenue (NZD)"]

        # The monthly rows round-trip the mocked figures to 2dp.
        assert rows[1] == ["2024-01", "300.00"]
        assert rows[2] == ["2024-02", "450.00"]
        assert rows[3] == ["2024-03", "400.00"]

        # Final row is the TOTAL matching the mocked total_inclusive to 2dp.
        assert rows[-1] == ["TOTAL", "1150.00"]


# ---------------------------------------------------------------------------
# Revenue export — PDF (real WeasyPrint render)
# ---------------------------------------------------------------------------


class TestRevenuePdfExport:
    """GET /reports/revenue?export=pdf — application/pdf + filename + %PDF body.

    Uses the REAL WeasyPrint renderer (installed in the container). The PDF path
    issues ONE extra db.execute after the four revenue-service queries to load
    the Organisation (``.scalar_one()``), so a 5th mocked result is appended.
    """

    @pytest.mark.asyncio
    async def test_revenue_pdf_headers_and_pdf_magic_bytes(self):
        org_id = str(uuid.uuid4())
        month_rows = [
            _mock_row(month="2024-01", revenue=Decimal("300.00")),
            _mock_row(month="2024-02", revenue=Decimal("850.00")),
        ]
        side_effect = _build_revenue_results(
            invoice_count=4,
            total_revenue_nzd=Decimal("1000.00"),
            total_gst_nzd=Decimal("150.00"),
            total_inclusive_nzd=Decimal("1150.00"),
            month_rows=month_rows,
        )

        # 5th execute: _maybe_export(pdf) loads the Organisation via .scalar_one().
        org_result = MagicMock()
        org_result.scalar_one.return_value = types.SimpleNamespace(name="Acme Ltd")
        side_effect.append(org_result)

        db = _build_db(side_effect)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/reports/revenue",
                params={
                    "start_date": "2024-01-01",
                    "end_date": "2024-02-29",
                    "export": "pdf",
                },
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="revenue_{TODAY}.pdf"'
        )
        # Real WeasyPrint output always begins with the PDF magic bytes.
        assert resp.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Storage export — CSV (second endpoint for breadth)
# ---------------------------------------------------------------------------


class TestStorageCsvExport:
    """GET /reports/storage?export=csv — text/csv + filename + Category,Bytes header.

    get_storage_usage issues ONE db.execute for the org storage row
    (``.one_or_none()``), then calls ``calculate_org_storage`` — which is
    monkeypatched here to keep the mock simple (it otherwise issues its own
    queries). The org storage row query still needs a mocked result.
    """

    @pytest.mark.asyncio
    async def test_storage_csv_headers_and_breakdown(self, monkeypatch):
        org_id = str(uuid.uuid4())

        # Org storage row -> .one_or_none() with named scalar attributes.
        storage_row_result = MagicMock()
        storage_row_result.one_or_none.return_value = _mock_row(
            storage_used_bytes=2048,
            storage_quota_gb=100,
        )
        db = _build_db([storage_row_result])

        # Keep calculate_org_storage pure for the test — it is imported inside
        # get_storage_usage at call time, so patching the source module works.
        async def _fake_calculate_org_storage(_db, _org_id):
            return {
                "total_bytes": 2048,
                "breakdown": [
                    {"category": "Invoices", "bytes": 1024},
                    {"category": "Customers", "bytes": 1024},
                ],
            }

        monkeypatch.setattr(
            "app.modules.storage.service.calculate_org_storage",
            _fake_calculate_org_storage,
        )

        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/reports/storage",
                params={"export": "csv"},
            )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert (
            resp.headers["content-disposition"]
            == f'attachment; filename="storage_{TODAY}.csv"'
        )

        body = resp.content.decode("utf-8")
        assert body.startswith("Category,Bytes")

        rows = list(csv.reader(io.StringIO(body)))
        assert rows[0] == ["Category", "Bytes"]
        assert ["Invoices", "1024"] in rows
        assert ["Customers", "1024"] in rows


# ---------------------------------------------------------------------------
# Regression — no export param still returns JSON (R18.5)
# ---------------------------------------------------------------------------


class TestRevenueNoExportRegression:
    """GET /reports/revenue (no export) — unchanged JSON response shape (R18.5)."""

    @pytest.mark.asyncio
    async def test_revenue_without_export_returns_json(self):
        org_id = str(uuid.uuid4())
        side_effect = _build_revenue_results(
            invoice_count=3,
            total_revenue_nzd=Decimal("900.00"),
            total_gst_nzd=Decimal("135.00"),
            total_inclusive_nzd=Decimal("1035.00"),
            month_rows=[_mock_row(month="2024-06", revenue=Decimal("1035.00"))],
        )
        db = _build_db(side_effect)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/reports/revenue")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")

        data = resp.json()
        # Expected JSON fields are present (not a file download).
        assert data["invoice_count"] == 3
        assert data["total_invoices"] == 3
        assert data["total_inclusive"] == "1035.00"
        assert data["monthly_breakdown"] == [
            {"month": "2024-06", "revenue": "1035.00"}
        ]
