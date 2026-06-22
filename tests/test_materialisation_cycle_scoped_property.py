"""Property-based test for cycle-scoped materialisation membership (Task 7.1).

Feature: per-staff-pay-cycle, Property 8: Cycle-scoped materialisation membership.

Exercises ``materialise_missing_timesheets`` (Components → service.py
materialisation, Decision 6) against the real dev Postgres database, mirroring
the DB-backed Hypothesis pattern in
``tests/test_pay_cycle_resolution_priority_property.py``.

For each example we seed one organisation with a randomised set of **active**
pay cycles (one example may have a single cycle, another two or three — covering
the single-cycle and multi-cycle generators), optionally flag one as the org
Default_Cycle, and create a batch of active staff members. Each staff member is
either given a staff-level assignment to one of the cycles (so it resolves to
that cycle) or left unassigned (so it resolves to the Default_Cycle when one
exists, otherwise to nothing). Each staff member is also given a materialisation
"activity source": a clock entry inside the period, a ``fixed`` working
arrangement, or no activity at all.

One Pay_Period is created for a chosen active cycle. We then run
``materialise_missing_timesheets`` for that period (with a randomised
``include_all_active``) and assert the **exact** set of staff that received a
timesheet equals the independently-computed reference set:

    materialised == { candidate staff whose resolved cycle == period.pay_cycle_id }

where the candidate set is the same union the service gathers (clock-source +
fixed-source, plus every active staff member when ``include_all_active``). This
proves staff on a different cycle (REQ 6.2) and staff with no resolved cycle
(REQ 6.3) are excluded, and that ``include_all_active`` includes exactly the
matching active staff and no others (REQ 6.4, 7.1, 7.2). The materialised set
equalling the resolved-matching set exactly is REQ 10.4.

The whole generated state runs inside one transaction that is rolled back at the
end of every example, so the test leaves no rows behind. A fresh async engine is
created per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.1, 7.2

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_pay_cycle_resolution_priority_property.py).
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
from app.modules.payslips import models as _payslip_models  # noqa: F401
from app.modules.timesheets import models as _timesheet_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.organisations.models import Branch
from app.modules.payslips.models import PayPeriod
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.pay_cycles import PayCycle, PayCycleAssignment
from app.modules.timesheets.service import materialise_missing_timesheets


# Activity-source codes for a staff member.
_SOURCE_CLOCK = 0   # has a clock entry inside the period
_SOURCE_FIXED = 1   # working_arrangement == 'fixed'
_SOURCE_NONE = 2    # no activity (only a candidate when include_all_active)

_PERIOD_START = date(2026, 6, 1)
_PERIOD_END = date(2026, 6, 14)
_PERIOD_PAY = date(2026, 6, 17)

_FIXED_SCHEDULE = {
    "monday": {"start": "09:00", "end": "17:00"},
    "tuesday": {"start": "09:00", "end": "17:00"},
    "wednesday": {"start": "09:00", "end": "17:00"},
    "thursday": {"start": "09:00", "end": "17:00"},
    "friday": {"start": "09:00", "end": "17:00"},
}


# ---------------------------------------------------------------------------
# Generation strategy.
# ---------------------------------------------------------------------------

# Per-staff config: (assigned_cycle_slot, source).
#   assigned_cycle_slot: -1 => no staff-level assignment (resolves to default
#                              when one exists); >=0 => staff-level assignment to
#                              cycles[slot % num_cycles].
#   source: 0 clock, 1 fixed, 2 none.
_staff_spec = st.tuples(
    st.integers(min_value=-1, max_value=2),
    st.integers(min_value=_SOURCE_CLOCK, max_value=_SOURCE_NONE),
)


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


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    num_cycles: int,
    staff_specs: list[tuple[int, int]],
    default_cycle_slot: int,
    period_cycle_slot: int,
    include_all_active: bool,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = SubscriptionPlan(
                    name=f"materialise_plan_{uuid.uuid4().hex[:8]}",
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=f"materialise_org_{uuid.uuid4().hex[:8]}",
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    locale="en",
                    settings={},
                )
                session.add(org)
                await session.flush()
                org_id = org.id

                # A branch — new time_clock_entries rows require a branch_id
                # (DB check constraint ck_tce_branch_id_new_rows).
                branch = Branch(org_id=org_id, name="Test Branch", is_default=True)
                session.add(branch)
                await session.flush()
                branch_id = branch.id

                # --- Active cycles (single- or multi-cycle). ---
                default_slot = (
                    default_cycle_slot % num_cycles if default_cycle_slot >= 0 else -1
                )
                cycles: list[PayCycle] = []
                for slot in range(num_cycles):
                    cycles.append(
                        await _new_cycle(
                            session,
                            org_id=org_id,
                            label=f"cycle{slot}",
                            is_default=(slot == default_slot),
                        )
                    )
                default_cycle = cycles[default_slot] if default_slot >= 0 else None
                period_cycle = cycles[period_cycle_slot % num_cycles]

                # --- Per-staff setup; compute the reference materialised set. ---
                expected_ids: set[uuid.UUID] = set()

                for assigned_slot, source in staff_specs:
                    is_fixed = source == _SOURCE_FIXED
                    staff = StaffMember(
                        org_id=org_id,
                        name="Materialise Test Staff",
                        first_name="Materialise",
                        employment_type="permanent",
                        working_arrangement="fixed" if is_fixed else "rostered",
                        availability_schedule=_FIXED_SCHEDULE if is_fixed else {},
                        is_active=True,
                    )
                    session.add(staff)
                    await session.flush()

                    # Resolved cycle for this staff member.
                    if assigned_slot >= 0:
                        assigned_cycle = cycles[assigned_slot % num_cycles]
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=assigned_cycle.id,
                                target_type="staff",
                                target_id=staff.id,
                            )
                        )
                        resolved_cycle_id: uuid.UUID | None = assigned_cycle.id
                    elif default_cycle is not None:
                        resolved_cycle_id = default_cycle.id
                    else:
                        resolved_cycle_id = None

                    # Activity source -> clock entry seeding.
                    if source == _SOURCE_CLOCK:
                        session.add(
                            TimeClockEntry(
                                org_id=org_id,
                                staff_id=staff.id,
                                clock_in_at=datetime.combine(
                                    _PERIOD_START, time(9, 0), tzinfo=timezone.utc
                                ),
                                clock_out_at=datetime.combine(
                                    _PERIOD_START, time(17, 0), tzinfo=timezone.utc
                                ),
                                source="admin_manual",
                                worked_minutes=480,
                                branch_id=branch_id,
                            )
                        )

                    # Candidate set mirrors the service's gathering logic:
                    #   clock-source OR fixed-source always; every active staff
                    #   member when include_all_active.
                    is_candidate = (
                        include_all_active
                        or source == _SOURCE_CLOCK
                        or source == _SOURCE_FIXED
                    )
                    if (
                        is_candidate
                        and resolved_cycle_id is not None
                        and resolved_cycle_id == period_cycle.id
                    ):
                        expected_ids.add(staff.id)

                # --- The cycle-scoped Pay_Period. ---
                period = PayPeriod(
                    org_id=org_id,
                    start_date=_PERIOD_START,
                    end_date=_PERIOD_END,
                    pay_date=_PERIOD_PAY,
                    pay_cycle_id=period_cycle.id,
                    status="open",
                )
                session.add(period)
                await session.flush()

                # --- Run the cycle-scoped materialisation sweep. ---
                result = await materialise_missing_timesheets(
                    session,
                    org_id=org_id,
                    pay_period_id=period.id,
                    include_all_active=include_all_active,
                )

                # --- Actual materialised set for this period. ---
                rows = await session.execute(
                    select(Timesheet.staff_id).where(
                        Timesheet.org_id == org_id,
                        Timesheet.pay_period_id == period.id,
                    )
                )
                actual_ids = {row[0] for row in rows.all()}

                assert actual_ids == expected_ids, (
                    f"materialised set {actual_ids} != expected resolved-matching "
                    f"set {expected_ids} (period cycle {period_cycle.id}, "
                    f"include_all_active={include_all_active})"
                )
                # created_count counts exactly the new rows (DB started empty).
                assert result.created_count == len(expected_ids), (
                    f"created_count={result.created_count} but expected "
                    f"{len(expected_ids)}"
                )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 8: Cycle-scoped materialisation membership.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    num_cycles=st.integers(min_value=1, max_value=3),
    staff_specs=st.lists(_staff_spec, min_size=1, max_size=6),
    default_cycle_slot=st.integers(min_value=-1, max_value=2),
    period_cycle_slot=st.integers(min_value=0, max_value=2),
    include_all_active=st.booleans(),
)
def test_cycle_scoped_materialisation_membership(
    num_cycles: int,
    staff_specs: list[tuple[int, int]],
    default_cycle_slot: int,
    period_cycle_slot: int,
    include_all_active: bool,
):
    """Property 8: Cycle-scoped materialisation membership.

    # Feature: per-staff-pay-cycle, Property 8

    For a Pay_Period that belongs to a specific active cycle, the set of staff
    that receive a materialised timesheet equals exactly the set of candidate
    staff (clock-source + fixed-source, plus every active staff member when
    ``include_all_active``) whose resolved cycle id equals the period's
    ``pay_cycle_id``. Staff on a different cycle and staff with no resolved cycle
    are excluded; the single- and multi-cycle generators are both exercised via
    ``num_cycles``.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 7.1, 7.2**
    """
    asyncio.run(
        _run_example(
            num_cycles,
            staff_specs,
            default_cycle_slot,
            period_cycle_slot,
            include_all_active,
        )
    )
