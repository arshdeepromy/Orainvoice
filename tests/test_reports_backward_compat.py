"""Backward-compatibility assertion tests for the reports-remediation feature
(task 7.1 — backend backward-compatibility checkpoint).

The reports-remediation spec adds fields *additively* and introduces a single
opt-in ``?export=`` switch. Its Backward-Compatibility Contract (design
§"Backward-Compatibility Contract", requirements R18.2/18.4/18.5/18.6) promises:

  - R18.5  With NO ``export`` param, every ``/reports/*`` endpoint returns the
           same JSON *shape* (its ``response_model``) it returned before this
           feature — every pre-feature field is retained.
  - R18.2  The Revenue response retains ``invoice_count`` alongside the new
           ``total_invoices`` alias (and they are equal).
  - R18.4  New fields are additive — ``monthly_breakdown`` (revenue),
           ``vehicles`` (fleet), ``daily_breakdown`` (sms) and the populated
           storage ``breakdown`` are present *in addition to* the legacy fields.
  - R18.6  No database migration is introduced — all new values are computed at
           query time, so no ``alembic/versions/*`` migration references any of
           the additive tokens.

These exercise the HTTP endpoints end-to-end (router + ``response_model``
serialisation) with a mocked async DB session, mirroring the mocked-DB +
``httpx`` ``ASGITransport`` approach of ``tests/test_reports_revenue_endpoint.py``
and ``tests/test_reports_export_endpoints.py``.

Scope: this is a focused backward-compat *shape* suite — it asserts status,
content-type, JSON-object-ness, the full pre-feature field set, and the new
additive fields. It is deliberately NOT a re-test of every computed figure
(those are covered by the per-report tests). The implementation is NOT modified.

Coverage: revenue, invoice_status, top_services, outstanding, gst_return,
customer_statement, carjam, sms, storage, fleet (all ten ``/reports/*`` JSON
report endpoints), plus the R18.6 migration-scan test.

Requirements: 18.2, 18.4, 18.5, 18.6
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Mock-result helpers (one per SQLAlchemy result-consumption style)
# ---------------------------------------------------------------------------


def _mock_row(**kwargs) -> MagicMock:
    """A mock SQLAlchemy result row exposing the given named attributes."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _one(row) -> MagicMock:
    """Result whose .one() returns ``row``."""
    r = MagicMock()
    r.one.return_value = row
    return r


def _one_or_none(row) -> MagicMock:
    """Result whose .one_or_none() returns ``row``."""
    r = MagicMock()
    r.one_or_none.return_value = row
    return r


