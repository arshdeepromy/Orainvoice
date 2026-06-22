"""Unit tests for the ``run_pay_period`` null-cycle guard (Task 8.2).

Feature: per-staff-pay-cycle, Decision 6 — Pay-run scoping is inherited; add the
null-cycle guard.

The pay run derives its staff scope from the period's ``pay_cycle_id``
(materialisation is cycle-scoped). A period that is missing, or one whose
``pay_cycle_id`` is ``NULL``, cannot be cycle-scoped — so ``run_pay_period``
refuses to proceed by raising ``PayRunScopingError("pay_period_missing_cycle")``
(REQ 8.5). A period that *does* carry a ``pay_cycle_id`` runs normally and
produces payslip drafts for its locked timesheets.

These are example/unit tests (not property tests). They run against the real dev
Postgres database, mirroring the DB-backed pattern used by
``tests/test_payrun_independent_per_cycle_property.py`` (fresh async engine per
test bound to the ``asyncio.run`` event loop, everything inside one transaction
that is rolled back at the end so no rows are left behind).

Validates: Requirements 8.5

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_payrun_independent_per_cycle_property.py).
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
from app.modules.payslips.models import PayPeriod, Payslip
from app.modules.staff.models import StaffMember
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.payrun import PayRunScopingError, run_pay_period
from app.modules.timesheets.pay_cycles import PayCycle


# A period date range used by every example.
_PERIOD_START = date(2026, 6, 1)
_PERIOD_END = date(2026, 6, 14)
_PERIOD_PAY = date(2026, 6, 17)

# Non-zero worked time so the locked timesheet flows a real payslip draft.
_ORDINARY_MINUTES = 2400  # 40h


# ---------------------------------------------------------------------------
# Engine / session + seed helpers (fresh engine per test — bound to the loop).
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


async def _seed_org(session: AsyncSession) -> uuid.UUID:
    plan = SubscriptionPlan(
        name=f"nullcycle_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"nullcycle_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()
    return org.id


async def _new_cycle(session: AsyncSession, *, org_id: uuid.UUID) -> PayCycle:
    cycle = PayCycle(
        org_id=org_id,
        name=f"cycle {uuid.uuid4().hex[:6]}",
        frequency="fortnightly",
        anchor_date=date(2026, 1, 5),
        pay_date_offset_days=3,
        is_default=True,
        active=True,
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def _new_period(
    session: AsyncSession, *, org_id: uuid.UUID, pay_cycle_id: uuid.UUID | None
) -> PayPeriod:
    period = PayPeriod(
        org_id=org_id,
        start_date=_PERIOD_START,
        end_date=_PERIOD_END,
        pay_date=_PERIOD_PAY,
        pay_cycle_id=pay_cycle_id,
        status="open",
    )
    session.add(period)
    await session.flush()
    return period


async def _new_locked_timesheet(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    period: PayPeriod,
) -> StaffMember:
    """Create an active staff member with a locked timesheet for the period."""
    staff = StaffMember(
        org_id=org_id,
        name="NullCycle Test Staff",
        first_name="NullCycle",
        employment_type="permanent",
        working_arrangement="rostered",
        hourly_rate=Decimal("25.00"),
        tax_code="M",
        is_active=True,
    )
    session.add(staff)
    await session.flush()

    timesheet = Timesheet(
        org_id=org_id,
        staff_id=staff.id,
        pay_period_id=period.id,
        status="locked",
        locked_at=datetime.now(timezone.utc),
        actual_minutes=_ORDINARY_MINUTES,
        ordinary_minutes=_ORDINARY_MINUTES,
    )
    session.add(timesheet)
    await session.flush()
    return staff


# ---------------------------------------------------------------------------
# Per-test drivers.
# ---------------------------------------------------------------------------


async def _run_null_cycle_period() -> None:
    """A period whose ``pay_cycle_id`` is NULL must be refused (REQ 8.5)."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _seed_org(session)
                # Period deliberately created with NO pay cycle.
                period = await _new_period(session, org_id=org_id, pay_cycle_id=None)
                # Even a fully locked timesheet must not be processed.
                await _new_locked_timesheet(session, org_id=org_id, period=period)

                with pytest.raises(PayRunScopingError) as exc_info:
                    await run_pay_period(
                        session,
                        org_id=org_id,
                        pay_period_id=period.id,
                        actor_id=uuid.uuid4(),
                    )
                assert exc_info.value.code == "pay_period_missing_cycle"

                # No payslip rows were created for the refused run.
                from sqlalchemy import select

                payslips = await session.execute(
                    select(Payslip.id).where(Payslip.pay_period_id == period.id)
                )
                assert payslips.first() is None
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


async def _run_missing_period() -> None:
    """A missing period (unknown id) must be refused the same way (REQ 8.5)."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _seed_org(session)
                with pytest.raises(PayRunScopingError) as exc_info:
                    await run_pay_period(
                        session,
                        org_id=org_id,
                        pay_period_id=uuid.uuid4(),  # never inserted
                        actor_id=uuid.uuid4(),
                    )
                assert exc_info.value.code == "pay_period_missing_cycle"
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


async def _run_scoped_period() -> None:
    """A period WITH a ``pay_cycle_id`` runs normally (happy path, REQ 8.5)."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _seed_org(session)
                cycle = await _new_cycle(session, org_id=org_id)
                period = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle.id
                )
                staff = await _new_locked_timesheet(
                    session, org_id=org_id, period=period
                )

                summary = await run_pay_period(
                    session,
                    org_id=org_id,
                    pay_period_id=period.id,
                    actor_id=uuid.uuid4(),
                )

                # The scoped run proceeded and processed the locked timesheet.
                assert summary.pay_period_id == period.id
                assert summary.total_timesheets == 1
                assert summary.payslips_generated == 1
                assert summary.errors == []

                # A payslip draft exists for the staff member in this period.
                from sqlalchemy import select

                payslip_rows = await session.execute(
                    select(Payslip.staff_id).where(
                        Payslip.org_id == org_id,
                        Payslip.pay_period_id == period.id,
                    )
                )
                assert {row[0] for row in payslip_rows.all()} == {staff.id}
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_run_pay_period_refuses_null_cycle_period():
    """A period with ``pay_cycle_id=NULL`` is refused with the scoping code.

    **Validates: Requirements 8.5**
    """
    asyncio.run(_run_null_cycle_period())


def test_run_pay_period_refuses_missing_period():
    """A missing pay period is refused with the same scoping code.

    **Validates: Requirements 8.5**
    """
    asyncio.run(_run_missing_period())


def test_run_pay_period_runs_scoped_period():
    """A period with a ``pay_cycle_id`` runs successfully (happy path).

    **Validates: Requirements 8.5**
    """
    asyncio.run(_run_scoped_period())
