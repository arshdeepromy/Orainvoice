"""Property-based test for default-cycle fallback (Task 3.3).

Feature: per-staff-pay-cycle, Property 3: Fallback to default when no specific
match.

Exercises ``resolve_pay_cycle_for_staff`` and
``resolve_pay_cycles_for_staff_batch`` (Decision 3 / Decision 4) against the real
dev Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_pay_cycle_resolution_priority_property.py`` and
``tests/test_pay_cycle_staff_assignment_invariant_property.py``.

For each example we seed one organisation with a batch of staff members for whom
**no** assignment matches at any specific level (staff, employment_type, branch,
or ``all``). To make this a meaningful test rather than an empty one, the org may
also carry *distractor* assignments and extra active cycles that are deliberately
constructed to never match our staff:

- staff-level assignments targeting fresh random uuids (not our staff);
- branch-level assignments targeting fresh random uuids (locations none of our
  staff are assigned to);
- employment_type assignments only for the employment types **none** of our
  staff actually have;
- spare active, non-default cycles with no assignment at all.

No ``all`` assignment is ever created, because an ``all`` assignment matches every
staff member and would defeat the "no specific match" precondition.

We then assert the fallback behaviour:

- WHEN an active Default_Cycle exists, every staff member resolves to it with
  ``is_default=True`` (REQ 4.3, 5.2, 9.1, 9.3); and
- WHEN no Default_Cycle exists, every staff member resolves to ``None``
  (REQ 4.6, 5.3).

The single-staff resolver and the batch resolver are asserted to agree, since the
design re-expresses the single resolver as a thin wrapper over the same priority
logic.

The whole generated state runs inside one transaction that is rolled back at the
end of every example, so the test leaves no rows behind. A fresh async engine is
created per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 4.3, 4.6, 5.2, 5.3, 9.1, 9.3

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (the dev DB runs on ``localhost:5434``).
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


# ---------------------------------------------------------------------------
# Generation strategy.
# ---------------------------------------------------------------------------

# Per-staff config: which employment type the staff member has, and whether the
# staff member is given a (unique) location assignment so the batch resolver
# derives a branch for them. Neither knob can produce a match because all
# distractor assignments deliberately target other ids / unused types.
_staff_config = st.tuples(
    st.integers(min_value=0, max_value=len(_EMPLOYMENT_TYPES) - 1),
    st.booleans(),  # has_location
)


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
) -> uuid.UUID:
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
    return cycle.id


async def _run_example(
    staff_configs: list[tuple[int, bool]],
    default_present: bool,
    distractor_staff: bool,
    distractor_branch: bool,
    distractor_emptype: bool,
    spare_cycles: int,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = SubscriptionPlan(
                    name=f"paycycle_def_plan_{uuid.uuid4().hex[:8]}",
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=f"paycycle_def_org_{uuid.uuid4().hex[:8]}",
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    locale="en",
                    settings={},
                )
                session.add(org)
                await session.flush()
                org_id = org.id

                # --- Optional active default cycle. ---
                default_cycle_id: uuid.UUID | None = None
                if default_present:
                    default_cycle_id = await _new_cycle(
                        session, org_id=org_id, label="default", is_default=True
                    )

                # --- Spare active cycles with NO assignment. These must never be
                # picked: the resolver only returns a cycle that an assignment (or
                # the default flag) points at. ---
                for _ in range(spare_cycles):
                    await _new_cycle(session, org_id=org_id, label="spare")

                # --- Staff members (no matching assignment at any level). ---
                staff_list: list[StaffMember] = []
                # staff.id -> (employment_type, branch_location_id | None)
                staff_meta: dict[uuid.UUID, tuple[str, uuid.UUID | None]] = {}
                used_types: set[int] = set()

                for emp_index, has_location in staff_configs:
                    employment_type = _EMPLOYMENT_TYPES[emp_index]
                    used_types.add(emp_index)
                    staff = StaffMember(
                        org_id=org_id,
                        name="Default Fallback Staff",
                        first_name="Default",
                        employment_type=employment_type,
                        is_active=True,
                    )
                    session.add(staff)
                    await session.flush()
                    staff_list.append(staff)

                    branch_location_id: uuid.UUID | None = None
                    if has_location:
                        branch_location_id = uuid.uuid4()
                        session.add(
                            StaffLocationAssignment(
                                staff_id=staff.id, location_id=branch_location_id
                            )
                        )

                    staff_meta[staff.id] = (employment_type, branch_location_id)

                # --- Distractor assignments that cannot match our staff. ---
                # A distractor cycle is active but assigned to a target none of
                # our staff have, so resolution must NOT pick it up.
                if distractor_staff:
                    cid = await _new_cycle(session, org_id=org_id, label="dis_staff")
                    session.add(
                        PayCycleAssignment(
                            org_id=org_id,
                            pay_cycle_id=cid,
                            target_type="staff",
                            target_id=uuid.uuid4(),  # not one of our staff
                        )
                    )

                if distractor_branch:
                    cid = await _new_cycle(session, org_id=org_id, label="dis_branch")
                    session.add(
                        PayCycleAssignment(
                            org_id=org_id,
                            pay_cycle_id=cid,
                            target_type="branch",
                            target_id=uuid.uuid4(),  # a location none of our staff have
                        )
                    )

                if distractor_emptype:
                    # Only assign employment types that NONE of our staff have, so
                    # the employment_type level cannot match.
                    unused_types = [
                        t for t in range(len(_EMPLOYMENT_TYPES)) if t not in used_types
                    ]
                    for t in unused_types:
                        cid = await _new_cycle(
                            session, org_id=org_id, label=f"dis_emptype{t}"
                        )
                        session.add(
                            PayCycleAssignment(
                                org_id=org_id,
                                pay_cycle_id=cid,
                                target_type="employment_type",
                                target_id=employment_type_target_id(
                                    _EMPLOYMENT_TYPES[t]
                                ),
                            )
                        )

                await session.flush()

                # --- Batch resolver. ---
                batch = await resolve_pay_cycles_for_staff_batch(
                    session, org_id=org_id, staff_members=staff_list
                )

                for staff in staff_list:
                    employment_type, branch_location_id = staff_meta[staff.id]
                    resolved = batch.get(staff.id)

                    if default_present:
                        # REQ 4.3, 5.2, 9.1, 9.3: falls back to the active default
                        # with is_default=True.
                        assert resolved is not None, (
                            "batch expected the default cycle but got None"
                        )
                        assert resolved.cycle.id == default_cycle_id, (
                            f"batch resolved to {resolved.cycle.id} but expected "
                            f"the default {default_cycle_id}"
                        )
                        assert resolved.is_default is True, (
                            "batch is_default must be True for a default fallback"
                        )
                    else:
                        # REQ 4.6, 5.3: no default => no resolved cycle.
                        assert resolved is None, (
                            f"batch expected None but got "
                            f"{resolved.cycle.id if resolved else None}"
                        )

                    # --- Single resolver agrees (caller supplies branch + type). ---
                    single = await resolve_pay_cycle_for_staff(
                        session,
                        org_id=org_id,
                        staff_id=staff.id,
                        branch_id=branch_location_id,
                        employment_type=employment_type,
                    )
                    if default_present:
                        assert single is not None and single.id == default_cycle_id, (
                            f"single resolved to {single.id if single else None} "
                            f"but expected the default {default_cycle_id}"
                        )
                    else:
                        assert single is None, (
                            f"single expected None but got "
                            f"{single.id if single else None}"
                        )
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3: Fallback to default when no specific match.
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
    default_present=st.booleans(),
    distractor_staff=st.booleans(),
    distractor_branch=st.booleans(),
    distractor_emptype=st.booleans(),
    spare_cycles=st.integers(min_value=0, max_value=3),
)
def test_fallback_to_default_when_no_specific_match(
    staff_configs: list[tuple[int, bool]],
    default_present: bool,
    distractor_staff: bool,
    distractor_branch: bool,
    distractor_emptype: bool,
    spare_cycles: int,
):
    """Property 3: Fallback to default when no specific match.

    # Feature: per-staff-pay-cycle, Property 3

    Given staff members for whom no assignment matches at the staff,
    employment_type, branch, or ``all`` level (only deliberately non-matching
    distractor assignments and unassigned spare cycles exist), resolution falls
    back to the org Default_Cycle: when an active default exists every staff
    resolves to it with ``is_default=True``; when no default exists every staff
    resolves to ``None``. The single-staff resolver and the batch resolver agree.

    **Validates: Requirements 4.3, 4.6, 5.2, 5.3, 9.1, 9.3**
    """
    asyncio.run(
        _run_example(
            staff_configs,
            default_present,
            distractor_staff,
            distractor_branch,
            distractor_emptype,
            spare_cycles,
        )
    )
