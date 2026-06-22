"""Property-based test for onboarding token generation (Task 4.3).

Feature: staff-onboarding-link
Property 1: Token generation is well-formed and time-bounded

Exercises ``app.modules.staff.onboarding_tokens.mint`` against the real dev
Postgres database (mirroring the DB-backed Hypothesis pattern in
``tests/test_email_preview_editable_fragment.py`` /
``tests/test_email_compose_default_equivalence.py``). For each example we seed
one organisation + staff member, mint a sequence of onboarding tokens, and
assert the four guarantees the design promises for token generation:

1. **Entropy (R2.1)** — every RAW token returned by ``mint`` decodes (URL-safe
   base64) to at least 32 bytes of randomness (``secrets.token_urlsafe(32)``).
2. **Uniqueness** — no two mints (within an example, and globally across the
   whole run) ever collide on the raw token value.
3. **Single live row (R2.5)** — because ``mint`` revokes any prior *pending*
   token first, exactly one ``pending`` row exists for the staff member after
   any number of mints; all earlier rows are ``revoked``.
4. **Time-bound (R2.2, R2.3)** — the live token's ``expires_at`` equals
   ``created_at + 7 days`` (within a small clock-skew tolerance).

Validates: Requirements 2.1, 2.2, 2.3

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- The handful of helper functions create a fresh async engine per example
  (asyncpg connections are bound to the event loop ``asyncio.run`` creates),
  exactly like the reference DB-backed property tests in this repo.
"""

from __future__ import annotations

import asyncio
import base64
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
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_email_preview_editable_fragment.py).
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember, StaffOnboardingToken

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_4_3_token_gen"

# Allowed skew between the Python-computed ``expires_at`` and the DB-default
# ``created_at`` (network + clock skew between the app process and Postgres).
_SKEW_TOLERANCE_SECONDS = 10.0

# 7-day TTL the service promises (kept local so the test fails loudly if the
# service constant ever drifts).
_EXPECTED_TTL_SECONDS = 7 * 24 * 60 * 60

# Accumulates every raw token minted across ALL Hypothesis examples so we can
# assert global uniqueness (no collisions anywhere in the run).
_ALL_RAW_TOKENS: set[str] = set()


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


async def _cleanup(factory) -> None:
    """Delete every row created by the seeder (keyed on the org-name marker).

    ``staff_onboarding_tokens`` and ``staff_members`` are removed via the
    ON DELETE CASCADE from ``organisations``, but we delete them explicitly
    first to keep the intent obvious and the teardown order safe.
    """
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in ("staff_onboarding_tokens", "staff_members"):
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


async def _seed_org_and_staff(factory) -> dict:
    """Seed one org + one active staff member; return their ids."""
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

            staff = StaffMember(
                org_id=org.id,
                name="Onboarding Test Staff",
                first_name="Onboarding",
                last_name="Tester",
                email="onboard-test@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


# ---------------------------------------------------------------------------
# Entropy decoding helper.
# ---------------------------------------------------------------------------


def _urlsafe_decoded_len(raw: str) -> int:
    """Decode a ``secrets.token_urlsafe`` value and return its byte length.

    ``token_urlsafe`` emits unpadded URL-safe base64, so we restore the
    stripped ``=`` padding before decoding.
    """
    padding = "=" * (-len(raw) % 4)
    return len(base64.urlsafe_b64decode(raw + padding))


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(num_mints: int) -> list[str]:
    """Seed, mint ``num_mints`` tokens, assert the four guarantees, clean up.

    Returns the list of raw tokens minted so the caller can fold them into the
    global uniqueness set.
    """
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        raw_tokens: list[str] = []
        async with factory() as session:
            async with session.begin():
                for _ in range(num_mints):
                    raw = await onboarding_tokens.mint(
                        session, org_id=org_id, staff_id=staff_id
                    )
                    raw_tokens.append(raw)

        # --- 1. Entropy (R2.1): every raw token >= 32 bytes of randomness. ---
        for raw in raw_tokens:
            assert isinstance(raw, str) and raw, "mint must return a non-empty raw token"
            decoded_len = _urlsafe_decoded_len(raw)
            assert decoded_len >= 32, (
                f"token {raw!r} decodes to {decoded_len} bytes, expected >= 32"
            )

        # --- 2. Uniqueness: no collisions within this example. ---
        assert len(set(raw_tokens)) == len(raw_tokens), (
            "mint produced a duplicate raw token within one staff member"
        )

        # --- 3. Single live row (R2.5) + correct row accounting. ---
        async with factory() as session:
            pending_count = (
                await session.execute(
                    select(func.count())
                    .select_from(StaffOnboardingToken)
                    .where(
                        StaffOnboardingToken.org_id == org_id,
                        StaffOnboardingToken.staff_id == staff_id,
                        StaffOnboardingToken.status == "pending",
                    )
                )
            ).scalar_one()
            total_count = (
                await session.execute(
                    select(func.count())
                    .select_from(StaffOnboardingToken)
                    .where(
                        StaffOnboardingToken.org_id == org_id,
                        StaffOnboardingToken.staff_id == staff_id,
                    )
                )
            ).scalar_one()

            assert pending_count == 1, (
                f"expected exactly one pending token after {num_mints} mints, "
                f"got {pending_count}"
            )
            assert total_count == num_mints, (
                f"expected {num_mints} total rows (1 pending + "
                f"{num_mints - 1} revoked), got {total_count}"
            )

            # --- 4. Time-bound (R2.2, R2.3): expires_at == created_at + 7d. ---
            live = (
                await session.execute(
                    select(StaffOnboardingToken).where(
                        StaffOnboardingToken.org_id == org_id,
                        StaffOnboardingToken.staff_id == staff_id,
                        StaffOnboardingToken.status == "pending",
                    )
                )
            ).scalar_one()

            assert live.expires_at is not None and live.created_at is not None
            ttl_seconds = (live.expires_at - live.created_at).total_seconds()
            assert abs(ttl_seconds - _EXPECTED_TTL_SECONDS) <= _SKEW_TOLERANCE_SECONDS, (
                f"expires_at - created_at = {ttl_seconds}s, expected "
                f"{_EXPECTED_TTL_SECONDS}s (±{_SKEW_TOLERANCE_SECONDS}s)"
            )
            # The live token's hash must match the last raw token minted.
            assert live.token_hash == onboarding_tokens._hash_token(raw_tokens[-1]), (
                "the surviving pending row must correspond to the most recent mint"
            )

        return raw_tokens
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 1: Token generation is well-formed and time-bounded.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(num_mints=st.integers(min_value=1, max_value=6))
def test_token_generation_is_well_formed_and_time_bounded(num_mints: int):
    """Property 1: Token generation is well-formed and time-bounded.

    For any number of sequential mints against a staff member, every RAW token
    carries >= 32 bytes of entropy and is unique, exactly one ``pending`` row
    survives (``mint`` revokes prior pending tokens), and that row's
    ``expires_at`` equals ``created_at + 7 days``.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    raw_tokens = asyncio.run(_run_example(num_mints))

    # Global uniqueness across every example in the run (random 256-bit tokens
    # must never collide anywhere).
    for raw in raw_tokens:
        assert raw not in _ALL_RAW_TOKENS, (
            f"token {raw!r} collided with a token minted in another example"
        )
        _ALL_RAW_TOKENS.add(raw)


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
