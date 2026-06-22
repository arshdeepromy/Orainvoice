"""Property-based test for minimal public-prefill PII exposure (Task 8.12).

Feature: staff-onboarding-link
Property 18: Public prefill exposes only first name and email

Drives the REAL public prefill endpoint
``GET /api/v2/public/staff-onboarding/{token}`` (``onboarding_prefill`` in
``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
client (``httpx.AsyncClient`` + ``ASGITransport``) — the route is public so no
JWT is required. The DB harness mirrors the other DB-backed onboarding property
tests in this repo (fresh async engine per example, full ORM import block,
``_ORG_MARKER`` cleanup, ``_seed_org_and_staff``, ``@settings`` with
health-check suppression, and an ``asyncio.run`` driver).

For every example we seed one organisation and one **fully populated, active**
staff member — every PII column carries a recognizable, unique plaintext
sentinel (phone, position, employee_id, last_name, emergency contacts,
hourly_rate, and envelope-encrypted IRD/bank with their own plaintext
sentinels) — then mint a pending onboarding token and ``GET`` the prefill.

Two scenarios are parametrized:

(a) **no draft saved** — ``response.draft`` is ``null`` and the body carries
    only ``first_name`` / ``email`` of the staff identity plus org name, the
    static option lists, and ``bank_account_required``.
(b) **a draft saved** (via ``onboarding_tokens.save_draft`` with IRD/bank
    sentinels) — ``response.draft`` is present with ``ird_number`` /
    ``bank_account_number`` returned **masked** (``has_ird`` / ``has_bank``
    flags), and the raw response text never contains the IRD/bank plaintext
    sentinels.

In BOTH scenarios we serialize the full response JSON to a string and assert
it does NOT contain ANY of the staff PII plaintext sentinels (phone, position,
employee_id, last_name, emergency contacts, hourly_rate, IRD-plaintext,
bank-plaintext), and that the only staff-identity values exposed are exactly
``first_name`` and ``email``. ≥100 examples are generated per scenario.

Validates: Requirements 11.6

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
- The staff record's encrypted IRD/bank are NEVER read by the prefill path, so
  their plaintext sentinels must never appear. The draft's IRD/bank ARE read
  (decrypted server-side) but are exposed masked only — never as plaintext.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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
from app.core.encryption import envelope_encrypt
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.public_router import onboarding_public_router
from app.modules.staff.security import mask_bank_account, mask_ird

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_12_min_prefill"

# The exact set of top-level keys the prefill response is allowed to carry.
# The ONLY staff-identity values among these are ``first_name`` and ``email``;
# everything else is org chrome, static option lists, or the (masked) draft.
_ALLOWED_RESPONSE_KEYS = {
    "first_name",
    "email",
    "org_name",
    "tax_code_options",
    "residency_options",
    "kiwisaver_rate_options",
    "bank_account_required",
    "draft",
    "completion_percentage",
    "last_saved_at",
}


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


async def _seed_org_and_staff(factory, fixture: dict) -> dict:
    """Seed one org + one FULLY POPULATED active staff member; return ids/identity."""
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
                name=fixture["first_name"],
                first_name=fixture["first_name"],
                last_name=fixture["last_name_sentinel"],
                email=fixture["email"],
                # --- fully populated PII (each a recognizable sentinel) ---
                phone=fixture["phone_sentinel"],
                employee_id=fixture["empid_sentinel"],
                position=fixture["position_sentinel"],
                hourly_rate=fixture["hourly_rate"],
                tax_code="M",
                residency_type="citizen",
                emergency_contact_name=fixture["emerg_name_sentinel"],
                emergency_contact_phone=fixture["emerg_phone_sentinel"],
                ird_number_encrypted=envelope_encrypt(fixture["ird_plain_sentinel"]),
                bank_account_number_encrypted=envelope_encrypt(
                    fixture["bank_plain_sentinel"]
                ),
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {
                "org_id": org.id,
                "staff_id": staff.id,
                "first_name": staff.first_name,
                "email": staff.email,
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
    # Mirror app/main.py mount point for the onboarding public router.
    app.include_router(
        onboarding_public_router, prefix="/api/v2/public/staff-onboarding"
    )
    return app


# ---------------------------------------------------------------------------
# Generators — a fully-populated staff fixture with unique PII sentinels.
# ---------------------------------------------------------------------------

# Lowercase ASCII letters for the EXPOSED identity fields (first_name / email
# local part). Lowercase guarantees they can never collide with the UPPERCASE
# sentinel strings, so a case-sensitive substring search is meaningful.
_lower_alpha = st.text(
    alphabet=st.characters(min_codepoint=ord("a"), max_codepoint=ord("z")),
    min_size=1,
    max_size=12,
)

# A per-example unique marker (UPPERCASE letters + digits) that seeds every
# sentinel so each example's PII strings are unique and recognizable.
_marker = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="ABCDEFGHJKLMNPQRSTUVWXYZ23456789",
    ),
    min_size=8,
    max_size=12,
)


@st.composite
def _staff_fixture(draw) -> dict:
    """Build a fully-populated staff fixture with unique, recognizable sentinels."""
    marker = draw(_marker)
    first_name = draw(_lower_alpha)
    email_local = draw(_lower_alpha)
    # hourly_rate in a distinctive high range so its string never coincidentally
    # collides with option-list ints / percentages in the response body.
    rate_dollars = draw(st.integers(min_value=100000, max_value=9999999))

    return {
        "first_name": first_name,
        "email": f"{email_local}@example.com",
        # --- staff-record PII sentinels (must NEVER appear in the response) ---
        "last_name_sentinel": f"LASTNAMESENT{marker}",
        "phone_sentinel": f"PHONESENT{marker}",
        "empid_sentinel": f"EMPIDSENT{marker}",
        "position_sentinel": f"POSITIONSENT{marker}",
        "emerg_name_sentinel": f"EMERGNAMESENT{marker}",
        "emerg_phone_sentinel": f"EMERGPHONESENT{marker}",
        "ird_plain_sentinel": f"IRDPLAINSENT{marker}",
        "bank_plain_sentinel": f"BANKPLAINSENT{marker}",
        "hourly_rate": Decimal(rate_dollars),
        # --- draft IRD/bank sentinels (exposed MASKED only, scenario b) ---
        "draft_ird_sentinel": f"DRAFTIRDSENT{marker}123456789",
        "draft_bank_sentinel": f"DRAFTBANKSENT{marker}1234",
    }


def _pii_sentinels(fixture: dict) -> list[str]:
    """The full set of staff-record PII plaintext sentinels that must NOT leak."""
    return [
        fixture["last_name_sentinel"],
        fixture["phone_sentinel"],
        fixture["empid_sentinel"],
        fixture["position_sentinel"],
        fixture["emerg_name_sentinel"],
        fixture["emerg_phone_sentinel"],
        fixture["ird_plain_sentinel"],
        fixture["bank_plain_sentinel"],
        str(fixture["hourly_rate"]),
    ]


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(fixture: dict, *, with_draft: bool) -> None:
    """Seed, mint, optionally save a draft, GET prefill, assert minimal exposure."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory, fixture)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token; capture the RAW token for the URL. ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        # --- Scenario (b): save a draft carrying IRD/bank sentinels. ---
        if with_draft:
            async with factory() as session:
                async with session.begin():
                    row = await onboarding_tokens.resolve(session, raw)
                    assert row is not None, "minted token must resolve"
                    await onboarding_tokens.save_draft(
                        session,
                        row,
                        {
                            "ird_number": fixture["draft_ird_sentinel"],
                            "bank_account_number": fixture["draft_bank_sentinel"],
                            "tax_code": "M",
                            "documents_staged_count": 0,
                        },
                    )

        app = _build_app(factory)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/v2/public/staff-onboarding/{raw}")

        assert resp.status_code == 200, (
            f"expected 200 from prefill, got {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        blob = resp.text  # full serialized JSON for the leak scan

        # --- 1. Top-level keys never widen beyond the allowed schema set. ---
        assert set(body.keys()) <= _ALLOWED_RESPONSE_KEYS, (
            f"prefill exposed unexpected top-level keys: "
            f"{set(body.keys()) - _ALLOWED_RESPONSE_KEYS}"
        )

        # --- 2. The ONLY staff-identity values exposed are first_name+email. ---
        assert body["first_name"] == ids["first_name"], (
            "prefill must echo the seeded first_name (R11.6)"
        )
        assert body["email"] == ids["email"], (
            "prefill must echo the seeded email (R11.6)"
        )

        # --- 3. No staff-record PII plaintext sentinel appears ANYWHERE. ---
        for sentinel in _pii_sentinels(fixture):
            assert sentinel not in blob, (
                f"prefill leaked a staff PII sentinel ({sentinel!r}) — R11.6 "
                f"requires exposing nothing beyond first_name + email. Body: {blob}"
            )

        # --- 4. Draft exposure: present + masked (b) or absent (a). ---
        if with_draft:
            draft = body.get("draft")
            assert draft is not None, "scenario (b) must return the saved draft"
            assert draft.get("has_ird") is True, "draft must flag has_ird"
            assert draft.get("has_bank") is True, "draft must flag has_bank"

            # IRD/bank come back MASKED only — never the plaintext sentinel.
            assert draft.get("ird_number") == mask_ird(fixture["draft_ird_sentinel"])
            assert draft.get("bank_account_number") == mask_bank_account(
                fixture["draft_bank_sentinel"]
            )
            assert fixture["draft_ird_sentinel"] not in blob, (
                "draft IRD plaintext sentinel leaked — must be masked (R11.6)"
            )
            assert fixture["draft_bank_sentinel"] not in blob, (
                "draft bank plaintext sentinel leaked — must be masked (R11.6)"
            )
        else:
            assert body.get("draft") is None, (
                "scenario (a) must return draft=null when no draft saved"
            )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 18: Public prefill exposes only first name and email.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("with_draft", [False, True])
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(fixture=_staff_fixture())
def test_prefill_exposes_only_first_name_and_email(fixture: dict, with_draft: bool):
    """Property 18: Public prefill exposes only first name and email.

    Driving the real ``GET /api/v2/public/staff-onboarding/{token}`` endpoint
    against a fully-populated, active staff record: the ``200`` body exposes
    ONLY ``first_name`` / ``email`` of the staff identity (plus org chrome,
    static option lists, and the optional masked draft). No phone, position,
    employee_id, last_name, emergency-contact, hourly_rate, or IRD/bank
    plaintext ever appears — and a saved draft returns IRD/bank masked only.

    **Validates: Requirements 11.6**
    """
    asyncio.run(_run_example(fixture, with_draft=with_draft))


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
