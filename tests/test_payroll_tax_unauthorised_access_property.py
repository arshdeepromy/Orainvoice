"""Property-based test for Property 6: unauthorised access is rejected and audited.

# Feature: payroll-tax-settings, Property 6: Unauthorised access is rejected and audited

Exercises the two authorisation surfaces of the Payroll_Tax_Settings feature
(spec tasks 8.1, 8.2) against the real dev Postgres database, mirroring the
DB-backed Hypothesis pattern used by the other payroll-tax property tests
(e.g. ``tests/test_payroll_tax_audited_changes_property.py`` and
``tests/test_payroll_tax_persistence_roundtrip_property.py``): a fresh async
engine per example (asyncpg connections are bound to the event loop
``asyncio.run`` creates).

The property under test
-----------------------
For any user role that is **not authorised** for a tier, a view/modify request
is rejected with an authorisation error, no configuration is persisted, and an
access-denied entry is recorded in the ``audit_log``:

* **Org tier** (``/api/v2/payroll-tax-settings``) — any authenticated role other
  than ``org_admin``. The sole gate is the route dependency
  :func:`audit_denied_tax_access` (``app/modules/payroll_tax/dependencies.py``):
  calling it with a non-``org_admin`` role raises ``HTTPException(403)`` and
  writes a ``payroll_tax.org.access_denied`` audit entry **out-of-band** (a fresh
  committing session).

* **Platform tier** (``/api/v2/admin/platform-tax-default``) — denied roles are
  pre-empted by :class:`RBACMiddleware` (``app/middleware/rbac.py``) *before* the
  route runs, which both returns ``403`` and writes a
  ``payroll_tax.platform.access_denied`` audit entry out-of-band (Req 2.3). This
  test drives the middleware as an ASGI app and asserts the ``403`` response, the
  audit row, and that the downstream route is **never reached** (so nothing is
  persisted).

  Note: ``check_role_path_access`` denies ``org_admin``, ``branch_admin``,
  ``location_manager``, ``staff_member``, ``franchise_admin`` and ``kiosk`` on the
  ``/api/v2/admin/`` prefix, so the middleware-level denial audit fires for those.
  ``salesperson`` is *not* matched by the middleware's ``/api/v2/admin/`` rules
  (it only denies ``/api/v1/admin/``); its denial is handled by the route's
  defence-in-depth ``require_role("global_admin")`` instead, which is outside the
  middleware audit path — so it is excluded from the platform-tier role set here.

Cleanup
-------
Both denial audits are written **out-of-band on a fresh ``async_session_factory``
session that COMMITS independently** of any test transaction. Each example
therefore generates unique ``user_id``/``org_id`` UUIDs and, after asserting the
audit row exists, deletes the ``audit_log`` rows it created (filtered by the
unique ``user_id``) using a committing session, so nothing leaks between
examples. The test connection is the ``postgres`` superuser (see
``docker-compose.yml``), which bypasses the ``REVOKE DELETE`` on ``audit_log``,
so this cleanup is permitted.

**Validates: Requirements 2.3, 3.5**
"""

from __future__ import annotations

import asyncio
import json
import uuid

import sqlalchemy as sa
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests in this repo).
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
from app.modules.payroll_tax import models as _payroll_tax_models  # noqa: F401

from app.middleware.rbac import RBACMiddleware
from app.modules.payroll_tax.dependencies import audit_denied_tax_access

# A single persistent event loop is shared across all Hypothesis examples. The
# production code under test (``audit_denied_tax_access`` / ``RBACMiddleware``)
# writes its denial audit via the app's *global* ``async_session_factory``, whose
# asyncpg connection pool binds to the first event loop that uses it. Using
# ``asyncio.run`` per example would create a new loop each time and the cached
# pool would raise "attached to a different loop"; one persistent loop avoids it.
_LOOP: asyncio.AbstractEventLoop | None = None


def _run_sync(coro):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


ORG_TIER_PATH = "/api/v2/payroll-tax-settings"
PLATFORM_TIER_PATH = "/api/v2/admin/platform-tax-default"

