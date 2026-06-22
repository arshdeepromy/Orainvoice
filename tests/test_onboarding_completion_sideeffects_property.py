"""Property-based test for onboarding completion side-effects (Task 8.13).

Feature: staff-onboarding-link
Property 26: Successful submit fires the completion side-effects; a draft save
fires none.

Drives the REAL public onboarding endpoints end-to-end through an in-process
ASGI client (``httpx.AsyncClient`` + ``ASGITransport``):

  * ``POST /api/v2/public/staff-onboarding/{token}``      → ``onboarding_submit``
  * ``PUT  /api/v2/public/staff-onboarding/{token}/draft`` → ``onboarding_save_draft``

Both routes are public (the auth middleware bypasses ``/api/v2/public/``), so no
JWT is required. The DB harness mirrors the other DB-backed onboarding property
tests in this repo (fresh async engine per example, full ORM import block,
``_ORG_MARKER`` cleanup, ``_seed_*`` helpers, ``@settings`` with health-check
suppression, and an ``asyncio.run`` driver).

For every example we seed TWO organisations + one active staff member (in org-1)
plus a generated set of ``users`` rows spread across both orgs with varying
roles (``org_admin`` / ``branch_admin`` / ``salesperson``), active flags, and
case-varied emails (to exercise the recipient resolver's case-insensitive
dedup). We then mint a pending onboarding token, and against the SAME seed:

1. **Draft save fires NONE (R15.5, R16.5)** — ``PUT /{token}/draft`` creates no
   in-app notification and attempts no confirmation or notification email.
2. **Submit fires the completion side-effects (R15.1, R16.1–R16.4)** —
   ``POST /{token}`` produces EXACTLY ONE org-scoped in-app notification
   (audience ``["org_admin","branch_admin"]``, ``entity_type="staff_member"``,
   ``entity_id=staff.id``, ``link_url="/staff/{id}"``), attempts EXACTLY ONE
   staff confirmation email, and sends one org-completion email per distinct
   active ``org_admin``/``branch_admin`` user of THIS org only (deduped by email,
   never another org's users).

Validates: Requirements 15.1, 15.5, 16.1, 16.2, 16.3, 16.4, 16.5

Side-effect isolation strategy (record calls without performing I/O):

  * ``app.modules.staff.public_router.create_in_app_notification`` → ``AsyncMock``
    so the in-transaction notification is recorded (and asserted) without
    touching the notifications schema.
  * ``onboarding_delivery.send_onboarding_confirmation_email`` → ``AsyncMock`` so
    the staff confirmation attempt is counted (and, being mocked, its internal
    ``send_email`` never fires — cleanly separating it from the org emails).
  * ``onboarding_delivery.send_email`` → ``AsyncMock`` so each org-completion
    email is recorded by its ``message.to_email``.
  * ``resolve_org_notification_recipients`` and ``compose_org_completion_email``
    run REAL against the DB so the org-scope / active-filter / dedup logic that
    R16.3/R16.4 demand is genuinely exercised, not stubbed.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_onboarding_persist_identity_property.py).
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

from app.core.database import get_db_session
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_13_completion_sfx"

# Seeded staff identity (the staff confirmation email targets this address).
_STAFF_FIRST_NAME = "Onboarding"
_STAFF_EMAIL = "onboard-8-13@example.com"

# Email domains: org-1 admins vs org-2 (other org) admins live on distinct
# domains so the global UNIQUE(users.email) constraint is never violated and so
# "another org's user" is unmistakable in assertions.
_THIS_ORG_DOMAIN = "org1.test"
_OTHER_ORG_DOMAIN = "org2.test"

# Small local-part pool so case variants collide → exercises dedup.
_EMAIL_LOCALS = ("alice", "bob", "carol", "dave")
_ADMIN_ROLES = ("org_admin", "branch_admin")


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        poolclass=NullPool,
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
                "app_notifications",
                "compliance_documents",
                "staff_onboarding_tokens",
                "staff_members",
                "users",
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


async def _seed(factory, user_rows: list[dict]) -> dict:
    """Seed two orgs + one active staff member (org-1) + the given user rows.

    ``user_rows`` items: ``{"email", "role", "active", "other_org"}``. Returns
    the ids the test needs (org-1 id, org-2 id, staff id).
    """
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan",
                monthly_price_nzd=0,
                user_seats=50,
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
                settings={},
            )
            org2 = Organisation(
                name=f"{_ORG_MARKER}_2_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add_all([org1, org2])
            await session.flush()

            staff = StaffMember(
                org_id=org1.id,
                name="Onboarding Test Staff",
                first_name=_STAFF_FIRST_NAME,
                last_name="OriginalLast",
                email=_STAFF_EMAIL,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            for row in user_rows:
                session.add(
                    User(
                        org_id=org2.id if row["other_org"] else org1.id,
                        email=row["email"],
                        role=row["role"],
                        is_active=row["active"],
                    )
                )
            await session.flush()

            return {
                "org1_id": org1.id,
                "org2_id": org2.id,
                "staff_id": staff.id,
            }


def _build_app(factory) -> FastAPI:
    """Build an app exposing ONLY the public onboarding router at the prod path."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    async def _override_db():
        async with factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(
        onboarding_public_router, prefix="/api/v2/public/staff-onboarding"
    )
    return app


