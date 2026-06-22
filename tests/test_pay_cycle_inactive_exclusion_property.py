"""Property-based test for inactive-cycle exclusion (Task 3.2).

Feature: per-staff-pay-cycle, Property 2: Inactive cycles are excluded at every
level.

Exercises ``resolve_pay_cycle_for_staff`` and
``resolve_pay_cycles_for_staff_batch`` (Decision 3 / Decision 4) against the real
dev Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_pay_cycle_resolution_priority_property.py``.

For each example we seed one organisation whose pay-cycle assignments at every
level may point at either an **active** or an **inactive** cycle (or be absent).
Each level is independently set to one of three states:

- ``absent``   — no assignment at this level;
- ``active``   — an assignment to a distinct **active** cycle;
- ``inactive`` — an assignment to a distinct **inactive** cycle.

Org-level shared state covers the ``employment_type`` (per type), ``all`` and
org ``default`` levels; per-staff state covers the ``staff`` and ``branch``
levels (each staff gets a unique location so the batch resolver derives an
unambiguous branch).

The property under test (REQ 4.5): the resolver excludes inactive cycles at
**every** level. An assignment that points at an inactive cycle must be skipped
and resolution must **fall through** to the next level rather than returning the
inactive cycle or short-circuiting to ``None``. We compute the expected result
as the cycle from the first level (in priority order staff → employment_type →
branch → all → default) whose state is ``active``; ``absent`` and ``inactive``
levels are both transparently skipped. When the only matching level is the org
default and that default is active the staff resolves to it with
``is_default=True``; an inactive default is excluded (it is not an active cycle),
so resolution returns ``None`` when no active level matches.

Every assignment points at a **distinct** cycle so the resolved cycle id
uniquely identifies which level won. The single-staff resolver and the batch
resolver are asserted to agree, since the design re-expresses the single
resolver as a thin wrapper over the same priority logic.

The whole generated state runs inside one transaction that is rolled back at the
end of every example, so the test leaves no rows behind. A fresh async engine is
created per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 4.5

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff.models import StaffLocationAssignment, StaffMember
from app.modules.timesheets.pay_cycles import (
    PayCycle,
    PayCycleAssignment,
    employment_type_target_id,
    resolve_pay_cycle_for_staff,
    resolve_pay_cycles_for_staff_batch,
)


_EMPLOYMENT_TYPES = ("permanent", "casual", "fixed_term")

# Per-level state: 0 = absent, 1 = active assignment, 2 = inactive assignment.
ABSENT, ACTIVE, INACTIVE = 0, 1, 2
_level_state = st.integers(min_value=ABSENT, max_value=INACTIVE)

# Per-staff config: (employment_type_index, staff_level_state, branch_level_state).
_staff_config = st.tuples(
    st.integers(min_value=0, max_value=len(_EMPLOYMENT_TYPES) - 1),
    _level_state,
    _level_state,
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
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    label: str,
    active: bool,
    is_default: bool = False,
) -> uuid.UUID:
    cycle = PayCycle(
        org_id=org_id,
        name=f"{label} {uuid.uuid4().hex[:6]}",
        frequency="fortnightly",
        anchor_date=date(2026, 1, 5),
        pay_date_offset_days=3,
        is_default=is_default,
        active=active,
    )
    session.add(cycle)
    await session.flush()
    return cycle.id


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    staff_configs: list[tuple[int, int, int]],
    emptype_state: list[int],
    all_state: int,
    default_state: int,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = SubscriptionPlan(
                    name=f"paycycle_inact_plan_{uuid.uuid4().hex[:8]}",
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=f"paycycle_inact_org_{uuid.uuid4().hex[:8]}",
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    locale="en",
                    settings={},
                )
                session.add(org)
                await session.flush()
                org_id = org.id

                # --- Org default cycle (active or inactive, or absent). ---
                # Only an ACTIVE default is selectable by the resolver; an
                # INACTIVE default is excluded (REQ 4.5) and behaves like absent.
                default_cycle_id: uuid.UUID | None = None
                if default_state != ABSENT:
                    default_cycle_id = await _new_cycle(
                        session,
                        org_id=org_id,
                        label="default",
                        active=(default_state == ACTIVE),
                        is_default=True,
                    )

                # --- 'all'-level assignment (active or inactive, or absent). ---
                all_cycle_id: uuid.UUID | None = None
                if all_state != ABSENT:
                    all_cycle_id = await _new_cycle(
                        session,
                        org_id=org_id,
                        label="all",
                        active=(all_state == ACTIVE),
                    )
                    session.add(
                        PayCycleAssignment(
                            org_id=org_id,
                            pay_cycle_id=all_cycle_id,
                            target_type="all",
                            target_id=None,
                        )
                    )

                # --- employment_type-level assignments (per type). ---
                emptype_cycle_id: dict[int, uuid.UUID] = {}
                for t, state in enumerate(emptype_state):
                    if state == ABSENT:
                        continue
                    cid = await _new_cycle(
                        session,
                        org_id=org_id,
                        label=f"emptype{t}",
                        active=(state == ACTIVE),
                    )
                    emptype_cycle_id[t] = cid
                    session.add(
                        PayCycleAssignment(
                            org_id=org_id,
                            pay_cycle_id=cid,
                            target_type="employment_type",
                            target_id=employment_type_target_id(_EMPLOYMENT_TYPES[t]),
                        )
                    )

                # --- Per-staff setup. ---
                staff_list: list[StaffMember] = []
                # staff.id -> (expected_cycle_id | None, expected_is_default,
                #              branch_location_id, employment_type)
                expected: dict[
                    uuid.UUID, tuple[uuid.UUID | None, bool, uuid.UUID, str]
                ] = {}

                for emp_index, staff_state, branch_state in staff_configs:
                    employment_type = _EMPLOYMENT_TYPES[emp_index]
                    staff = StaffMember(
                        org_id=org_id,
                        name="Inactive Exclusion Test Staff",
                        first_name="Inactive",
                        employment_type=employment_type,
                        is_active=True,
                    )
                    session.add(staff)
                    await session.flush()
                    staff_list.append(staff)

                    # Unique location so the batch resolver derives an
                    # unambiguous branch for this staff member.
                    branch_location_id = uuid.uuid4()
                    session.add(
                        StaffLocationAssignment(
                            staff_id=staff.id, location_id=branch_location_id
                        )
                    )

                    staff_cycle_id: uuid.UUID | None = None
                    if staff_state != ABSENT:
                        staff_cycle_id = await _new_cycle(
                            session,
                            org_id=org_id,
                            label="staff",
                            active=(staff_state == ACTIVE),
                        )
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=staff_cycle_id,
                                target_type="staff",
                                target_id=staff.id,
                            )
                        )

                    branch_cycle_id: uuid.UUID | None = None
                    if branch_state != ABSENT:
                        branch_cycle_id = await _new_cycle(
                            session,
                            org_id=org_id,
                            label="branch",
                            active=(branch_state == ACTIVE),
                        )
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=branch_cycle_id,
                                target_type="branch",
                                target_id=branch_location_id,
                            )
                        )

                    # Expected = first level (in priority order) whose state is
                    # ACTIVE. Inactive and absent levels are both skipped — this
                    # is the inactive-exclusion property (REQ 4.5).
                    emp_state = emptype_state[emp_index]
                    if staff_state == ACTIVE:
                        exp_cycle, exp_default = staff_cycle_id, False
                    elif emp_state == ACTIVE:
                        exp_cycle, exp_default = emptype_cycle_id[emp_index], False
                    elif branch_state == ACTIVE:
                        exp_cycle, exp_default = branch_cycle_id, False
                    elif all_state == ACTIVE:
                        exp_cycle, exp_default = all_cycle_id, False
                    elif default_state == ACTIVE:
                        exp_cycle, exp_default = default_cycle_id, True
                    else:
                        # Every present level is inactive (or absent), and the
                        # default (if any) is inactive → no active cycle matches.
                        exp_cycle, exp_default = None, False

                    expected[staff.id] = (
                        exp_cycle,
                        exp_default,
                        branch_location_id,
                        employment_type,
                    )

                await session.flush()

                # --- Batch resolver: resolves the whole page in memory. ---
                batch = await resolve_pay_cycles_for_staff_batch(
                    session, org_id=org_id, staff_members=staff_list
                )

                for staff in staff_list:
                    exp_cycle, exp_default, branch_location_id, employment_type = (
                        expected[staff.id]
                    )
                    resolved = batch.get(staff.id)

                    if exp_cycle is None:
                        assert resolved is None, (
                            f"batch expected None (all matching levels inactive) "
                            f"but got {resolved.cycle.id if resolved else None}"
                        )
                    else:
                        assert resolved is not None, (
                            f"batch returned None but expected active cycle "
                            f"{exp_cycle}"
                        )
                        assert resolved.cycle.id == exp_cycle, (
                            f"batch resolved to {resolved.cycle.id} but expected "
                            f"{exp_cycle} (inactive level should have been skipped)"
                        )
                        assert resolved.cycle.active is True, (
                            "batch resolved to an INACTIVE cycle — inactive cycles "
                            "must be excluded at every level (REQ 4.5)"
                        )
                        assert resolved.is_default is exp_default, (
                            f"batch is_default={resolved.is_default} but expected "
                            f"{exp_default}"
                        )

                    # --- Single resolver agrees (caller supplies branch + type). ---
                    single = await resolve_pay_cycle_for_staff(
                        session,
                        org_id=org_id,
                        staff_id=staff.id,
                        branch_id=branch_location_id,
                        employment_type=employment_type,
                    )
                    if exp_cycle is None:
                        assert single is None, (
                            f"single expected None but got "
                            f"{single.id if single else None}"
                        )
                    else:
                        assert single is not None and single.id == exp_cycle, (
                            f"single resolved to {single.id if single else None} "
                            f"but expected {exp_cycle}"
                        )
                        assert single.active is True, (
                            "single resolved to an INACTIVE cycle — inactive "
                            "cycles must be excluded at every level (REQ 4.5)"
                        )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2: Inactive cycles are excluded at every level.
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
    staff_configs=st.lists(_staff_config, min_size=1, max_size=5),
    emptype_state=st.lists(_level_state, min_size=3, max_size=3),
    all_state=_level_state,
    default_state=_level_state,
)
def test_inactive_cycles_excluded_at_every_level(
    staff_configs: list[tuple[int, int, int]],
    emptype_state: list[int],
    all_state: int,
    default_state: int,
):
    """Property 2: Inactive cycles are excluded at every level.

    # Feature: per-staff-pay-cycle, Property 2

    Each resolution level (staff, employment_type, branch, all, default) may
    point at an active cycle, an inactive cycle, or be absent. Resolution must
    exclude inactive cycles at **every** level: an assignment to an inactive
    cycle is skipped and resolution falls through to the next level, returning
    the cycle from the first **active** level (or ``None`` when no active level
    matches). The resolver never returns an inactive cycle, and the single-staff
    and batch resolvers agree.

    **Validates: Requirements 4.5**
    """
    asyncio.run(
        _run_example(staff_configs, emptype_state, all_state, default_state)
    )
