"""Property-based test: Employee Portal cookie scoping + cross-portal rejection.

# Feature: organisation-employee-portal, Property 18: Cookie scoping and cross-portal rejection

**Validates: Requirements 6.1, 6.2, 16.7, 16.8**

Property 18 (design.md) has two halves:

1. **Cookie scoping (R6.1, R6.2, R16.7).** *For any* Employee Portal session,
   the ``emp_portal_session`` cookie is ``HttpOnly``, scoped to ``Path=/e``, and
   marked ``Secure`` exactly when the environment is ``staging``/``production``;
   the companion ``emp_portal_csrf`` cookie is *readable* (NOT ``HttpOnly``, so
   the SPA can echo it as ``X-CSRF-Token``), is also scoped to ``Path=/e``, and
   shares the same ``Secure`` policy. The ``/e`` scope keeps both cookies off
   ``/api/*`` (staff app), ``/fleet`` (fleet portal), and the customer portal.
   This half is pure (no DB): it drives the router's ``_set_session_cookies``
   helper with generated token/csrf values across the three environments and
   parses the emitted ``Set-Cookie`` headers.

2. **Cross-portal rejection (R16.8).** *For any* session/CSRF cookie value
   issued by the customer portal, the fleet portal, or the staff app, that value
   never validates as an Employee Portal credential. The rejection is
   **structural**: employee sessions live in their own ``employee_portal_sessions``
   table keyed by ``sha256(session_token)``; a foreign cookie value has no row
   there, so ``router._resolve_session_ctx`` returns ``None`` for it. This half
   is DB-backed (transactional dev Postgres): it seeds a genuine employee
   session (positive control — proves resolution works and the negatives are not
   vacuous), then asserts that arbitrary foreign tokens never resolve.

DB-backed conventions follow ``tests/test_employee_portal_store_separation_property.py``
(fresh async engine per example, full ORM import block, org-name marker for
cleanup, ``asyncio.run`` driver). The cookie half follows the pure-response
pattern of ``tests/test_employee_portal_logout_me.py``. >= 100 examples each.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.responses import JSONResponse
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text as sa_text

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_store_separation_property.py).
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
from app.modules.employee_portal import router as R
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.employee_portal.services import session_service
from app.modules.staff.models import StaffMember


# ===========================================================================
# Half 1 — Cookie scoping (pure, no DB). R6.1, R6.2, R16.7.
# ===========================================================================

# A cookie value is the urlsafe-base64 alphabet that ``secrets.token_urlsafe``
# emits; constraining to it keeps the property about cookie *attributes* (not
# about how the cookie library escapes exotic characters).
_TOKEN_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
_token_strategy = st.text(alphabet=_TOKEN_ALPHABET, min_size=1, max_size=64)

# The three environments the app recognises; Secure is on iff staging/prod.
_environment_strategy = st.sampled_from(["development", "staging", "production"])


def _parse_set_cookies(response: JSONResponse) -> dict[str, list[str]]:
    """Return ``{cookie_name: [attribute, ...]}`` from a response's Set-Cookie.

    Each attribute is the raw, stripped ``;``-delimited segment (e.g.
    ``"Path=/e"``, ``"HttpOnly"``, ``"Secure"``). The first segment is the
    ``name=value`` pair, from which we key by ``name``.
    """
    out: dict[str, list[str]] = {}
    for key, value in response.raw_headers:
        k = key.decode() if isinstance(key, bytes) else key
        if k.lower() != "set-cookie":
            continue
        raw = value.decode() if isinstance(value, bytes) else value
        segments = [seg.strip() for seg in raw.split(";")]
        name = segments[0].split("=", 1)[0]
        out[name] = segments
    return out


def _has_attr(segments: list[str], attr: str) -> bool:
    """Case-insensitive presence check for a flag attribute (HttpOnly/Secure)."""
    return any(seg.lower() == attr.lower() for seg in segments)


@hyp_settings(max_examples=150, deadline=None)
@given(
    session_token=_token_strategy,
    csrf_token=_token_strategy,
    environment=_environment_strategy,
)
def test_session_cookie_scoping_and_flags(
    session_token: str, csrf_token: str, environment: str
) -> None:
    """The session cookie is HttpOnly + Path=/e + Secure-in-staging/prod; the
    CSRF cookie is readable + Path=/e (R6.1, R6.2, R16.7).

    **Validates: Requirements 6.1, 6.2, 16.7**
    """
    original_env = app_settings.environment
    app_settings.environment = environment
    try:
        expect_secure = environment in {"staging", "production"}
        # Sanity: the helper's own predicate agrees with the spec mapping.
        assert R._is_secure_origin() is expect_secure

        response = JSONResponse(content={"ok": True})
        R._set_session_cookies(
            response, session_token=session_token, csrf_token=csrf_token
        )
        cookies = _parse_set_cookies(response)

        # Both cookies are emitted.
        assert R._SESSION_COOKIE_NAME in cookies
        assert R._CSRF_COOKIE_NAME in cookies

        sess = cookies[R._SESSION_COOKIE_NAME]
        csrf = cookies[R._CSRF_COOKIE_NAME]

        # --- Session cookie: HttpOnly bearer secret, scoped to /e. ---
        assert _has_attr(sess, "HttpOnly"), "session cookie must be HttpOnly (R16.7)"
        assert "Path=/e" in sess, "session cookie must be scoped to /e (R6.1, R6.2)"
        assert _has_attr(sess, "Secure") is expect_secure, (
            "session cookie Secure flag must match staging/prod environment"
        )

        # --- CSRF cookie: readable (NOT HttpOnly) double-submit value, /e. ---
        assert not _has_attr(csrf, "HttpOnly"), (
            "CSRF cookie must be readable by JS (not HttpOnly) for double-submit"
        )
        assert "Path=/e" in csrf, "CSRF cookie must be scoped to /e (R6.1, R6.2)"
        assert _has_attr(csrf, "Secure") is expect_secure, (
            "CSRF cookie Secure flag must match staging/prod environment"
        )
    finally:
        app_settings.environment = original_env


# ===========================================================================
# Half 2 — Cross-portal rejection (DB-backed). R16.8.
# ===========================================================================

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_18_cookie_scoping"


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


async def _seed_portal_user_and_session(
    factory, org_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    """Seed an active Portal_User + a genuine session; return (user_id, raw_token).

    The raw session token is the value the HttpOnly ``emp_portal_session`` cookie
    would carry — the positive control that *does* validate.
    """
    async with factory() as session:
        async with session.begin():
            staff = StaffMember(
                org_id=org_id,
                name="Cookie Scoping Staff",
                first_name="Cookie",
                last_name="Scoping",
                email=f"cookie-{uuid.uuid4().hex[:10]}@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            user = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff.id,
                email=f"cookie-{uuid.uuid4().hex[:10]}@example.com",
                password_hash=ep_auth.hash_password_sync("P!cookie-scoping-pw"),
                is_active=True,
            )
            session.add(user)
            await session.flush()

            _sess, raw_token = await session_service.create_session(session, user)
            return user.id, raw_token


# Foreign cookie values standing in for customer-portal / fleet-portal / staff-app
# session or CSRF cookies. Realistic urlsafe token shapes, plus a few literal
# names to make the "wrong portal" intent explicit.
_foreign_token_strategy = st.one_of(
    st.text(alphabet=_TOKEN_ALPHABET, min_size=1, max_size=64),
    st.sampled_from(
        [
            "fleet_portal_session_value",
            "customer_portal_session_value",
            "staff_app_jwt.header.payload.sig",
            "fleet_portal_csrf_value",
            "customer_portal_csrf_value",
        ]
    ),
)


async def _run_rejection_example(foreign_tokens: list[str]) -> None:
    """Seed a genuine session, then assert foreign tokens never resolve."""
    engine, factory = await _make_engine_and_factory()
    try:
        org_id = await _seed_org(factory)
        user_id, raw_token = await _seed_portal_user_and_session(factory, org_id)
        now = datetime.now(timezone.utc)

        async with factory() as session:
            # --- Positive control: the genuine employee token DOES validate,
            #     so the rejections below are meaningful (not vacuously None). ---
            ctx = await R._resolve_session_ctx(session, raw_token, now)
            assert ctx is not None, "a genuine employee session token must validate"
            assert ctx.org_id == org_id
            assert ctx.portal_user_id == user_id

        for foreign in foreign_tokens:
            # An astronomically unlikely collision with the genuine 32-byte
            # token would be a real positive, not a foreign cookie — skip it.
            if foreign == raw_token:
                continue
            async with factory() as session:
                result = await R._resolve_session_ctx(session, foreign, now)
                assert result is None, (
                    "a customer/fleet/staff cookie value must never validate as "
                    "an employee portal credential (R16.8) — no row in "
                    f"employee_portal_sessions for {foreign!r}"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@hyp_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(foreign_tokens=st.lists(_foreign_token_strategy, min_size=1, max_size=5))
def test_foreign_cookie_never_validates_as_employee_credential(
    foreign_tokens: list[str],
) -> None:
    """Cross-portal rejection is structural: a customer/fleet/staff cookie value
    has no row in ``employee_portal_sessions`` and never validates (R16.8).

    **Validates: Requirements 16.8**
    """
    asyncio.run(_run_rejection_example(foreign_tokens))


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
