"""Property-based test for onboarding submit no-partial-write on rejection (Task 8.10).

Feature: staff-onboarding-link
Property 16: Rejected submissions never partially write

Drives the REAL public submit endpoint
``POST /api/v2/public/staff-onboarding/{token}`` (``onboarding_submit`` in
``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
client (``httpx.AsyncClient`` + ``ASGITransport``) — the route is public so no
JWT is required. The DB harness mirrors the sibling DB-backed onboarding
property tests in this repo (fresh async engine per example, full ORM import
block, ``_ORG_MARKER`` cleanup, ``_seed_org_and_staff``, ``@settings`` with
health-check suppression, and an ``asyncio.run`` driver).

For every example we seed one organisation + one active staff member with a
set of KNOWN pre-existing column values, mint a pending onboarding token via
``onboarding_tokens.mint``, and save a prior draft on the token. We then POST a
submit that is guaranteed to be REJECTED by one of two modes:

1. **VALIDATION failure (422)** — the submitted form carries an invalid field
   (emergency-contact mismatch, malformed bank account, or a too-short IRD).
   The handler collects field errors and returns ``422`` BEFORE any DB write.

2. **ENCRYPTION failure (422)** — ``envelope_encrypt`` is patched to raise. The
   form is otherwise VALID and includes IRD/bank so encryption is attempted;
   the handler catches the failure and returns ``422 encryption_failed``,
   again BEFORE any column write.

After the ``422`` we re-query both the staff row and the token row from a fresh
session and assert the durable post-state:

1. **No partial write (R9.2)** — every seeded staff column is UNCHANGED
   (mutable fields, encrypted secret columns, and the identity fields).
2. **Token still pending (R9.7)** — the token ``status`` is still ``pending``
   and ``consumed_at`` is ``NULL`` (the link remains eligible for resubmission).
3. **Prior draft intact (R9.7)** — the previously-saved draft blob is unchanged
   (a rejection never purges the draft).

Validates: Requirements 9.2, 9.7

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
- The unrelated best-effort completion side effects (the org in-app
  notification and the completion emails) are isolated with no-op patches as
  the sibling tests do; they never run on the rejection path anyway, but the
  patches keep the harness identical and free of network coupling.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
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
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember, StaffOnboardingToken
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_10_no_partial_write"

# ---------------------------------------------------------------------------
# KNOWN pre-existing staff column values. After ANY rejection the re-queried
# staff row must equal these EXACTLY — nothing partially written (R9.2).
# ---------------------------------------------------------------------------
_SEED_FIRST_NAME = "Onboarding"
_SEED_EMAIL = "onboard-test@example.com"
_SEED_LAST_NAME = "SeededLast"
_SEED_PHONE = "0210000000"
_SEED_EC_NAME = "SeededEmergencyName"
_SEED_EC_PHONE = "0211111111"
_SEED_TAX_CODE = "M"
_SEED_STUDENT_LOAN = False
_SEED_KIWISAVER_ENROLLED = False
_SEED_KIWISAVER_RATE = Decimal("3")
_SEED_RESIDENCY = "citizen"
_SEED_VISA_EXPIRY = date(2030, 1, 1)

_TAX_CODES = ("M", "ME", "S", "SH", "ST", "SB", "CAE", "NSW", "ND")
_RESIDENCY_TYPES = ("citizen", "permanent_resident", "work_visa", "student_visa", "other")
_KIWISAVER_RATES = (3, 4, 6, 8, 10)


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


async def _seed_org_and_staff(factory) -> dict:
    """Seed one org + one active staff member with KNOWN column values."""
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
                first_name=_SEED_FIRST_NAME,
                last_name=_SEED_LAST_NAME,
                email=_SEED_EMAIL,
                phone=_SEED_PHONE,
                emergency_contact_name=_SEED_EC_NAME,
                emergency_contact_phone=_SEED_EC_PHONE,
                tax_code=_SEED_TAX_CODE,
                student_loan=_SEED_STUDENT_LOAN,
                kiwisaver_enrolled=_SEED_KIWISAVER_ENROLLED,
                kiwisaver_employee_rate=_SEED_KIWISAVER_RATE,
                residency_type=_SEED_RESIDENCY,
                visa_expiry_date=_SEED_VISA_EXPIRY,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


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
# Generators.
# ---------------------------------------------------------------------------

_name_text = st.text(
    alphabet=st.characters(min_codepoint=ord("A"), max_codepoint=ord("z")).filter(
        str.isalpha
    ),
    min_size=1,
    max_size=20,
)
_digit_text = st.text(alphabet="0123456789", min_size=5, max_size=12)


def _valid_ird() -> st.SearchStrategy[str]:
    return st.one_of(
        st.text(alphabet="0123456789", min_size=8, max_size=8),
        st.text(alphabet="0123456789", min_size=9, max_size=9),
    )


def _valid_bank() -> st.SearchStrategy[str]:
    def _digits(n: int) -> st.SearchStrategy[str]:
        return st.integers(min_value=0, max_value=10**n - 1).map(lambda x: str(x).zfill(n))

    return st.builds(
        lambda a, b, c, d: f"{a}-{b}-{c}-{d}",
        _digits(2),
        _digits(4),
        _digits(7),
        st.one_of(_digits(2), _digits(3)),
    )


_future_visa_date = st.integers(min_value=1, max_value=3650).map(
    lambda days: (date.today() + timedelta(days=days))
)

# A fully VALID submission payload (the same shape the success-path sibling
# test generates). For the validation mode we corrupt one field; for the
# encryption mode we send it as-is (and patch envelope_encrypt to raise).
_base_valid_submission = st.fixed_dictionaries(
    {
        "last_name": _name_text,
        "phone": _digit_text,
        "emergency_contact_name": _name_text,
        "emergency_contact_phone": _digit_text,
        "tax_code": st.sampled_from(_TAX_CODES),
        "student_loan": st.booleans(),
        "kiwisaver_enrolled": st.booleans(),
        "kiwisaver_employee_rate": st.sampled_from(_KIWISAVER_RATES),
        "residency_type": st.sampled_from(_RESIDENCY_TYPES),
        "visa_expiry_date": _future_visa_date,
        "ird_number": _valid_ird(),
        "bank_account_number": _valid_bank(),
    }
)

# Two rejection modes; validation mode picks which field to invalidate.
_INVALIDATIONS = ("emergency_mismatch", "bad_bank", "bad_ird")

_example_strategy = st.one_of(
    st.fixed_dictionaries(
        {
            "mode": st.just("validation"),
            "submission": _base_valid_submission,
            "invalidation": st.sampled_from(_INVALIDATIONS),
        }
    ),
    st.fixed_dictionaries(
        {
            "mode": st.just("encryption"),
            "submission": _base_valid_submission,
            "invalidation": st.just(None),
        }
    ),
)


def _to_form(submission: dict) -> dict:
    """Render a submission dict as multipart/form string fields."""
    return {
        "last_name": submission["last_name"],
        "phone": submission["phone"],
        "emergency_contact_name": submission["emergency_contact_name"],
        "emergency_contact_phone": submission["emergency_contact_phone"],
        "tax_code": submission["tax_code"],
        "student_loan": "true" if submission["student_loan"] else "false",
        "kiwisaver_enrolled": "true" if submission["kiwisaver_enrolled"] else "false",
        "kiwisaver_employee_rate": str(submission["kiwisaver_employee_rate"]),
        "residency_type": submission["residency_type"],
        "visa_expiry_date": submission["visa_expiry_date"].isoformat(),
        "ird_number": submission["ird_number"],
        "bank_account_number": submission["bank_account_number"],
    }


def _apply_invalidation(form: dict, invalidation: str) -> dict:
    """Corrupt exactly one field so the handler rejects with a 422 (R9.1/R9.2)."""
    form = dict(form)
    if invalidation == "emergency_mismatch":
        # Name present, phone blank → partial emergency contact → 422.
        form["emergency_contact_name"] = "PresentName"
        form["emergency_contact_phone"] = ""
    elif invalidation == "bad_bank":
        # Not a valid NZ bank account format → 422.
        form["bank_account_number"] = "not-a-valid-bank"
    elif invalidation == "bad_ird":
        # Too short for the 8/9-digit length gate → 422.
        form["ird_number"] = "123"
    else:  # pragma: no cover — guarded by the strategy
        raise AssertionError(f"unknown invalidation {invalidation!r}")
    return form


# The known prior draft saved on the token before the (rejected) submit.
_PRIOR_DRAFT = {"last_name": "DraftLast", "phone": "0277777777"}


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(example: dict) -> None:
    """Seed, mint, save a prior draft, POST a REJECTED submit, assert no write."""
    mode = example["mode"]
    submission = example["submission"]

    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token + save a prior draft (R9.7 intact check). --
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )
                row = await onboarding_tokens.resolve(session, raw)
                await onboarding_tokens.save_draft(session, row, dict(_PRIOR_DRAFT))

        # Capture the durable pre-submit token state to compare against later.
        async with factory() as session:
            row = await onboarding_tokens.resolve(session, raw)
            assert row is not None and row.status == "pending"
            token_id = row.id
            draft_before = row.draft_data_encrypted
            assert draft_before is not None, "prior draft should be saved"

        app = _build_app(factory)
        form = _to_form(submission)
        if mode == "validation":
            form = _apply_invalidation(form, example["invalidation"])

        # Isolate the unrelated best-effort completion side effects (they do not
        # run on the rejection path, but keep the harness identical + offline).
        patches = [
            patch(
                "app.modules.staff.public_router._dispatch_completion_emails",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.staff.public_router.create_in_app_notification",
                new=AsyncMock(return_value=None),
            ),
        ]
        if mode == "encryption":
            # Force the IRD/bank envelope encryption to raise so the handler
            # rejects with 422 encryption_failed BEFORE any column write.
            def _boom(*_args, **_kwargs):
                raise RuntimeError("forced encryption failure for Property 16")

            patches.append(
                patch(
                    "app.modules.staff.public_router.envelope_encrypt",
                    side_effect=_boom,
                )
            )

        from contextlib import ExitStack

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=form
                )

        # --- The submit MUST be rejected with a 422 (no success path). ------
        assert resp.status_code == 422, (
            f"[{mode}] expected 422 rejection, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("ok") is False, f"[{mode}] rejection body not ok=false: {resp.text}"
        if mode == "encryption":
            # Encryption failures surface a distinct machine code (R9.7).
            assert "encryption_failed" in resp.text, (
                f"[encryption] expected encryption_failed code: {resp.text}"
            )

        # --- Re-query staff from a FRESH session: NOTHING written (R9.2). ----
        async with factory() as session:
            staff = await session.get(StaffMember, staff_id)
            assert staff is not None, "staff row vanished after rejected submit"

            # Mutable fields unchanged from the seeded values.
            assert staff.last_name == _SEED_LAST_NAME
            assert staff.phone == _SEED_PHONE
            assert staff.emergency_contact_name == _SEED_EC_NAME
            assert staff.emergency_contact_phone == _SEED_EC_PHONE
            assert staff.tax_code == _SEED_TAX_CODE
            assert staff.student_loan is _SEED_STUDENT_LOAN
            assert staff.kiwisaver_enrolled is _SEED_KIWISAVER_ENROLLED
            assert Decimal(staff.kiwisaver_employee_rate) == _SEED_KIWISAVER_RATE
            assert staff.residency_type == _SEED_RESIDENCY
            assert staff.visa_expiry_date == _SEED_VISA_EXPIRY

            # Encrypted secret columns never partially written (stay NULL).
            assert staff.ird_number_encrypted is None, (
                f"[{mode}] IRD column was written despite rejection (partial write)"
            )
            assert staff.bank_account_number_encrypted is None, (
                f"[{mode}] bank column was written despite rejection (partial write)"
            )

            # Identity fields preserved.
            assert staff.first_name == _SEED_FIRST_NAME
            assert staff.email == _SEED_EMAIL

        # --- Re-query the token: still pending, not consumed, draft intact. --
        async with factory() as session:
            token = await session.get(StaffOnboardingToken, token_id)
            assert token is not None, "token row vanished after rejected submit"
            assert token.status == "pending", (
                f"[{mode}] token must remain pending after rejection, "
                f"got {token.status!r}"
            )
            assert token.consumed_at is None, (
                f"[{mode}] token must not be consumed after rejection"
            )
            # Prior draft untouched by a rejection (R9.7).
            assert token.draft_data_encrypted == draft_before, (
                f"[{mode}] prior draft must remain intact after rejection"
            )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 16: Rejected submissions never partially write.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(example=_example_strategy)
def test_rejected_submissions_never_partially_write(example: dict):
    """Property 16: Rejected submissions never partially write.

    Driving the real ``POST /api/v2/public/staff-onboarding/{token}`` endpoint:
    whether the submit is rejected by a field VALIDATION failure or by a forced
    ENCRYPTION failure, the response is a ``422`` and the durable post-state is
    unchanged — every seeded staff column is identical, the encrypted secret
    columns are still NULL (no partial write), and the token remains ``pending``
    with ``consumed_at`` NULL and its prior draft intact (eligible for resubmit).

    **Validates: Requirements 9.2, 9.7**
    """
    asyncio.run(_run_example(example))


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
