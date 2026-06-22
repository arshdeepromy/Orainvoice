"""Property-based test for clear→default resolution (Task 6.2).

Feature: per-staff-pay-cycle, Property 5: Clearing the cycle resolves to default.

Exercises ``StaffService.create_staff`` / ``StaffService.update_staff`` plus the
batch resolver ``resolve_pay_cycles_for_staff_batch`` against the real dev
Postgres database, mirroring the DB-backed Hypothesis pattern in
``tests/test_staff_pay_cycle_atomic_rejection_property.py``.

The property covers the two ways a staff member ends up with no staff-level
assignment and therefore resolves to the organisation's Default_Cycle:

- **clear-on-update (REQ 3.3):** a staff member is first assigned a specific
  (non-default) active cycle, then the cycle is *cleared* via an update with
  ``pay_cycle_id=None``. After clearing, the staff member's Resolved_Cycle must
  be the org Default_Cycle with ``is_default=True``.
- **create-with-no-cycle (REQ 2.3):** a staff member created without a cycle has
  no staff-level assignment, so it must resolve to the org Default_Cycle with
  ``is_default=True``.

Both paths run inside a single OUTER transaction that seeds the org and its
cycles; the whole transaction is rolled back at the end of every example so the
test leaves no rows behind. A fresh async engine is created per example because
asyncpg connections are bound to the event loop ``asyncio.run`` creates — exactly
like the reference DB-backed property tests in this repo.

Validates: Requirements 3.3, 2.3

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
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
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


async def _seed(session: AsyncSession, *, non_default_count: int) -> dict:
    """Seed one org with an active default cycle + N non-default active cycles.

    Flush only — the caller rolls everything back at the end of the example.
    Returns the org id, the default cycle id, and the list of non-default
    (assignable) active cycle ids.
    """
    plan = SubscriptionPlan(
        name=f"paycycle_clear_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"paycycle_clear_org_{uuid.uuid4().hex[:8]}",
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

    default_cycle = _make_cycle(is_default=True)
    non_default_cycles = [_make_cycle(is_default=False) for _ in range(non_default_count)]
    session.add_all([default_cycle, *non_default_cycles])
    await session.flush()

    return {
        "org_id": org.id,
        "default_cycle_id": default_cycle.id,
        "non_default_cycle_ids": [c.id for c in non_default_cycles],
    }


async def _resolved(session: AsyncSession, org_id: uuid.UUID, staff) -> object:
    """Return the single staff member's ResolvedCycle via the batch resolver.

    The batch resolver issues its own fresh queries for the org's cycles and
    assignments within this (still-open) transaction, so it reflects the latest
    flushed state without needing to expire the staff object — expiring it would
    instead force a sync lazy-load of ``staff.id`` outside the async greenlet
    context when the resolver reads it.
    """
    resolved_map = await resolve_pay_cycles_for_staff_batch(
        session, org_id=org_id, staff_members=[staff]
    )
    return resolved_map[staff.id]


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    op: str,
    non_default_count: int,
    assign_index: int,
    first_name: str,
    employment_type: str,
) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                seed = await _seed(session, non_default_count=non_default_count)
                org_id = seed["org_id"]
                default_cycle_id = seed["default_cycle_id"]
                non_default_ids = seed["non_default_cycle_ids"]
                svc = StaffService(session)

                if op == "create_no_cycle":
                    # REQ 2.3: a staff member created with no cycle has no
                    # staff-level assignment, so it resolves to the default.
                    staff = await svc.create_staff(
                        org_id,
                        StaffMemberCreate(
                            first_name=first_name,
                            last_name="Default",
                            employment_type=employment_type,
                        ),
                    )
                    resolved = await _resolved(session, org_id, staff)

                else:  # clear_on_update
                    # Assign a specific (non-default) active cycle first ...
                    assigned_id = non_default_ids[assign_index % len(non_default_ids)]
                    staff = await svc.create_staff(
                        org_id,
                        StaffMemberCreate(
                            first_name=first_name,
                            last_name="Cleared",
                            employment_type=employment_type,
                            pay_cycle_id=assigned_id,
                        ),
                    )

                    # Sanity: before clearing, the staff resolves to the
                    # explicitly assigned (non-default) cycle, NOT the default.
                    before = await _resolved(session, org_id, staff)
                    assert before is not None
                    assert before.cycle.id == assigned_id, (
                        "assigned cycle should resolve before clearing; "
                        f"got {before.cycle.id} expected {assigned_id}"
                    )
                    assert before.is_default is False, (
                        "an explicit staff-level assignment must not be flagged "
                        "is_default"
                    )

                    # ... then CLEAR it via an update with pay_cycle_id=None
                    # (REQ 3.3). The explicit None is "set" in exclude_unset, so
                    # the tri-state update removes the assignment.
                    updated = await svc.update_staff(
                        org_id,
                        staff.id,
                        StaffMemberUpdate(pay_cycle_id=None),
                    )
                    assert updated is not None
                    resolved = await _resolved(session, org_id, updated)

                # REQ 3.3 / 2.3: after clearing (or never assigning), the staff
                # member's Resolved_Cycle is the org Default_Cycle, flagged as
                # the default.
                assert resolved is not None, (
                    f"staff must resolve to the org default (op={op!r})"
                )
                assert resolved.cycle.id == default_cycle_id, (
                    f"resolved cycle must be the org default (op={op!r}); "
                    f"got {resolved.cycle.id} expected {default_cycle_id}"
                )
                assert resolved.is_default is True, (
                    f"resolved cycle must be flagged is_default (op={op!r})"
                )
                assert resolved.cycle.is_default is True, (
                    f"resolved cycle row must have is_default=True (op={op!r})"
                )
            finally:
                # Never persist — discard the whole seeded fixture.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 5: Clearing the cycle resolves to default.
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
    op=st.sampled_from(["clear_on_update", "create_no_cycle"]),
    # 1-4 assignable non-default active cycles so the "which cycle was first
    # assigned" choice genuinely varies (REQ 3.3 — vary the first assignment).
    non_default_count=st.integers(min_value=1, max_value=4),
    assign_index=st.integers(min_value=0, max_value=9),
    first_name=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
    employment_type=st.sampled_from(["permanent", "casual", "fixed_term"]),
)
def test_clearing_cycle_resolves_to_default(
    op: str,
    non_default_count: int,
    assign_index: int,
    first_name: str,
    employment_type: str,
):
    """Property 5: Clearing the cycle resolves to default.

    # Feature: per-staff-pay-cycle, Property 5

    A staff member that has no staff-level assignment — either because an
    existing assignment was cleared via an update with ``pay_cycle_id=None``
    (REQ 3.3) or because it was created without a cycle (REQ 2.3) — resolves to
    the organisation's Default_Cycle, with the resolved cycle flagged
    ``is_default=True``. The first-assigned (non-default) cycle is varied across
    examples.

    **Validates: Requirements 3.3, 2.3**
    """
    asyncio.run(
        _run_example(op, non_default_count, assign_index, first_name, employment_type)
    )
