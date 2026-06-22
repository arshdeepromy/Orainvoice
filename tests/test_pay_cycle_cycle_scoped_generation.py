"""Unit tests for cycle-scoped pay-period generation + employment-type encoding.

Feature: per-staff-pay-cycle, Task 4.1.

Covers the two production changes in task 4 against the real dev Postgres
database (mirroring the DB-backed pattern in
``tests/test_pay_cycle_resolution_priority_property.py``):

1. **Cycle-scoped generation (Decision 5 / REQ 8.1, 8.3).**
   ``auto_generate_pay_periods`` now scopes its existence check to
   ``(org_id, pay_cycle_id, start_date)``. Two **active** cycles configured
   identically (same frequency + anchor) therefore each generate their own
   independent set of pay periods — including periods that share a
   ``start_date`` across the two cycles, which the 0225 migration's relaxed
   ``UNIQUE(org_id, pay_cycle_id, start_date)`` key now permits. Under the old
   ``UNIQUE(org_id, start_date)`` key the second cycle's same-start_date period
   would have been skipped by the existence check (and rejected by the DB).

2. **Employment-type encoding path (Decision 3 / REQ 8.1).**
   ``assign_pay_cycle(target_type='employment_type', target_id=<raw string>)``
   stores ``target_id = employment_type_target_id(<string>)`` (a deterministic
   UUIDv5). A staff member with that employment type then resolves to the
   assigned cycle via ``resolve_pay_cycle_for_staff``.

Each test runs inside one transaction that is rolled back at the end, so it
leaves no rows behind. A fresh async engine is created per test because asyncpg
connections are bound to the event loop ``asyncio.run`` creates — exactly like
the reference DB-backed tests in this repo.

The DB connection honours the ``DATABASE_URL`` env override exposed by
``app.config.settings`` (the dev DB on ``localhost:5434``); when Postgres is not
reachable the tests skip rather than fail red.

**Validates: Requirements 8.1, 8.3**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.payslips.models import PayPeriod
from app.modules.staff.models import StaffMember
from app.modules.timesheets.pay_cycles import (
    PayCycle,
    PayCycleAssignment,
    assign_pay_cycle,
    auto_generate_pay_periods,
    employment_type_target_id,
    resolve_pay_cycle_for_staff,
)


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
        name=f"paycycle_gen_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"paycycle_gen_org_{uuid.uuid4().hex[:8]}",
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
    label: str,
    frequency: str = "weekly",
    anchor: date = date(2026, 1, 5),
    is_default: bool = False,
) -> uuid.UUID:
    cycle = PayCycle(
        org_id=org_id,
        name=f"{label} {uuid.uuid4().hex[:6]}",
        frequency=frequency,
        anchor_date=anchor,
        pay_date_offset_days=3,
        is_default=is_default,
        active=True,
    )
    session.add(cycle)
    await session.flush()
    return cycle.id


# ---------------------------------------------------------------------------
# Test 1 — two active cycles generate independent periods (incl. same start).
# ---------------------------------------------------------------------------


async def _run_two_cycles_independent_generation() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        if not await _check_db_reachable(engine):
            pytest.skip("Postgres not reachable for cycle-scoped generation test")

        async with factory() as session:
            try:
                org_id = await _seed_org(session)

                # Two active cycles configured identically (same frequency +
                # anchor) so generate_upcoming_periods produces the SAME set of
                # start_dates for each — guaranteeing shared start_dates across
                # the two cycles.
                cycle_a = await _new_cycle(
                    session, org_id=org_id, label="Weekly A"
                )
                cycle_b = await _new_cycle(
                    session, org_id=org_id, label="Weekly B"
                )
                await session.flush()

                created_a = await auto_generate_pay_periods(
                    session, org_id=org_id, pay_cycle_id=cycle_a, ahead_count=4
                )
                created_b = await auto_generate_pay_periods(
                    session, org_id=org_id, pay_cycle_id=cycle_b, ahead_count=4
                )

                # Each cycle generated its own independent periods (REQ 8.1).
                assert len(created_a) == 4, (
                    f"cycle A should generate 4 periods, got {len(created_a)}"
                )
                assert len(created_b) == 4, (
                    f"cycle B should generate 4 periods, got {len(created_b)}: "
                    "the cycle-scoped existence check must not skip cycle B's "
                    "periods just because cycle A already has the same start_date"
                )

                # Read back: periods are partitioned by pay_cycle_id.
                rows = (
                    await session.execute(
                        select(PayPeriod).where(PayPeriod.org_id == org_id)
                    )
                ).scalars().all()

                a_starts = {p.start_date for p in rows if p.pay_cycle_id == cycle_a}
                b_starts = {p.start_date for p in rows if p.pay_cycle_id == cycle_b}

                assert len(a_starts) == 4
                assert len(b_starts) == 4

                # REQ 8.3: the two cycles share at least one start_date and both
                # such rows persist — only possible after the 0225 migration
                # relaxed the uniqueness key to include pay_cycle_id.
                shared = a_starts & b_starts
                assert shared, (
                    "the two identically-configured cycles must share at least "
                    "one start_date for this test to exercise REQ 8.3"
                )
                for start in shared:
                    same_start = [p for p in rows if p.start_date == start]
                    cycle_ids = {p.pay_cycle_id for p in same_start}
                    assert cycle_a in cycle_ids and cycle_b in cycle_ids, (
                        f"both cycles must own a period starting {start}"
                    )

                # Re-running generation for cycle A is idempotent: cycle-scoped
                # existence check finds the existing rows and creates nothing.
                created_a_again = await auto_generate_pay_periods(
                    session, org_id=org_id, pay_cycle_id=cycle_a, ahead_count=4
                )
                assert created_a_again == [], (
                    "re-generating cycle A must be a no-op (idempotent)"
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_two_cycles_generate_independent_periods_same_start_date() -> None:
    """Two active cycles generate independent periods, including a shared
    start_date, via the cycle-scoped existence check.

    **Validates: Requirements 8.1, 8.3**
    """
    asyncio.run(_run_two_cycles_independent_generation())


# ---------------------------------------------------------------------------
# Test 2 — employment_type assignment via the encoding path resolves.
# ---------------------------------------------------------------------------


async def _run_employment_type_encoding_resolves() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        if not await _check_db_reachable(engine):
            pytest.skip("Postgres not reachable for employment-type encoding test")

        async with factory() as session:
            try:
                org_id = await _seed_org(session)

                emptype_cycle = await _new_cycle(
                    session, org_id=org_id, label="Casual cycle"
                )

                # Write via the encoding path: pass the RAW employment-type
                # string; assign_pay_cycle encodes it to the UUIDv5 target id.
                assignment = await assign_pay_cycle(
                    session,
                    org_id=org_id,
                    pay_cycle_id=emptype_cycle,
                    target_type="employment_type",
                    target_id="casual",
                )

                # The stored target_id is the deterministic encoding (REQ 8.1).
                assert assignment.target_id == employment_type_target_id("casual"), (
                    "assign_pay_cycle must encode the employment-type string to "
                    "its UUIDv5 target id"
                )

                # Sanity: the row really is in the table with the encoded id.
                stored = (
                    await session.execute(
                        select(PayCycleAssignment).where(
                            PayCycleAssignment.org_id == org_id,
                            PayCycleAssignment.target_type == "employment_type",
                        )
                    )
                ).scalar_one()
                assert stored.target_id == employment_type_target_id("casual")

                # A staff member with that employment type resolves to the cycle.
                staff = StaffMember(
                    org_id=org_id,
                    name="Casual Worker",
                    first_name="Casual",
                    employment_type="casual",
                    is_active=True,
                )
                session.add(staff)
                await session.flush()

                resolved = await resolve_pay_cycle_for_staff(
                    session,
                    org_id=org_id,
                    staff_id=staff.id,
                    employment_type="casual",
                )
                assert resolved is not None, (
                    "a casual staff member must resolve via the employment_type "
                    "assignment written through the encoding path"
                )
                assert resolved.id == emptype_cycle, (
                    f"resolved to {resolved.id} but expected {emptype_cycle}"
                )

                # A staff member of a DIFFERENT employment type does not match
                # the casual-only assignment (no default → None).
                other = StaffMember(
                    org_id=org_id,
                    name="Permanent Worker",
                    first_name="Permanent",
                    employment_type="permanent",
                    is_active=True,
                )
                session.add(other)
                await session.flush()

                resolved_other = await resolve_pay_cycle_for_staff(
                    session,
                    org_id=org_id,
                    staff_id=other.id,
                    employment_type="permanent",
                )
                assert resolved_other is None, (
                    "a permanent staff member must NOT match the casual-only "
                    "employment_type assignment (and there is no default cycle)"
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_employment_type_assignment_encoding_resolves() -> None:
    """An employment_type assignment written via the encoding path resolves to
    the assigned cycle for a matching staff member.

    **Validates: Requirements 8.1**
    """
    asyncio.run(_run_employment_type_encoding_resolves())
