"""Property-based test for the persisted-assignment round-trip (Task 6.3).

Feature: per-staff-pay-cycle, Property 7: Persisted assignment round-trips to
the response.

Exercises ``StaffService.create_staff`` / ``StaffService.update_staff`` against
the real dev Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_staff_pay_cycle_atomic_rejection_property.py``.

REQ 2.1 / 2.2 require that a chosen pay cycle is persisted as a staff-level
assignment on create / update, and REQ 5.1 requires the staff response to carry
that staff member's Resolved_Cycle id and name. Property 7 ties the two together:
the cycle that goes **in** on the form must be the cycle that comes back **out**
in the response — with ``pay_cycle_is_default=False`` because the staff member
matched at the (most specific) staff level, not via the org default — and a fresh
resolution (re-read) of the same persisted state must yield the identical answer.

How the round-trip is proved genuinely (chosen cycle in → same cycle out):

- A staff member is created (or created-then-updated) with a chosen **active,
  non-default** cycle. The chosen cycle is varied across examples so the property
  holds for whichever active cycle the user picks, never a fixed one.
- The response fields are computed exactly the way the staff router's
  ``_enrich_reporting_to`` / ``list_staff`` build them: validate the ORM row
  through ``StaffMemberResponse`` then overlay the three pay-cycle fields from
  ``resolve_pay_cycles_for_staff_batch`` (the service-write + resolver-read
  round-trip). We assert the built ``StaffMemberResponse`` reports the chosen
  cycle id + name and ``pay_cycle_is_default=False``.
- A **fresh resolution** then re-reads the persisted state: the session is
  expired, the staff member is re-loaded from the database, and the batch
  resolver is run again. The re-read must yield the same cycle id, name, and
  ``is_default=False`` — proving the assignment is durably persisted, not just an
  in-memory artefact of the write call.

Everything runs inside one outer transaction that is rolled back at the end of
every example, so the test leaves no rows behind. A fresh async engine is created
per example because asyncpg connections are bound to the event loop
``asyncio.run`` creates — exactly like the reference DB-backed property tests in
this repo.

Validates: Requirements 2.1, 2.2, 5.1

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (the dev DB is ``localhost:5434``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

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
# tests/test_staff_pay_cycle_atomic_rejection_property.py).
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
from app.modules.staff.models import StaffMember
from app.modules.staff.schemas import (
    StaffMemberCreate,
    StaffMemberResponse,
    StaffMemberUpdate,
)
from app.modules.staff.service import StaffService
from app.modules.timesheets.pay_cycles import (
    PayCycle,
    resolve_pay_cycles_for_staff_batch,
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


async def _seed(session: AsyncSession, *, num_active_cycles: int):
    """Seed one org with one active default cycle + ``num_active_cycles`` active
    NON-default cycles. Returns the org id and the ordered list of non-default
    active cycle ids (the candidates a user may choose). Flush only — the caller
    rolls everything back.
    """
    plan = SubscriptionPlan(
        name=f"paycycle_rt_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()
    org = Organisation(
        name=f"paycycle_rt_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()

    def _make_cycle(*, is_default: bool) -> PayCycle:
        return PayCycle(
            org_id=org.id,
            name=f"Cycle {uuid.uuid4().hex[:6]}",
            frequency="fortnightly",
            anchor_date=date(2026, 1, 5),
            pay_date_offset_days=3,
            is_default=is_default,
            active=True,
        )

    # One active default cycle so the org always HAS a default; the chosen
    # cycle must still win at the staff level with is_default=False.
    default_cycle = _make_cycle(is_default=True)
    non_default = [_make_cycle(is_default=False) for _ in range(num_active_cycles)]
    session.add_all([default_cycle, *non_default])
    await session.flush()

    return org.id, [c.id for c in non_default]


async def _resolved_response(
    session: AsyncSession, staff: StaffMember
) -> StaffMemberResponse:
    """Build the staff response the same way the router does.

    Validates the ORM row through ``StaffMemberResponse`` then overlays the three
    pay-cycle fields from ``resolve_pay_cycles_for_staff_batch`` — the exact
    population path used by ``_enrich_reporting_to`` / ``list_staff``.
    """
    data = StaffMemberResponse.model_validate(staff).model_dump()
    resolved_map = await resolve_pay_cycles_for_staff_batch(
        session, org_id=staff.org_id, staff_members=[staff],
    )
    resolved = resolved_map.get(staff.id)
    if resolved is not None:
        data["pay_cycle_id"] = resolved.cycle.id
        data["pay_cycle_name"] = resolved.cycle.name
        data["pay_cycle_is_default"] = resolved.is_default
    else:
        data["pay_cycle_id"] = None
        data["pay_cycle_name"] = None
        data["pay_cycle_is_default"] = False
    return StaffMemberResponse(**data)


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    op: str,
    num_active_cycles: int,
    chosen_offset: int,
    first_name: str,
    position: str,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, cycle_ids = await _seed(
                    session, num_active_cycles=num_active_cycles
                )
                # Vary the chosen cycle across examples (REQ 2.1/2.2 must hold
                # for whichever active cycle the user picks).
                chosen_id = cycle_ids[chosen_offset % len(cycle_ids)]
                # The chosen cycle's name, for the REQ 5.1 name assertion.
                chosen_name = (
                    await session.execute(
                        select(PayCycle.name).where(PayCycle.id == chosen_id)
                    )
                ).scalar_one()

                svc = StaffService(session)

                if op == "create":
                    staff = await svc.create_staff(
                        org_id,
                        StaffMemberCreate(
                            first_name=first_name,
                            last_name="RoundTrip",
                            position=position,
                            pay_cycle_id=chosen_id,
                        ),
                    )
                else:  # update
                    # Create WITHOUT a cycle (resolves to default), then update
                    # to the chosen cycle — proving the persisted-after-update
                    # assignment round-trips (REQ 2.2).
                    staff = await svc.create_staff(
                        org_id,
                        StaffMemberCreate(first_name=first_name, position="orig"),
                    )
                    await svc.update_staff(
                        org_id,
                        staff.id,
                        StaffMemberUpdate(
                            position=position,
                            pay_cycle_id=chosen_id,
                        ),
                    )
                    await session.flush()

                staff_id = staff.id

                # --- Round-trip #1: response built right after the write. ---
                resp = await _resolved_response(session, staff)
                assert resp.pay_cycle_id == chosen_id, (
                    f"{op}: response pay_cycle_id must equal the chosen cycle "
                    f"(chosen={chosen_id}, got={resp.pay_cycle_id})"
                )
                assert resp.pay_cycle_name == chosen_name, (
                    f"{op}: response pay_cycle_name must be the chosen cycle's "
                    f"name (expected={chosen_name!r}, got={resp.pay_cycle_name!r})"
                )
                assert resp.pay_cycle_is_default is False, (
                    f"{op}: a staff-level assignment must resolve with "
                    f"pay_cycle_is_default=False, not via the org default"
                )

                # --- Round-trip #2: fresh resolution after a real re-read. ---
                # Expire and re-load the staff member from the DB so resolution
                # runs against the persisted state, not the in-memory object the
                # write produced (proves durability, REQ 2.1/2.2/5.1).
                session.expire_all()
                reread = (
                    await session.execute(
                        select(StaffMember).where(StaffMember.id == staff_id)
                    )
                ).scalar_one()
                resp2 = await _resolved_response(session, reread)
                assert resp2.pay_cycle_id == chosen_id, (
                    f"{op}: re-read response pay_cycle_id must equal the chosen "
                    f"cycle (chosen={chosen_id}, got={resp2.pay_cycle_id})"
                )
                assert resp2.pay_cycle_name == chosen_name, (
                    f"{op}: re-read response pay_cycle_name must equal the "
                    f"chosen cycle's name"
                )
                assert resp2.pay_cycle_is_default is False, (
                    f"{op}: re-read must still resolve with "
                    f"pay_cycle_is_default=False"
                )
            finally:
                # Never persist — discard the whole seeded fixture.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 7: Persisted assignment round-trips to the response.
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
    op=st.sampled_from(["create", "update"]),
    num_active_cycles=st.integers(min_value=1, max_value=4),
    chosen_offset=st.integers(min_value=0, max_value=3),
    first_name=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
    position=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
)
def test_persisted_assignment_round_trips_to_response(
    op: str,
    num_active_cycles: int,
    chosen_offset: int,
    first_name: str,
    position: str,
):
    """Property 7: Persisted assignment round-trips to the response.

    # Feature: per-staff-pay-cycle, Property 7

    For both create and update, a chosen active non-default cycle is persisted as
    a staff-level assignment and surfaces in the staff response: the resolved
    ``pay_cycle_id`` equals the chosen cycle, ``pay_cycle_name`` is the chosen
    cycle's name, and ``pay_cycle_is_default`` is ``False`` (matched at the staff
    level). A fresh resolution after re-reading the staff member from the
    database yields the identical result, proving the assignment is durably
    persisted. The chosen cycle is varied across examples.

    **Validates: Requirements 2.1, 2.2, 5.1**
    """
    asyncio.run(
        _run_example(op, num_active_cycles, chosen_offset, first_name, position)
    )