# ---------------------------------------------------------------------------
# Generators — vary the recipient set (counts, dup emails, other-org, inactive).
# ---------------------------------------------------------------------------

_user_spec = st.fixed_dictionaries(
    {
        "local": st.sampled_from(_EMAIL_LOCALS),
        # Uppercase the local part → a case-variant of the same address so the
        # resolver's case-insensitive dedup is exercised.
        "upper": st.booleans(),
        "role": st.sampled_from(("org_admin", "branch_admin", "salesperson")),
        "active": st.booleans(),
        "other_org": st.booleans(),
    }
)

_users_strategy = st.lists(_user_spec, min_size=0, max_size=8)


def _materialise_users(specs: list[dict]) -> tuple[list[dict], set[str]]:
    """Turn generated specs into seedable user rows + the expected recipient set.

    De-dupes by the EXACT (case-sensitive) email string so the global
    ``UNIQUE(users.email)`` constraint is never violated, while still allowing
    case-variant pairs (distinct case-sensitively) to flow through and exercise
    the resolver's case-insensitive dedup. The expected recipient set is the
    case-folded emails of the active ``org_admin``/``branch_admin`` users of
    THIS org only.
    """
    rows: list[dict] = []
    seen_email: set[str] = set()
    expected_lower: set[str] = set()

    for spec in specs:
        local = spec["local"].upper() if spec["upper"] else spec["local"]
        domain = _OTHER_ORG_DOMAIN if spec["other_org"] else _THIS_ORG_DOMAIN
        email = f"{local}@{domain}"
        if email in seen_email:
            continue
        seen_email.add(email)
        row = {
            "email": email,
            "role": spec["role"],
            "active": spec["active"],
            "other_org": spec["other_org"],
        }
        rows.append(row)
        if (
            not spec["other_org"]
            and spec["role"] in _ADMIN_ROLES
            and spec["active"]
        ):
            expected_lower.add(email.lower())

    return rows, expected_lower


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(specs: list[dict]) -> None:
    """Seed, mint, then exercise BOTH the draft save and the submit paths."""
    engine, factory = await _make_engine_and_factory()
    try:
        user_rows, expected_lower = _materialise_users(specs)
        ids = await _seed(factory, user_rows)
        org1_id = ids["org1_id"]
        staff_id = ids["staff_id"]

        # Mint a pending token; capture the RAW token for the URL.
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org1_id, staff_id=staff_id
                )

        app = _build_app(factory)

        notif_mock = AsyncMock(return_value=None)
        confirm_mock = AsyncMock(return_value=None)
        send_email_mock = AsyncMock(return_value=None)

        with patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=notif_mock,
        ), patch(
            "app.modules.staff.onboarding_delivery.send_onboarding_confirmation_email",
            new=confirm_mock,
        ), patch(
            "app.modules.staff.onboarding_delivery.send_email",
            new=send_email_mock,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # ----- (1) DRAFT SAVE fires NONE (R15.5, R16.5) ------------
                draft_resp = await client.put(
                    f"/api/v2/public/staff-onboarding/{raw}/draft",
                    json={"last_name": "DraftLast", "phone": "021000000"},
                )
                assert draft_resp.status_code == 200, (
                    f"expected 200 from draft save, got "
                    f"{draft_resp.status_code}: {draft_resp.text}"
                )
                assert notif_mock.call_count == 0, (
                    "draft save must NOT create an in-app notification (R16.5)"
                )
                assert confirm_mock.call_count == 0, (
                    "draft save must NOT attempt a staff confirmation email (R15.5)"
                )
                assert send_email_mock.call_count == 0, (
                    "draft save must NOT attempt any org completion email (R16.5)"
                )

                # Reset before the submit so the counts below are submit-only.
                notif_mock.reset_mock()
                confirm_mock.reset_mock()
                send_email_mock.reset_mock()

                # ----- (2) SUBMIT fires the completion side-effects --------
                submit_resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}",
                    data={"last_name": "SubmittedLast"},
                )

        assert submit_resp.status_code == 200, (
            f"expected 200 from submit, got "
            f"{submit_resp.status_code}: {submit_resp.text}"
        )
        assert submit_resp.json().get("ok") is True, f"submit not ok: {submit_resp.text}"

        # --- In-app notification: EXACTLY ONE, correctly targeted (R16.1/2/4) ---
        assert notif_mock.call_count == 1, (
            f"submit must create EXACTLY ONE in-app notification, got "
            f"{notif_mock.call_count}"
        )
        notif_kwargs = notif_mock.call_args.kwargs
        assert notif_kwargs.get("org_id") == org1_id, (
            "in-app notification must be org-scoped to the token's org (R16.4)"
        )
        assert notif_kwargs.get("audience_roles") == ["org_admin", "branch_admin"], (
            "in-app notification audience must be [org_admin, branch_admin] (R16.1)"
        )
        assert notif_kwargs.get("entity_type") == "staff_member", (
            "in-app notification entity_type must be staff_member (R16.2)"
        )
        assert notif_kwargs.get("entity_id") == staff_id, (
            "in-app notification entity_id must be the completing staff id (R16.2)"
        )
        assert notif_kwargs.get("link_url") == f"/staff/{staff_id}", (
            "in-app notification must link to the staff detail page (R16.2)"
        )
        assert notif_kwargs.get("category") == "staff_onboarding"

        # --- Staff confirmation email: attempted EXACTLY ONCE (R15.1) -----
        assert confirm_mock.call_count == 1, (
            f"submit must attempt EXACTLY ONE staff confirmation email, got "
            f"{confirm_mock.call_count}"
        )
        confirm_kwargs = confirm_mock.call_args.kwargs
        assert confirm_kwargs.get("staff_email") == _STAFF_EMAIL, (
            "staff confirmation email must target the staff member's own address (R15.1)"
        )

        # --- Org completion emails: one per distinct active admin of THIS org,
        #     deduped, never another org's user (R16.3, R16.4) ---------------
        recorded = [call.args[1].to_email for call in send_email_mock.call_args_list]
        recorded_lower = [e.lower() for e in recorded]

        # No duplicates were sent (deduped by email).
        assert len(recorded_lower) == len(set(recorded_lower)), (
            f"org completion emails must be deduped, got duplicates in {recorded}"
        )
        # Exactly the expected set of this-org active admins (case-folded).
        assert set(recorded_lower) == expected_lower, (
            f"org completion recipients mismatch: got {sorted(set(recorded_lower))}, "
            f"expected {sorted(expected_lower)}"
        )
        # Belt-and-braces: never another org's domain.
        assert all(not e.endswith(f"@{_OTHER_ORG_DOMAIN}") for e in recorded_lower), (
            f"org completion email leaked to another org's user: {recorded}"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 26: Successful submit fires the completion side-effects; a draft
# save fires none.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(specs=_users_strategy)
def test_completion_side_effects_on_submit_vs_draft(specs: list[dict]):
    """Property 26: submit fires the completion side-effects; a draft save fires none.

    Driving the real public onboarding endpoints: a ``PUT /{token}/draft`` fires
    NO in-app notification and NO email; a subsequent ``POST /{token}`` produces
    EXACTLY ONE correctly-targeted, org-scoped in-app notification, attempts
    EXACTLY ONE staff confirmation email, and sends one org-completion email per
    distinct active ``org_admin``/``branch_admin`` user of THIS org only (deduped
    by email, never another org's users).

    **Validates: Requirements 15.1, 15.5, 16.1, 16.2, 16.3, 16.4, 16.5**
    """
    asyncio.run(_run_example(specs))


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
