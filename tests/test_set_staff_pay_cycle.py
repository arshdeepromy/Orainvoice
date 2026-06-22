"""Example/unit tests for ``set_staff_pay_cycle`` and ``employment_type_target_id``
(Task 2.2).

Feature: per-staff-pay-cycle — Decision 2 (delete-then-insert replace semantics)
and Decision 3 (deterministic employment-type target-id encoding).

These are *example* tests (not property tests). They cover the concrete cases
called out by the task:

- Switch A→B leaves exactly one staff-level row (now pointing at B) — REQ 3.1.
- Re-assign A→A succeeds (idempotent), leaves one row, reports success — REQ 3.2.
- Clear (``pay_cycle_id=None``) removes the row — REQ 3.3.
- A cycle id from another org raises ``PayCycleValidationError`` with code
  ``pay_cycle_not_found`` — REQ 2.4.
- An inactive cycle id raises ``PayCycleValidationError`` with code
  ``pay_cycle_inactive`` — REQ 2.5.
- ``employment_type_target_id`` is stable/deterministic (same input → same
  UUID, different inputs → different UUIDs) — Decision 3.

The DB-backed cases follow the same conventions as the Property 4 test in
``tests/test_pay_cycle_staff_assignment_invariant_property.py``: a fresh async
engine per test (asyncpg connections are bound to the event loop
``asyncio.run`` creates), seed an org + active cycles, and roll back at the end
so no rows are left behind.

Validates: Requirements 2.4, 2.5, 3.1, 3.2, 3.3.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (point it at the dev DB on ``localhost:5434``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
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
from app.modules.timesheets.pay_cycles import (
    EMPLOYMENT_TYPE_NS,
    PayCycle,
    PayCycleAssignment,
    PayCycleValidationError,
    employment_type_target_id,
    set_staff_pay_cycle,
)


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


async def _seed_plan(session: AsyncSession) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        name=f"set_cycle_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()
    return plan


async def _seed_org(session: AsyncSession, plan: SubscriptionPlan) -> Organisation:
    org = Organisation(
        name=f"set_cycle_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()
    return org


async def _seed_cycle(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    is_default: bool = False,
    active: bool = True,
) -> PayCycle:
    cycle = PayCycle(
        org_id=org_id,
        name=f"Cycle {uuid.uuid4().hex[:6]}",
        frequency="fortnightly",
        anchor_date=date(2026, 1, 5),
        pay_date_offset_days=3,
        is_default=is_default,
        active=active,
    )
    session.add(cycle)
    await session.flush()
    return cycle


async def _count_staff_assignments(
    session: AsyncSession, *, org_id: uuid.UUID, staff_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(PayCycleAssignment)
        .where(
            PayCycleAssignment.org_id == org_id,
            PayCycleAssignment.target_type == "staff",
            PayCycleAssignment.target_id == staff_id,
        )
    )
    return int(result.scalar_one())


async def _staff_cycle_id(
    session: AsyncSession, *, org_id: uuid.UUID, staff_id: uuid.UUID
) -> uuid.UUID | None:
    result = await session.execute(
        select(PayCycleAssignment.pay_cycle_id).where(
            PayCycleAssignment.org_id == org_id,
            PayCycleAssignment.target_type == "staff",
            PayCycleAssignment.target_id == staff_id,
        )
    )
    return result.scalars().first()


# ---------------------------------------------------------------------------
# DB-backed example tests for set_staff_pay_cycle.
# ---------------------------------------------------------------------------


async def _switch_a_to_b() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org = await _seed_org(session, plan)
                cycle_a = await _seed_cycle(session, org_id=org.id, is_default=True)
                cycle_b = await _seed_cycle(session, org_id=org.id)
                staff_id = uuid.uuid4()

                # Assign A.
                assignment_a = await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=cycle_a.id
                )
                assert assignment_a is not None
                assert assignment_a.pay_cycle_id == cycle_a.id

                # Switch A -> B.
                assignment_b = await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=cycle_b.id
                )
                assert assignment_b is not None
                assert assignment_b.pay_cycle_id == cycle_b.id

                # Exactly one row, now pointing at B (REQ 3.1).
                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 1
                assert await _staff_cycle_id(
                    session, org_id=org.id, staff_id=staff_id
                ) == cycle_b.id
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_switch_a_to_b_leaves_single_row_pointing_at_b():
    """Switching A→B leaves exactly one staff-level row pointing at B (REQ 3.1)."""
    asyncio.run(_switch_a_to_b())


async def _reassign_a_to_a() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org = await _seed_org(session, plan)
                cycle_a = await _seed_cycle(session, org_id=org.id, is_default=True)
                staff_id = uuid.uuid4()

                first = await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=cycle_a.id
                )
                assert first is not None

                # Re-assign the same cycle — idempotent, reports success (REQ 3.2).
                again = await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=cycle_a.id
                )
                assert again is not None
                assert again.pay_cycle_id == cycle_a.id

                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 1
                assert await _staff_cycle_id(
                    session, org_id=org.id, staff_id=staff_id
                ) == cycle_a.id
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_reassign_same_cycle_is_idempotent_and_succeeds():
    """Re-assigning A→A succeeds, leaves exactly one row (REQ 3.2)."""
    asyncio.run(_reassign_a_to_a())


async def _clear_removes_row() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org = await _seed_org(session, plan)
                cycle_a = await _seed_cycle(session, org_id=org.id, is_default=True)
                staff_id = uuid.uuid4()

                await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=cycle_a.id
                )
                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 1

                # Clear — removes the row, returns None (REQ 3.3).
                cleared = await set_staff_pay_cycle(
                    session, org_id=org.id, staff_id=staff_id, pay_cycle_id=None
                )
                assert cleared is None
                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_clear_removes_staff_assignment():
    """Clearing (pay_cycle_id=None) removes the staff-level row (REQ 3.3)."""
    asyncio.run(_clear_removes_row())


async def _wrong_org_cycle_raises() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org = await _seed_org(session, plan)
                other_org = await _seed_org(session, plan)
                # Cycle belongs to other_org, not org.
                foreign_cycle = await _seed_cycle(session, org_id=other_org.id)
                staff_id = uuid.uuid4()

                with pytest.raises(PayCycleValidationError) as exc_info:
                    await set_staff_pay_cycle(
                        session,
                        org_id=org.id,
                        staff_id=staff_id,
                        pay_cycle_id=foreign_cycle.id,
                    )
                assert exc_info.value.code == "pay_cycle_not_found"

                # Nothing persisted for the staff member (REQ 2.4).
                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_wrong_org_cycle_raises_pay_cycle_not_found():
    """A cycle id from another org raises pay_cycle_not_found (REQ 2.4)."""
    asyncio.run(_wrong_org_cycle_raises())


async def _inactive_cycle_raises() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org = await _seed_org(session, plan)
                inactive_cycle = await _seed_cycle(
                    session, org_id=org.id, active=False
                )
                staff_id = uuid.uuid4()

                with pytest.raises(PayCycleValidationError) as exc_info:
                    await set_staff_pay_cycle(
                        session,
                        org_id=org.id,
                        staff_id=staff_id,
                        pay_cycle_id=inactive_cycle.id,
                    )
                assert exc_info.value.code == "pay_cycle_inactive"

                # Nothing persisted for the staff member (REQ 2.5).
                assert await _count_staff_assignments(
                    session, org_id=org.id, staff_id=staff_id
                ) == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_inactive_cycle_raises_pay_cycle_inactive():
    """An inactive cycle id raises pay_cycle_inactive (REQ 2.5)."""
    asyncio.run(_inactive_cycle_raises())


# ---------------------------------------------------------------------------
# Pure-function tests for employment_type_target_id (Decision 3).
# ---------------------------------------------------------------------------


def test_employment_type_target_id_is_deterministic():
    """Same employment-type string always maps to the same UUID (Decision 3)."""
    for emp_type in ("permanent", "casual", "fixed_term"):
        assert employment_type_target_id(emp_type) == employment_type_target_id(
            emp_type
        )


def test_employment_type_target_id_differs_per_input():
    """Different employment-type strings map to different UUIDs (Decision 3)."""
    permanent = employment_type_target_id("permanent")
    casual = employment_type_target_id("casual")
    fixed_term = employment_type_target_id("fixed_term")
    assert len({permanent, casual, fixed_term}) == 3


def test_employment_type_target_id_is_uuid5_of_fixed_namespace():
    """The mapping is a UUIDv5 over the fixed namespace constant (Decision 3)."""
    expected = uuid.uuid5(EMPLOYMENT_TYPE_NS, "permanent")
    assert employment_type_target_id("permanent") == expected
    assert employment_type_target_id("permanent").version == 5
