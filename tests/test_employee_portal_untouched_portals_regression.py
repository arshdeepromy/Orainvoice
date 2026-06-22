"""Regression guard: the customer portal and fleet portal are untouched.

Implements: Organisation Employee Portal task 17.8 — Requirement 17.3.

R17.3: *WHEN the feature is deployed, THE existing customer portal
(``/portal/{token}``) and fleet portal (``/fleet/...``) SHALL continue to return
the same response content and status they returned before the feature was
deployed.*

The Employee Portal ships as a deliberate near-clone of the fleet portal, with
new routers (``/e/api/*``), a new ``organisations.slug`` column, new staff
uniqueness indexes, and new middleware prefixes. None of that may change the
*observable contract* of the two pre-existing portals. This test pins that
contract so an accidental regression (a removed/renamed route, a changed HTTP
method, a renamed or re-scoped session cookie, a changed error status, or a lost
no-store cache header) fails loudly.

What we assert as the **stable contract** (chosen to be meaningful without being
brittle — we assert that the known routes are still *present and unchanged*, not
that the route set is frozen, so legitimately adding a new customer/fleet
endpoint never trips this guard):

1. **Route registration** — every canonical token-addressed customer-portal
   route and every canonical fleet-portal route is still declared on its router
   with exactly the same path template and HTTP method(s).
2. **Cookie names + scoping** — the customer portal still issues/clears
   ``portal_session`` (HttpOnly) + ``portal_csrf`` (readable) scoped to ``/``;
   the fleet portal still issues ``fleet_portal_session`` (HttpOnly) +
   ``fleet_portal_csrf`` (readable) scoped to ``/fleet``. These cookie names are
   exactly what the Employee Portal must *not* collide with (R6.2/R16.8), so
   pinning them here doubles as the "no cross-portal cookie drift" guard.
3. **Representative request behaviour** —
   - customer portal: ``GET /api/v1/portal/{invalid-token}`` still returns
     ``400`` and every portal response still carries ``Cache-Control: no-store``
     + ``Pragma: no-cache`` (the ``PortalCacheRoute`` behaviour);
   - fleet portal: ``GET /fleet/api/version`` still returns ``200`` with the
     ``{version, build_sha}`` shape, and ``GET /fleet/api/me`` with no session
     cookie is still rejected ``401``.

Why mount the routers directly instead of ``app.main.create_app()``: the full
application factory imports the un-installed ``stripe`` package via the billing
router (a pre-existing sandbox limitation), so we mount **only** the genuine
customer-portal and fleet-portal routers under their production prefixes
(``/api/v1/portal`` and ``/fleet/api``) on minimal FastAPI apps and drive them
with an in-process ASGI transport — exactly the pattern used by task 17.5's
``tests/test_employee_portal_cross_portal_cookie_rejection.py``. The route table,
the dependency injection, the cookie helpers and the error handling are all the
real production code paths.

The DB-backed representative checks require the transactional dev Postgres at
``DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI, Response
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings
from app.core.database import get_db_session

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# tests, e.g. tests/test_employee_portal_cross_portal_cookie_rejection.py).
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

from app.modules.portal.router import router as customer_portal_router
from app.modules.fleet_portal.router import router as fleet_portal_router
from app.modules.fleet_portal import router as fleet_router_mod


# Production mount prefixes (see app/main.py).
_CUSTOMER_PREFIX = "/api/v1/portal"
_FLEET_PREFIX = "/fleet/api"


# ---------------------------------------------------------------------------
# Frozen "before deploy" route contracts.
#
# These are the canonical, pre-existing routes each portal exposed before the
# Employee Portal feature. We assert each is STILL present with the same
# method(s) — a removal, rename, or method change is a regression. We do NOT
# assert the route set is exactly equal, so adding new (unrelated) endpoints to
# either portal later never trips this guard.
# ---------------------------------------------------------------------------

_CUSTOMER_PORTAL_CONTRACT: set[tuple[str, str]] = {
    ("POST", "/logout"),
    ("POST", "/recover"),
    ("POST", "/stripe-webhook"),
    ("GET", "/{token}"),
    ("GET", "/{token}/invoices"),
    ("GET", "/{token}/invoices/{invoice_id}/pdf"),
    ("GET", "/{token}/vehicles"),
    ("GET", "/{token}/jobs"),
    ("GET", "/{token}/claims"),
    ("GET", "/{token}/quotes"),
    ("POST", "/{token}/quotes/{quote_id}/accept"),
    ("GET", "/{token}/assets"),
    ("GET", "/{token}/bookings"),
    ("POST", "/{token}/bookings"),
    ("GET", "/{token}/bookings/slots"),
    ("PATCH", "/{token}/bookings/{booking_id}/cancel"),
    ("POST", "/{token}/pay/{invoice_id}"),
    ("GET", "/{token}/messages"),
    ("GET", "/{token}/loyalty"),
    ("GET", "/{token}/documents"),
    ("PATCH", "/{token}/profile"),
}

_FLEET_PORTAL_CONTRACT: set[tuple[str, str]] = {
    ("GET", "/version"),
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/forgot-password"),
    ("POST", "/auth/reset-password/{token}"),
    ("GET", "/auth/invite-status/{token}"),
    ("POST", "/auth/accept-invite/{token}"),
    ("GET", "/me"),
    ("GET", "/vehicles"),
    ("GET", "/vehicles/{vehicle_id}"),
    ("POST", "/vehicles/{vehicle_id}/odometer"),
    ("GET", "/dashboard"),
    ("GET", "/drivers"),
    ("POST", "/drivers/invite"),
}


def _route_pairs(router) -> set[tuple[str, str]]:
    """Flatten an APIRouter into a set of ``(METHOD, path)`` pairs."""
    pairs: set[tuple[str, str]] = set()
    for route in router.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if path is None:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            pairs.add((method, path))
    return pairs


# ---------------------------------------------------------------------------
# (1) Route registration unchanged
# ---------------------------------------------------------------------------


def test_customer_portal_route_contract_unchanged() -> None:
    """Every canonical customer-portal route is still present + unchanged (R17.3)."""
    actual = _route_pairs(customer_portal_router)
    missing = _CUSTOMER_PORTAL_CONTRACT - actual
    assert not missing, f"customer portal routes changed/removed: {sorted(missing)}"


def test_fleet_portal_route_contract_unchanged() -> None:
    """Every canonical fleet-portal route is still present + unchanged (R17.3)."""
    actual = _route_pairs(fleet_portal_router)
    missing = _FLEET_PORTAL_CONTRACT - actual
    assert not missing, f"fleet portal routes changed/removed: {sorted(missing)}"


# ---------------------------------------------------------------------------
# (2) Cookie names + scoping unchanged
# ---------------------------------------------------------------------------


def _set_cookie_headers(response: httpx.Response | Response) -> list[str]:
    if isinstance(response, httpx.Response):
        return response.headers.get_list("set-cookie")
    return [
        v.decode() if isinstance(v, bytes) else v
        for (k, v) in response.raw_headers
        if (k.decode() if isinstance(k, bytes) else k).lower() == "set-cookie"
    ]


def test_customer_portal_cookie_names_and_scoping_unchanged() -> None:
    """The customer portal still uses ``portal_session``/``portal_csrf`` on ``/``.

    Driving ``POST /logout`` (no cookie presented) exercises the real cookie
    teardown path: both cookies are cleared, scoped to ``/``, with the session
    cookie HttpOnly and the CSRF cookie readable (R17.3; and the names the
    Employee Portal must not collide with — R6.2/R16.8).
    """

    async def _run() -> None:
        engine = create_async_engine(
            app_settings.database_url, pool_size=1, max_overflow=0
        )
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async def _override_db():
            async with factory() as session:
                async with session.begin():
                    yield session

        app = FastAPI()
        app.include_router(customer_portal_router, prefix=_CUSTOMER_PREFIX)
        app.dependency_overrides[get_db_session] = _override_db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                resp = await client.post(f"{_CUSTOMER_PREFIX}/logout")
                assert resp.status_code == 200, resp.text
                headers = _set_cookie_headers(resp)
                joined = "\n".join(headers)

                assert "portal_session=" in joined
                assert "portal_csrf=" in joined

                session_line = next(
                    c for c in headers if c.startswith("portal_session=")
                )
                csrf_line = next(c for c in headers if c.startswith("portal_csrf="))

                # Both scoped to the root path (unchanged).
                assert "Path=/" in session_line and "Path=/fleet" not in session_line
                assert "Path=/" in csrf_line and "Path=/fleet" not in csrf_line
                # Session cookie HttpOnly; CSRF cookie readable by JS.
                assert "HttpOnly" in session_line
                assert "HttpOnly" not in csrf_line
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_fleet_portal_cookie_names_and_scoping_unchanged() -> None:
    """The fleet portal still uses ``fleet_portal_session``/``fleet_portal_csrf`` on ``/fleet``."""
    # The cookie names are the source of truth the Employee Portal mirrors but
    # must never reuse — pin them.
    assert fleet_router_mod._SESSION_COOKIE_NAME == "fleet_portal_session"
    assert fleet_router_mod._CSRF_COOKIE_NAME == "fleet_portal_csrf"

    resp = Response()
    fleet_router_mod._set_session_cookies(
        resp, session_token="sess-tok", csrf_token="csrf-tok"
    )
    headers = _set_cookie_headers(resp)
    joined = "\n".join(headers)

    assert "fleet_portal_session=sess-tok" in joined
    assert "fleet_portal_csrf=csrf-tok" in joined

    session_line = next(c for c in headers if c.startswith("fleet_portal_session="))
    csrf_line = next(c for c in headers if c.startswith("fleet_portal_csrf="))

    # Both scoped to /fleet (unchanged — does not leak to the staff app or /e).
    assert "Path=/fleet" in session_line
    assert "Path=/fleet" in csrf_line
    # Session cookie HttpOnly; CSRF cookie readable by JS.
    assert "HttpOnly" in session_line
    assert "HttpOnly" not in csrf_line


# ---------------------------------------------------------------------------
# (3) Representative request behaviour unchanged
# ---------------------------------------------------------------------------


def test_customer_portal_representative_behaviour_unchanged() -> None:
    """``GET /api/v1/portal/{invalid}`` → 400 with no-store cache headers (R17.3)."""

    async def _run() -> None:
        # Use a per-test engine disposed within this loop and override the
        # route's DB dependency, so we never bind the global connection pool to
        # an ``asyncio.run`` loop that later closes (avoids cross-loop teardown).
        engine = create_async_engine(
            app_settings.database_url, pool_size=1, max_overflow=0
        )
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async def _override_db():
            async with factory() as session:
                async with session.begin():
                    yield session

        app = FastAPI()
        app.include_router(customer_portal_router, prefix=_CUSTOMER_PREFIX)
        app.dependency_overrides[get_db_session] = _override_db

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                resp = await client.get(
                    f"{_CUSTOMER_PREFIX}/this-is-not-a-valid-portal-token"
                )
                # Unchanged: an unrecognised token is rejected 400.
                assert resp.status_code == 400, resp.text
                # Unchanged: PortalCacheRoute pins no-store on every response.
                assert resp.headers.get("cache-control") == "no-store"
                assert resp.headers.get("pragma") == "no-cache"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_fleet_portal_representative_behaviour_unchanged() -> None:
    """``GET /fleet/api/version`` → 200 {version,build_sha}; ``/me`` no cookie → 401."""

    async def _run() -> None:
        engine = create_async_engine(
            app_settings.database_url, pool_size=1, max_overflow=0
        )
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async def _override_db():
            async with factory() as session:
                async with session.begin():
                    yield session

        app = FastAPI()
        app.include_router(fleet_portal_router, prefix=_FLEET_PREFIX)
        app.dependency_overrides[get_db_session] = _override_db

        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                ver = await client.get(f"{_FLEET_PREFIX}/version")
                assert ver.status_code == 200, ver.text
                assert set(ver.json().keys()) == {"version", "build_sha"}

                # Unchanged: an unauthenticated /me is rejected 401 (no session).
                me = await client.get(f"{_FLEET_PREFIX}/me")
                assert me.status_code == 401, me.text
        finally:
            await engine.dispose()

    asyncio.run(_run())
