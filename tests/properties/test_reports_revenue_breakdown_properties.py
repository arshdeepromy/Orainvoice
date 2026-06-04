"""Property-based tests for the Revenue report monthly breakdown.

Feature: reports-remediation (A1 — Revenue `monthly_breakdown` + `total_invoices`).

Property 1 — Revenue monthly breakdown sums to the period total and the alias
mirrors the count:

  * Σ monthly_breakdown[i].revenue == total_inclusive  (within ±0.01)
  * total_invoices == invoice_count

This is a real-DB property test: the property is a statement about the SQL
aggregation inside ``get_revenue_summary`` (the grouped-by-month sum must
reconcile to the ungrouped period total, under the same status/date filters).
For each Hypothesis example we seed an arbitrary invoice dataset, run the
service, and assert the property. All inserts happen inside a transaction that
is rolled back after every example, so no test data persists.

**Validates: Requirements 1.1, 1.2, 1.3**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from hypothesis import given, settings as hyp_settings, strategies as st, HealthCheck
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401

from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.reports.service import get_revenue_summary


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORG_NAME = "Revenue Breakdown PBT Org"
_PLAN_NAME = "Revenue Breakdown PBT Plan"

# Fixed reporting period for the property. Issue dates are generated across a
# wider window so some invoices fall OUTSIDE the period (exercising the
# date-range filter shared by the totals query and the monthly query).
PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2024, 12, 31)

# Statuses that get_revenue_summary EXCLUDES from revenue (draft + voided).
EXCLUDED_STATUSES = {"draft", "voided"}


# ---------------------------------------------------------------------------
# Hypothesis settings + strategies
# ---------------------------------------------------------------------------

PBT_SETTINGS = hyp_settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)

# All statuses allowed by the invoices CHECK constraint, including the two
# that must be excluded from revenue. Generating both included and excluded
# statuses verifies the two queries apply the SAME status filter.
status_strategy = st.sampled_from([
    "draft", "issued", "partially_paid", "paid",
    "overdue", "voided", "refunded", "partially_refunded",
])

# 2-decimal-place money. The service multiplies total * exchange_rate_to_nzd;
# we hold the rate at exactly 1.000000 (NZD) so per-month sums stay at 2dp and
# the sum-of-rounded-months equals the rounded-grand-total exactly (well within
# the ±0.01 tolerance the property allows). Multi-currency conversion is
# covered by the existing reports_v2 currency tests.
total_strategy = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Issue dates span ~1 year before to ~6 months after the period so the
# generated dataset includes in-range and out-of-range invoices.
issue_date_strategy = st.dates(
    min_value=date(2023, 6, 1),
    max_value=date(2025, 6, 30),
)

invoice_spec_strategy = st.fixed_dictionaries({
    "total": total_strategy,
    "status": status_strategy,
    "issue_date": issue_date_strategy,
})

dataset_strategy = st.lists(invoice_spec_strategy, min_size=0, max_size=15)


# ---------------------------------------------------------------------------
# DB session helper
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, "object"]:
    """Create a fresh engine + session for the test run."""
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    return factory(), test_engine


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

class TestP1RevenueMonthlyBreakdown:
    """Property 1: Σ monthly_breakdown revenue == total_inclusive (±0.01) and
    total_invoices == invoice_count, over arbitrary invoice datasets.

    **Validates: Requirements 1.1, 1.2, 1.3**
    """

    @pytest_asyncio.fixture(autouse=True)
    async def _org_fixtures(self):
        """Create a committed plan/org/user/customer reused across examples,
        and tear them down (including any leaked invoices) afterwards."""
        session, engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)

                plan = SubscriptionPlan(
                    name=_PLAN_NAME,
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=_ORG_NAME,
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    settings={"gst_percentage": 15, "invoice_prefix": "RPBT-"},
                )
                session.add(org)
                await session.flush()

                user = User(
                    org_id=org.id,
                    email=f"revpbt-{uuid.uuid4().hex[:8]}@example.com",
                    first_name="Revenue",
                    last_name="PBT",
                    role="org_admin",
                    password_hash="not-a-real-hash",
                )
                session.add(user)
                await session.flush()

                customer = Customer(
                    org_id=org.id,
                    first_name="Rev",
                    last_name="Customer",
                )
                session.add(customer)
                await session.flush()

                self.org_id = org.id
                self.user_id = user.id
                self.customer_id = customer.id
        finally:
            await session.close()
            await engine.dispose()

        yield

        # Teardown — remove all data created under this org.
        session, engine = await _make_session()
        try:
            async with session.begin():
                await session.execute(sa_text(
                    "DELETE FROM line_items WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM invoices WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM customers WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM users WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM organisations WHERE name = :n"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM subscription_plans WHERE name = :n"
                ), {"n": _PLAN_NAME})
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    @PBT_SETTINGS
    @given(dataset=dataset_strategy)
    async def test_monthly_breakdown_sums_to_total_and_alias_mirrors_count(
        self, dataset: list[dict],
    ) -> None:
        """P1: monthly breakdown reconciles to the period total; the
        total_invoices alias equals invoice_count."""
        session, engine = await _make_session()
        try:
            # Each example runs in its own transaction that is ALWAYS rolled
            # back (in the finally), so generated invoices never persist.
            await session.begin()
            await _set_rls_org_id(session, str(self.org_id))

            for spec in dataset:
                session.add(Invoice(
                    org_id=self.org_id,
                    customer_id=self.customer_id,
                    created_by=self.user_id,
                    status=spec["status"],
                    issue_date=spec["issue_date"],
                    currency="NZD",
                    exchange_rate_to_nzd=Decimal("1.000000"),
                    total=spec["total"],
                    subtotal=spec["total"],
                    gst_amount=Decimal("0.00"),
                ))
            await session.flush()

            data = await get_revenue_summary(
                session, self.org_id, PERIOD_START, PERIOD_END,
            )

            # ---- Independently recompute the expectation from the dataset ----
            included = [
                s for s in dataset
                if s["status"] not in EXCLUDED_STATUSES
                and PERIOD_START <= s["issue_date"] <= PERIOD_END
            ]
            expected_count = len(included)

            expected_total = sum(
                (s["total"] for s in included), Decimal("0")
            ).quantize(Decimal("0.01"))

            expected_by_month: dict[str, Decimal] = {}
            for s in included:
                key = s["issue_date"].strftime("%Y-%m")
                expected_by_month[key] = (
                    expected_by_month.get(key, Decimal("0")) + s["total"]
                )
            expected_by_month = {
                k: v.quantize(Decimal("0.01")) for k, v in expected_by_month.items()
            }

            breakdown = data["monthly_breakdown"]

            # ---- Requirement 1.3: total_invoices alias mirrors invoice_count
            assert data["total_invoices"] == data["invoice_count"], (
                f"total_invoices ({data['total_invoices']}) != "
                f"invoice_count ({data['invoice_count']})"
            )
            assert data["invoice_count"] == expected_count, (
                f"invoice_count {data['invoice_count']} != expected {expected_count}"
            )

            # ---- Requirement 1.1: breakdown sorted ascending by month
            months = [pt["month"] for pt in breakdown]
            assert months == sorted(months), (
                f"monthly_breakdown not sorted ascending: {months}"
            )
            assert len(months) == len(set(months)), (
                f"monthly_breakdown has duplicate months: {months}"
            )

            # ---- Requirement 1.2: each month's revenue is the GST-inclusive
            # total for that month under the same filters.
            actual_by_month = {pt["month"]: pt["revenue"] for pt in breakdown}
            assert actual_by_month == expected_by_month, (
                f"per-month revenue mismatch: actual={actual_by_month} "
                f"expected={expected_by_month}"
            )

            # ---- Property 1: Σ monthly revenue == total_inclusive (±0.01)
            sum_breakdown = sum(
                (pt["revenue"] for pt in breakdown), Decimal("0")
            )
            assert abs(sum_breakdown - data["total_inclusive"]) <= Decimal("0.01"), (
                f"Σ monthly_breakdown revenue ({sum_breakdown}) != "
                f"total_inclusive ({data['total_inclusive']})"
            )
            # And the total itself matches our independent computation.
            assert data["total_inclusive"] == expected_total, (
                f"total_inclusive {data['total_inclusive']} != expected {expected_total}"
            )
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()
