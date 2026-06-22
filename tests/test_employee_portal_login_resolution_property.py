"""Property-based test: Employee Portal single-organisation login resolution.

# Feature: organisation-employee-portal, Property 12: Single-organisation login resolution

**Validates: Requirements 6.3, 6.11**

Property 12 (design.md): *For any* login attempt carrying an org slug, the
``POST /e/api/auth/login`` endpoint resolves the Portal_User within **exactly**
the organisation that owns that slug and **never** authenticates a Portal_User
belonging to another org — even when the *same* email + password exists in two
different orgs. An unresolvable (unknown) slug yields a neutral
``404 portal_unavailable`` with **no session** established for any org.

The endpoint under test is the real route function
``app.modules.employee_portal.router.login`` (task 10.1). It:

1. resolves the org by ``normalise_slug(slug)`` against
   ``lower(organisations.slug)`` — unknown slug → neutral ``404
   portal_unavailable`` (R6.11, no enumeration);
2. requires ``employee_portal_enabled``;
3. sets the RLS ``app.current_org_id`` GUC from the *resolved* org;
4. looks up the active Portal_User by ``org_id`` + ``lower(email)`` and verifies
   the bcrypt password;
5. on success mints an ``employee_portal_sessions`` row scoped to that org and
   returns ``{portal_user_id, email, first_name, staff_id}``.

To exercise the cross-org isolation we seed **two** portal-enabled orgs (each
with its own slug) and seed the **same** email + password as an active
Portal_User in **both** orgs (each linked to its own staff member). For each
generated scenario we then:

- **org_a** — log in at org A's slug; assert the response authenticates org A's
  Portal_User (its ``portal_user_id`` / ``staff_id``) and never org B's, that a
  session row is created scoped to org A, and that **no** session exists for
  org B.
- **org_b** — symmetric: logging in at org B's slug authenticates only org B's
  Portal_User and creates a session scoped only to org B.
- **unknown** — log in at a slug that resolves to no org; assert a neutral
  ``404 portal_unavailable`` with no identity fields and **no** session created
  for either org.

This is a DB-backed Hypothesis test against the transactional dev Postgres,
mirroring the established pattern in
``tests/test_employee_portal_single_use_token_property.py`` and
``tests/test_employee_portal_session_invalidation_property.py``: a fresh async
engine per example (asyncpg connections are bound to the loop ``asyncio.run``
creates), the full ORM import block, an org-name marker for orphan cleanup, and
an ``asyncio.run`` driver. The route is invoked directly with a seeded async
session (wrapped in ``session.begin()`` so its writes commit, mirroring the
request transaction) and a fake ``Request``; all assertions re-read rows from a
fresh session so they pin the committed state.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

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
# property tests, e.g. tests/test_employee_portal_single_use_token_property.py).
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
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal import router as portal_router
from app.modules.employee_portal import schemas as S
from app.modules.employee_portal.models import (
    EmployeePortalSession,
    EmployeePortalUser,
)
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P12_login_resolution"

# The three login scenarios exercised by the property.
_SCENARIOS = ["org_a", "org_b", "unknown"]


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


async def _seed_two_orgs_same_credential(
    factory, *, email: str, password_hash: str
) -> dict:
    """Seed two portal-enabled orgs each holding the SAME email+password user.

    Returns the ids + slugs needed to drive and assert on a login: each org's
    id + slug, each org's Portal_User id, and each org's linked staff id.
    """
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

            slug_a = _valid_slug("epp-a")
            slug_b = _valid_slug("epp-b")

            # Both orgs are portal-enabled with their own distinct slug.
            org_a = Organisation(
                name=f"{_ORG_MARKER}_A_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=slug_a,
                settings={"employee_portal_enabled": True},
            )
            org_b = Organisation(
                name=f"{_ORG_MARKER}_B_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=slug_b,
                settings={"employee_portal_enabled": True},
            )
            session.add_all([org_a, org_b])
            await session.flush()

            staff_a = StaffMember(
                org_id=org_a.id,
                name="Login Resolution Staff A",
                first_name="ResolveA",
                last_name="Staff",
                email=email,
                is_active=True,
            )
            staff_b = StaffMember(
                org_id=org_b.id,
                name="Login Resolution Staff B",
                first_name="ResolveB",
                last_name="Staff",
                email=email,
                is_active=True,
            )
            session.add_all([staff_a, staff_b])
            await session.flush()

            # The SAME email + password hash in BOTH orgs (the org-scoped active
            # email uniqueness index permits the same email across orgs).
            user_a = EmployeePortalUser(
                org_id=org_a.id,
                staff_id=staff_a.id,
                email=email,
                password_hash=password_hash,
                is_active=True,
            )
            user_b = EmployeePortalUser(
                org_id=org_b.id,
                staff_id=staff_b.id,
                email=email,
                password_hash=password_hash,
                is_active=True,
            )
            session.add_all([user_a, user_b])
            await session.flush()

            return {
                "org_a_id": org_a.id,
                "org_b_id": org_b.id,
                "slug_a": slug_a,
                "slug_b": slug_b,
                "user_a_id": user_a.id,
                "user_b_id": user_b.id,
                "staff_a_id": staff_a.id,
                "staff_b_id": staff_b.id,
            }


def _fake_request() -> SimpleNamespace:
    """Minimal stand-in for the FastAPI ``Request`` the login route consumes.

    The route only reads ``request.client.host`` (via ``_client_ip``); supply a
    client so the audit row records an IP exactly as a real request would.
    """
    return SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))


def _body(resp) -> dict:
    return json.loads(bytes(resp.body))


async def _count_sessions(factory, org_id: uuid.UUID) -> int:
    async with factory() as session:
        res = await session.execute(
            select(func.count())
            .select_from(EmployeePortalSession)
            .where(EmployeePortalSession.org_id == org_id)
        )
        return int(res.scalar_one())


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(scenario: str, local: str, password: str) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        # Same email + same password hash in both orgs. Hash once and reuse the
        # string for both users (a bcrypt hash verifies regardless of which row
        # it is stored on) so each example costs a single hash.
        email = f"{local}-{uuid.uuid4().hex[:10]}@example.com"
        password_hash = ep_auth.hash_password_sync(password)

        seed = await _seed_two_orgs_same_credential(
            factory, email=email, password_hash=password_hash
        )
        org_a_id = seed["org_a_id"]
        org_b_id = seed["org_b_id"]

        # Pick the slug to log in with for this scenario.
        if scenario == "org_a":
            login_slug = seed["slug_a"]
        elif scenario == "org_b":
            login_slug = seed["slug_b"]
        else:  # unknown — resolves to no org at all.
            login_slug = _valid_slug("epp-missing")

        # --- Invoke the real login route, committing its writes via begin(). ---
        async with factory() as session:
            async with session.begin():
                resp = await portal_router.login(
                    body=S.LoginRequest(
                        slug=login_slug, email=email, password=password
                    ),
                    request=_fake_request(),
                    db=session,
                )

        body = _body(resp)

        if scenario == "unknown":
            # Neutral not-found, no identity leaked, and NO session anywhere.
            assert resp.status_code == 404, body
            assert body.get("code") == "portal_unavailable", body
            assert "portal_user_id" not in body
            assert "staff_id" not in body
            assert await _count_sessions(factory, org_a_id) == 0
            assert await _count_sessions(factory, org_b_id) == 0
            return

        # --- Successful login: identify the expected vs other org. ---
        if scenario == "org_a":
            this_user_id = seed["user_a_id"]
            this_staff_id = seed["staff_a_id"]
            this_org_id = org_a_id
            other_user_id = seed["user_b_id"]
            other_staff_id = seed["staff_b_id"]
            other_org_id = org_b_id
        else:  # org_b
            this_user_id = seed["user_b_id"]
            this_staff_id = seed["staff_b_id"]
            this_org_id = org_b_id
            other_user_id = seed["user_a_id"]
            other_staff_id = seed["staff_a_id"]
            other_org_id = org_a_id

        assert resp.status_code == 200, body

        # Authenticated EXACTLY the Portal_User of the slug's org — never the
        # same-credential user of the other org (R6.3).
        assert body["portal_user_id"] == str(this_user_id), body
        assert body["staff_id"] == str(this_staff_id), body
        assert body["portal_user_id"] != str(other_user_id), body
        assert body["staff_id"] != str(other_staff_id), body
        assert body["email"] == email

        # A session was created scoped to THIS org only; the other org has none.
        assert await _count_sessions(factory, this_org_id) == 1
        assert await _count_sessions(factory, other_org_id) == 0

        # The created session row is bound to this org + this Portal_User.
        async with factory() as session:
            rows = (
                await session.execute(
                    select(EmployeePortalSession).where(
                        EmployeePortalSession.org_id == this_org_id
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].portal_user_id == this_user_id
            assert rows[0].org_id == this_org_id
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 12: Single-organisation login resolution.
# ---------------------------------------------------------------------------

# Local-part of the shared email — lowercase alnum so storage normalisation is a
# no-op and the same generated value keys identically in both orgs.
_local_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=3,
    max_size=20,
)

# Keep passwords short so the per-example bcrypt hash/verify cost stays
# affordable; the length gate itself is covered by Property 11.
_password_strategy = st.integers(min_value=8, max_value=20).map(lambda n: "p" * n)


@settings(
    max_examples=110,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    scenario=st.sampled_from(_SCENARIOS),
    local=_local_strategy,
    password=_password_strategy,
)
def test_single_organisation_login_resolution(
    scenario: str, local: str, password: str
) -> None:
    """Property 12: Single-organisation login resolution.

    # Feature: organisation-employee-portal, Property 12: Single-organisation login resolution

    A login carrying a slug resolves the Portal_User within exactly that org and
    never authenticates a same-credential user of another org; an unresolvable
    slug yields a neutral ``404 portal_unavailable`` with no session.

    **Validates: Requirements 6.3, 6.11**
    """
    asyncio.run(_run_example(scenario, local, password))


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
