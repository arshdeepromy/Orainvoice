"""Property-based test for single-cycle regression equivalence (Task 7.2).

Feature: per-staff-pay-cycle, Property 9: Single-cycle regression equivalence.

Exercises ``materialise_missing_timesheets`` (Components -> service.py
materialisation, Decision 6) against the real dev Postgres database, mirroring
the DB-backed Hypothesis pattern in
``tests/test_materialisation_cycle_scoped_property.py``.

This property guards backward compatibility (REQ 9.1, 9.2, 9.3 / REQ 10.6): for
a **single-cycle** organisation — one active cycle that is also the
Default_Cycle — cycle scoping must introduce no regression. Every active staff
member resolves to that single cycle (REQ 9.1), whether or not they carry a
staff-level assignment (REQ 9.3), so the cycle-scoped membership filter is a
no-op and the materialised staff set must equal the *pre-feature* reference
computation.

The reference set is built the way the old single-cycle behaviour worked: the
union of clock-source staff, fixed-source staff, and — when
``include_all_active`` is set — every active staff member, with **no cycle
filtering** whatsoever. The single Pay_Period belongs to the sole cycle, and we
assert the cycle-scoped ``materialise_missing_timesheets`` produces exactly that
reference set (REQ 9.2, 10.6).

For each example we seed one organisation with exactly one active, default pay
cycle and a batch of active staff members. Each staff member is either given a
staff-level assignment to the single cycle (resolves to it explicitly) or left
unassigned (resolves to it via the default fallback). Each staff member is also
given a materialisation "activity source": a clock entry inside the period, a
``fixed`` working arrangement, or no activity at all.

The whole generated state runs inside one transaction that is rolled back at the
end of every example, so the test leaves no rows behind. A fresh async engine is
created per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 9.1, 9.2, 9.3

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

# Per-staff config: (assigned, source).
#   assigned: when True, give the staff a staff-level assignment to the single
#             cycle (it resolves to that cycle explicitly); when False, leave the
#             staff unassigned so it resolves to the single cycle via the default
#             fallback (REQ 9.3). Either way, every active staff member resolves
#             to the one cycle (REQ 9.1).
#   source: 0 clock, 1 fixed, 2 none.
_staff_spec = st.tuples(
    st.booleans(),
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
    staff_specs: list[tuple[bool, int]],
    include_all_active: bool,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = SubscriptionPlan(
                    name=f"single_cycle_plan_{uuid.uuid4().hex[:8]}",
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=f"single_cycle_org_{uuid.uuid4().hex[:8]}",
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

                # --- The single, default, active cycle (single-cycle org). ---
                cycle = await _new_cycle(
                    session, org_id=org_id, label="solo", is_default=True
                )

                # --- Per-staff setup; compute the PRE-FEATURE reference set. ---
                # The reference computation deliberately ignores pay cycles
                # entirely — it is exactly the candidate union the old
                # single-cycle materialisation produced: clock-source +
                # fixed-source, plus every active staff member when
                # include_all_active.
                expected_ids: set[uuid.UUID] = set()

                for assigned, source in staff_specs:
                    is_fixed = source == _SOURCE_FIXED
                    staff = StaffMember(
                        org_id=org_id,
                        name="Single Cycle Test Staff",
                        first_name="Single",
                        employment_type="permanent",
                        working_arrangement="fixed" if is_fixed else "rostered",
                        availability_schedule=_FIXED_SCHEDULE if is_fixed else {},
                        is_active=True,
                    )
                    session.add(staff)
                    await session.flush()

                    # Optionally pin the staff to the single cycle explicitly.
                    # Unassigned staff fall back to the default cycle (REQ 9.3);
                    # both paths resolve to the one cycle (REQ 9.1).
                    if assigned:
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=cycle.id,
                                target_type="staff",
                                target_id=staff.id,
                            )
                        )

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

                    # Pre-feature reference: candidate union with NO cycle
                    # filtering. clock-source OR fixed-source always; every
                    # active staff member when include_all_active.
                    is_candidate = (
                        include_all_active
                        or source == _SOURCE_CLOCK
                        or source == _SOURCE_FIXED
                    )
                    if is_candidate:
                        expected_ids.add(staff.id)

                # --- The Pay_Period for the sole cycle. ---
                period = PayPeriod(
                    org_id=org_id,
                    start_date=_PERIOD_START,
                    end_date=_PERIOD_END,
                    pay_date=_PERIOD_PAY,
                    pay_cycle_id=cycle.id,
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
                    f"single-cycle materialised set {actual_ids} != pre-feature "
                    f"reference set {expected_ids} "
                    f"(include_all_active={include_all_active}) — cycle scoping "
                    f"introduced a regression"
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
# Property 9: Single-cycle regression equivalence.
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
    staff_specs=st.lists(_staff_spec, min_size=1, max_size=6),
    include_all_active=st.booleans(),
)
def test_single_cycle_regression_equivalence(
    staff_specs: list[tuple[bool, int]],
    include_all_active: bool,
):
    """Property 9: Single-cycle regression equivalence.

    # Feature: per-staff-pay-cycle, Property 9

    For a single-cycle organisation (exactly one active cycle that is the
    Default_Cycle), every active staff member resolves to that one cycle
    (REQ 9.1) whether assigned explicitly or via the default fallback
    (REQ 9.3). The cycle-scoped ``materialise_missing_timesheets`` must
    therefore produce a materialised staff set identical to the pre-feature
    reference computation (clock-source + fixed-source, plus every active staff
    member when ``include_all_active``), with no cycle filtering — proving cycle
    scoping introduces no regression (REQ 9.2, 10.6).

    **Validates: Requirements 9.1, 9.2, 9.3**
    """
    asyncio.run(
        _run_example(
            staff_specs,
            include_all_active,
        )
    )
