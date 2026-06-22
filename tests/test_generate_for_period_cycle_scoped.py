"""DB-backed tests for cycle-scoped ``generate_for_period`` (Part 1).

``app.modules.payslips.service.generate_for_period`` historically drafted a
payslip for EVERY active staff member in the org on the bulk
(``staff_ids=None``) path, ignoring pay cycle. For a multi-cycle org that is
wrong: a period scoped to cycle A should only draft payslips for staff who
resolve to cycle A.

This module asserts the corrected behaviour against the real dev Postgres
database, mirroring the DB-backed pattern in
``tests/test_payrun_independent_per_cycle_property.py``: a fresh async engine
per example, all ORM model modules imported so SQLAlchemy can resolve string
relationships at mapper-configuration time, and the whole generated state run
inside one transaction that is rolled back at the end so no rows are left
behind.

Cases:
  - Cycle-A period drafts only for cycle-A staff (assigned-A + unassigned →
    default A); none for cycle-B staff. Cycle-B period drafts only for
    cycle-B staff.
  - A legacy period (``pay_cycle_id=None``) still drafts for ALL active staff
    (back-compat).
  - Passing an explicit ``staff_ids`` list (the deliberate / termination path)
    drafts for those staff even when they resolve to a different cycle — the
    cycle filter is not applied.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
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
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.leave import models as _leave_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.timesheets import models as _timesheet_models  # noqa: F401
from app.modules.payslips import models as _payslip_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.payslips.models import PayPeriod, Payslip
from app.modules.payslips.service import generate_for_period
from app.modules.staff.models import StaffMember
from app.modules.timesheets.pay_cycles import PayCycle, PayCycleAssignment


_PERIOD_START = date(2026, 6, 8)
_PERIOD_END = date(2026, 6, 14)
_PERIOD_PAY = date(2026, 6, 17)


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per test — bound to the run loop).
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


async def _new_org(session: AsyncSession) -> uuid.UUID:
    plan = SubscriptionPlan(
        name=f"gen_cycle_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"gen_cycle_org_{uuid.uuid4().hex[:8]}",
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
    session: AsyncSession, *, org_id: uuid.UUID, label: str, is_default: bool = False
) -> PayCycle:
    cycle = PayCycle(
        org_id=org_id,
        name=f"{label} {uuid.uuid4().hex[:6]}",
        frequency="fortnightly",
        anchor_date=date(2026, 1, 5),
        pay_date_offset_days=3,
        is_default=is_default,
        active=True,
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def _new_staff(session: AsyncSession, *, org_id: uuid.UUID) -> StaffMember:
    staff = StaffMember(
        org_id=org_id,
        name="Gen Cycle Test Staff",
        first_name="Gen",
        employment_type="permanent",
        working_arrangement="rostered",
        hourly_rate=Decimal("25.00"),
        tax_code="M",
        is_active=True,
    )
    session.add(staff)
    await session.flush()
    return staff


async def _assign(
    session: AsyncSession, *, org_id: uuid.UUID, cycle_id: uuid.UUID, staff_id: uuid.UUID
) -> None:
    session.add(
        PayCycleAssignment(
            org_id=org_id,
            pay_cycle_id=cycle_id,
            target_type="staff",
            target_id=staff_id,
        )
    )
    await session.flush()


async def _new_period(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    pay_cycle_id: uuid.UUID | None,
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


async def _drafted_staff_ids(
    session: AsyncSession, *, org_id: uuid.UUID, period_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Payslip.staff_id).where(
            Payslip.org_id == org_id,
            Payslip.pay_period_id == period_id,
        )
    )
    return {row[0] for row in rows.all()}


# ---------------------------------------------------------------------------
# Test 1 — cycle-scoped bulk path.
# ---------------------------------------------------------------------------


async def _run_cycle_scoped() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _new_org(session)

                cycle_a = await _new_cycle(
                    session, org_id=org_id, label="cycleA", is_default=True
                )
                cycle_b = await _new_cycle(
                    session, org_id=org_id, label="cycleB", is_default=False
                )

                # Staff assigned to A, to B, and one unassigned (-> default A).
                staff_a = await _new_staff(session, org_id=org_id)
                staff_b = await _new_staff(session, org_id=org_id)
                staff_unassigned = await _new_staff(session, org_id=org_id)
                await _assign(
                    session, org_id=org_id, cycle_id=cycle_a.id, staff_id=staff_a.id
                )
                await _assign(
                    session, org_id=org_id, cycle_id=cycle_b.id, staff_id=staff_b.id
                )

                expected_a = {staff_a.id, staff_unassigned.id}
                expected_b = {staff_b.id}

                period_a = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle_a.id
                )
                period_b = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle_b.id
                )

                # --- Cycle-A period: only cycle-A staff. ---
                await generate_for_period(
                    session, org_id=org_id, period_id=period_a.id, staff_ids=None
                )
                drafted_a = await _drafted_staff_ids(
                    session, org_id=org_id, period_id=period_a.id
                )
                assert drafted_a == expected_a, (
                    f"cycle-A period drafted {drafted_a} but expected "
                    f"{expected_a}"
                )
                assert staff_b.id not in drafted_a, (
                    "cycle-B staff must NOT be drafted on a cycle-A period"
                )

                # --- Cycle-B period: only cycle-B staff. ---
                await generate_for_period(
                    session, org_id=org_id, period_id=period_b.id, staff_ids=None
                )
                drafted_b = await _drafted_staff_ids(
                    session, org_id=org_id, period_id=period_b.id
                )
                assert drafted_b == expected_b, (
                    f"cycle-B period drafted {drafted_b} but expected "
                    f"{expected_b}"
                )
                assert drafted_a.isdisjoint(drafted_b), (
                    f"cycle drafts overlap: {drafted_a & drafted_b}"
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_generate_for_period_is_cycle_scoped():
    """Bulk ``generate_for_period`` drafts only the period-cycle's staff."""
    asyncio.run(_run_cycle_scoped())


