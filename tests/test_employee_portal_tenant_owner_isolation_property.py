"""Property-based test: Employee Portal tenant and owner isolation.

# Feature: organisation-employee-portal, Property 19: Tenant and owner isolation

**Validates: Requirements 7.1, 7.5, 16.3, 16.4**

Property 19 (design.md): *For any* authenticated Employee Portal data request,
every record returned belongs to **both** the session's organisation **and**
the session's linked staff member; a request for any record outside that scope
is denied with a not-found/forbidden response that returns **no fields** of the
record and **does not disclose its existence**.

The authenticated data surface under test is the real route function
``app.modules.employee_portal.router.profile`` (task 11.3) — the MVP profile
view. It is session-gated via :func:`require_portal_session`, which validates
the ``emp_portal_session`` cookie, sets the RLS ``app.current_org_id`` GUC from
the **session row's** ``org_id`` (server-trusted, R16.3), and exposes the
session's linked ``staff_id``. ``profile`` then scopes its read to *both* the
session's ``staff_id`` **and** ``org_id`` (own record only, R7.1) so a
foreign/other-org id can never resolve — it returns ``409 not_linked`` with no
staff-scoped fields and a body that is byte-for-byte identical whether or not a
matching staff row exists in some other org (R7.5, R16.4 — no existence signal).

The ``GET /e/api/roster`` endpoint (task 11.4) shares the same isolation
contract — own roster only, scoped to the session's ``staff_id`` + ``org_id``.
This test seeds schedule entries for several staff across two orgs and asserts
that the roster returned for the session's staff belongs to *both* the session's
org and its own staff (never another staff in the same org, never another org's
staff). The roster call is guarded by ``getattr`` so the profile isolation
property is still fully exercised even if the roster route is absent.

To exercise the property we seed **two** portal-enabled orgs:

- **org 1** — staff A (the session owner) + staff B (another staff, same org),
  each with its own active Portal_User and several ``schedule_entries``.
- **org 2** — staff D (another org's staff) with its own Portal_User and
  schedule entries.

For each generated scenario we then:

- **own** — mint a real session for staff A's Portal_User and resolve it through
  the genuine :func:`require_portal_session` dependency (which sets RLS from the
  session and yields the real :class:`EmployeePortalSessionCtx`). Assert
  ``profile`` returns **staff A's own** record (its ``staff_id``), belonging to
  both org 1 and staff A — never staff B's or staff D's. If the roster route
  exists, assert every roster entry returned belongs to org 1 **and** staff A.
- **cross_org** — construct a context whose ``org_id`` is org 1 (the session's
  org) but whose ``staff_id`` points at staff D **in another org**. Set RLS to
  org 1 (as the dependency would) and assert ``profile`` denies with
  ``409 not_linked``, returning no record fields. Assert the denial is
  byte-for-byte identical to the denial for a **random non-existent** staff id,
  proving no existence signal (R16.4).
- **not_linked** — construct a context with ``staff_id`` unset (the Portal_User
  has no linked staff, R7.7) and assert ``profile`` denies with
  ``409 not_linked`` and no fields.

This is a DB-backed Hypothesis test against the transactional dev Postgres,
mirroring the established pattern in
``tests/test_employee_portal_login_resolution_property.py``: a fresh async
engine per example (asyncpg connections are bound to the loop ``asyncio.run``
creates), the full ORM import block, an org-name marker for orphan cleanup, and
an ``asyncio.run`` driver. The route is invoked directly with a seeded async
session; assertions re-read the committed state.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_login_resolution_property.py).
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
from app.modules.employee_portal import models as _emp_portal_models  # noqa: F401

from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal import router as portal_router
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.employee_portal.services import session_service
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P19_tenant_owner_isolation"

_SESSION_COOKIE_NAME = "emp_portal_session"

# The three authenticated-data scenarios exercised by the property.
_SCENARIOS = ["own", "cross_org", "not_linked"]


# ---------------------------------------------------------------------------
# Engine / cleanup helpers (fresh engine per example).
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


async def _cleanup(factory) -> None:
    """Delete every row created by the seeder (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in (
                "employee_portal_audit_log",
                "employee_portal_sessions",
                "employee_portal_users",
                "schedule_entries",
                "staff_members",
            ):
                await session.execute(
                    sa_text(f"DELETE FROM {tbl} WHERE org_id IN ({org_subq})"),
                    params,
                )
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name LIKE :marker"),
                {"marker": f"{_ORG_MARKER}_plan%"},
            )


