"""Property-based test for atomic rejection of an invalid/inactive cycle (Task 6.1).

Feature: per-staff-pay-cycle, Property 6: Invalid or inactive cycle is rejected
atomically.

Exercises ``StaffService.create_staff`` / ``StaffService.update_staff`` against
the real dev Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_pay_cycle_staff_assignment_invariant_property.py``.

REQ 2.4 / 2.5 require that when the selected ``pay_cycle_id`` is invalid — it
belongs to another organisation / does not exist (``pay_cycle_not_found``) or
refers to an inactive cycle (``pay_cycle_inactive``) — the staff service rejects
the **entire** operation: it must NOT create or modify the staff member, and it
must NOT create a staff-level assignment.

Proving genuine atomicity (not just "the test transaction rolled back") requires
distinguishing rows that must SURVIVE from rows that must NOT persist. We do that
with a SAVEPOINT that mirrors the request-transaction boundary of
``get_db_session`` (which commits only on a clean return and rolls back on a
raised exception):

- An **outer** transaction seeds the org, its cycles, and (for the update case)
  the staff member. This data must survive the operation-under-test.
- The create/update call runs inside ``session.begin_nested()`` (a SAVEPOINT).
  When the service raises ``PayCycleValidationError`` the savepoint is rolled
  back automatically — exactly as the real request transaction would roll back.
- After the savepoint rolls back we assert, **within the still-open outer
  transaction** (so the seed is visible), that no staff row was created (create
  case), the seeded staff member is unmodified (update case), and no staff-level
  assignment persists.
- The whole outer transaction is rolled back at the end of every example, so the
  test leaves no rows behind.

A fresh async engine is created per example because asyncpg connections are bound
to the event loop ``asyncio.run`` creates — exactly like the reference DB-backed
property tests in this repo.

Validates: Requirements 2.4, 2.5

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (the dev DB is ``localhost:5434``).
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
# tests/test_pay_cycle_staff_assignment_invariant_property.py).
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
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.staff.service import StaffService
from app.modules.timesheets.pay_cycles import (
    PayCycle,
    PayCycleAssignment,
    PayCycleValidationError,
)


# The kinds of invalid cycle id a request might carry. All three must be
# rejected atomically; "wrong_org" and "nonexistent" map to
# ``pay_cycle_not_found`` (REQ 2.4), "inactive" maps to ``pay_cycle_inactive``
# (REQ 2.5).
_BAD_KINDS = ("wrong_org", "nonexistent", "inactive")


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


async def _seed(session: AsyncSession):
    """Seed two orgs with cycles. Returns the ids the test needs.

    Org A gets one active default cycle and one inactive cycle. Org B gets one
    active cycle (used to exercise the wrong-org rejection path). Flush only —
    the caller rolls everything back.
    """
    async def _make_org() -> uuid.UUID:
        plan = SubscriptionPlan(
            name=f"paycycle_atomic_plan_{uuid.uuid4().hex[:8]}",
            monthly_price_nzd=0,
            user_seats=5,
            storage_quota_gb=1,
            carjam_lookups_included=0,
            enabled_modules=[],
        )
        session.add(plan)
        await session.flush()
        org = Organisation(
            name=f"paycycle_atomic_org_{uuid.uuid4().hex[:8]}",
            plan_id=plan.id,
            status="active",
            storage_quota_gb=1,
            locale="en",
            settings={},
        )
        session.add(org)
        await session.flush()
        return org.id

    org_a = await _make_org()
    org_b = await _make_org()

    def _make_cycle(org_id: uuid.UUID, *, is_default: bool, active: bool) -> PayCycle:
        return PayCycle(
            org_id=org_id,
            name=f"Cycle {uuid.uuid4().hex[:6]}",
            frequency="fortnightly",
            anchor_date=date(2026, 1, 5),
            pay_date_offset_days=3,
            is_default=is_default,
            active=active,
        )

    a_active = _make_cycle(org_a, is_default=True, active=True)
    a_inactive = _make_cycle(org_a, is_default=False, active=False)
    b_active = _make_cycle(org_b, is_default=True, active=True)
    session.add_all([a_active, a_inactive, b_active])
    await session.flush()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "a_inactive_cycle": a_inactive.id,
        "b_active_cycle": b_active.id,
    }


def _bad_cycle_id(seed: dict, bad_kind: str) -> uuid.UUID:
    if bad_kind == "wrong_org":
        return seed["b_active_cycle"]
    if bad_kind == "inactive":
        return seed["a_inactive_cycle"]
    # nonexistent
    return uuid.uuid4()


async def _count_staff(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(StaffMember)
                .where(StaffMember.org_id == org_id)
            )
        ).scalar_one()
    )


async def _count_staff_assignments(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(PayCycleAssignment)
                .where(
                    PayCycleAssignment.org_id == org_id,
                    PayCycleAssignment.target_type == "staff",
                )
            )
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    op: str,
    bad_kind: str,
    first_name: str,
    position: str,
    set_extra_fields: bool,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                seed = await _seed(session)
                org_a = seed["org_a"]
                svc = StaffService(session)
                bad_id = _bad_cycle_id(seed, bad_kind)

                if op == "create":
                    create_kwargs: dict = {
                        "first_name": first_name,
                        "last_name": "Reject",
                        "pay_cycle_id": bad_id,
                    }
                    if set_extra_fields:
                        create_kwargs["position"] = position
                    payload = StaffMemberCreate(**create_kwargs)

                    raised = False
                    try:
                        async with session.begin_nested():  # SAVEPOINT = request boundary
                            await svc.create_staff(org_a, payload)
                    except PayCycleValidationError:
                        raised = True

                    assert raised, (
                        f"create_staff must reject an invalid cycle "
                        f"(bad_kind={bad_kind!r})"
                    )

                    # Savepoint rolled back: re-read the persisted state.
                    session.expire_all()
                    # REQ 2.4/2.5: the staff member must NOT have been created.
                    assert await _count_staff(session, org_a) == 0, (
                        "rejected create must not persist any staff row "
                        f"(bad_kind={bad_kind!r})"
                    )
                    # ...and no staff-level assignment must persist.
                    assert await _count_staff_assignments(session, org_a) == 0, (
                        "rejected create must not persist a staff assignment "
                        f"(bad_kind={bad_kind!r})"
                    )

                else:  # update
                    # Seed a staff member in the OUTER transaction so it must
                    # survive the rejected update unmodified.
                    existing = await svc.create_staff(
                        org_a,
                        StaffMemberCreate(first_name="Before", position="orig"),
                    )
                    staff_id = existing.id
                    await session.flush()

                    payload = StaffMemberUpdate(
                        position=position,  # a real mutation that must roll back
                        pay_cycle_id=bad_id,
                    )

                    raised = False
                    try:
                        async with session.begin_nested():  # SAVEPOINT
                            await svc.update_staff(org_a, staff_id, payload)
                    except PayCycleValidationError:
                        raised = True

                    assert raised, (
                        f"update_staff must reject an invalid cycle "
                        f"(bad_kind={bad_kind!r})"
                    )

                    session.expire_all()
                    # The staff member still exists (only this one) ...
                    assert await _count_staff(session, org_a) == 1
                    # ... and is UNMODIFIED: the position change rolled back
                    # (REQ 2.4/2.5 "SHALL NOT modify the staff member").
                    reread = (
                        await session.execute(
                            select(StaffMember).where(StaffMember.id == staff_id)
                        )
                    ).scalar_one()
                    assert reread.position == "orig", (
                        "rejected update must not modify the staff member "
                        f"(bad_kind={bad_kind!r}); position={reread.position!r}"
                    )
                    # ... and no staff-level assignment persists.
                    assert await _count_staff_assignments(session, org_a) == 0, (
                        "rejected update must not persist a staff assignment "
                        f"(bad_kind={bad_kind!r})"
                    )
            finally:
                # Never persist — discard the whole seeded fixture.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 6: Invalid or inactive cycle is rejected atomically.
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
    bad_kind=st.sampled_from(_BAD_KINDS),
    # Randomised payload entropy so the input space is large enough for ≥100
    # distinct examples (the op × bad_kind grid alone is only 6 combinations).
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
    set_extra_fields=st.booleans(),
)
def test_invalid_or_inactive_cycle_rejected_atomically(
    op: str,
    bad_kind: str,
    first_name: str,
    position: str,
    set_extra_fields: bool,
):
    """Property 6: Invalid or inactive cycle is rejected atomically.

    # Feature: per-staff-pay-cycle, Property 6

    For both create and update, when the selected ``pay_cycle_id`` belongs to
    another org / does not exist (``pay_cycle_not_found``, REQ 2.4) or refers to
    an inactive cycle (``pay_cycle_inactive``, REQ 2.5), the staff service
    rejects the entire operation atomically: no staff row is created, an existing
    staff member is left unmodified, and no staff-level assignment persists.

    **Validates: Requirements 2.4, 2.5**
    """
    asyncio.run(_run_example(op, bad_kind, first_name, position, set_extra_fields))
