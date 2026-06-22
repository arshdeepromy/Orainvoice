"""Property-based test: Portal-user / org-user identity store separation.

# Feature: organisation-employee-portal, Property 10: Portal-user / org-user store separation

**Validates: Requirements 5.1**

Property 10 (design.md): the Employee Portal stores its login credentials
(``employee_portal_users``) in an identity store that is **disjoint** from the
global org-user (``users``) pool, such that:

* a Portal_User credential authenticates **only** via the employee-portal code
  path (a lookup keyed on ``employee_portal_users``) and **never** via the
  global org-user authentication path, and
* a global org-user credential **never** authenticates as a Portal_User —

even when the *same* email address exists as a row in **both** tables.

Task 10.1 (``POST /e/api/auth/login``) is not yet implemented, so there is no
portal login-resolution function to exercise. Per the task guidance we instead
assert the store separation at the **data / service layer**: the two resolution
code paths are structurally distinct table lookups, so a portal-user lookup can
never return a global ``users`` row and a global-user lookup can never return an
``employee_portal_users`` row.

The two resolution paths mirrored here are the *actual* code paths:

* **Portal path** — the documented login lookup (design "Web employee login"
  sequence): ``SELECT employee_portal_users WHERE org_id=? AND lower(email)=?
  AND is_active`` (the same predicate ``account_service.request_reset`` uses to
  resolve an active Portal_User).
* **Global org-user path** — ``authenticate_user`` in
  ``app/modules/auth/service.py`` resolves a credential with
  ``SELECT users WHERE email = ?`` and verifies with
  ``app.modules.auth.password.verify_password``.

This is a DB-backed Hypothesis property test against the transactional dev
Postgres, following the reference pattern in
``tests/test_employee_portal_password_length_property.py`` (a fresh async engine
per example, the full ORM import block so SQLAlchemy can configure mappers, an
org-name marker for cleanup, and an ``asyncio.run`` driver). >= 100 examples.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_password_length_property.py).
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
from app.modules.employee_portal import models as _emp_portal_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.auth import password as global_password
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_5_1_store_separation"


# ---------------------------------------------------------------------------
# Engine / cleanup helpers (mirror the reference DB-backed property test)
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
                "staff_members",
                "users",  # global org-users seeded for the collision scenarios
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
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


async def _seed_org(factory) -> uuid.UUID:
    """Seed one org (with a subscription plan) and return its id."""
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            org = Organisation(
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add(org)
            await session.flush()
            return org.id


# ---------------------------------------------------------------------------
# The two resolution code paths under test (faithful mirrors)
# ---------------------------------------------------------------------------


async def _resolve_portal_user(
    session: AsyncSession, org_id: uuid.UUID, email: str
) -> EmployeePortalUser | None:
    """Portal login lookup — keyed solely on ``employee_portal_users``.

    Mirrors the documented ``/e/api/auth/login`` resolution (design sequence)
    and ``account_service.request_reset``: an active Portal_User within the
    resolved org matched on the normalised (``lower``) email. This query never
    touches the global ``users`` table.
    """
    res = await session.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.org_id == org_id,
            func.lower(EmployeePortalUser.email) == email.strip().lower(),
            EmployeePortalUser.is_active.is_(True),
        )
    )
    return res.scalars().first()


async def _resolve_global_user(session: AsyncSession, email: str) -> User | None:
    """Global org-user login lookup — keyed solely on ``users``.

    Mirrors ``authenticate_user`` in ``app/modules/auth/service.py``:
    ``SELECT users WHERE email = ?``. This query never touches the
    ``employee_portal_users`` table.
    """
    res = await session.execute(select(User).where(User.email == email))
    return res.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def _seed_portal_user(
    factory, org_id: uuid.UUID, email: str, password: str
) -> uuid.UUID:
    """Seed an active Portal_User + its linked staff row; return the portal id."""
    async with factory() as session:
        async with session.begin():
            staff = StaffMember(
                org_id=org_id,
                name="Store Separation Staff",
                first_name="Store",
                last_name="Separation",
                email=email,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            user = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff.id,
                email=email.strip().lower(),
                password_hash=ep_auth.hash_password_sync(password),
                is_active=True,
            )
            session.add(user)
            await session.flush()
            return user.id


async def _seed_global_user(
    factory, org_id: uuid.UUID, email: str, password: str
) -> uuid.UUID:
    """Seed a global org-user (``users`` row); return its id."""
    async with factory() as session:
        async with session.begin():
            user = User(
                org_id=org_id,
                email=email,
                role="org_admin",
                password_hash=global_password.hash_password_sync(password),
                is_active=True,
                is_email_verified=True,
            )
            session.add(user)
            await session.flush()
            return user.id


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# ASCII-only, kept <= 40 chars so the global hasher (raw bcrypt, 72-byte limit)
# never rejects a generated password. A "x" prefix guarantees length >= 1.
_password_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=8,
    max_size=40,
)

# Local-part of an email — lowercase alnum so storage normalisation is a no-op
# and the same generated value keys identically in both tables.
_local_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=3,
    max_size=20,
)

_scenario_strategy = st.sampled_from(["portal_only", "collide", "global_only"])


def _unique_email(local: str) -> str:
    """Make a generated local-part globally unique (``users.email`` is UNIQUE)."""
    return f"{local}-{uuid.uuid4().hex[:10]}@example.com"


async def _run_example(scenario: str, local: str, pw_a: str, pw_b: str) -> None:
    """Seed one of the three scenarios and assert the disjoint-store invariants."""
    engine, factory = await _make_engine_and_factory()
    try:
        org_id = await _seed_org(factory)
        email = _unique_email(local)

        # Ensure the two passwords are genuinely distinct so a cross-store
        # credential mix-up could not coincidentally verify.
        portal_pw = "P!" + pw_a
        global_pw = "G@" + pw_b

        portal_id: uuid.UUID | None = None
        global_id: uuid.UUID | None = None

        if scenario in ("portal_only", "collide"):
            portal_id = await _seed_portal_user(factory, org_id, email, portal_pw)
        if scenario in ("collide", "global_only"):
            global_id = await _seed_global_user(factory, org_id, email, global_pw)

        async with factory() as session:
            portal_hit = await _resolve_portal_user(session, org_id, email)
            global_hit = await _resolve_global_user(session, email)

            # ---- Structural type disjointness: each path only ever yields
            # rows from its own table. ----
            if portal_hit is not None:
                assert isinstance(portal_hit, EmployeePortalUser)
            if global_hit is not None:
                assert isinstance(global_hit, User)

            if scenario == "portal_only":
                # The portal credential resolves only via the portal path...
                assert portal_hit is not None and portal_hit.id == portal_id
                assert ep_auth.verify_password_sync(portal_pw, portal_hit.password_hash)
                # ...and has NO presence in the global org-user store, so it can
                # never authenticate at /api/v*/auth (no row → no credential).
                assert global_hit is None

            elif scenario == "global_only":
                # A global org-user credential never resolves as a Portal_User:
                # the portal path finds nothing for that email.
                assert portal_hit is None
                # The global user exists and verifies on its own path only.
                assert global_hit is not None and global_hit.id == global_id
                assert global_password.verify_password_sync(
                    global_pw, global_hit.password_hash
                )

            else:  # "collide" — the SAME email exists in BOTH tables.
                assert portal_hit is not None and portal_hit.id == portal_id
                assert global_hit is not None and global_hit.id == global_id

                # Disjoint identities: different rows, different PK namespaces.
                assert portal_hit.id != global_hit.id

                # The portal credential authenticates only against the portal
                # row, and does NOT authenticate the global org-user.
                assert ep_auth.verify_password_sync(portal_pw, portal_hit.password_hash)
                assert not global_password.verify_password_sync(
                    portal_pw, global_hit.password_hash
                )

                # The global credential authenticates only against the global
                # row, and does NOT authenticate the Portal_User.
                assert global_password.verify_password_sync(
                    global_pw, global_hit.password_hash
                )
                assert not ep_auth.verify_password_sync(
                    global_pw, portal_hit.password_hash
                )

            # ---- Cross-table id disjointness (the core "separate identity
            # store" structural fact): an id from one store never appears in
            # the other store's table. ----
            if portal_id is not None:
                cross = await session.execute(
                    select(User.id).where(User.id == portal_id)
                )
                assert cross.first() is None, (
                    "a portal-user id must never exist in the global users table"
                )
            if global_id is not None:
                cross = await session.execute(
                    select(EmployeePortalUser.id).where(
                        EmployeePortalUser.id == global_id
                    )
                )
                assert cross.first() is None, (
                    "a global-user id must never exist in employee_portal_users"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    scenario=_scenario_strategy,
    local=_local_strategy,
    pw_a=_password_strategy,
    pw_b=_password_strategy,
)
def test_portal_and_org_user_stores_are_disjoint(
    scenario: str, local: str, pw_a: str, pw_b: str
) -> None:
    """Property 10: ``employee_portal_users`` and ``users`` are disjoint stores.

    A Portal_User credential resolves only via the employee-portal path and
    never as a global org-user; a global org-user credential never resolves as
    a Portal_User — even when the same email exists in both tables.

    **Validates: Requirements 5.1**
    """
    asyncio.run(_run_example(scenario, local, pw_a, pw_b))


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
