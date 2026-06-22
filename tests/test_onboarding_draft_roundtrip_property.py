"""Property-based test for onboarding draft save/load round-trip (Task 4.5).

Feature: staff-onboarding-link
Property 19: Draft save/load round-trip with encrypted-at-rest secrets

Exercises ``app.modules.staff.onboarding_tokens.save_draft`` /
``load_draft`` against the real dev Postgres database (mirroring the
DB-backed Hypothesis pattern established in
``tests/test_onboarding_token_generation_property.py`` — task 4.3). For each
example we seed one organisation + staff member, mint an onboarding token,
save an *arbitrary* partial / empty / submit-invalid payload as a draft, then
re-resolve the token from a fresh session and assert the four guarantees the
design promises for draft persistence:

1. **Non-sensitive round-trip (R12.1, R12.3)** — every non-sensitive field in
   the payload survives ``save_draft`` → re-``resolve`` → ``load_draft``
   exactly (after JSON normalisation of ``date`` / ``Decimal`` values, which
   ``save_draft`` serialises via ``_json_default``).
2. **Full-payload fidelity (R12.1)** — the decrypted draft reproduces the
   ORIGINAL payload, *including* the sensitive ``ird_number`` and
   ``bank_account_number`` (``load_draft`` returns the whole stored blob).
3. **Encrypted at rest (R12.6)** — the raw ``draft_data_encrypted`` BYTES are
   ciphertext that does NOT contain the IRD / bank plaintext sentinels.
4. **Partial accepted without validation (R12.5)** — ``save_draft`` accepts
   partial / empty / submit-invalid payloads without raising and leaves the
   token ``pending``.

Validates: Requirements 12.1, 12.3, 12.5, 12.6

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres
  (migration 0223 already applied on localhost:5434).
- A fresh async engine is created per example (asyncpg connections are bound
  to the event loop ``asyncio.run`` creates), exactly like the reference
  DB-backed property test (task 4.3).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests).
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
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_4_5_draft_roundtrip"

# Recognisable plaintext sentinels embedded in the sensitive fields so the
# "encrypted at rest" assertion can prove the ciphertext does not leak them.
_IRD_SENTINEL = "IRDPLAINTEXT_049317502"
_BANK_SENTINEL = "BANKPLAINTEXT_12-3456-7890123-00"


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
    """Delete every row created by the seeder (keyed on the org-name marker)."""
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
                name="Onboarding Draft Staff",
                first_name="Onboarding",
                last_name="Drafter",
                email="onboard-draft-test@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


# ---------------------------------------------------------------------------
# Payload normalisation helper.
# ---------------------------------------------------------------------------


def _json_normalise(value):
    """Mirror what ``save_draft`` persists: ``date`` → ISO str, ``Decimal`` → str.

    The draft is round-tripped through ``json.dumps(..., default=_json_default)``
    and ``json.loads`` so ``date`` and ``Decimal`` values come back as the
    strings ``_json_default`` produced. This computes the expected post-round-
    trip form of a Python value so the test compares like with like.
    """
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _json_normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_normalise(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Hypothesis strategy: arbitrary partial / empty / submit-invalid payloads.
# ---------------------------------------------------------------------------


def _optional(strategy):
    """A field that may be present or entirely absent from the payload."""
    return st.one_of(st.none(), strategy)


# Non-sensitive onboarding fields. Each is independently optional so we cover
# empty payloads, partial payloads, and "all present but invalid" payloads.
_non_sensitive_fields = st.fixed_dictionaries(
    {},
    optional={
        "last_name": st.text(min_size=0, max_size=40),
        "phone": st.text(
            alphabet="0123456789 +-()", min_size=0, max_size=20
        ),
        "emergency_contact_name": st.text(min_size=0, max_size=40),
        "emergency_contact_phone": st.text(
            alphabet="0123456789 +-()", min_size=0, max_size=20
        ),
        "emergency_contact_relationship": st.text(min_size=0, max_size=30),
        # tax_code is intentionally allowed to be invalid (submit-invalid data
        # must still save as a draft — R12.5).
        "tax_code": st.text(min_size=0, max_size=10),
        "student_loan": st.booleans(),
        "kiwisaver_enrolled": st.booleans(),
        # Rate can arrive as a Decimal (model_dump) or a raw string from the
        # client — both must round-trip.
        "kiwisaver_employee_rate": st.one_of(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("10"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.sampled_from(["3", "4", "6", "8", "10"]),
        ),
        "residency_type": st.sampled_from(
            ["citizen", "resident", "work_visa", "student_visa", ""]
        ),
        "visa_expiry_date": st.dates(
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)
        ),
        "documents_staged_count": st.integers(min_value=0, max_value=20),
    },
)


@st.composite
def _draft_payloads(draw):
    """Build an arbitrary partial payload, optionally with sensitive fields.

    Roughly a third of payloads omit one or both sensitive fields so the
    encrypted-at-rest assertion only checks the sentinels that are actually
    present, while the empty-payload case (no fields at all) is also reachable.
    """
    payload = dict(draw(_non_sensitive_fields))

    include_ird = draw(st.booleans())
    include_bank = draw(st.booleans())

    has_ird = False
    has_bank = False
    if include_ird:
        # Suffix keeps each example's sentinel distinct without losing the
        # recognisable prefix the ciphertext must not contain.
        suffix = draw(st.text(alphabet="0123456789", min_size=0, max_size=4))
        payload["ird_number"] = f"{_IRD_SENTINEL}{suffix}"
        has_ird = True
    if include_bank:
        suffix = draw(st.text(alphabet="0123456789", min_size=0, max_size=4))
        payload["bank_account_number"] = f"{_BANK_SENTINEL}{suffix}"
        has_bank = True

    return payload, has_ird, has_bank


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(payload: dict, has_ird: bool, has_bank: bool) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint + save the draft. ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )
                row = await onboarding_tokens.resolve(session, raw)
                assert row is not None
                # R12.5: partial / empty / invalid payload saves without raising.
                await onboarding_tokens.save_draft(session, row, payload)

        # --- Re-resolve from a FRESH session (resume-on-any-device path). ---
        async with factory() as session:
            row = await onboarding_tokens.resolve(session, raw)
            assert row is not None

            # R12.7: saving a draft must not consume the token.
            assert row.status == "pending", (
                f"save_draft must leave token pending, got {row.status!r}"
            )
            # A draft was saved => draft_updated_at is set, blob present.
            assert row.draft_updated_at is not None
            assert row.draft_data_encrypted is not None

            loaded = onboarding_tokens.load_draft(row)
            assert loaded is not None

            # --- 1 & 2. Full-payload fidelity incl. sensitive fields (R12.1, R12.3). ---
            expected = _json_normalise(payload)
            assert loaded == expected, (
                "load_draft must reproduce the original payload exactly "
                f"(expected {expected!r}, got {loaded!r})"
            )

            # Spell out the non-sensitive round-trip explicitly (R12.1/R12.3):
            for key, original in payload.items():
                if key in ("ird_number", "bank_account_number"):
                    continue
                assert loaded[key] == _json_normalise(original), (
                    f"non-sensitive field {key!r} did not round-trip: "
                    f"{loaded.get(key)!r} != {_json_normalise(original)!r}"
                )

            # --- 3. Encrypted at rest: sentinels absent from ciphertext (R12.6). ---
            raw_bytes = bytes(row.draft_data_encrypted)
            if has_ird:
                assert _IRD_SENTINEL.encode("utf-8") not in raw_bytes, (
                    "IRD plaintext sentinel leaked into draft_data_encrypted"
                )
            if has_bank:
                assert _BANK_SENTINEL.encode("utf-8") not in raw_bytes, (
                    "bank plaintext sentinel leaked into draft_data_encrypted"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 19: Draft save/load round-trip with encrypted-at-rest secrets.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(case=_draft_payloads())
def test_draft_save_load_roundtrip_with_encryption_at_rest(case):
    """Property 19: Draft save/load round-trip with encrypted-at-rest secrets.

    For any partial onboarding payload (including empty, incomplete, or
    submit-invalid data), saving it as a draft and then loading it reproduces
    every non-sensitive field exactly, the stored ``draft_data_encrypted``
    bytes are ciphertext that does not contain the IRD or bank-account
    plaintext, and decrypting the stored blob reproduces the original payload
    — so a draft accepts arbitrary partial data while keeping partial IRD/bank
    encrypted at rest.

    **Validates: Requirements 12.1, 12.3, 12.5, 12.6**
    """
    payload, has_ird, has_bank = case
    asyncio.run(_run_example(payload, has_ird, has_bank))


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
