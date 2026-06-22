"""Unit test for ``list_pay_periods`` carrying the pay-cycle name.

Feature: per-staff-pay-cycle, Task 9.1.

Covers the two production changes in task 9 against the real dev Postgres
database (mirroring the DB-backed pattern in
``tests/test_pay_cycle_cycle_scoped_generation.py``):

1. **Cycle name on the payload (REQ 8.2).**
   ``PayPeriodResponse`` gained ``pay_cycle_name`` and ``list_pay_periods``
   left-joins ``PayCycle`` so each pay period in the response carries its
   cycle's name (or ``None`` for a legacy period with no ``pay_cycle_id``).

2. **Two cycles sharing a date range stay distinguishable (REQ 8.3).**
   After the 0225 migration relaxed the uniqueness key to
   ``(org_id, pay_cycle_id, start_date)``, two active cycles can each own a
   pay period with the same ``start_date``. ``list_pay_periods`` must return
   both rows, each labelled with its own cycle name, so the period selector
   can disambiguate them.

The handler is invoked directly with a fake ``Request`` exposing
``request.state.org_id`` (exactly how ``_get_org_id`` reads it) and the seeded
async session. Each test runs inside one transaction rolled back at the end, so
it leaves no rows behind. A fresh async engine is created per test because
asyncpg connections are bound to the event loop ``asyncio.run`` creates — just
like the reference DB-backed tests in this repo.

The DB connection honours the ``DATABASE_URL`` env override exposed by
``app.config.settings`` (the dev DB on ``localhost:5434``); when Postgres is not
reachable the tests skip rather than fail red.

**Validates: Requirements 8.2, 8.3**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.payslips.models import PayPeriod
from app.modules.payslips.router import list_pay_periods
from app.modules.timesheets.pay_cycles import PayCycle


# ---------------------------------------------------------------------------
# Engine / session + seed helpers (fresh engine per test — bound to run loop).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _check_db_reachable(engine) -> bool:
    from sqlalchemy import text as sql_text

    try:
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — any connect failure means skip
        return False


async def _seed_org(session: AsyncSession) -> uuid.UUID:
    plan = SubscriptionPlan(
        name=f"paycycle_name_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"paycycle_name_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()
    return org.id


async def _new_cycle(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    frequency: str = "weekly",
    anchor: date = date(2026, 1, 5),
) -> uuid.UUID:
    cycle = PayCycle(
        org_id=org_id,
        name=name,
        frequency=frequency,
        anchor_date=anchor,
        pay_date_offset_days=3,
        is_default=False,
        active=True,
    )
    session.add(cycle)
    await session.flush()
    return cycle.id


async def _new_period(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    pay_cycle_id: uuid.UUID | None,
    start: date,
) -> uuid.UUID:
    period = PayPeriod(
        org_id=org_id,
        start_date=start,
        end_date=start,
        pay_date=start,
        pay_cycle_id=pay_cycle_id,
        status="open",
    )
    session.add(period)
    await session.flush()
    return period.id


def _fake_request(org_id: uuid.UUID) -> SimpleNamespace:
    """Minimal stand-in for the FastAPI ``Request`` the handler consumes.

    ``list_pay_periods`` only reads ``request.state.org_id`` (via
    ``_get_org_id``), so a ``SimpleNamespace`` with a ``state`` namespace is
    sufficient.
    """
    return SimpleNamespace(state=SimpleNamespace(org_id=str(org_id)))


# ---------------------------------------------------------------------------
# Test — cycle name on the payload + two cycles sharing a date range.
# ---------------------------------------------------------------------------


async def _run_list_pay_periods_carries_cycle_name() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        if not await _check_db_reachable(engine):
            pytest.skip("Postgres not reachable for list_pay_periods cycle-name test")

        async with factory() as session:
            try:
                org_id = await _seed_org(session)

                weekly_name = f"Weekly {uuid.uuid4().hex[:6]}"
                fortnightly_name = f"Fortnightly {uuid.uuid4().hex[:6]}"
                cycle_weekly = await _new_cycle(
                    session, org_id=org_id, name=weekly_name, frequency="weekly"
                )
                cycle_fortnightly = await _new_cycle(
                    session,
                    org_id=org_id,
                    name=fortnightly_name,
                    frequency="fortnightly",
                )

                shared_start = date(2026, 6, 8)
                # Two periods from different active cycles sharing a date range
                # (only persistable after the 0225 migration — REQ 8.3).
                period_weekly = await _new_period(
                    session,
                    org_id=org_id,
                    pay_cycle_id=cycle_weekly,
                    start=shared_start,
                )
                period_fortnightly = await _new_period(
                    session,
                    org_id=org_id,
                    pay_cycle_id=cycle_fortnightly,
                    start=shared_start,
                )
                # A legacy period with no cycle — its name must serialise None.
                period_legacy = await _new_period(
                    session,
                    org_id=org_id,
                    pay_cycle_id=None,
                    start=date(2026, 5, 1),
                )

                resp = await list_pay_periods(
                    request=_fake_request(org_id),
                    offset=0,
                    limit=50,
                    status=None,
                    db=session,
                )

                by_id = {item.id: item for item in resp.items}

                # All three seeded periods are present.
                assert period_weekly in by_id
                assert period_fortnightly in by_id
                assert period_legacy in by_id

                # REQ 8.2: each period carries its cycle name.
                assert by_id[period_weekly].pay_cycle_name == weekly_name
                assert by_id[period_fortnightly].pay_cycle_name == fortnightly_name
                # Legacy period (no cycle) → name is None.
                assert by_id[period_legacy].pay_cycle_name is None
                assert by_id[period_legacy].pay_cycle_id is None

                # REQ 8.3: the two periods share the same date range but remain
                # distinguishable by their (distinct) cycle names.
                assert (
                    by_id[period_weekly].start_date
                    == by_id[period_fortnightly].start_date
                    == shared_start
                )
                assert (
                    by_id[period_weekly].pay_cycle_name
                    != by_id[period_fortnightly].pay_cycle_name
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_list_pay_periods_carries_cycle_name_two_cycles_same_date() -> None:
    """``list_pay_periods`` labels each period with its cycle name and keeps two
    cycles sharing a date range distinguishable.

    **Validates: Requirements 8.2, 8.3**
    """
    asyncio.run(_run_list_pay_periods_carries_cycle_name())