# Any authenticated role other than ``org_admin`` is unauthorised for the org
# tier; ``audit_denied_tax_access`` audits + 403s every one of them.
ORG_DENIED_ROLES = [
    "global_admin",
    "salesperson",
    "branch_admin",
    "location_manager",
    "staff_member",
    "franchise_admin",
    "kiosk",
]

# Roles that ``check_role_path_access`` denies on the ``/api/v2/admin/`` prefix,
# i.e. the roles for which RBACMiddleware emits the platform denial audit. (See
# module docstring on why ``salesperson``/``global_admin`` are excluded.)
PLATFORM_DENIED_ROLES = [
    "org_admin",
    "branch_admin",
    "location_manager",
    "staff_member",
    "franchise_admin",
    "kiosk",
]

_METHODS = ["GET", "PUT"]


def _as_obj(value):
    """Coerce a JSONB column value (returned as a str by asyncpg) to Python."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _make_request(*, method: str, path: str, role: str, user_id, org_id) -> Request:
    """Build a minimal Starlette ``Request`` with the auth fields the gate reads."""
    scope = {
        "type": "http",
        "method": method,
        "scheme": "http",
        "server": ("testserver", 80),
        "path": path,
        "root_path": "",
        "query_string": b"",
        "headers": [(b"user-agent", b"pytest"), (b"host", b"testserver")],
        "state": {
            "user_id": str(user_id),
            "role": role,
            "org_id": str(org_id),
            "client_ip": "127.0.0.1",
        },
    }
    return Request(scope)


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


async def _fetch_denial_audit(session: AsyncSession, *, action: str, user_id) -> dict | None:
    row = (
        await session.execute(
            sa.text(
                """
                SELECT user_id, org_id, entity_type, after_value
                FROM audit_log
                WHERE action = :action AND user_id = :uid
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"action": action, "uid": str(user_id)},
        )
    ).mappings().first()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "org_id": row["org_id"],
        "entity_type": row["entity_type"],
        "after_value": _as_obj(row["after_value"]),
    }


async def _delete_audit_rows_for_user(factory, user_id) -> None:
    """Remove the out-of-band (committed) audit rows this example created."""
    async with factory() as session:
        async with session.begin():
            await session.execute(
                sa.text("DELETE FROM audit_log WHERE user_id = :uid"),
                {"uid": str(user_id)},
            )


# ---------------------------------------------------------------------------
# Org-tier driver: the sole gate dependency rejects + audits directly.
# ---------------------------------------------------------------------------


async def _run_org_example(role: str, method: str) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
    request = _make_request(
        method=method,
        path=ORG_TIER_PATH,
        role=role,
        user_id=user_id,
        org_id=org_id,
    )

    engine, factory = await _make_engine_and_factory()
    try:
        # --- The gate must reject the unauthorised role with a 403. ---
        raised: HTTPException | None = None
        try:
            await audit_denied_tax_access(request)
        except HTTPException as exc:
            raised = exc
        assert raised is not None, (
            f"org tier: role {role!r} should be rejected but no HTTPException raised"
        )
        assert raised.status_code == 403, (
            f"org tier: role {role!r} should be rejected with 403, got {raised.status_code}"
        )

        async with factory() as session:
            # --- An access-denied audit entry was recorded (Req 3.5). ---
            audit = await _fetch_denial_audit(
                session, action="payroll_tax.org.access_denied", user_id=user_id
            )
            assert audit is not None, (
                f"org tier: no payroll_tax.org.access_denied audit for role {role!r}"
            )
            assert str(audit["user_id"]) == str(user_id)
            assert str(audit["org_id"]) == str(org_id)
            assert audit["entity_type"] == "org_tax_settings"
            assert audit["after_value"]["role"] == role
            assert audit["after_value"]["path"] == ORG_TIER_PATH
            assert audit["after_value"]["method"] == method

            # --- Nothing was persisted: no org_tax_settings row for this org. ---
            cnt = await session.scalar(
                sa.text("SELECT count(*) FROM org_tax_settings WHERE org_id = :oid"),
                {"oid": str(org_id)},
            )
            assert cnt == 0, (
                f"org tier: a denied request must not persist config; found {cnt} rows"
            )

        await _delete_audit_rows_for_user(factory, user_id)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Platform-tier driver: RBACMiddleware rejects + audits before the route runs.
