"""Property-based test: Employee Portal anti-enumeration response invariance.

# Feature: organisation-employee-portal, Property 13: Anti-enumeration response invariance

**Validates: Requirements 6.4, 14.1, 16.6**

Property 13 (design.md): two login (or password-reset) requests that differ
*only* in whether the supplied email matches an active Portal_User must produce
a **byte-for-byte identical** response (same HTTP status, same machine code,
same message body) so account existence is never revealed; and a failed login
against an *unknown* email must still write an ``employee_portal_audit_log`` row
whose ``portal_user_id`` is ``NULL`` (R16.6).

The two surfaces under test live in ``app.modules.employee_portal.router``:

- ``login`` (``POST /e/api/auth/login``) — a non-matching email and a matching
  email with the wrong password both return the generic ``401
  invalid_credentials`` with identical text (R6.4); the unknown-email failure
  still records a ``login_failed`` audit row with a null ``portal_user_id``
  (R16.6).
- ``request_password_reset`` (``POST /e/api/auth/password/reset-request``) —
  a matching and a non-matching email both return the byte-for-byte identical
  ``200`` confirmation (R14.1).

This is a DB-backed Hypothesis test against the transactional dev Postgres,
mirroring the established pattern in
``tests/test_employee_portal_single_use_token_property.py`` and
``tests/test_employee_portal_store_separation_property.py``: a fresh async
engine per example (asyncpg connections are bound to the loop ``asyncio.run``
creates), the full ORM import block so SQLAlchemy can configure mappers, an
org-name marker for orphan cleanup, and an ``asyncio.run`` driver. The route
functions are invoked directly with a seeded session and a fake ``Request``
(constructed from a minimal ASGI scope — a real Starlette ``Request``, not a
mock). The outbound reset email is the only thing stubbed, because Property 13
is about response invariance, not email delivery (delivery is covered by the
task-7 helpers); stubbing it keeps the per-example cost down and avoids the
multi-provider failover path. >= 100 examples.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

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
from app.modules.employee_portal import employee_portal_delivery
from app.modules.employee_portal import router as ep_router
from app.modules.employee_portal import schemas as S
from app.modules.employee_portal.models import (
    EmployeePortalAuditLog,
    EmployeePortalUser,
)
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P13_anti_enumeration"

# The single known credential the seeded Portal_User holds. The login test
# always submits a *different* password for the matching-email case so the
# verify fails and the generic 401 path is taken.
_KNOWN_PASSWORD = "Correct-Horse-Battery-9"


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
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


async def _seed_org_and_user(factory, known_email: str) -> dict:
    """Seed one portal-enabled org (slug set) + ONE active Portal_User.

    Returns the org id, the org slug, and the seeded user id. The org's
    ``settings`` JSONB carries ``employee_portal_enabled=True`` so the login /
    reset endpoints pass the enablement gate, and a unique normalised ``slug``
    so ``normalise_slug`` resolution succeeds.
    """
    slug = f"epp{uuid.uuid4().hex[:18]}"  # lowercase alnum → valid + unique slug
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
                slug=slug,
                settings={"employee_portal_enabled": True},
            )
            session.add(org)
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Anti Enumeration Staff",
                first_name="Anti",
                last_name="Enumeration",
                email=known_email,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            user = EmployeePortalUser(
                org_id=org.id,
                staff_id=staff.id,
                email=known_email.strip().lower(),
                password_hash=ep_auth.hash_password_sync(_KNOWN_PASSWORD),
                is_active=True,
                failed_login_attempts=0,
                locked_until=None,
            )
            session.add(user)
            await session.flush()

            return {"org_id": org.id, "slug": slug, "user_id": user.id}


def _fake_request() -> Request:
    """Build a real Starlette ``Request`` from a minimal ASGI scope.

    The route functions only touch ``request.client.host`` (for the audit
    ``ip_address``) and ``request.headers`` (the reset endpoint reads
    ``origin``), so a minimal HTTP scope is sufficient — this is a genuine
    ``Request`` object, not a mock.
    """
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/e/api/auth/login",
        "raw_path": b"/e/api/auth/login",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"origin", b"http://localhost"), (b"host", b"localhost")],
        "client": ("127.0.0.1", 12345),
        "server": ("localhost", 80),
    }
    return Request(scope)


def _body_bytes(response) -> bytes:
    """Return the rendered body bytes of a JSONResponse."""
    return bytes(response.body)


async def _run_example(
    known_local: str, other_local: str, wrong_pw_seed: str
) -> None:
    """Seed one org+user, then assert login & reset response invariance."""
    engine, factory = await _make_engine_and_factory()
    try:
        # Distinct, unique addresses. The unique uuid suffix guarantees the
        # "other" email never collides with the known one even if the generated
        # local parts happen to be equal.
        known_email = f"{known_local}-{uuid.uuid4().hex[:10]}@example.com"
        other_email = f"{other_local}-{uuid.uuid4().hex[:10]}@example.com"

        # The matching-email login uses a password that is guaranteed to differ
        # from the seeded one, so it always takes the generic 401 path.
        wrong_password = "WRONG_" + wrong_pw_seed
        assert wrong_password != _KNOWN_PASSWORD

        seeded = await _seed_org_and_user(factory, known_email)
        org_id = seeded["org_id"]
        slug = seeded["slug"]
        user_id = seeded["user_id"]

        req = _fake_request()

        # ---- LOGIN: matching email + wrong password vs non-matching email ----
        login_match = S.LoginRequest(
            slug=slug, email=known_email, password=wrong_password
        )
        login_miss = S.LoginRequest(
            slug=slug, email=other_email, password=wrong_password
        )

        async with factory() as session:
            async with session.begin():
                resp_match = await ep_router.login(login_match, req, session)
                resp_miss = await ep_router.login(login_miss, req, session)
            # commit happens at the end of the begin() block → audit rows + the
            # failed-attempt increment persist.

        # Byte-for-byte identical: an attacker cannot distinguish a real account
        # (wrong password) from a non-existent one (R6.4).
        assert resp_match.status_code == 401
        assert resp_miss.status_code == 401
        assert resp_match.status_code == resp_miss.status_code
        assert _body_bytes(resp_match) == _body_bytes(resp_miss), (
            "login responses for a matching vs non-matching email must be "
            "byte-for-byte identical (anti-enumeration, R6.4)"
        )

        # ---- AUDIT: the unknown-email failure wrote a row with NULL user (R16.6).
        async with factory() as session:
            # The matching-email failure recorded a row carrying the real user id.
            matched_rows = await session.execute(
                select(func.count())
                .select_from(EmployeePortalAuditLog)
                .where(
                    EmployeePortalAuditLog.org_id == org_id,
                    EmployeePortalAuditLog.action == "login_failed",
                    EmployeePortalAuditLog.portal_user_id == user_id,
                )
            )
            assert matched_rows.scalar_one() >= 1

            # The unknown-email failure recorded a row with a NULL portal user
            # reference — present, but revealing nothing about account existence.
            null_rows = await session.execute(
                select(func.count())
                .select_from(EmployeePortalAuditLog)
                .where(
                    EmployeePortalAuditLog.org_id == org_id,
                    EmployeePortalAuditLog.action == "login_failed",
                    EmployeePortalAuditLog.portal_user_id.is_(None),
                )
            )
            assert null_rows.scalar_one() >= 1, (
                "a failed unknown-email login must still write an audit row "
                "with a NULL portal_user_id (R16.6)"
            )

        # ---- RESET: matching email vs non-matching email -> identical 200. ----
        # Stub the outbound email — Property 13 is about response invariance, not
        # delivery; the matching branch issues a real reset token either way.
        async def _noop_reset_email(*args, **kwargs):
            return None

        reset_match = S.PasswordResetRequest(slug=slug, email=known_email)
        reset_miss = S.PasswordResetRequest(slug=slug, email=other_email)

        with patch.object(
            employee_portal_delivery,
            "send_password_reset_email",
            new=_noop_reset_email,
        ):
            async with factory() as session:
                async with session.begin():
                    resp_rmatch = await ep_router.request_password_reset(
                        reset_match, req, session
                    )
            async with factory() as session:
                async with session.begin():
                    resp_rmiss = await ep_router.request_password_reset(
                        reset_miss, req, session
                    )

        assert resp_rmatch.status_code == 200
        assert resp_rmiss.status_code == 200
        assert resp_rmatch.status_code == resp_rmiss.status_code
        assert _body_bytes(resp_rmatch) == _body_bytes(resp_rmiss), (
            "password-reset confirmations for a matching vs non-matching email "
            "must be byte-for-byte identical (anti-enumeration, R14.1)"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Lowercase-alnum local parts so storage normalisation (trim + lowercase) is a
# no-op and the generated value keys identically against the lower(email) index.
_local_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=1,
    max_size=18,
)

# Wrong-password seed — any printable ASCII, kept short so the per-example
# bcrypt verify cost stays affordable. The "WRONG_" prefix added at use-site
# guarantees it differs from the seeded known password.
_wrong_pw_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=24,
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    known_local=_local_strategy,
    other_local=_local_strategy,
    wrong_pw_seed=_wrong_pw_strategy,
)
def test_anti_enumeration_response_invariance(
    known_local: str, other_local: str, wrong_pw_seed: str
) -> None:
    """Property 13: anti-enumeration response invariance.

    # Feature: organisation-employee-portal, Property 13: Anti-enumeration response invariance

    A login (or password-reset) request that differs only in whether the email
    matches an active Portal_User produces a byte-for-byte identical response,
    and a failed unknown-email login still writes an audit row with a NULL
    portal-user reference.

    **Validates: Requirements 6.4, 14.1, 16.6**
    """
    asyncio.run(_run_example(known_local, other_local, wrong_pw_seed))


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
