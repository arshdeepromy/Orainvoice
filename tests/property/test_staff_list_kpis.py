"""Property-based test for ``StaffService.get_list_kpis``.

Covers task **3.2** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 6: List KPI aggregates reflect the staff population**

*For any* set of active staff members, ``get_list_kpis`` SHALL return
``with_login_count`` equal to the number of active staff with a non-null
``user_id``, and ``avg_hourly_rate`` equal to the mean of the non-null
``hourly_rate`` values (or ``null`` when no active staff have an hourly
rate). ``total_staff`` and ``employee_count`` are likewise scoped to the
*active* population.

**Feature: staff-redesign, Property 6**

**Validates: Requirements 1.6**

Hypothesis generates a random staff population with varying ``is_active``,
``role_type`` (employee/contractor), a linked user (``user_id`` set to a
random uuid vs ``None`` — ``staff_members.user_id`` carries no FK
constraint, so no real ``users`` row is needed), and ``hourly_rate``
(``None`` or a generated value). The population is seeded into the real
Postgres instance in the dev compose stack (Hypothesis tests in this
codebase run against the real DB — see
``tests/property/test_staff_month_stats_hours_logged.py``).

Run via: ``docker compose exec -T app python -m pytest \
tests/property/test_staff_list_kpis.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings as h_settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Pre-import the full set of model modules so SQLAlchemy can resolve all
# string-based relationship references when ``configure_mappers()`` runs.
# Mirrors the import block in ``app/main.py`` that runs at app startup.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.invoices import attachment_models as _invoice_attachment_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.time_tracking_v2 import models as _time_tracking_v2_models  # noqa: F401
from app.modules.payslips import models as _payslips_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.config import settings
from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff.models import StaffMember
from app.modules.staff.service import StaffService


# ---------------------------------------------------------------------------
# Hypothesis configuration
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        # Each example provisions a fresh org / staff population and runs a
        # sequence of async DB calls; the function-scoped-fixture health
        # check would otherwise block the run.
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# hourly_rate is Numeric(10, 2); generate two-decimal values within a
# realistic range, or NULL. Quantizing to 2 dp keeps the seeded value and
# the reference mean aligned with the column precision.
_hourly_rate_strategy = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=200_00).map(
        lambda cents: (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    ),
)


@st.composite
def _staff_spec(draw) -> dict:
    """One generated staff member.

    ``is_active`` — included in the KPI population only when true.
    ``role_type`` — employee vs contractor.
    ``has_login`` — user_id set to a random uuid vs None.
    ``hourly_rate`` — set value or NULL.
    """
    return {
        "is_active": draw(st.booleans()),
        "role_type": draw(st.sampled_from(["employee", "contractor"])),
        "has_login": draw(st.booleans()),
        "hourly_rate": draw(_hourly_rate_strategy),
    }


_population_strategy = st.lists(_staff_spec(), min_size=0, max_size=12)


# ---------------------------------------------------------------------------
# Per-example engine + fixtures
# ---------------------------------------------------------------------------


async def _make_session():
    """Build a fresh engine + session per Hypothesis example."""
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


async def _create_org(session: AsyncSession) -> dict:
    """Create plan + org for one example."""
    plan = SubscriptionPlan(
        name=f"List KPIs Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"List KPIs Org {uuid.uuid4().hex[:6]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={},
        timezone="UTC",
    )
    session.add(org)
    await session.flush()

    await _set_rls_org_id(session, str(org.id))

    return {"plan_id": plan.id, "org_id": org.id}


async def _cleanup(session: AsyncSession, fixtures: dict) -> None:
    """Delete every row created for this example (child tables first)."""
    org_id = fixtures.get("org_id")
    plan_id = fixtures.get("plan_id")
    if not org_id:
        return
    try:
        await _set_rls_org_id(session, None)
        for table in ("staff_members", "organisations"):
            await session.execute(
                sa_text(f"DELETE FROM {table} WHERE org_id = :oid"),
                {"oid": str(org_id)},
            )
        if plan_id:
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE id = :pid"),
                {"pid": str(plan_id)},
            )
        await session.commit()
    except Exception:
        await session.rollback()


def _make_staff(*, org_id: uuid.UUID, idx: int, spec: dict) -> StaffMember:
    """Build a StaffMember from a generated spec."""
    return StaffMember(
        org_id=org_id,
        name=f"Staff {idx}",
        first_name=f"Staff{idx}",
        last_name="Member",
        role_type=spec["role_type"],
        is_active=spec["is_active"],
        user_id=uuid.uuid4() if spec["has_login"] else None,
        hourly_rate=spec["hourly_rate"],
        availability_schedule={},
        skills=[],
    )


# ===========================================================================
# Property 6 — List KPI aggregates
# ===========================================================================


class TestListKpisProperty:
    """**Feature: staff-redesign, Property 6**

    ``with_login_count`` equals the number of active staff with a non-null
    ``user_id``; ``avg_hourly_rate`` equals the mean of the non-null
    ``hourly_rate`` values over active staff (``None`` when there are none).

    **Validates: Requirements 1.6**
    """

    @PBT_SETTINGS
    @given(population=_population_strategy)
    @pytest.mark.asyncio
    async def test_list_kpis_reflect_active_population(
        self, population: list[dict],
    ) -> None:
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_org(session)
            org_id = fixtures["org_id"]
            await _set_rls_org_id(session, str(org_id))

            for idx, spec in enumerate(population):
                session.add(_make_staff(org_id=org_id, idx=idx, spec=spec))
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            # Reference computation over exactly the active staff.
            active = [s for s in population if s["is_active"]]
            expected_total = len(active)
            expected_employees = sum(
                1 for s in active if s["role_type"] == "employee"
            )
            expected_with_login = sum(1 for s in active if s["has_login"])

            rates = [
                s["hourly_rate"]
                for s in active
                if s["hourly_rate"] is not None
            ]
            if rates:
                expected_avg = sum(rates, Decimal(0)) / Decimal(len(rates))
            else:
                expected_avg = None

            svc = StaffService(session)
            kpis = await svc.get_list_kpis(org_id)

            assert kpis.total_staff == expected_total, (
                f"total_staff {kpis.total_staff} != expected "
                f"{expected_total}"
            )
            assert kpis.employee_count == expected_employees, (
                f"employee_count {kpis.employee_count} != expected "
                f"{expected_employees}"
            )
            assert kpis.with_login_count == expected_with_login, (
                f"with_login_count {kpis.with_login_count} != expected "
                f"{expected_with_login}"
            )

            if expected_avg is None:
                assert kpis.avg_hourly_rate is None, (
                    f"avg_hourly_rate {kpis.avg_hourly_rate} != expected None"
                )
            else:
                assert kpis.avg_hourly_rate is not None, (
                    "avg_hourly_rate None but expected "
                    f"{expected_avg}"
                )
                # SQL AVG returns extended numeric precision; compare with a
                # small tolerance to absorb rounding differences between the
                # DB mean and the Decimal reference mean.
                assert abs(kpis.avg_hourly_rate - expected_avg) < Decimal(
                    "0.01"
                ), (
                    f"avg_hourly_rate {kpis.avg_hourly_rate} != expected "
                    f"{expected_avg} (rates={rates})"
                )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()