# ---------------------------------------------------------------------------


async def _run_platform_example(role: str, method: str) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    sent: list[dict] = []
    downstream_called = {"v": False}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def downstream_app(scope, receive, send):
        # If this runs, the middleware failed to pre-empt the unauthorised role,
        # so the (persisting) route would be reachable — a failure for Req 2.3.
        downstream_called["v"] = True
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": b"{}"})

    scope = {
        "type": "http",
        "method": method,
        "scheme": "http",
        "server": ("testserver", 80),
        "path": PLATFORM_TIER_PATH,
        "root_path": "",
        "query_string": b"",
        "headers": [(b"user-agent", b"pytest"), (b"host", b"testserver")],
        "state": {
            "user_id": str(user_id),
            "role": role,
            "org_id": str(org_id),
            "client_ip": "127.0.0.1",
        },
    }

    engine, factory = await _make_engine_and_factory()
    try:
        await RBACMiddleware(downstream_app)(scope, receive, send)

        # --- The middleware must reject with a 403 before the route runs. ---
        start = next((m for m in sent if m["type"] == "http.response.start"), None)
        assert start is not None, (
            f"platform tier: role {role!r} produced no HTTP response"
        )
        assert start["status"] == 403, (
            f"platform tier: role {role!r} should be rejected with 403, got {start['status']}"
        )
        assert downstream_called["v"] is False, (
            f"platform tier: the route must not be reached for denied role {role!r} "
            "(nothing may be persisted)"
        )

        async with factory() as session:
            # --- An access-denied audit entry was recorded (Req 2.3). ---
            audit = await _fetch_denial_audit(
                session, action="payroll_tax.platform.access_denied", user_id=user_id
            )
            assert audit is not None, (
                f"platform tier: no payroll_tax.platform.access_denied audit for role {role!r}"
            )
            assert str(audit["user_id"]) == str(user_id)
            # Platform actions are non-org-scoped — org_id recorded as NULL.
            assert audit["org_id"] is None
            assert audit["entity_type"] == "platform_tax_default"
            assert audit["after_value"]["role"] == role
            assert audit["after_value"]["path"] == PLATFORM_TIER_PATH
            assert audit["after_value"]["method"] == method

        await _delete_audit_rows_for_user(factory, user_id)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Scenario strategy — one unauthorised access attempt against either tier.
# ---------------------------------------------------------------------------


@st.composite
def _scenario(draw):
    tier = draw(st.sampled_from(["org", "platform"]))
    method = draw(st.sampled_from(_METHODS))
    if tier == "org":
        role = draw(st.sampled_from(ORG_DENIED_ROLES))
    else:
        role = draw(st.sampled_from(PLATFORM_DENIED_ROLES))
    return {"tier": tier, "role": role, "method": method}


async def _run_example(scenario: dict) -> None:
    if scenario["tier"] == "org":
        await _run_org_example(scenario["role"], scenario["method"])
    else:
        await _run_platform_example(scenario["role"], scenario["method"])


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_scenario())
def test_unauthorised_access_is_rejected_and_audited(scenario: dict):
    """Property 6: Unauthorised access is rejected and audited.

    # Feature: payroll-tax-settings, Property 6: Unauthorised access is rejected and audited

    For any role that is not authorised for a tier (any role other than
    ``org_admin`` for the org settings, any role other than ``global_admin`` for
    the platform default), a view/modify request is rejected with a 403, no
    configuration is persisted, and an access-denied ``audit_log`` entry is
    recorded.

    **Validates: Requirements 2.3, 3.5**
    """
    _run_sync(_run_example(scenario))
