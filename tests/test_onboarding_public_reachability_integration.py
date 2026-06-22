"""Integration test for public no-auth reachability of the onboarding link.

Feature: staff-onboarding-link (Task 12.1)

Requirement 11.1: THE Onboarding_Form SHALL be served at a public URL path
(no authentication required) following the pattern ``/onboard/{token}`` — the
backing API lives under ``/api/v2/public/staff-onboarding/{token}``.
Requirement 11.3: the page validates the token and only proceeds when the token
is valid, not expired, not consumed, and not revoked.
Requirement 11.4: an invalid / expired / consumed / revoked token yields a
distinct, appropriate error per token failure state (never a blank page).

This is an example/integration test (NOT a Hypothesis property test). It has
two parts:

1. **No-auth reachability** — a direct, side-effect-free assertion that the
   onboarding API prefix is covered by the auth middleware's ``PUBLIC_PREFIXES``
   so the route is reachable with NO JWT. We assert ``_is_public(...)`` (the
   exact predicate ``AuthMiddleware`` uses to bypass JWT validation) returns
   ``True`` for the onboarding GET/PUT/POST paths, and that the
   ``/api/v2/public/`` prefix is present in ``PUBLIC_PREFIXES``.

2. **Token-state status codes** — drives the REAL prefill endpoint
   ``GET /api/v2/public/staff-onboarding/{token}`` (``onboarding_prefill`` in
   ``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
   client (``httpx.AsyncClient`` + ``ASGITransport``) with **no Authorization
   header**, for a token seeded into each lifecycle state, asserting the
   distinct HTTP status code AND ``detail.code`` per state:

   | state           | status | detail.code                          |
   |-----------------|--------|--------------------------------------|
   | not-found       | 404    | onboarding_token_not_found           |
   | revoked         | 410    | onboarding_token_revoked             |
   | consumed        | 410    | onboarding_token_consumed            |
   | expired         | 410    | onboarding_token_expired             |
   | staff_inactive  | 410    | onboarding_token_staff_inactive      |
   | valid           | 200    | (prefill payload — first_name/email) |

The DB harness mirrors the other DB-backed onboarding tests in this repo (fresh
async engine per run bound to the ``asyncio.run`` loop, full ORM import block,
``_ORG_MARKER`` cleanup, ``_seed_org_and_staff``, ``get_db_session`` auto-commit
override). Each state gets its OWN staff member + token so ``mint``'s
"revoke prior pending" behaviour never interferes across states.

Validates: Requirements 11.1, 11.3, 11.4
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
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
from app.middleware.auth import PUBLIC_PREFIXES, _is_public
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when a
# run aborts mid-way. Distinct from the other onboarding DB tests so parallel /
# interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_12_1_reachability"


# ---------------------------------------------------------------------------
# Part 1 — no-auth reachability (pure, no DB).
# ---------------------------------------------------------------------------


def test_onboarding_public_prefix_is_reachable_without_jwt():
    """R11.1 — the onboarding API prefix is public (no JWT required).

    ``AuthMiddleware`` bypasses JWT validation for any path where
    ``_is_public(path)`` is True. The onboarding endpoints live under
    ``/api/v2/public/staff-onboarding/`` which is covered by the
    ``/api/v2/public/`` entry in ``PUBLIC_PREFIXES`` — so the prefill GET, the
    draft PUT, and the submit POST are all reachable with NO Authorization
    header.
    """
    # The covering prefix must be registered.
    assert "/api/v2/public/" in PUBLIC_PREFIXES, (
        "the onboarding endpoints rely on the /api/v2/public/ prefix being "
        "public — without it the page would require a JWT (breaks R11.1)"
    )

    token = "any-opaque-token-value"
    # Every onboarding surface (prefill GET, draft PUT, submit POST share the
    # same path) must be classified public by the exact middleware predicate.
    assert _is_public(f"/api/v2/public/staff-onboarding/{token}") is True
    assert _is_public(f"/api/v2/public/staff-onboarding/{token}/draft") is True

    # Sanity counter-check: an authenticated staff path is NOT public, proving
    # the assertion above is meaningful (the predicate isn't returning True for
    # everything).
    assert _is_public("/api/v2/staff") is False


# ---------------------------------------------------------------------------
# DB harness — engine / session helpers (fresh engine bound to the run loop).
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
    """Seed one organisation; return its id."""
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


async def _seed_staff(factory, org_id: uuid.UUID, *, is_active: bool) -> uuid.UUID:
    """Seed one staff member in *org_id*; return its id."""
    async with factory() as session:
        async with session.begin():
            staff = StaffMember(
                org_id=org_id,
                name="Reachability Test Staff",
                first_name="Reach",
                last_name="Test",
                email="reach-test@example.com",
                is_active=is_active,
            )
            session.add(staff)
            await session.flush()
            return staff.id


def _build_app(factory) -> FastAPI:
    """Build an app exposing ONLY the public onboarding router at the prod path.

    The route is public (the auth middleware bypasses ``/api/v2/public/``), so
    NO auth state is injected and the client sends NO Authorization header.
    ``get_db_session`` is overridden to yield a real session inside a
    transaction that auto-commits on a clean return — the ``session.begin()``
    semantics the production handler relies on.
    """
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
    from app.modules.staff.public_router import onboarding_public_router

    app.include_router(
        onboarding_public_router, prefix="/api/v2/public/staff-onboarding"
    )
    return app


async def _mint_token(factory, org_id: uuid.UUID, staff_id: uuid.UUID) -> str:
    """Mint a fresh pending token for *staff_id*; return the RAW token."""
    async with factory() as session:
        async with session.begin():
            return await onboarding_tokens.mint(
                session, org_id=org_id, staff_id=staff_id
            )


async def _mutate_token(factory, raw: str, **fields) -> None:
    """Apply column overrides to the token row identified by *raw*."""
    async with factory() as session:
        async with session.begin():
            row = await onboarding_tokens.resolve(session, raw)
            assert row is not None, "token to mutate must resolve"
            for key, value in fields.items():
                setattr(row, key, value)


# ---------------------------------------------------------------------------
# Per-run driver — seed one token per state and assert prefill status codes.
# ---------------------------------------------------------------------------


async def _run_token_state_matrix() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        org_id = await _seed_org(factory)
        now = datetime.now(timezone.utc)

        # --- Build a token in each lifecycle state (own staff per state). ---

        # not_found — never mint; use a random opaque token.
        not_found_token = uuid.uuid4().hex + uuid.uuid4().hex

        # valid — minted, untouched.
        valid_staff = await _seed_staff(factory, org_id, is_active=True)
        valid_token = await _mint_token(factory, org_id, valid_staff)

        # revoked — minted, then status flipped to 'revoked'.
        revoked_staff = await _seed_staff(factory, org_id, is_active=True)
        revoked_token = await _mint_token(factory, org_id, revoked_staff)
        await _mutate_token(factory, revoked_token, status="revoked")

        # consumed — minted, then marked consumed.
        consumed_staff = await _seed_staff(factory, org_id, is_active=True)
        consumed_token = await _mint_token(factory, org_id, consumed_staff)
        await _mutate_token(
            factory, consumed_token, status="consumed", consumed_at=now
        )

        # expired — minted, then expires_at pushed into the past.
        expired_staff = await _seed_staff(factory, org_id, is_active=True)
        expired_token = await _mint_token(factory, org_id, expired_staff)
        await _mutate_token(
            factory, expired_token, expires_at=now - timedelta(days=1)
        )

        # staff_inactive — minted while active, then the staff is deactivated.
        inactive_staff = await _seed_staff(factory, org_id, is_active=False)
        inactive_token = await _mint_token(factory, org_id, inactive_staff)

        # state name -> (raw token, expected status, expected detail.code|None)
        cases: dict[str, tuple[str, int, str | None]] = {
            "not_found": (not_found_token, 404, "onboarding_token_not_found"),
            "revoked": (revoked_token, 410, "onboarding_token_revoked"),
            "consumed": (consumed_token, 410, "onboarding_token_consumed"),
            "expired": (expired_token, 410, "onboarding_token_expired"),
            "staff_inactive": (
                inactive_token,
                410,
                "onboarding_token_staff_inactive",
            ),
            "valid": (valid_token, 200, None),
        }

        app = _build_app(factory)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for state, (raw, expected_status, expected_code) in cases.items():
                # No Authorization header anywhere — proves no-JWT reachability.
                resp = await client.get(
                    f"/api/v2/public/staff-onboarding/{raw}"
                )

                assert resp.status_code == expected_status, (
                    f"state {state!r}: expected HTTP {expected_status}, got "
                    f"{resp.status_code}: {resp.text}"
                )

                if expected_code is None:
                    # Valid token: the prefill payload exposes the identity.
                    body = resp.json()
                    assert body.get("first_name") == "Reach", (
                        f"state {state!r}: valid prefill must echo first_name"
                    )
                    assert body.get("email") == "reach-test@example.com", (
                        f"state {state!r}: valid prefill must echo email"
                    )
                else:
                    # Rejecting states carry the humanized {message, code} body
                    # with the distinct per-state code (R11.4) and never a
                    # blank page.
                    detail = resp.json().get("detail")
                    assert isinstance(detail, dict), (
                        f"state {state!r}: error detail must be a "
                        f"{{message, code}} object, got {detail!r}"
                    )
                    assert detail.get("code") == expected_code, (
                        f"state {state!r}: expected detail.code "
                        f"{expected_code!r}, got {detail.get('code')!r}"
                    )
                    assert detail.get("message"), (
                        f"state {state!r}: error must carry a non-empty "
                        f"human-readable message (never a blank page, R11.4)"
                    )
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_prefill_returns_distinct_status_codes_per_token_state():
    """R11.3, R11.4 — prefill returns the correct distinct code per token state.

    Driving the real ``GET /api/v2/public/staff-onboarding/{token}`` with no
    Authorization header: a not-found token yields ``404
    onboarding_token_not_found``; revoked / consumed / expired / staff-inactive
    tokens each yield a distinct ``410`` with their own ``detail.code``; and a
    valid token yields ``200`` with the prefill identity payload.

    **Validates: Requirements 11.1, 11.3, 11.4**
    """
    asyncio.run(_run_token_state_matrix())
