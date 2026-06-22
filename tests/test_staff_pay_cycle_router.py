"""Route tests for staff create/update with a pay cycle (Task 6.4).

Feature: per-staff-pay-cycle — Components → staff router (POST/PUT /api/v2/staff).

These tests exercise the actual route handlers
``app.modules.staff.router.create_staff`` / ``update_staff`` against the real
dev Postgres database (rather than the heavy-mock pattern in
``tests/test_staff_router.py``), so they genuinely cover the route's response
shape and its ``PayCycleValidationError`` → HTTP 422 mapping.

Why call the handler functions directly (instead of going through the full
ASGI app + auth + module middleware)? The established route-test convention in
this repo (see ``tests/test_staff_router.py``: ``get_pay_rate_history``,
``email_roster``) invokes the handler coroutine directly with a fake ``Request``
whose ``state`` carries the org/user context the middleware would normally set,
and patches ``ModuleService.is_enabled`` so the ``staff_management`` module gate
passes. We follow that same convention but back it with a real DB session so the
persistence assertions (a staff row + a staff-level assignment are created on
success; nothing persists on a 422 rejection) are meaningful.

Transaction handling mirrors the request-transaction boundary of
``get_db_session`` (which commits only on a clean return and rolls back on a
raised exception):

- A real outer transaction seeds the org + cycles (and, for the update cases,
  the staff member). This data must survive.
- For the **rejection** cases the handler call runs inside
  ``session.begin_nested()`` (a SAVEPOINT). When the handler raises
  ``HTTPException(422)`` the savepoint rolls back automatically — exactly as the
  real request transaction would — and we then assert, in the still-open outer
  transaction, that no staff row and no staff-level assignment persisted.
- For the **success** cases the handler runs against the outer session directly
  so its ``db.flush()`` / ``db.refresh()`` calls behave as in production; we
  assert the response body carries the resolved cycle and that the rows landed.
- Every example rolls the whole outer transaction back at the end, so the test
  leaves no rows behind.

A fresh async engine is created per test because asyncpg connections are bound
to the event loop ``asyncio.run`` creates — exactly like the reference DB-backed
tests in this repo.

Validates: Requirements 2.1, 2.2, 2.4, 2.5, 5.1

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (the dev DB is ``localhost:5434``). When Postgres is
  unreachable the tests skip rather than fail red.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, InterfaceError
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
from app.modules.staff.router import create_staff, update_staff
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.timesheets.pay_cycles import PayCycle, PayCycleAssignment


# Patch target for the module gate — the same target the existing route tests use.
_MODULE_GATE = "app.core.modules.ModuleService.is_enabled"


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


def _fake_request(org_id: uuid.UUID) -> SimpleNamespace:
    """A minimal ``Request`` stand-in.

    The staff handlers read ``request.state.org_id`` / ``user_id`` /
    ``client_ip`` and (for the onboarding-link branch, which we never trigger)
    ``request.headers``. A ``SimpleNamespace`` with a ``state`` and an empty
    ``headers`` dict is all that's exercised here.
    """
    return SimpleNamespace(
        state=SimpleNamespace(org_id=org_id, user_id=None, client_ip=None),
        headers={},
    )


async def _seed_plan(session: AsyncSession) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        name=f"paycycle_route_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()
    return plan


async def _seed_org(session: AsyncSession, plan: SubscriptionPlan) -> uuid.UUID:
    org = Organisation(
        name=f"paycycle_route_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()
    return org.id


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


async def _count_staff_assignments(
    session: AsyncSession, org_id: uuid.UUID, staff_id: uuid.UUID | None = None
) -> int:
    stmt = (
        select(func.count())
        .select_from(PayCycleAssignment)
        .where(
            PayCycleAssignment.org_id == org_id,
            PayCycleAssignment.target_type == "staff",
        )
    )
    if staff_id is not None:
        stmt = stmt.where(PayCycleAssignment.target_id == staff_id)
    return int((await session.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# Skip cleanly when the dev Postgres is not reachable.
# ---------------------------------------------------------------------------


def _run(coro_factory) -> None:
    try:
        asyncio.run(coro_factory())
    except (OperationalError, InterfaceError, ConnectionRefusedError, OSError) as exc:
        pytest.skip(f"dev Postgres not reachable for route DB test: {exc}")


# ===========================================================================
# POST /api/v2/staff — success (201-equivalent: returns the resolved cycle)
# ===========================================================================


async def _create_with_valid_cycle() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org_id = await _seed_org(session, plan)
                # A default active cycle + a separate active cycle to assign, so
                # the resolved cycle is unambiguously the chosen one and
                # is_default is False (staff-level assignment, REQ 5.1).
                await _seed_cycle(session, org_id=org_id, is_default=True)
                chosen = await _seed_cycle(session, org_id=org_id, is_default=False)

                request = _fake_request(org_id)
                payload = StaffMemberCreate(
                    first_name="Ada",
                    last_name="Create",
                    pay_cycle_id=chosen.id,
                )

                with patch(_MODULE_GATE, new_callable=AsyncMock, return_value=True):
                    resp = await create_staff(payload, request, db=session)

                # Response carries the resolved cycle (REQ 2.1, 5.1).
                assert resp.pay_cycle_id == chosen.id
                assert resp.pay_cycle_name == chosen.name
                assert resp.pay_cycle_is_default is False

                # The staff row + exactly one staff-level assignment persisted.
                assert await _count_staff(session, org_id) == 1
                assert (
                    await _count_staff_assignments(session, org_id, resp.id) == 1
                )
                cycle_id = (
                    await session.execute(
                        select(PayCycleAssignment.pay_cycle_id).where(
                            PayCycleAssignment.org_id == org_id,
                            PayCycleAssignment.target_type == "staff",
                            PayCycleAssignment.target_id == resp.id,
                        )
                    )
                ).scalars().first()
                assert cycle_id == chosen.id
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_create_staff_with_valid_cycle_returns_resolved_cycle():
    """POST with a valid pay_cycle_id returns the resolved cycle and persists
    a staff row + one staff-level assignment (REQ 2.1, 5.1)."""
    _run(_create_with_valid_cycle)


# ===========================================================================
# PUT /api/v2/staff/{id} — success (returns the resolved cycle)
# ===========================================================================


async def _update_with_valid_cycle() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                from app.modules.staff.service import StaffService

                plan = await _seed_plan(session)
                org_id = await _seed_org(session, plan)
                await _seed_cycle(session, org_id=org_id, is_default=True)
                chosen = await _seed_cycle(session, org_id=org_id, is_default=False)

                # Seed a staff member with NO cycle assignment first.
                svc = StaffService(session)
                existing = await svc.create_staff(
                    org_id, StaffMemberCreate(first_name="Grace", last_name="Update")
                )
                staff_id = existing.id
                await session.flush()
                assert await _count_staff_assignments(session, org_id, staff_id) == 0

                request = _fake_request(org_id)
                payload = StaffMemberUpdate(pay_cycle_id=chosen.id)

                with patch(_MODULE_GATE, new_callable=AsyncMock, return_value=True):
                    resp = await update_staff(
                        staff_id, payload, request, db=session
                    )

                # Response carries the resolved cycle (REQ 2.2, 5.1).
                assert resp.id == staff_id
                assert resp.pay_cycle_id == chosen.id
                assert resp.pay_cycle_name == chosen.name
                assert resp.pay_cycle_is_default is False

                # Exactly one staff-level assignment now exists, pointing at it.
                assert await _count_staff_assignments(session, org_id, staff_id) == 1
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_update_staff_with_valid_cycle_returns_resolved_cycle():
    """PUT with a valid pay_cycle_id returns the resolved cycle and persists
    exactly one staff-level assignment (REQ 2.2, 5.1)."""
    _run(_update_with_valid_cycle)


# ===========================================================================
# POST /api/v2/staff — 422 + rollback for invalid / inactive cycle
# ===========================================================================


async def _create_rejected(bad_kind: str) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                plan = await _seed_plan(session)
                org_id = await _seed_org(session, plan)
                await _seed_cycle(session, org_id=org_id, is_default=True)

                if bad_kind == "wrong_org":
                    other_org_id = await _seed_org(session, plan)
                    bad_cycle = await _seed_cycle(session, org_id=other_org_id)
                    bad_id = bad_cycle.id
                    expected_code = "pay_cycle_not_found"
                elif bad_kind == "inactive":
                    bad_cycle = await _seed_cycle(
                        session, org_id=org_id, active=False
                    )
                    bad_id = bad_cycle.id
                    expected_code = "pay_cycle_inactive"
                else:  # nonexistent
                    bad_id = uuid.uuid4()
                    expected_code = "pay_cycle_not_found"

                request = _fake_request(org_id)
                payload = StaffMemberCreate(
                    first_name="Rejected",
                    last_name="Create",
                    pay_cycle_id=bad_id,
                )

                excinfo = None
                with patch(_MODULE_GATE, new_callable=AsyncMock, return_value=True):
                    try:
                        async with session.begin_nested():  # SAVEPOINT = request boundary
                            await create_staff(payload, request, db=session)
                    except HTTPException as exc:
                        excinfo = exc

                assert excinfo is not None, (
                    f"create must reject bad cycle (bad_kind={bad_kind!r})"
                )
                assert excinfo.status_code == 422
                assert excinfo.detail == {"detail": expected_code}

                # Savepoint rolled back — nothing persisted (REQ 2.4, 2.5).
                session.expire_all()
                assert await _count_staff(session, org_id) == 0
                assert await _count_staff_assignments(session, org_id) == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bad_kind", ["wrong_org", "inactive", "nonexistent"])
def test_create_staff_invalid_cycle_returns_422_and_persists_nothing(bad_kind):
    """POST with a wrong-org / inactive / nonexistent pay_cycle_id returns 422
    and creates no staff row and no assignment (REQ 2.4, 2.5)."""
    _run(lambda: _create_rejected(bad_kind))


# ===========================================================================
# PUT /api/v2/staff/{id} — 422 + rollback for invalid / inactive cycle
# ===========================================================================


async def _update_rejected(bad_kind: str) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                from app.modules.staff.service import StaffService

                plan = await _seed_plan(session)
                org_id = await _seed_org(session, plan)
                await _seed_cycle(session, org_id=org_id, is_default=True)

                if bad_kind == "wrong_org":
                    other_org_id = await _seed_org(session, plan)
                    bad_cycle = await _seed_cycle(session, org_id=other_org_id)
                    bad_id = bad_cycle.id
                    expected_code = "pay_cycle_not_found"
                elif bad_kind == "inactive":
                    bad_cycle = await _seed_cycle(
                        session, org_id=org_id, active=False
                    )
                    bad_id = bad_cycle.id
                    expected_code = "pay_cycle_inactive"
                else:  # nonexistent
                    bad_id = uuid.uuid4()
                    expected_code = "pay_cycle_not_found"

                # Seed a staff member that must survive the rejected update
                # unmodified.
                svc = StaffService(session)
                existing = await svc.create_staff(
                    org_id,
                    StaffMemberCreate(first_name="Before", position="orig"),
                )
                staff_id = existing.id
                await session.flush()

                request = _fake_request(org_id)
                payload = StaffMemberUpdate(position="changed", pay_cycle_id=bad_id)

                excinfo = None
                with patch(_MODULE_GATE, new_callable=AsyncMock, return_value=True):
                    try:
                        async with session.begin_nested():  # SAVEPOINT
                            await update_staff(staff_id, payload, request, db=session)
                    except HTTPException as exc:
                        excinfo = exc

                assert excinfo is not None, (
                    f"update must reject bad cycle (bad_kind={bad_kind!r})"
                )
                assert excinfo.status_code == 422
                assert excinfo.detail == {"detail": expected_code}

                # Savepoint rolled back — staff unchanged, no assignment (REQ 2.4, 2.5).
                session.expire_all()
                assert await _count_staff(session, org_id) == 1
                reread = (
                    await session.execute(
                        select(StaffMember).where(StaffMember.id == staff_id)
                    )
                ).scalar_one()
                assert reread.position == "orig"
                assert await _count_staff_assignments(session, org_id, staff_id) == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bad_kind", ["wrong_org", "inactive", "nonexistent"])
def test_update_staff_invalid_cycle_returns_422_and_leaves_staff_unchanged(bad_kind):
    """PUT with a wrong-org / inactive / nonexistent pay_cycle_id returns 422,
    leaves the staff member unmodified, and creates no assignment (REQ 2.4, 2.5)."""
    _run(lambda: _update_rejected(bad_kind))
