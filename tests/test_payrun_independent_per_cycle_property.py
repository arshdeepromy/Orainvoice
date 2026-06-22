"""Property-based test for independent per-cycle pay runs (Task 8.1).

Feature: per-staff-pay-cycle, Property 10: Independent per-cycle pay runs.

Exercises ``run_pay_period`` (Components → payrun.py, Decision 6) end-to-end on
top of cycle-scoped ``materialise_missing_timesheets`` against the real dev
Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_materialisation_cycle_scoped_property.py`` and
``tests/test_pay_cycle_resolution_priority_property.py``.

For each example we seed one organisation with **exactly two** active pay cycles
(A and B — the two-cycle generator REQ 7.3 contemplates). A is flagged the org
Default_Cycle. A batch of active staff members is created; each is either:

- staff-level assigned to cycle A (slot ``0``),
- staff-level assigned to cycle B (slot ``1``), or
- left unassigned (slot ``-1``) so it resolves to the org Default_Cycle (A).

So every staff member resolves to cycle A (assigned-A + unassigned) or cycle B
(assigned-B). We ``assume`` at least one of each so both pay runs are non-trivial
and the disjointness assertion is meaningful.

Two Pay_Period records are created **sharing the same date range** (REQ 8.3):
one scoped to cycle A, one scoped to cycle B. For each period we run the real
cycle-scoped ``materialise_missing_timesheets`` (``include_all_active=True``),
lock the resulting timesheets, then run the real ``run_pay_period``. We then
inspect the staff actually processed by each pay run (the locked timesheets it
scoped over and the ``payslips`` rows it produced) and assert:

- the two pay runs' staff sets are **disjoint** — no staff appears in both
  cycles' pay runs (the core of REQ 7.3);
- each pay run's staff set equals exactly the staff resolving to that period's
  cycle (one independent result per period, no staff combined across cycles);
- the per-run summary's ``total_timesheets`` and the generated payslip staff set
  agree with that partition.

The whole generated state runs inside one transaction that is rolled back at the
end of every example, so the test leaves no rows behind. A fresh async engine is
created per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 7.3

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

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_materialisation_cycle_scoped_property.py).
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
from app.modules.timesheets.payrun import run_pay_period
from app.modules.timesheets.pay_cycles import PayCycle, PayCycleAssignment
from app.modules.timesheets.service import materialise_missing_timesheets


# Cycle slot codes for a staff member.
_SLOT_UNASSIGNED = -1   # no staff-level assignment -> resolves to default (A)
_SLOT_A = 0             # staff-level assignment to cycle A
_SLOT_B = 1             # staff-level assignment to cycle B

# Both periods share the same date range (REQ 8.3 — two cycles, same range).
_PERIOD_START = date(2026, 6, 1)
_PERIOD_END = date(2026, 6, 14)
_PERIOD_PAY = date(2026, 6, 17)

# Non-zero worked time so each locked timesheet flows a real payslip draft.
_ORDINARY_MINUTES = 2400  # 40h


# ---------------------------------------------------------------------------
# Generation strategy.
# ---------------------------------------------------------------------------

# Each staff member is assigned to cycle A (0), cycle B (1), or left unassigned
# (-1, resolves to the org default cycle A).
_staff_slot = st.integers(min_value=_SLOT_UNASSIGNED, max_value=_SLOT_B)


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


async def _new_period(
    session: AsyncSession, *, org_id: uuid.UUID, pay_cycle_id: uuid.UUID
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


async def _materialise_lock_and_run(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    period: PayPeriod,
    actor_id: uuid.UUID,
) -> tuple[set[uuid.UUID], object, set[uuid.UUID]]:
    """Drive one period: cycle-scoped materialise -> lock -> run pay run.

    Returns ``(processed_staff_ids, summary, payslip_staff_ids)`` where
    ``processed_staff_ids`` is the staff set the pay run scoped over (the
    period's locked timesheets) and ``payslip_staff_ids`` is the staff set the
    pay run produced payslips for.
    """
    # 1. Cycle-scoped materialisation creates timesheets only for staff whose
    #    resolved cycle matches this period's pay_cycle_id.
    await materialise_missing_timesheets(
        session,
        org_id=org_id,
        pay_period_id=period.id,
        include_all_active=True,
    )

    # 2. Lock every materialised timesheet for the period (give it worked time
    #    so the pay run produces a real payslip draft). run_pay_period only
    #    processes 'locked' timesheets.
    await session.execute(
        update(Timesheet)
        .where(
            Timesheet.org_id == org_id,
            Timesheet.pay_period_id == period.id,
        )
        .values(
            status="locked",
            locked_at=datetime.now(timezone.utc),
            actual_minutes=_ORDINARY_MINUTES,
            ordinary_minutes=_ORDINARY_MINUTES,
        )
    )
    await session.flush()

    # The staff set the pay run scopes over == the period's locked timesheets.
    processed_rows = await session.execute(
        select(Timesheet.staff_id).where(
            Timesheet.org_id == org_id,
            Timesheet.pay_period_id == period.id,
            Timesheet.status == "locked",
        )
    )
    processed_staff_ids = {row[0] for row in processed_rows.all()}

    # 3. Run the real pay run for this period.
    summary = await run_pay_period(
        session, org_id=org_id, pay_period_id=period.id, actor_id=actor_id,
    )

    # The staff set the pay run produced payslips for.
    payslip_rows = await session.execute(
        select(Payslip.staff_id).where(
            Payslip.org_id == org_id,
            Payslip.pay_period_id == period.id,
        )
    )
    payslip_staff_ids = {row[0] for row in payslip_rows.all()}

    return processed_staff_ids, summary, payslip_staff_ids


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(staff_slots: list[int]) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = SubscriptionPlan(
                    name=f"payrun_indep_plan_{uuid.uuid4().hex[:8]}",
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=f"payrun_indep_org_{uuid.uuid4().hex[:8]}",
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    locale="en",
                    settings={},
                )
                session.add(org)
                await session.flush()
                org_id = org.id

                # --- Exactly two active cycles; A is the org default. ---
                cycle_a = await _new_cycle(
                    session, org_id=org_id, label="cycleA", is_default=True
                )
                cycle_b = await _new_cycle(
                    session, org_id=org_id, label="cycleB", is_default=False
                )

                # --- Staff; track which cycle each resolves to. ---
                expected_a: set[uuid.UUID] = set()  # resolve to cycle A
                expected_b: set[uuid.UUID] = set()  # resolve to cycle B

                for slot in staff_slots:
                    staff = StaffMember(
                        org_id=org_id,
                        name="PayRun Test Staff",
                        first_name="PayRun",
                        employment_type="permanent",
                        working_arrangement="rostered",
                        hourly_rate=Decimal("25.00"),
                        tax_code="M",
                        is_active=True,
                    )
                    session.add(staff)
                    await session.flush()

                    if slot == _SLOT_A:
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=cycle_a.id,
                                target_type="staff",
                                target_id=staff.id,
                            )
                        )
                        expected_a.add(staff.id)
                    elif slot == _SLOT_B:
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=cycle_b.id,
                                target_type="staff",
                                target_id=staff.id,
                            )
                        )
                        expected_b.add(staff.id)
                    else:  # unassigned -> resolves to the default cycle (A)
                        expected_a.add(staff.id)

                await session.flush()

                # Both pay runs must be non-trivial for disjointness to bite.
                assume(len(expected_a) >= 1 and len(expected_b) >= 1)

                # --- Two periods sharing the same date range (REQ 8.3). ---
                period_a = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle_a.id
                )
                period_b = await _new_period(
                    session, org_id=org_id, pay_cycle_id=cycle_b.id
                )

                actor_id = uuid.uuid4()

                proc_a, summary_a, pay_a = await _materialise_lock_and_run(
                    session, org_id=org_id, period=period_a, actor_id=actor_id,
                )
                proc_b, summary_b, pay_b = await _materialise_lock_and_run(
                    session, org_id=org_id, period=period_b, actor_id=actor_id,
                )

                # --- Each pay run scopes over exactly its cycle's staff. ---
                assert proc_a == expected_a, (
                    f"period A processed {proc_a} but expected cycle-A staff "
                    f"{expected_a}"
                )
                assert proc_b == expected_b, (
                    f"period B processed {proc_b} but expected cycle-B staff "
                    f"{expected_b}"
                )

                # --- Core of REQ 7.3: the two pay runs never share a staff. ---
                assert proc_a.isdisjoint(proc_b), (
                    f"pay-run staff sets overlap across cycles: "
                    f"{proc_a & proc_b}"
                )

                # --- Independent results per period (no staff combined). ---
                assert summary_a.total_timesheets == len(expected_a), (
                    f"period A summary total_timesheets="
                    f"{summary_a.total_timesheets} but expected {len(expected_a)}"
                )
                assert summary_b.total_timesheets == len(expected_b), (
                    f"period B summary total_timesheets="
                    f"{summary_b.total_timesheets} but expected {len(expected_b)}"
                )

                # --- Generated payslips partition the staff the same way. ---
                assert pay_a == expected_a, (
                    f"period A payslip staff {pay_a} != cycle-A staff "
                    f"{expected_a}"
                )
                assert pay_b == expected_b, (
                    f"period B payslip staff {pay_b} != cycle-B staff "
                    f"{expected_b}"
                )
                assert pay_a.isdisjoint(pay_b), (
                    f"payslip staff sets overlap across cycles: {pay_a & pay_b}"
                )
                assert summary_a.payslips_generated == len(expected_a)
                assert summary_b.payslips_generated == len(expected_b)
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 10: Independent per-cycle pay runs.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
        HealthCheck.filter_too_much,
    ],
)
@given(staff_slots=st.lists(_staff_slot, min_size=2, max_size=6))
def test_independent_per_cycle_pay_runs(staff_slots: list[int]):
    """Property 10: Independent per-cycle pay runs.

    # Feature: per-staff-pay-cycle, Property 10

    For an organisation running two active cycles simultaneously, each
    Pay_Period yields one independent pay-run result: the staff processed by the
    cycle-A period and the staff processed by the cycle-B period are disjoint
    (no staff appears in both cycles' pay runs), and each run's staff set equals
    exactly the staff resolving to that period's cycle. The per-run summary's
    ``total_timesheets`` / ``payslips_generated`` and the generated payslip rows
    agree with that partition, so no staff is combined across cycles.

    **Validates: Requirements 7.3**
    """
    asyncio.run(_run_example(staff_slots))
