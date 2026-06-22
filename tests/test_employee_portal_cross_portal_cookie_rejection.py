"""Integration test: cross-portal cookie rejection at ``GET /e/api/auth/me``.

Implements: Organisation Employee Portal task 17.5 — Requirements 16.7, 16.8.

R16.8 requires that a session/CSRF cookie issued by **another** portal (the
customer portal, the B2B fleet portal, or the staff app) can **never** validate
as an Employee Portal credential. The acceptance test for the task is concrete:

    Present a ``fleet_portal_session`` cookie to ``GET /e/api/auth/me`` → rejected.

This test exercises the **real HTTP path** through the employee portal router
(``require_portal_session`` → ``_resolve_session_ctx`` → ``is_session_valid``)
rather than calling the resolver directly. Because the full application factory
(``app.main.create_app``) cannot be imported in this sandbox — the billing
router imports the un-installed ``stripe`` package, a pre-existing
environmental limitation — we mount **only** the employee portal router under
its production prefix ``/e/api`` on a minimal FastAPI app and drive it with an
in-process ASGI transport (``httpx.ASGITransport``). The route, its dependency
injection, the cookie parsing, the session lookup, and the validity predicate
are all the genuine production code; only the unrelated routers are omitted.

The rejection is **structural** (design.md, Property 18): employee sessions
live in their own ``employee_portal_sessions`` table keyed on
``sha256(session_token)``. A genuine fleet session token lives in
``portal_sessions.session_token`` (raw) and is *valid for the fleet portal*, but
hashing it and looking it up in ``employee_portal_sessions`` finds no row, so
``/e/api/auth/me`` returns the neutral ``401 session_invalid`` envelope. To make
the rejection meaningful (not vacuous), the test also:

* mints a **genuine fleet portal session** via the real
  ``fleet_portal.session_service.create_fleet_portal_session`` code path and
  asserts that token IS a valid, unexpired row in ``portal_sessions`` (a
  positive control on the fleet side), and
* mints a **genuine employee portal session** and asserts it DOES authenticate
  at ``/e/api/auth/me`` with ``200`` (a positive control on the employee side).

R16.7 (cookie scoping) is additionally covered by the dedicated property test
``tests/test_employee_portal_cookie_scoping_property.py``; here we assert the
cookie-name half of it — a cookie literally named ``fleet_portal_session`` is
not even read by the employee portal (which only reads ``emp_portal_session``),
so it is rejected regardless of its value.

DB conventions follow the reference DB-backed tests in this suite
(``tests/test_employee_portal_store_separation_property.py``): a fresh async
engine, the full ORM import block so SQLAlchemy can configure mappers, an
org-name marker for cleanup, and an ``asyncio.run`` driver. Requires the
transactional dev Postgres at
``DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# tests, e.g. tests/test_employee_portal_store_separation_property.py).
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
from app.modules.customers.models import Customer
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.models import (
    EmployeePortalSession,
    EmployeePortalUser,
)
from app.modules.employee_portal.services import session_service
from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount
from app.modules.fleet_portal.services import (
    session_service as fleet_session_service,
)
from app.modules.portal.models import PortalSession
from app.modules.staff.models import StaffMember


# Marker baked into seeded org names so cleanup can find orphans even when a
# run aborts mid-way. Distinct from the other portal DB tests so parallel /
# interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_17_5_cross_portal"

# Cookie names — the employee portal only ever reads ``emp_portal_session``;
# ``fleet_portal_session`` belongs to the (separate) fleet portal.
_EMP_COOKIE = "emp_portal_session"
_FLEET_COOKIE = "fleet_portal_session"


# ---------------------------------------------------------------------------
# Engine / cleanup helpers (mirror the reference DB-backed tests)
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
            # portal_sessions has no org_id column — clear it via the
            # customers / portal_accounts created under this marker's orgs.
            await session.execute(
                sa_text(
                    "DELETE FROM portal_sessions WHERE customer_id IN "
                    f"(SELECT id FROM customers WHERE org_id IN ({org_subq}))"
                ),
                params,
            )
            for tbl in (
                "employee_portal_audit_log",
                "employee_portal_sessions",
                "employee_portal_users",
                "staff_members",
                "fleet_driver_assignments",
                "portal_accounts",
                "portal_fleet_accounts",
                "customers",
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


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def _seed(factory) -> dict:
    """Seed an org with a genuine employee session AND a genuine fleet session.

    Returns a dict with the org id, the portal user id, and the two raw session
    tokens (the values the respective portals' HttpOnly cookies would carry).
    """
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
            org_id = org.id

            # --- Employee portal user + a genuine employee session. ----------
            staff = StaffMember(
                org_id=org_id,
                name="Cross Portal Staff",
                first_name="Cross",
                last_name="Portal",
                email=f"emp-{uuid.uuid4().hex[:10]}@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            emp_user = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff.id,
                email=f"emp-{uuid.uuid4().hex[:10]}@example.com",
                password_hash=ep_auth.hash_password_sync("P!cross-portal-pw"),
                is_active=True,
            )
            session.add(emp_user)
            await session.flush()
            emp_user_id = emp_user.id

            _emp_sess, emp_token = await session_service.create_session(
                session, emp_user
            )

            # --- Genuine fleet portal session (the real minting path). --------
            customer = Customer(
                org_id=org_id,
                first_name="Fleet",
                last_name="Customer",
            )
            session.add(customer)
            await session.flush()

            fleet_account = PortalFleetAccount(
                org_id=org_id,
                customer_id=customer.id,
                display_name="Cross Portal Fleet",
                is_active=True,
            )
            session.add(fleet_account)
            await session.flush()

            portal_account = PortalAccount(
                org_id=org_id,
                customer_id=customer.id,
                email=f"fleet-{uuid.uuid4().hex[:10]}@example.com",
                password_hash=ep_auth.hash_password_sync("P!fleet-pw"),
                portal_user_role="fleet_admin",
                fleet_account_id=fleet_account.id,
                is_active=True,
            )
            session.add(portal_account)
            await session.flush()

            # Mint via the actual fleet session service so the token is exactly
            # what a real fleet login would put in the fleet_portal_session
            # cookie (a row in portal_sessions keyed by the raw token).
            fleet_token, _fleet_csrf = (
                await fleet_session_service.create_fleet_portal_session(
                    session, portal_account=portal_account
                )
            )

    return {
        "org_id": org_id,
        "emp_user_id": emp_user_id,
        "staff_id": staff.id,
        "emp_token": emp_token,
        "fleet_token": fleet_token,
    }


# ---------------------------------------------------------------------------
# Minimal app (only the employee portal router — see module docstring)
# ---------------------------------------------------------------------------


def _build_employee_portal_app() -> FastAPI:
    """Mount ONLY the employee portal router under its production /e/api prefix.

    This avoids ``app.main.create_app`` (which imports the un-installed
    ``stripe`` via the billing router) while exercising the genuine
    ``GET /e/api/auth/me`` route, dependencies, and cookie handling.
    """
    from app.modules.employee_portal.router import router as employee_portal_router

    app = FastAPI()
    app.include_router(employee_portal_router, prefix="/e/api")
    return app


async def _get_me(client: httpx.AsyncClient, cookie_header: str) -> httpx.Response:
    """``GET /e/api/auth/me`` with an explicit ``Cookie`` header.

    Setting the raw header (rather than the per-request ``cookies=`` kwarg)
    keeps the test independent of httpx cookie-jar versioning and makes the
    presented cookie name/value unambiguous.
    """
    return await client.get("/e/api/auth/me", headers={"Cookie": cookie_header})


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


async def _run() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seeded = await _seed(factory)
        emp_token: str = seeded["emp_token"]
        fleet_token: str = seeded["fleet_token"]
        emp_user_id: uuid.UUID = seeded["emp_user_id"]

        # --- Structural pre-conditions (make the negatives non-vacuous). -----
        async with factory() as session:
            # The fleet token IS a valid, unexpired fleet/customer portal
            # session row — i.e. it genuinely authenticates the OTHER portal.
            now = datetime.now(timezone.utc)
            fleet_row = (
                await session.execute(
                    select(PortalSession).where(
                        PortalSession.session_token == fleet_token
                    )
                )
            ).scalars().first()
            assert fleet_row is not None, "fleet token must be a real fleet session"
            assert fleet_row.expires_at > now, "fleet session must be unexpired"

            # That same fleet token has NO row in employee_portal_sessions —
            # the rejection at /e/api/auth/me is therefore structural (R16.8).
            fleet_hash = hashlib.sha256(fleet_token.encode()).hexdigest()
            emp_hit = (
                await session.execute(
                    select(EmployeePortalSession).where(
                        EmployeePortalSession.session_token_hash == fleet_hash
                    )
                )
            ).scalars().first()
            assert emp_hit is None, (
                "a fleet session token must not exist in employee_portal_sessions"
            )

        # --- Drive the real /e/api/auth/me route over in-process HTTP. -------
        app = _build_employee_portal_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            # Case A — a cookie literally named ``fleet_portal_session`` is not
            # even read by the employee portal (which reads emp_portal_session),
            # so /me rejects it with the neutral session_invalid envelope (R16.7).
            resp_a = await _get_me(client, f"{_FLEET_COOKIE}={fleet_token}")
            assert resp_a.status_code == 401, resp_a.text
            assert resp_a.json()["detail"]["code"] == "session_invalid"

            # Case B — even if the fleet token is smuggled into the employee
            # portal's own cookie slot, it has no row in employee_portal_sessions
            # and is rejected (the core R16.8 cross-portal rejection).
            resp_b = await _get_me(client, f"{_EMP_COOKIE}={fleet_token}")
            assert resp_b.status_code == 401, resp_b.text
            assert resp_b.json()["detail"]["code"] == "session_invalid"

            # Case C — positive control: a genuine employee session token DOES
            # authenticate, proving cases A/B reject for the right reason and
            # not because the route is simply broken.
            resp_c = await _get_me(client, f"{_EMP_COOKIE}={emp_token}")
            assert resp_c.status_code == 200, resp_c.text
            body = resp_c.json()
            assert body["portal_user_id"] == str(emp_user_id)
            assert body["staff_id"] == str(seeded["staff_id"])

            # Case D — no cookie at all is likewise rejected (baseline).
            resp_d = await client.get("/e/api/auth/me")
            assert resp_d.status_code == 401, resp_d.text
            assert resp_d.json()["detail"]["code"] == "session_invalid"
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_fleet_session_cookie_rejected_at_employee_me() -> None:
    """A ``fleet_portal_session`` cookie never validates at ``GET /e/api/auth/me``.

    Validates: Requirements 16.7, 16.8.
    """
    asyncio.run(_run())


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted run."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
