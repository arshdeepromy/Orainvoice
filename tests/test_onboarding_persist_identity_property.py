"""Property-based test for onboarding submit persistence + identity (Task 8.8).

Feature: staff-onboarding-link
Property 14: Successful submission persists provided data and preserves identity fields

Drives the REAL public submit endpoint
``POST /api/v2/public/staff-onboarding/{token}`` (``onboarding_submit`` in
``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
client (``httpx.AsyncClient`` + ``ASGITransport``) — the route is public so no
JWT is required. The DB harness mirrors the other DB-backed onboarding property
tests in this repo (fresh async engine per example, full ORM import block,
``_ORG_MARKER`` cleanup, ``_seed_org_and_staff``, ``@settings`` with
health-check suppression, and an ``asyncio.run`` driver).

For every example we seed one organisation + one active staff member (recording
the original ``first_name`` / ``email``), mint a pending onboarding token via
``onboarding_tokens.mint``, then POST a generated set of VALID field values to
the public submit endpoint. After a ``200`` we re-query ``staff_members`` from a
fresh session and assert:

1. **Mutable fields persisted (R9.3)** — every provided mutable field equals the
   submitted value: ``last_name``, ``phone``, ``emergency_contact_name``,
   ``emergency_contact_phone``, ``tax_code``, ``student_loan``,
   ``kiwisaver_enrolled``, ``kiwisaver_employee_rate``, ``residency_type``,
   ``visa_expiry_date``.
2. **Encrypted secrets persisted (R9.3, R9.4)** — the IRD number and bank
   account number round-trip through ``envelope_decrypt_str`` back to exactly
   the submitted plaintext (verified by decryption, not by reading ciphertext).
3. **Identity preserved (R4.2)** — ``first_name`` and ``email`` are UNCHANGED
   from the seeded staff record (the submit must never mutate them).

Validates: Requirements 4.2, 9.3

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
- The two post-commit, best-effort side effects that are NOT part of Property 14
  (the org in-app notification and the completion emails) are isolated with
  no-op patches so the test exercises the real persistence path without making
  network calls or coupling to the notifications schema. The persistence path
  itself (encrypt → write staff columns → consume token) runs fully real.
"""

from __future__ import annotations

import asyncio
import uuid
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
# tests/test_onboarding_single_use_property.py).
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
from app.core.encryption import envelope_decrypt_str
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_8_persist_identity"

# Known seeded identity fields — the submit must NEVER mutate these (R4.2).
_ORIG_FIRST_NAME = "Onboarding"
_ORIG_EMAIL = "onboard-test@example.com"

# Valid option lists (kept local so the test fails loudly if the authoritative
# schema lists ever drift).
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
                first_name=_ORIG_FIRST_NAME,
                last_name="OriginalLast",
                email=_ORIG_EMAIL,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


def _build_app(factory) -> FastAPI:
    """Build an app exposing ONLY the public onboarding router at the prod path.

    The public route requires no JWT (the auth middleware bypasses
    ``/api/v2/public/``), so no auth state is injected. ``get_db_session`` is
    overridden to yield a real session from the test factory inside a
    transaction that auto-commits on a clean return — exactly the
    ``session.begin()`` semantics the production handler relies on.
    """
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        # The handler reads request.state.client_ip in some branches; populate
        # a benign value so nothing trips on a missing attribute.
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
# Generators — VALID submitted values.
# ---------------------------------------------------------------------------

# ASCII-letter names (no surrounding whitespace) so the handler's
# ``value.strip() or None`` write stores exactly the submitted string.
_name_text = st.text(
    alphabet=st.characters(min_codepoint=ord("A"), max_codepoint=ord("z")).filter(
        str.isalpha
    ),
    min_size=1,
    max_size=20,
)
_digit_text = st.text(alphabet="0123456789", min_size=5, max_size=12)


def _valid_ird() -> st.SearchStrategy[str]:
    """8- or 9-digit IRD strings (no separators → strip is a no-op)."""
    return st.one_of(
        st.text(alphabet="0123456789", min_size=8, max_size=8),
        st.text(alphabet="0123456789", min_size=9, max_size=9),
    )


def _valid_bank() -> st.SearchStrategy[str]:
    """Valid NZ bank account: 2-4-7-2 or 2-4-7-3 digit groups."""

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


_submission_strategy = st.fixed_dictionaries(
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


def _to_form(submission: dict) -> dict:
    """Render the generated submission as multipart/form string fields."""
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


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(submission: dict) -> None:
    """Seed, mint, POST the submit endpoint, assert persistence + identity."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token; capture the RAW token for the URL. ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        app = _build_app(factory)
        form = _to_form(submission)

        # Isolate the unrelated post-commit / in-transaction side effects that
        # are not part of Property 14 (notifications + completion emails) so the
        # test exercises the real persistence path without network I/O.
        with patch(
            "app.modules.staff.public_router._dispatch_completion_emails",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=form
                )

        assert resp.status_code == 200, (
            f"expected 200 from submit, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("ok") is True, f"submit not ok: {resp.text}"

        # --- Re-query the persisted staff row from a FRESH session. ---
        async with factory() as session:
            staff = await session.get(StaffMember, staff_id)
            assert staff is not None, "staff row vanished after submit"

            # 1. Mutable fields persisted exactly as submitted (R9.3).
            assert staff.last_name == submission["last_name"]
            assert staff.phone == submission["phone"]
            assert staff.emergency_contact_name == submission["emergency_contact_name"]
            assert staff.emergency_contact_phone == submission["emergency_contact_phone"]
            assert staff.tax_code == submission["tax_code"]
            assert staff.student_loan is submission["student_loan"]
            assert staff.kiwisaver_enrolled is submission["kiwisaver_enrolled"]
            assert staff.kiwisaver_employee_rate is not None
            assert Decimal(staff.kiwisaver_employee_rate) == Decimal(
                submission["kiwisaver_employee_rate"]
            )
            assert staff.residency_type == submission["residency_type"]
            assert staff.visa_expiry_date == submission["visa_expiry_date"]

            # 2. Encrypted secrets round-trip via decryption (R9.3, R9.4).
            assert staff.ird_number_encrypted is not None
            assert (
                envelope_decrypt_str(staff.ird_number_encrypted)
                == submission["ird_number"]
            )
            assert staff.bank_account_number_encrypted is not None
            assert (
                envelope_decrypt_str(staff.bank_account_number_encrypted)
                == submission["bank_account_number"]
            )

            # 3. Identity fields preserved — never mutated by the submit (R4.2).
            assert staff.first_name == _ORIG_FIRST_NAME, (
                "submit must not mutate first_name (R4.2 identity preserved)"
            )
            assert staff.email == _ORIG_EMAIL, (
                "submit must not mutate email (R4.2 identity preserved)"
            )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 14: Successful submission persists provided data and preserves
# identity fields.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(submission=_submission_strategy)
def test_submit_persists_data_and_preserves_identity(submission: dict):
    """Property 14: Successful submission persists provided data and preserves identity.

    Driving the real ``POST /api/v2/public/staff-onboarding/{token}`` endpoint:
    after a ``200`` every provided mutable field (including IRD/bank verified by
    decryption) equals the submitted value, while ``first_name`` and ``email``
    remain exactly as seeded (identity preserved).

    **Validates: Requirements 4.2, 9.3**
    """
    asyncio.run(_run_example(submission))


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
