"""Property-based test for configured-required bank account (Task 8.6).

Feature: staff-onboarding-link
Property 12: Bank account becomes mandatory when configured required

Validates: Requirements 5.4

What this exercises
-------------------
Requirement 5.4 says: WHERE an administrator has configured the bank account
field as required, THE Onboarding_Form SHALL require a bank account number
before allowing submission (otherwise the field stays optional, R5.3). The
decision lives in the public submit handler
``app.modules.staff.public_router.onboarding_submit``:

    bank_provided = _present(bank_account_number)        # non-empty after strip
    if bank_provided:
        reject  iff  not validate_nz_bank_account(...)   # malformed-when-present
    elif bank_account_required:                          # org config (R5.4)
        reject  (empty + required)
    # else: empty + not-required -> accept

``bank_account_required`` is read from org settings under the key
``onboarding_bank_account_required`` via ``get_org_settings``.

Testable-surface decision (documented deviation)
------------------------------------------------
The task's first preference is to drive the actual HTTP endpoint against the
real dev DB. There is **no clean HTTP harness** for that here:

* the existing ``httpx`` / ``ASGITransport`` harnesses in this suite build a
  *mock-DB* mini-app, so they cannot exercise the real submit write-path; and
* the live ``/api/v2/public/staff-onboarding/`` endpoint is behind a 30 req/min
  per-IP rate limiter (``rate_limit.py``), which a >=100-example property run
  would trip, making an end-to-end HTTP harness unreliable.

So instead of the HTTP layer we drive the **real handler coroutine**
``onboarding_submit(...)`` directly against the real dev Postgres (mirroring the
DB-backed pattern in ``tests/test_onboarding_token_generation_property.py``).
This still exercises the genuine R5.4 decision through the real code path:
``get_org_settings`` reading ``onboarding_bank_account_required``,
``classify_token_state``, the real ``validate_nz_bank_account`` validator, the
``staff_members`` write, ``envelope_encrypt`` of an accepted bank number, and
``onboarding_tokens.consume``. Only two *unrelated* best-effort side effects are
isolated (they are R15/R16, not R5.4, and would otherwise make 100 examples slow
and network-flaky): the post-commit completion emails
(``_dispatch_completion_emails``) and the in-app completion notification
(``create_in_app_notification``) are patched to no-ops. The bank-required
decision under test is fully real.

Per example we:
  1. seed one org (carrying ``settings={"onboarding_bank_account_required": R}``)
     plus one active staff member;
  2. mint a fresh onboarding token;
  3. invoke the real ``onboarding_submit`` with a generated bank value;
  4. assert accept/reject matches the R5.4 rule, and confirm the durable DB
     side effects (token consumed + bank encrypted on accept; nothing written +
     token still pending on reject).

Generators cover (bank_account_required in {True, False}) x (bank value in
{empty, whitespace, absent, valid 2-4-7-2, valid 2-4-7-3, malformed}).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

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
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens, public_router
from app.modules.staff.models import StaffMember, StaffOnboardingToken
from app.modules.staff.onboarding_validation import validate_nz_bank_account
from app.modules.staff.public_router import onboarding_submit
from app.modules.staff.schemas import OnboardingSubmitResponse

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_8_6_bank_required"


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    # NullPool: open and close a real connection per checkout (no lingering
    # pooled connections), so a >=100-example run — each on its own event loop
    # via asyncio.run — keeps a tiny, bounded footprint on the shared dev DB
    # and never trips the server's max_connections limit.
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
                "staff_onboarding_tokens",
                "compliance_documents",
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


async def _seed_org_and_staff(factory, *, bank_required: bool) -> dict:
    """Seed one org (with the bank-required setting) + one active staff member."""
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
                settings={"onboarding_bank_account_required": bool(bank_required)},
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
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(*, bank_required: bool, bank_value: str | None, category: str):
    """Seed, mint, drive the real submit handler, assert R5.4, then clean up."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory, bank_required=bank_required)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # Mint a fresh token for this example.
        async with factory() as session:
            async with session.begin():
                raw_token = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        # Expected outcome per the R5.4 rule.
        present = category in ("valid", "malformed")
        if present:
            expect_accept = category == "valid"
        else:  # empty / whitespace / absent
            expect_accept = not bank_required

        # Drive the REAL submit handler. Isolate only the unrelated best-effort
        # R15/R16 completion side effects (emails + in-app notification); the
        # bank-required decision under test stays fully real.
        async with factory() as session:
            async with session.begin():
                with patch.object(
                    public_router,
                    "_dispatch_completion_emails",
                    new=AsyncMock(return_value=None),
                ), patch.object(
                    public_router,
                    "create_in_app_notification",
                    new=AsyncMock(return_value=None),
                ):
                    result = await onboarding_submit(
                        token=raw_token,
                        db=session,
                        last_name=None,
                        phone=None,
                        emergency_contact_name=None,
                        emergency_contact_phone=None,
                        bank_account_number=bank_value,
                        ird_number=None,
                        tax_code=None,
                        student_loan=None,
                        kiwisaver_enrolled=None,
                        kiwisaver_employee_rate=None,
                        residency_type=None,
                        visa_expiry_date=None,
                        documents=[],
                    )

        # --- Assert the accept/reject decision (R5.4) ----------------------
        if expect_accept:
            assert isinstance(result, OnboardingSubmitResponse), (
                f"expected acceptance for required={bank_required} "
                f"category={category} value={bank_value!r}, got {result!r}"
            )
            assert result.ok is True
        else:
            assert isinstance(result, JSONResponse), (
                f"expected a 422 rejection for required={bank_required} "
                f"category={category} value={bank_value!r}, got {result!r}"
            )
            assert result.status_code == 422, (
                f"expected 422, got {result.status_code}"
            )
            import json as _json

            body = _json.loads(bytes(result.body))
            assert body.get("ok") is False
            assert "bank_account_number" in (body.get("errors") or {}), (
                f"rejection must flag the bank field; body={body}"
            )

        # --- Confirm durable DB side effects match the decision ------------
        async with factory() as session:
            tok = (
                await session.execute(
                    select(StaffOnboardingToken).where(
                        StaffOnboardingToken.staff_id == staff_id,
                        StaffOnboardingToken.org_id == org_id,
                    )
                )
            ).scalar_one()
            staff_row = (
                await session.execute(
                    select(StaffMember).where(StaffMember.id == staff_id)
                )
            ).scalar_one()

            if expect_accept:
                assert tok.status == "consumed", (
                    "a successful submit must consume the token (R2.5/R9.6)"
                )
                assert tok.consumed_at is not None
                if category == "valid":
                    assert staff_row.bank_account_number_encrypted is not None, (
                        "an accepted valid bank number must be stored encrypted"
                    )
            else:
                assert tok.status == "pending", (
                    "a rejected submit must leave the token pending (R9.7)"
                )
                assert tok.consumed_at is None
                assert staff_row.bank_account_number_encrypted is None, (
                    "a rejected submit must not write the bank number"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Generators over (bank value, category).
# ---------------------------------------------------------------------------


def _digits(n: int):
    """Strategy emitting an exactly-``n``-digit zero-padded numeric string."""
    return st.integers(min_value=0, max_value=10 ** n - 1).map(lambda v: str(v).zfill(n))


# Valid NZ bank account: 2-4-7-2 or 2-4-7-3.
_valid_2472 = st.tuples(_digits(2), _digits(4), _digits(7), _digits(2)).map(
    lambda p: "-".join(p)
)
_valid_2473 = st.tuples(_digits(2), _digits(4), _digits(7), _digits(3)).map(
    lambda p: "-".join(p)
)
_valid_bank = st.one_of(_valid_2472, _valid_2473).map(lambda s: (s, "valid"))

# Empty / absent (treated as "not present" by the handler's _present()).
_empty_bank = st.sampled_from(["", None]).map(lambda s: (s, "empty"))
_whitespace_bank = st.sampled_from(["   ", "\t", " \n ", "  \t  "]).map(
    lambda s: (s, "whitespace")
)

# Malformed-when-present: non-empty strings that fail the NZ format. Includes
# off-by-one suffix lengths (1 and 4 digits) plus arbitrary noisy text; the
# real validator filters out any accidental valid match so these are guaranteed
# present-and-invalid.
_malformed_bank = (
    st.one_of(
        st.from_regex(r"\d{2}-\d{4}-\d{7}-\d{1}", fullmatch=True),  # 1-digit suffix
        st.from_regex(r"\d{2}-\d{4}-\d{7}-\d{4}", fullmatch=True),  # 4-digit suffix
        st.from_regex(r"\d{1,3}-\d{1,5}-\d{1,8}", fullmatch=True),  # wrong groups
        st.sampled_from(
            [
                "12-3456-7890123",  # missing suffix
                "not-a-bank-number",
                "1234567890123",  # no separators
                "12 3456 7890123 00",  # spaces not hyphens
                "AB-CDEF-GHIJKLM-NO",
            ]
        ),
        st.text(min_size=1, max_size=12),
    )
    .filter(lambda s: s.strip() != "" and not validate_nz_bank_account(s))
    .map(lambda s: (s, "malformed"))
)

_bank_strategy = st.one_of(
    _valid_bank,
    _empty_bank,
    _whitespace_bank,
    _malformed_bank,
)


# ---------------------------------------------------------------------------
# Property 12: Bank account becomes mandatory when configured required.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(bank_required=st.booleans(), bank=_bank_strategy)
def test_bank_account_required_when_configured(
    bank_required: bool, bank: tuple[str | None, str]
):
    """Property 12: Bank account becomes mandatory when configured required.

    For any org configuration and any bank value, the real onboarding submit
    handler accepts/rejects exactly per Requirement 5.4:

    * required + empty/absent/whitespace -> REJECTED (422, flags bank field);
    * required + format-valid            -> ACCEPTED (token consumed, encrypted);
    * not-required + empty/absent        -> ACCEPTED;
    * any + malformed-when-present       -> REJECTED (format gate, R5.2).

    **Validates: Requirements 5.4**
    """
    bank_value, category = bank
    asyncio.run(
        _run_example(
            bank_required=bank_required,
            bank_value=bank_value,
            category=category,
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