def _valid_slug(prefix: str) -> str:
    """Build a globally-unique, format-valid slug (``^[a-z0-9]+(-[a-z0-9]+)*$``)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def _seed(factory, *, password_hash: str, n_entries: int, local: str) -> dict:
    """Seed two portal-enabled orgs with staff, Portal_Users, and schedule rows.

    org 1: staff A (session owner) + staff B (another staff, same org).
    org 2: staff D (another org's staff).
    Each staff gets ``n_entries`` ``schedule_entries`` rows in its OWN org.

    ``local`` seeds the generated email identifiers so each example is a fresh,
    independent universe; the isolation property must hold regardless.

    Returns the ids needed to drive and assert on the isolation property.
    """
    uniq = f"{local}-{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan_{uuid.uuid4().hex[:8]}",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            org1 = Organisation(
                name=f"{_ORG_MARKER}_1_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=_valid_slug("epp-iso-1"),
                settings={"employee_portal_enabled": True},
            )
            org2 = Organisation(
                name=f"{_ORG_MARKER}_2_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=_valid_slug("epp-iso-2"),
                settings={"employee_portal_enabled": True},
            )
            session.add_all([org1, org2])
            await session.flush()

            staff_a = StaffMember(
                org_id=org1.id, name="Isolation Staff A", first_name="IsoA",
                last_name="Staff", email=f"a-{uniq}@example.com",
                is_active=True,
            )
            staff_b = StaffMember(
                org_id=org1.id, name="Isolation Staff B", first_name="IsoB",
                last_name="Staff", email=f"b-{uniq}@example.com",
                is_active=True,
            )
            staff_d = StaffMember(
                org_id=org2.id, name="Isolation Staff D", first_name="IsoD",
                last_name="Staff", email=f"d-{uniq}@example.com",
                is_active=True,
            )
            session.add_all([staff_a, staff_b, staff_d])
            await session.flush()

            user_a = EmployeePortalUser(
                org_id=org1.id, staff_id=staff_a.id,
                email=f"ua-{uniq}@example.com",
                password_hash=password_hash, is_active=True,
            )
            user_b = EmployeePortalUser(
                org_id=org1.id, staff_id=staff_b.id,
                email=f"ub-{uniq}@example.com",
                password_hash=password_hash, is_active=True,
            )
            user_d = EmployeePortalUser(
                org_id=org2.id, staff_id=staff_d.id,
                email=f"ud-{uniq}@example.com",
                password_hash=password_hash, is_active=True,
            )
            session.add_all([user_a, user_b, user_d])
            await session.flush()

            base = datetime.now(timezone.utc).replace(microsecond=0)
            # Anchor entries to the current week's Monday so they land squarely
            # inside the roster window ([Monday, Monday+7d)); with n_entries <= 3
            # the Mon/Tue/Wed offsets are always within the week. Titles encode
            # the owning staff so ownership can be asserted on the response.
            today = base.date()
            monday = today - timedelta(days=today.weekday())
            week_base = datetime.combine(monday, time(9, 0), tzinfo=timezone.utc)
            for staff, org in ((staff_a, org1), (staff_b, org1), (staff_d, org2)):
                for i in range(n_entries):
                    start = week_base + timedelta(days=i)
                    session.add(
                        ScheduleEntry(
                            org_id=org.id,
                            staff_id=staff.id,
                            title=f"Shift {i} {staff.first_name}",
                            start_time=start,
                            end_time=start + timedelta(hours=8),
                            entry_type="job",
                            status="scheduled",
                        )
                    )

            return {
                "org1_id": org1.id,
                "org2_id": org2.id,
                "staff_a_id": staff_a.id,
                "staff_b_id": staff_b.id,
                "staff_d_id": staff_d.id,
                "user_a_id": user_a.id,
                "user_b_id": user_b.id,
                "user_d_id": user_d.id,
            }


def _fake_request(session_token: str | None = None) -> SimpleNamespace:
    """Minimal stand-in for the FastAPI ``Request`` the portal routes consume.

    ``require_portal_session`` reads ``request.cookies.get(...)``; downstream
    audit writers read ``request.client.host``.
    """
    cookies = {} if session_token is None else {_SESSION_COOKIE_NAME: session_token}
    return SimpleNamespace(
        cookies=cookies, client=SimpleNamespace(host="203.0.113.9")
    )


def _body(resp) -> dict:
    return json.loads(bytes(resp.body))


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(scenario: str, n_entries: int, local: str) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        # One bcrypt hash reused for every Portal_User (create_session never
        # verifies the password, and the ctx-based scenarios never log in).
        password_hash = ep_auth.hash_password_sync("isolation-fixture-password")
        seed = await _seed(
            factory, password_hash=password_hash, n_entries=n_entries, local=local
        )

        org1_id = seed["org1_id"]
        staff_a_id = seed["staff_a_id"]
        staff_b_id = seed["staff_b_id"]
        staff_d_id = seed["staff_d_id"]

        roster_fn = getattr(portal_router, "roster", None)

        if scenario == "own":
            await _run_own(factory, seed, roster_fn, n_entries)
        elif scenario == "cross_org":
            await _run_cross_org(factory, org1_id, staff_d_id)
        else:  # not_linked
            await _run_not_linked(factory, org1_id)
    finally:
        await _cleanup(factory)
        await engine.dispose()


async def _run_own(factory, seed: dict, roster_fn, n_entries: int) -> None:
    """Authenticated owner: own record only, scoped to session org + staff."""
    org1_id = seed["org1_id"]
    staff_a_id = seed["staff_a_id"]
    staff_b_id = seed["staff_b_id"]
    staff_d_id = seed["staff_d_id"]

    # Mint a real session for staff A's Portal_User, then resolve it through the
    # genuine dependency so RLS is set exactly as a real request would.
    async with factory() as session:
        async with session.begin():
            user_a = (
                await session.execute(
                    select(EmployeePortalUser).where(
                        EmployeePortalUser.id == seed["user_a_id"]
                    )
                )
            ).scalars().one()
            await _set_rls_org_id(session, str(org1_id))
            _sess, raw_token = await session_service.create_session(session, user_a)

    async with factory() as session:
        async with session.begin():
            ctx = await portal_router.require_portal_session(
                request=_fake_request(raw_token), db=session
            )
            # The session's context is bound to org 1 + staff A.
            assert ctx.org_id == org1_id, ctx
            assert ctx.staff_id == staff_a_id, ctx

            # --- profile: own record, belonging to BOTH org 1 AND staff A. ---
            prof_resp = await portal_router.profile(ctx=ctx, db=session)
            assert prof_resp.status_code == 200
            prof = _body(prof_resp)
            assert prof["staff_id"] == str(staff_a_id), prof
            # Never another staff in the same org, never another org's staff.
            assert prof["staff_id"] != str(staff_b_id), prof
            assert prof["staff_id"] != str(staff_d_id), prof

            # --- roster (own roster only): every entry returned belongs to BOTH
            #     the session's org AND its own staff; never B's (same org) or
            #     D's (other org) (R7.1, R16.4). Entries expose only display
            #     fields, so ownership is asserted via the staff-encoded title
            #     and the response's own staff_id. ---
            if roster_fn is not None:
                roster_resp = await roster_fn(ctx=ctx, week_start=None, db=session)
                assert roster_resp.status_code == 200
                payload = _body(roster_resp)
                # The roster belongs to the session's own staff (R7.1).
                assert payload["staff_id"] == str(staff_a_id), payload
                assert payload["staff_id"] != str(staff_b_id), payload
                assert payload["staff_id"] != str(staff_d_id), payload
                entries = payload["entries"]
                # Exactly staff A's in-week entries are returned — and only those.
                assert len(entries) == n_entries, payload
                for entry in entries:
                    title = entry.get("title") or ""
                    assert "IsoA" in title, entry
                    assert "IsoB" not in title, entry
                    assert "IsoD" not in title, entry


def _ctx(org_id, staff_id):
    """Build an EmployeePortalSessionCtx directly for the out-of-scope scenarios."""
    return portal_router.EmployeePortalSessionCtx(
        org_id=org_id,
        portal_user_id=uuid.uuid4(),
        staff_id=staff_id,
        email="iso-ctx@example.com",
        session_id=uuid.uuid4(),
        csrf_token="iso-ctx-csrf",
    )


async def _profile_denial(factory, ctx) -> dict:
    """Call ``profile`` with a constructed ctx; return the denial {status, detail}.

    Sets RLS from the ctx's org exactly as ``require_portal_session`` would, so
    the denial reflects the real RLS + application-predicate scoping.
    """
    async with factory() as session:
        async with session.begin():
            await _set_rls_org_id(session, str(ctx.org_id))
            try:
                resp = await portal_router.profile(ctx=ctx, db=session)
            except HTTPException as exc:
                return {"status": exc.status_code, "detail": exc.detail}
            # A success path here would be a property violation — surface it.
            return {"status": resp.status_code, "detail": _body(resp)}


async def _run_cross_org(factory, org1_id, staff_d_id) -> None:
    """ctx scoped to org 1 but pointing at another org's staff → denied, no leak."""
    # A context whose org is the session's org (org 1) but whose staff_id is a
    # staff member in ANOTHER org (staff D / org 2). The combined RLS + explicit
    # org predicate means the row never resolves → 409 not_linked, no fields.
    foreign = await _profile_denial(factory, _ctx(org1_id, staff_d_id))
    assert foreign["status"] == 409, foreign
    assert foreign["detail"].get("code") == "not_linked", foreign
    # No record fields are disclosed in the denial body.
    for leaked in ("first_name", "last_name", "name", "email", "phone",
                   "ird_number", "bank_account_number"):
        assert leaked not in foreign["detail"], foreign

    # No existence signal (R16.4): the denial for a real-but-foreign staff id is
    # byte-for-byte identical to the denial for a wholly non-existent staff id.
    nonexistent = await _profile_denial(factory, _ctx(org1_id, uuid.uuid4()))
    assert nonexistent == foreign, (foreign, nonexistent)


async def _run_not_linked(factory, org1_id) -> None:
    """ctx with no linked staff → 409 not_linked, no fields (R7.7, R7.5)."""
    denial = await _profile_denial(factory, _ctx(org1_id, None))
    assert denial["status"] == 409, denial
    assert denial["detail"].get("code") == "not_linked", denial
    for leaked in ("first_name", "last_name", "name", "email", "phone",
                   "ird_number", "bank_account_number"):
        assert leaked not in denial["detail"], denial


# ---------------------------------------------------------------------------
# Property 19: Tenant and owner isolation.
# ---------------------------------------------------------------------------


# Identifier seed for the generated emails — lowercase alnum so each example
# seeds a fresh, independent universe and Hypothesis explores a wide input space
# (≥100 examples). Mirrors the local-part strategy in the login-resolution test.
_local_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=3,
    max_size=20,
)


@settings(
    max_examples=105,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    scenario=st.sampled_from(_SCENARIOS),
    n_entries=st.integers(min_value=1, max_value=3),
    local=_local_strategy,
)
def test_tenant_and_owner_isolation(
    scenario: str, n_entries: int, local: str
) -> None:
    """Property 19: Tenant and owner isolation.

    # Feature: organisation-employee-portal, Property 19: Tenant and owner isolation

    Every record an authenticated portal request returns belongs to BOTH the
    session's org AND its linked staff member; an out-of-scope request is denied
    with no fields and no existence signal.

    **Validates: Requirements 7.1, 7.5, 16.3, 16.4**
    """
    asyncio.run(_run_example(scenario, n_entries, local))


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted example."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
