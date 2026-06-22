"""Integration test: Employee Portal disable → session teardown (end-to-end).

# Feature: organisation-employee-portal, Task 17.3

**Validates: Requirements 4.5, 4.6**

Task 17.3 (tasks.md): *Disabling the portal removes all active sessions for the
org by the next request (R4.6 end-to-end).*

R4.6: *WHEN an Org_Admin disables the Employee_Portal for an Organisation, THE
Employee_Portal SHALL invalidate all active Employee_Portal_Sessions for that
Organisation within 30 seconds of the change being persisted.*

R4.5: *WHILE the Employee_Portal is disabled for an Organisation, THE
Employee_Portal SHALL reject every login attempt at that Organisation's branded
URL ... without establishing an Employee_Portal_Session.*

This drives the **real** disable path
(``organisations.service.set_employee_portal_enabled(enabled=False)`` →
``session_service.delete_sessions_for_org`` in the same ``session.begin()``
transaction, R4.6) and then the **real** ``/e/api`` request-time session gate
(``router.require_portal_session`` → ``session_service.is_session_valid``) so the
test exercises the full end-to-end teardown rather than a single helper.

The end-to-end flow per test:

1. Seed one org with the portal **enabled** (+ a valid slug) and an active
   Portal_User, then mint several real sessions via
   ``session_service.create_session``.
2. **Pre-condition** — confirm a ``/e/api`` request authenticates: resolving one
   session's cookie through ``require_portal_session`` yields a context and
   ``GET /e/api/auth/me`` returns ``200`` while the portal is enabled.
3. **Disable** the portal through ``set_employee_portal_enabled(enabled=False)``.
4. **Assert teardown** — every ``employee_portal_sessions`` row for the org is
   gone from committed state (a deleted row can never be valid — the strongest
   form of "invalidated").
5. **Assert the next request is rejected** — re-presenting the *same* session
   cookie to ``require_portal_session`` now raises ``401 session_invalid``, and a
   fresh login attempt against the disabled portal is rejected
   ``403 portal_unavailable`` with no new session established (R4.5).

A second test asserts the teardown is **org-scoped, never over-broad**: a second
portal-enabled org's sessions are untouched when the first org is disabled.

DB-backed against the transactional dev Postgres, mirroring the established
pattern in ``tests/test_employee_portal_session_invalidation_property.py``: the
full ORM import block (so SQLAlchemy resolves string relationships), an
org-name marker for orphan cleanup, a fresh async engine bound to the loop
``asyncio.run`` creates, and an ``asyncio.run`` driver. Assertions re-read rows
from the database (not in-memory ORM objects) so they pin committed state.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_session_invalidation_property.py).
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
from app.modules.employee_portal.services import session_service
from app.modules.employee_portal.services.session_service import hash_token
from app.modules.organisations.service import set_employee_portal_enabled
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB tests so parallel
# runs never trample each other's fixtures.
_ORG_MARKER = "TEST_EPP_disable_teardown"

_SESSION_COOKIE_NAME = "emp_portal_session"

# Shared fixture password (verified by the login-rejected-while-disabled path).
_FIXTURE_PASSWORD = "disable-teardown-fixture-pw"


# ---------------------------------------------------------------------------
# Engine / cleanup helpers (fresh engine per run).
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
                "audit_log",
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


def _fake_request(session_token: str | None = None) -> SimpleNamespace:
    """Minimal stand-in for the FastAPI ``Request`` the portal routes consume.

    ``require_portal_session`` reads ``request.cookies.get(...)``.
    """
    cookies = {} if session_token is None else {_SESSION_COOKIE_NAME: session_token}
    return SimpleNamespace(
        cookies=cookies, client=SimpleNamespace(host="203.0.113.7")
    )


async def _seed_enabled_org(factory, *, session_count: int) -> dict:
    """Seed a portal-enabled org + one active Portal_User + ``session_count`` sessions.

    Returns the org id, slug, portal-user email, and the raw session tokens (so a
    cookie can be re-presented to ``require_portal_session`` before and after the
    disable).
    """
    now = datetime.now(timezone.utc)
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

            slug = _valid_slug("epp-disable")
            org = Organisation(
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=slug,
                settings={"employee_portal_enabled": True},
            )
            session.add(org)
            await session.flush()
            org_id = org.id

            staff = StaffMember(
                org_id=org_id,
                name="Disable Teardown Staff",
                first_name="Disable",
                last_name="Staff",
                email=f"staff-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            email = f"user-{uuid.uuid4().hex[:8]}@example.com"
            user = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff.id,
                email=email,
                password_hash=ep_auth.hash_password_sync(_FIXTURE_PASSWORD),
                is_active=True,
            )
            session.add(user)
            await session.flush()

            raw_tokens: list[str] = []
            for _ in range(session_count):
                raw = secrets.token_urlsafe(32)
                session.add(
                    EmployeePortalSession(
                        org_id=org_id,
                        portal_user_id=user.id,
                        session_token_hash=hash_token(raw),
                        csrf_token=secrets.token_urlsafe(32),
                        created_at=now,
                        last_seen_at=now,
                        expires_at=now + timedelta(hours=12),
                    )
                )
                raw_tokens.append(raw)
            await session.flush()

            return {
                "org_id": org_id,
                "slug": slug,
                "email": email,
                "raw_tokens": raw_tokens,
            }


async def _session_count_for_org(factory, org_id: uuid.UUID) -> int:
    async with factory() as session:
        res = await session.execute(
            select(func.count())
            .select_from(EmployeePortalSession)
            .where(EmployeePortalSession.org_id == org_id)
        )
        return int(res.scalar_one())


# ---------------------------------------------------------------------------
# Test 1 — disable tears down ALL org sessions; the next request is rejected.
# ---------------------------------------------------------------------------


async def _run_disable_teardown() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed_enabled_org(factory, session_count=3)
        org_id = seed["org_id"]
        slug = seed["slug"]
        raw_tokens = seed["raw_tokens"]
        probe_token = raw_tokens[0]

        # --- Pre-condition: while enabled, a /e/api request authenticates. ---
        assert await _session_count_for_org(factory, org_id) == 3
        async with factory() as session:
            async with session.begin():
                ctx = await portal_router.require_portal_session(
                    request=_fake_request(probe_token), db=session
                )
                assert ctx.org_id == org_id, ctx
                me_resp = await portal_router.me(ctx=ctx, db=session)
                assert me_resp.status_code == 200, me_resp.status_code

        # --- Disable the portal through the real admin service path (R4.6). ---
        async with factory() as session:
            async with session.begin():
                returned = await set_employee_portal_enabled(
                    session,
                    org_id=org_id,
                    user_id=uuid.uuid4(),  # audit_log.user_id has no FK
                    enabled=False,
                )
                assert returned is False

        # --- Assert teardown: every session for the org is gone (R4.6). ------
        assert await _session_count_for_org(factory, org_id) == 0

        # --- Assert the NEXT request with the same cookie is rejected. -------
        # require_portal_session must now raise 401 session_invalid because the
        # row was deleted — a deleted session can never re-authenticate.
        for tok in raw_tokens:
            async with factory() as session:
                async with session.begin():
                    with pytest.raises(HTTPException) as exc_info:
                        await portal_router.require_portal_session(
                            request=_fake_request(tok), db=session
                        )
                    assert exc_info.value.status_code == 401, exc_info.value
                    assert exc_info.value.detail.get("code") == "session_invalid", (
                        exc_info.value.detail
                    )

        # --- R4.5: a fresh login against the disabled portal is rejected with
        #     no session established. ---------------------------------------
        async with factory() as session:
            async with session.begin():
                login_resp = await portal_router.login(
                    body=S.LoginRequest(
                        slug=slug, email=seed["email"], password=_FIXTURE_PASSWORD
                    ),
                    request=_fake_request(),
                    db=session,
                )
                assert login_resp.status_code == 403, login_resp.status_code

                body = json.loads(bytes(login_resp.body))
                assert body.get("code") == "portal_unavailable", body

        # No session was created by the rejected login attempt (R4.5).
        assert await _session_count_for_org(factory, org_id) == 0
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_disable_portal_tears_down_all_org_sessions_and_rejects_next_request() -> None:
    """Disabling the portal deletes every org session; the next /e/api request
    and any fresh login are then rejected (R4.5, R4.6 end-to-end)."""
    asyncio.run(_run_disable_teardown())


# ---------------------------------------------------------------------------
# Test 2 — teardown is org-scoped: another org's sessions are untouched.
# ---------------------------------------------------------------------------


async def _run_disable_is_org_scoped() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        org_a = await _seed_enabled_org(factory, session_count=2)
        org_b = await _seed_enabled_org(factory, session_count=2)

        assert await _session_count_for_org(factory, org_a["org_id"]) == 2
        assert await _session_count_for_org(factory, org_b["org_id"]) == 2

        # Disable ONLY org A.
        async with factory() as session:
            async with session.begin():
                await set_employee_portal_enabled(
                    session,
                    org_id=org_a["org_id"],
                    user_id=uuid.uuid4(),
                    enabled=False,
                )

        # Org A is fully torn down; org B is completely untouched (not over-broad).
        assert await _session_count_for_org(factory, org_a["org_id"]) == 0
        assert await _session_count_for_org(factory, org_b["org_id"]) == 2

        # Org B's session still authenticates a /e/api request.
        async with factory() as session:
            async with session.begin():
                ctx = await portal_router.require_portal_session(
                    request=_fake_request(org_b["raw_tokens"][0]), db=session
                )
                assert ctx.org_id == org_b["org_id"], ctx
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_disable_portal_teardown_is_org_scoped() -> None:
    """Disabling one org's portal never invalidates another org's sessions."""
    asyncio.run(_run_disable_is_org_scoped())


# ---------------------------------------------------------------------------
# Best-effort teardown of any rows left behind by an aborted run.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
