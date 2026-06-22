"""Property-based test for optional-field omission on onboarding submit (Task 8.5).

Feature: staff-onboarding-link
Property 11: Optional fields may be omitted

Drives the REAL public onboarding submit endpoint
(``POST /api/v2/public/staff-onboarding/{token}``) through the FastAPI app via
``httpx.AsyncClient(transport=ASGITransport(app=app))`` against the live dev
Postgres database (mirroring the DB-backed Hypothesis pattern in
``tests/test_onboarding_token_generation_property.py``). The public route needs
no JWT — the ``/api/v2/public/`` prefix already bypasses the auth middleware.

For each example we:

1. Seed one organisation + one active staff member that already carries
   **pre-existing** ``tax_code`` and envelope-encrypted ``ird_number_encrypted``
   / ``bank_account_number_encrypted`` values.
2. Mint a fresh onboarding token for that staff member.
3. POST a submit that **omits** the bank account, IRD number, tax code, and
   documents fields entirely, while supplying a fresh ``last_name`` (and
   sometimes ``phone``) so we can prove the submit actually ran.
4. Assert the pre-existing ``tax_code`` / ``ird_number_encrypted`` /
   ``bank_account_number_encrypted`` column values are **byte-for-byte
   unchanged** (the handler only writes a column when its field was provided),
   that no working-rights ``compliance_documents`` rows were created, that the
   supplied ``last_name`` WAS persisted, and that the token was consumed.

Validates: Requirements 5.3, 6.5, 7.5

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- The ``get_db_session`` dependency is overridden with a session bound to a
  fresh per-example async engine that mirrors the production transaction
  semantics (``session.begin()`` auto-commits on a clean return), so the
  submit's writes are durably committed and re-readable in a fresh session.
- The post-commit, best-effort completion emails (R15/R16) are patched to a
  no-op for hermeticity and speed: they are explicitly best-effort, fire AFTER
  all DB writes, and are entirely unrelated to the column-persistence property
  under test. Every DB write path (steps 5-8 of the handler) stays real.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
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
from app.modules.scheduling_v2 import models as _scheduling_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401

from app.core.database import get_db_session
from app.core.encryption import envelope_encrypt
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.compliance_docs.models import ComplianceDocument
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember, StaffOnboardingToken
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_8_5_optional_omit"

# Valid tax codes (design §R6.1) — any one is fine for the pre-existing value.
_TAX_CODES = ["M", "ME", "S", "SH", "ST", "SB", "CAE", "NSW", "ND"]

# Mount prefix for the public onboarding router (matches app/main.py).
_PREFIX = "/api/v2/public/staff-onboarding"


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
            for tbl in (
                "compliance_documents",
                "app_notifications",
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


async def _seed_org_and_staff(
    factory,
    *,
    tax_code: str,
    ird_plain: str,
    bank_plain: str,
    original_last_name: str,
) -> dict:
    """Seed one org + one active staff member with PRE-EXISTING optional values.

    Returns the org/staff ids and the exact encrypted byte blobs persisted so
    the assertion can compare for byte-for-byte equality after submit.
    """
    enc_ird = envelope_encrypt(ird_plain)
    enc_bank = envelope_encrypt(bank_plain)

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
                settings={},  # onboarding_bank_account_required defaults False
            )
            session.add(org)
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Onboarding Test Staff",
                first_name="Onboarding",
                last_name=original_last_name,
                email="onboard-omit-test@example.com",
                is_active=True,
                tax_code=tax_code,
                ird_number_encrypted=enc_ird,
                bank_account_number_encrypted=enc_bank,
            )
            session.add(staff)
            await session.flush()

            return {
                "org_id": org.id,
                "staff_id": staff.id,
                "enc_ird": bytes(enc_ird),
                "enc_bank": bytes(enc_bank),
            }


# ---------------------------------------------------------------------------
# App harness — mount the public onboarding router with a real DB session.
# ---------------------------------------------------------------------------


def _build_app(factory) -> FastAPI:
    """Mount the public onboarding router with a real, auto-committing session.

    The override mirrors the production ``get_db_session`` transaction
    semantics: it opens ``session.begin()`` so a clean handler return commits
    every write (staff update, in-app notification, token consume) durably.
    The public ``/api/v2/public/`` prefix already bypasses the auth middleware,
    so no JWT/context injection is needed.
    """
    app = FastAPI()

    async def _override_db():
        async with factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(onboarding_public_router, prefix=_PREFIX)
    return app


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(
    *,
    tax_code: str,
    ird_plain: str,
    bank_plain: str,
    original_last_name: str,
    new_last_name: str,
    new_phone: str | None,
) -> None:
    """Seed, submit omitting optional fields, assert no clobber, clean up."""
    engine, factory = await _make_engine_and_factory()
    try:
        seeded = await _seed_org_and_staff(
            factory,
            tax_code=tax_code,
            ird_plain=ird_plain,
            bank_plain=bank_plain,
            original_last_name=original_last_name,
        )
        org_id = seeded["org_id"]
        staff_id = seeded["staff_id"]
        enc_ird = seeded["enc_ird"]
        enc_bank = seeded["enc_bank"]

        # Mint a fresh onboarding token (raw token goes in the URL).
        async with factory() as session:
            async with session.begin():
                raw_token = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        # Build the multipart/form submit body OMITTING bank/ird/tax/documents.
        # Only last_name (and sometimes phone) are supplied — proving the
        # submit ran while leaving every omitted optional column untouched.
        form: dict[str, str] = {"last_name": new_last_name}
        if new_phone is not None:
            form["phone"] = new_phone

        app = _build_app(factory)
        # Patch ONLY the post-commit best-effort email dispatch (R15/R16) — it
        # fires AFTER all DB writes and is unrelated to column persistence.
        async def _noop(*args, **kwargs):  # noqa: ANN002, ANN003
            return None

        with patch(
            "app.modules.staff.public_router._dispatch_completion_emails",
            new=_noop,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="https://test"
            ) as client:
                resp = await client.post(f"{_PREFIX}/{raw_token}", data=form)

        assert resp.status_code == 200, (
            f"expected 200 submit, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("ok") is True, f"submit not ok: {body}"

        # --- Assertions: omitted optional columns are UNCHANGED -------------
        async with factory() as session:
            staff = (
                await session.execute(
                    select(StaffMember).where(StaffMember.id == staff_id)
                )
            ).scalar_one()

            # tax_code omitted → unchanged (R6.5).
            assert staff.tax_code == tax_code, (
                f"tax_code changed: {staff.tax_code!r} != {tax_code!r}"
            )
            # IRD encrypted blob omitted → byte-for-byte unchanged (R6.5).
            assert bytes(staff.ird_number_encrypted) == enc_ird, (
                "ird_number_encrypted was modified despite being omitted"
            )
            # Bank encrypted blob omitted → byte-for-byte unchanged (R5.3).
            assert bytes(staff.bank_account_number_encrypted) == enc_bank, (
                "bank_account_number_encrypted was modified despite being omitted"
            )
            # Documents omitted → none created (R7.5).
            doc_count = (
                await session.execute(
                    select(func.count())
                    .select_from(ComplianceDocument)
                    .where(ComplianceDocument.staff_id == staff_id)
                )
            ).scalar_one()
            assert doc_count == 0, (
                f"expected no working-rights documents, found {doc_count}"
            )

            # Sanity: the provided last_name WAS persisted (submit really ran).
            assert staff.last_name == new_last_name, (
                f"last_name not updated: {staff.last_name!r} != {new_last_name!r}"
            )

            # The token was consumed exactly once on success (R9.6).
            tok = (
                await session.execute(
                    select(StaffOnboardingToken).where(
                        StaffOnboardingToken.staff_id == staff_id,
                        StaffOnboardingToken.token_hash
                        == onboarding_tokens._hash_token(raw_token),
                    )
                )
            ).scalar_one()
            assert tok.status == "consumed", (
                f"token not consumed after submit: status={tok.status!r}"
            )
            assert tok.consumed_at is not None
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 11: Optional fields may be omitted.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    tax_code=st.sampled_from(_TAX_CODES),
    # 8- or 9-digit IRD plaintext (the value itself is opaque once encrypted).
    ird_plain=st.from_regex(r"\d{8,9}", fullmatch=True),
    # A plausible NZ bank account string; opaque once encrypted.
    bank_plain=st.from_regex(r"\d{2}-\d{4}-\d{7}-\d{2,3}", fullmatch=True),
    original_last_name=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
    new_last_name=st.text(
        alphabet=st.characters(min_codepoint=65, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
    new_phone=st.one_of(
        st.none(),
        st.from_regex(r"0[0-9]{8,9}", fullmatch=True),
    ),
)
def test_optional_fields_may_be_omitted(
    tax_code: str,
    ird_plain: str,
    bank_plain: str,
    original_last_name: str,
    new_last_name: str,
    new_phone: str | None,
):
    """Property 11: Optional fields may be omitted.

    Omitting the bank account, IRD number, tax code, and documents on submit
    leaves the corresponding pre-existing ``staff_members`` column values (and
    the linked compliance documents) unchanged, while a provided field (the
    last name) is still persisted and the token is consumed exactly once.

    **Validates: Requirements 5.3, 6.5, 7.5**
    """
    asyncio.run(
        _run_example(
            tax_code=tax_code,
            ird_plain=ird_plain,
            bank_plain=bank_plain,
            original_last_name=original_last_name,
            new_last_name=new_last_name,
            new_phone=new_phone,
        )
    )


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