def _scalar(value) -> MagicMock:
    """Result whose .scalar() returns ``value``."""
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _scalar_one_or_none(value) -> MagicMock:
    """Result whose .scalar_one_or_none() returns ``value``."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _all(rows) -> MagicMock:
    """Result whose .all() returns ``rows``."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _scalars_all(rows) -> MagicMock:
    """Result whose .scalars().all() returns ``rows``."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = rows
    return r


def _build_db(side_effect: list) -> AsyncMock:
    """Mock async DB whose execute() yields the given sequence of results."""
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


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _assert_backward_compatible(resp, *, legacy_keys: set, new_keys: set) -> dict:
    """Shared backward-compat assertions for a no-export JSON report response.

    Asserts (R18.4/18.5, R20.6):
      - HTTP 200 + ``application/json`` content-type,
      - the body is a JSON *object* (not a bare array),
      - every pre-feature ``response_model`` field is still present,
      - every new additive field is present alongside the legacy fields.
    Returns the parsed JSON for endpoint-specific follow-up assertions.
    """
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")

    data = resp.json()
    assert isinstance(data, dict), "response must be a JSON object, not a bare array"

    missing_legacy = legacy_keys - data.keys()
    assert not missing_legacy, f"pre-feature fields missing from response: {missing_legacy}"

    missing_new = new_keys - data.keys()
    assert not missing_new, f"additive fields missing from response: {missing_new}"

    return data


# ---------------------------------------------------------------------------
# Pre-feature ("legacy") response_model field sets, per report.
# These are the fields each /reports/* endpoint returned BEFORE this feature.
# With no `export` param they MUST all still be present (R18.5).
# ---------------------------------------------------------------------------

REVENUE_LEGACY = {
    "total_revenue", "total_gst", "total_inclusive", "invoice_count",
    "average_invoice", "total_refunds", "refund_gst", "net_revenue",
    "net_gst", "period_start", "period_end",
}
REVENUE_NEW = {"total_invoices", "monthly_breakdown"}

INVOICE_STATUS_LEGACY = {"breakdown", "period_start", "period_end"}

TOP_SERVICES_LEGACY = {"services", "period_start", "period_end"}

OUTSTANDING_LEGACY = {"invoices", "total_outstanding", "count"}

GST_RETURN_LEGACY = {
    "total_sales", "total_gst_collected", "net_gst", "standard_rated_sales",
    "standard_rated_gst", "zero_rated_sales", "total_refunds", "refund_gst",
    "adjusted_total_sales", "adjusted_gst_collected", "period_start", "period_end",
}

CUSTOMER_STATEMENT_LEGACY = {
    "customer_id", "customer_name", "items", "opening_balance",
    "closing_balance", "period_start", "period_end",
}

CARJAM_LEGACY = {
    "total_lookups", "included_in_plan", "overage_lookups",
    "overage_charge", "daily_breakdown",
}

SMS_LEGACY = {
    "total_sent", "included_in_plan", "package_credits_remaining",
    "effective_quota", "overage_count", "overage_charge_nzd",
    "per_sms_cost_nzd", "reset_at",
}
SMS_NEW = {"daily_breakdown"}

STORAGE_LEGACY = {"used_bytes", "used_gb", "quota_gb", "usage_percent"}
STORAGE_NEW = {"breakdown"}

FLEET_LEGACY = {
    "fleet_account_id", "fleet_name", "total_spend", "vehicles_serviced",
    "outstanding_balance", "period_start", "period_end",
}
FLEET_NEW = {"vehicles"}


# ===========================================================================
# Revenue — R18.2 (invoice_count alongside total_invoices) + R18.4/18.5
# ===========================================================================


class TestRevenueBackwardCompat:
    @pytest.mark.asyncio
    async def test_revenue_no_export_retains_shape_and_aliases(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _one(_mock_row(
                total_revenue_nzd=Decimal("1000.00"),
                total_gst_nzd=Decimal("150.00"),
                total_inclusive_nzd=Decimal("1150.00"),
                invoice_count=7,
            )),
            _scalar(Decimal("0")),   # credit-note refunds
            _scalar(Decimal("0")),   # refund payments
            _all([                    # monthly breakdown
                _mock_row(month="2024-01", revenue=Decimal("600.00")),
                _mock_row(month="2024-02", revenue=Decimal("550.00")),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/revenue")

        data = _assert_backward_compatible(resp, legacy_keys=REVENUE_LEGACY, new_keys=REVENUE_NEW)

        # R18.2: invoice_count retained alongside total_invoices, and equal.
        assert data["invoice_count"] == 7
        assert data["total_invoices"] == 7
        assert data["total_invoices"] == data["invoice_count"]

        # R18.4: new monthly_breakdown is additive (a list).
        assert isinstance(data["monthly_breakdown"], list)


# ===========================================================================
# Invoice Status — R18.5 (shape unchanged; object not array)
# ===========================================================================


class TestInvoiceStatusBackwardCompat:
    @pytest.mark.asyncio
    async def test_invoice_status_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _all([
                _mock_row(status="paid", count=5, total=Decimal("2500.00")),
                _mock_row(status="issued", count=3, total=Decimal("900.00")),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/invoices/status")

        data = _assert_backward_compatible(
            resp, legacy_keys=INVOICE_STATUS_LEGACY, new_keys=set()
        )
        assert isinstance(data["breakdown"], list)


# ===========================================================================
# Top Services — R18.5
# ===========================================================================


class TestTopServicesBackwardCompat:
    @pytest.mark.asyncio
    async def test_top_services_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _all([
                _mock_row(
                    description="Oil Change",
                    catalogue_item_id=None,
                    count=10,
                    total_revenue=Decimal("500.00"),
                ),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/top-services")

        data = _assert_backward_compatible(
            resp, legacy_keys=TOP_SERVICES_LEGACY, new_keys=set()
        )
        assert isinstance(data["services"], list)


# ===========================================================================
# Outstanding Invoices — R18.5 (object wrapper, not bare array — R20.6)
# ===========================================================================


class TestOutstandingBackwardCompat:
    @pytest.mark.asyncio
    async def test_outstanding_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _all([
                _mock_row(
                    id=uuid.uuid4(),
                    invoice_number="INV-001",
                    customer_id=uuid.uuid4(),
                    vehicle_rego="ABC123",
                    issue_date=date(2024, 1, 5),
                    due_date=date(2024, 2, 5),
                    total=Decimal("300.00"),
                    balance_due=Decimal("150.00"),
                    first_name="Jane",
                    last_name="Doe",
                ),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/outstanding")

        data = _assert_backward_compatible(
            resp, legacy_keys=OUTSTANDING_LEGACY, new_keys=set()
        )
        # Wrapped in an object (never a bare array) — R20.6/R18.x.
        assert isinstance(data["invoices"], list)
        assert data["count"] == 1


# ===========================================================================
# GST Return — R18.5
# ===========================================================================


class TestGstReturnBackwardCompat:
    @pytest.mark.asyncio
    async def test_gst_return_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _scalar(Decimal("1000.00")),  # standard-rated sales
            _scalar(Decimal("0")),        # zero-rated sales
            _one(_mock_row(               # gst totals
                total_gst_nzd=Decimal("150.00"),
                total_sales_nzd=Decimal("1150.00"),
            )),
            _scalar(Decimal("0")),        # credit-note refunds
            _scalar(Decimal("0")),        # refund payments
            _one(_mock_row(               # expenses (input tax)
                total_purchases=Decimal("0"),
                total_input_tax=Decimal("0"),
            )),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/gst-return")

        _assert_backward_compatible(resp, legacy_keys=GST_RETURN_LEGACY, new_keys=set())


# ===========================================================================
# Customer Statement — R18.5
# ===========================================================================


class TestCustomerStatementBackwardCompat:
    @pytest.mark.asyncio
    async def test_customer_statement_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        customer_id = uuid.uuid4()
        side_effect = [
            _scalar_one_or_none(  # customer lookup
                _mock_row(id=customer_id, first_name="Jane", last_name="Doe")
            ),
            _scalars_all([]),     # invoices in period (empty -> payments query skipped)
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get(f"/api/v1/reports/customer-statement/{customer_id}")

        data = _assert_backward_compatible(
            resp, legacy_keys=CUSTOMER_STATEMENT_LEGACY, new_keys=set()
        )
        assert isinstance(data["items"], list)


# ===========================================================================
# Carjam Usage — R18.5
# ===========================================================================


class TestCarjamUsageBackwardCompat:
    @pytest.mark.asyncio
    async def test_carjam_usage_no_export_retains_shape(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _one_or_none(_mock_row(carjam_lookups_included=100)),  # plan info
            _scalar(42),                  # total lookups
            _scalar_one_or_none(None),    # integration config (cost helper -> default)
            _all([                         # daily breakdown
                _mock_row(day=date(2024, 1, 1), count=10),
                _mock_row(day=date(2024, 1, 2), count=32),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/carjam-usage")

        data = _assert_backward_compatible(
            resp, legacy_keys=CARJAM_LEGACY, new_keys=set()
        )
        assert isinstance(data["daily_breakdown"], list)


# ===========================================================================
# SMS Usage — R18.4 (daily_breakdown additive) + R18.5
# ===========================================================================


class TestSmsUsageBackwardCompat:
    @pytest.mark.asyncio
    async def test_sms_usage_no_export_retains_shape_and_daily_breakdown(self):
        org_id = str(uuid.uuid4())
        side_effect = [
            _scalar(5),                    # total_sent (raw SQL .scalar())
            _all([                          # daily breakdown (raw SQL .all())
                _mock_row(day=date(2024, 1, 1), cnt=2),
                _mock_row(day=date(2024, 1, 2), cnt=3),
            ]),
            _one_or_none(_mock_row(sms_included=True, sms_included_quota=500)),  # plan
            _scalar(0),                    # package credits remaining
            _scalar_one_or_none(None),     # provider config (cost helper -> 0.0)
            _scalar(None),                 # reset_at
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/sms-usage")

        data = _assert_backward_compatible(resp, legacy_keys=SMS_LEGACY, new_keys=SMS_NEW)

        # R18.4: daily_breakdown is additive (a list).
        assert isinstance(data["daily_breakdown"], list)


# ===========================================================================
# Storage Usage — R18.4 (populated breakdown additive) + R18.5
# ===========================================================================


class TestStorageUsageBackwardCompat:
    @pytest.mark.asyncio
    async def test_storage_no_export_retains_shape_and_breakdown(self, monkeypatch):
        org_id = str(uuid.uuid4())
        side_effect = [
            _one_or_none(_mock_row(storage_used_bytes=2048, storage_quota_gb=100)),
        ]

        # calculate_org_storage is imported inside get_storage_usage at call
        # time; patch the source module so the breakdown is deterministic.
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

        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get("/api/v1/reports/storage")

        data = _assert_backward_compatible(
            resp, legacy_keys=STORAGE_LEGACY, new_keys=STORAGE_NEW
        )
        # R18.4: breakdown is populated additively, {category, bytes} shape.
        assert isinstance(data["breakdown"], list)
        assert data["breakdown"]
        assert {"category", "bytes"} <= data["breakdown"][0].keys()


# ===========================================================================
# Fleet Report — R18.4 (vehicles additive) + R18.5
# ===========================================================================


class TestFleetReportBackwardCompat:
    @pytest.mark.asyncio
    async def test_fleet_no_export_retains_shape_and_vehicles(self):
        org_id = str(uuid.uuid4())
        fleet_id = uuid.uuid4()
        side_effect = [
            _scalar_one_or_none(_mock_row(name="Acme Fleet")),  # fleet account
            _all([(uuid.uuid4(),)]),                            # customer ids
            _one(_mock_row(                                      # spend totals
                total_spend=Decimal("500.00"),
                outstanding=Decimal("100.00"),
            )),
            _scalar(2),                                         # distinct vehicles
            _all([                                               # per-vehicle aggregate
                _mock_row(
                    rego="ABC123", make="Toyota", model="Hilux",
                    total_spend=Decimal("300.00"),
                    last_service_date=date(2024, 3, 1),
                ),
                _mock_row(
                    rego="XYZ789", make="Ford", model="Ranger",
                    total_spend=Decimal("200.00"),
                    last_service_date=date(2024, 2, 1),
                ),
            ]),
        ]
        app = _build_app(org_id=org_id, role="org_admin", db=_build_db(side_effect))
        async with _client(app) as client:
            resp = await client.get(f"/api/v1/reports/fleet/{fleet_id}")

        data = _assert_backward_compatible(resp, legacy_keys=FLEET_LEGACY, new_keys=FLEET_NEW)

        # R18.4: vehicles[] is additive (a list).
        assert isinstance(data["vehicles"], list)
        assert len(data["vehicles"]) == 2


# ===========================================================================
# R18.6 — No database migration introduced by this feature
# ===========================================================================


class TestNoMigrationIntroduced:
    """R18.6: all new values are computed at query time, so the feature adds NO
    alembic migration. We assert that no migration file under alembic/versions/
    references any of the additive tokens this feature introduced — if a
    migration had been added for these fields, one of these tokens would appear.
    """

    # Tokens unique to the additive fields/endpoints this feature introduced.
    # None of these are column/table names — they are computed at query time.
    FEATURE_TOKENS = (
        "monthly_breakdown",
        "daily_breakdown",
        "total_invoices",
        "plan_sms_pricing",
    )

    def _versions_dir(self) -> Path:
        # tests/ -> repo root -> alembic/versions
        return Path(__file__).resolve().parents[1] / "alembic" / "versions"

    def test_alembic_versions_dir_exists(self):
        versions = self._versions_dir()
        assert versions.is_dir(), f"alembic versions dir not found at {versions}"

    def test_no_migration_references_feature_tokens(self):
        versions = self._versions_dir()
        offenders: dict[str, list[str]] = {}
        for migration in versions.glob("*.py"):
            try:
                text = migration.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hits = [tok for tok in self.FEATURE_TOKENS if tok in text]
            if hits:
                offenders[migration.name] = hits

        assert not offenders, (
            "reports-remediation must not introduce a DB migration (R18.6), "
            f"but additive tokens were found in migration files: {offenders}"
        )