# ---------------------------------------------------------------------------
# Test 2 — legacy period (pay_cycle_id is None) drafts for ALL active staff.
# ---------------------------------------------------------------------------


async def _run_legacy_period() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _new_org(session)

                cycle_a = await _new_cycle(
                    session, org_id=org_id, label="cycleA", is_default=True
                )
                cycle_b = await _new_cycle(
                    session, org_id=org_id, label="cycleB", is_default=False
                )

                staff_a = await _new_staff(session, org_id=org_id)
                staff_b = await _new_staff(session, org_id=org_id)
                staff_unassigned = await _new_staff(session, org_id=org_id)
                await _assign(
                    session, org_id=org_id, cycle_id=cycle_a.id, staff_id=staff_a.id
                )
                await _assign(
                    session, org_id=org_id, cycle_id=cycle_b.id, staff_id=staff_b.id
                )

                expected_all = {staff_a.id, staff_b.id, staff_unassigned.id}

                # Legacy period: no pay_cycle_id -> no cycle filter applied.
                legacy_period = await _new_period(
                    session, org_id=org_id, pay_cycle_id=None
                )
                await generate_for_period(
                    session,
                    org_id=org_id,
                    period_id=legacy_period.id,
                    staff_ids=None,
                )
                drafted = await _drafted_staff_ids(
                    session, org_id=org_id, period_id=legacy_period.id
                )
                assert drafted == expected_all, (
                    f"legacy period drafted {drafted} but expected ALL active "
                    f"staff {expected_all}"
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_generate_for_period_legacy_drafts_all_active():
    """A period with ``pay_cycle_id=None`` keeps the all-active behaviour."""
    asyncio.run(_run_legacy_period())


# ---------------------------------------------------------------------------
# Test 3 — explicit staff_ids (termination path) is NOT cycle-filtered.
# ---------------------------------------------------------------------------


async def _run_explicit_staff_ids() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id = await _new_org(session)

                cycle_a = await _new_cycle(
                    session, org_id=org_id, label="cycleA", is_default=True
                )
                cycle_b = await _new_cycle(
                    session, org_id=org_id, label="cycleB", is_default=False
                )

                # The deliberately-named staff resolves to cycle B, but the
                # period is scoped to cycle A. The explicit-staff path must
                # still draft for them.
                staff_b = await _new_staff(session, org_id=org_id)
                await _assign(
                    session, org_id=org_id, cycle_id=cycle_b.id, staff_id=staff_b.id
                )

                period_a = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle_a.id
                )

                await generate_for_period(
                    session,
                    org_id=org_id,
                    period_id=period_a.id,
                    staff_ids=[staff_b.id],
                )
                drafted = await _drafted_staff_ids(
                    session, org_id=org_id, period_id=period_a.id
                )
                assert drafted == {staff_b.id}, (
                    f"explicit staff_ids path drafted {drafted} but expected "
                    f"{{{staff_b.id}}} (cycle filter must NOT apply)"
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_generate_for_period_explicit_staff_ids_not_cycle_filtered():
    """Explicit ``staff_ids`` (termination path) bypasses the cycle filter."""
    asyncio.run(_run_explicit_staff_ids())
