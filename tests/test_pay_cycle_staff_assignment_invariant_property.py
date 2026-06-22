"""Property-based test for the exactly-one-staff-assignment invariant (Task 2.1).

Feature: per-staff-pay-cycle, Property 4: Exactly-one-staff-assignment invariant
under set/replace.

Exercises ``set_staff_pay_cycle`` (delete-then-insert replace semantics,
Decision 2) against the real dev Postgres database, mirroring the DB-backed
Hypothesis pattern in ``tests/test_org_scoped_staff_uniqueness_property.py``.

For each example we seed one organisation with a small pool of active pay
cycles, then apply a randomised sequence of ``set_staff_pay_cycle`` calls for a
single staff member. Each call is either:

- a *set/replace* to one of the org's active cycles (distinct or repeated), or
- a *clear* (``pay_cycle_id=None``).

After every call we assert the invariant the feature must guarantee:

- the number of ``target_type='staff'`` assignment rows for that staff member is
  always **at most one** (REQ 3.1, 3.4), and
- it is **exactly one** iff the most recent call supplied a non-null cycle id,
  and **zero** iff the most recent call cleared the assignment (REQ 3.2, 3.3).

The whole generated sequence runs inside one transaction that is rolled back at
the end of every example, so the test leaves no rows behind. A fresh async
engine is created per example because asyncpg connections are bound to the
event loop ``asyncio.run`` creates — exactly like the reference DB-backed
property tests in this repo.

Validates: Requirements 3.1, 3.2, 3.4 (REQ 10.5)

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_org_scoped_staff_uniqueness_property.py).
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
    PayCycle,
    PayCycleAssignment,
    set_staff_pay_cycle,
)


# Size of the pool of active cycles a generated sequence can choose from.
_N_CYCLES = 3

# Sentinel meaning "clear the assignment" (set_staff_pay_cycle(pay_cycle_id=None)).
_CLEAR = -1


# ---------------------------------------------------------------------------
# Generation strategy.
# ---------------------------------------------------------------------------

# A sequence of actions: each is a cycle index 0.._N_CYCLES-1 (set/replace) or
# _CLEAR (clear the assignment). Repeats arise naturally and exercise the
# idempotent re-assign path (REQ 3.2).
_action = st.integers(min_value=_CLEAR, max_value=_N_CYCLES - 1)


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
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


async def _seed_org_and_cycles(
    session: AsyncSession,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Create one org with ``_N_CYCLES`` active pay cycles (flush only)."""
    plan = SubscriptionPlan(
        name=f"paycycle_prop_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"paycycle_prop_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()

    cycle_ids: list[uuid.UUID] = []
    for i in range(_N_CYCLES):
        cycle = PayCycle(
            org_id=org.id,
            name=f"Cycle {i} {uuid.uuid4().hex[:6]}",
            frequency="fortnightly",
            anchor_date=date(2026, 1, 5),
            pay_date_offset_days=3,
            is_default=(i == 0),
            active=True,
        )
        session.add(cycle)
        await session.flush()
        cycle_ids.append(cycle.id)

    return org.id, cycle_ids


async def _count_staff_assignments(
    session: AsyncSession, *, org_id: uuid.UUID, staff_id: uuid.UUID
) -> int:
    """Count staff-level (``target_type='staff'``) assignment rows for staff."""
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


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(actions: list[int]) -> None:
    """Apply the action sequence; assert the exactly-one invariant after each."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, cycle_ids = await _seed_org_and_cycles(session)
                staff_id = uuid.uuid4()

                for action in actions:
                    pay_cycle_id = None if action == _CLEAR else cycle_ids[action]

                    returned = await set_staff_pay_cycle(
                        session,
                        org_id=org_id,
                        staff_id=staff_id,
                        pay_cycle_id=pay_cycle_id,
                    )

                    count = await _count_staff_assignments(
                        session, org_id=org_id, staff_id=staff_id
                    )

                    # Invariant 1: never more than one staff-level row (REQ 3.1, 3.4).
                    assert count <= 1, (
                        f"expected at most one staff-level assignment, found {count} "
                        f"after action={action!r} in sequence={actions!r}"
                    )

                    # Invariant 2: exactly one iff the last call set a cycle;
                    # zero iff it cleared (REQ 3.2, 3.3).
                    expected = 0 if pay_cycle_id is None else 1
                    assert count == expected, (
                        f"expected {expected} staff-level assignment(s) after "
                        f"action={action!r}, found {count} (sequence={actions!r})"
                    )

                    # The returned object agrees with the persisted state.
                    if pay_cycle_id is None:
                        assert returned is None
                    else:
                        assert returned is not None
                        assert returned.target_type == "staff"
                        assert returned.target_id == staff_id
                        assert returned.pay_cycle_id == pay_cycle_id
            finally:
                # Never persist — discard the whole generated sequence.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 4: Exactly-one-staff-assignment invariant under set/replace.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(actions=st.lists(_action, min_size=1, max_size=8))
def test_exactly_one_staff_assignment_under_set_replace(actions: list[int]):
    """Property 4: Exactly-one-staff-assignment invariant under set/replace.

    # Feature: per-staff-pay-cycle, Property 4

    Over a randomised sequence of ``set_staff_pay_cycle`` calls (distinct and
    repeated cycles interleaved with clears) for a single staff member, the
    delete-then-insert replace semantics guarantee that after every call:

    - at most one ``target_type='staff'`` assignment row exists for the staff
      member (REQ 3.1, 3.4), and
    - exactly one exists iff the most recent call supplied a non-null cycle id,
      and zero exists iff it cleared the assignment (REQ 3.2, 3.3).

    **Validates: Requirements 3.1, 3.2, 3.4 (REQ 10.5)**
    """
    asyncio.run(_run_example(actions))
