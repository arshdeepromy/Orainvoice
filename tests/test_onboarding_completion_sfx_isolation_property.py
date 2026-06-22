"""Property-based test for completion side-effect failure isolation (Task 8.14).

Feature: staff-onboarding-link
Property 27: Completion side-effect failures never roll back or block a submission

Drives the REAL public submit endpoint
``POST /api/v2/public/staff-onboarding/{token}`` (``onboarding_submit`` in
``app/modules/staff/public_router.py``) end-to-end through an in-process ASGI
client (``httpx.AsyncClient`` + ``ASGITransport``) — the route is public so no
JWT is required. The DB harness mirrors the other DB-backed onboarding property
tests in this repo (fresh async ``NullPool`` engine per example, full ORM
import block, ``_ORG_MARKER`` cleanup, auto-commit ``get_db_session`` override,
``@settings`` with health-check suppression, and an ``asyncio.run`` driver).

What this test proves
---------------------
Requirements **15.4** (Confirmation_Email is best-effort — a send failure is
logged and never rolls back or blocks the submit) and **16.6** (creating the
In_App_Notification or sending the completion email failing is logged and never
rolls back or blocks the submit) require that completion side-effect failures
are fully isolated from the durable submit.

For every example we seed one organisation + one active staff member, mint a
pending onboarding token (optionally first saving a prior draft so we can prove
the draft is purged), then POST a VALID submission while patching BOTH
post-commit completion-email surfaces to RAISE:

- ``onboarding_delivery.send_onboarding_confirmation_email`` → raises (R15.4),
- ``onboarding_delivery.send_email`` → raises (R16.6 — the per-recipient org
  completion email), with ``resolve_org_notification_recipients`` patched to
  return real recipients so the wrapped send loop is genuinely exercised.

After the submit we assert from a FRESH session that the failures were fully
isolated:

1. **Submit still succeeds** — ``200`` with ``ok=True`` and the thank-you
   on-screen confirmation message (R9.5 / R15.4 / R16.6).
2. **Staff fields persisted** — the mutable columns hold the submitted values.
3. **Token consumed** — ``status == "consumed"`` and ``consumed_at`` is set.
4. **Draft purged** — both draft columns are NULL.

i.e. a completion side-effect failure never rolls back or blocks the submit.

Honest finding re: the IN-TRANSACTION in-app notification (R16.1/R16.4 vs R16.6)
-------------------------------------------------------------------------------
The handler creates the org In_App_Notification INSIDE the submit transaction
(step 7) by calling ``create_in_app_notification(...)`` directly, WITHOUT its
own try/except. Isolation for that path is delegated entirely to the helper's
documented "never raises" contract (it swallows every exception internally and
returns ``None``). The post-commit emails, by contrast, are each wrapped in
``_dispatch_completion_emails`` and so are isolated at the handler level.

Because the in-app path's isolation lives in the helper, the genuinely
handler-isolated R15.4/R16.6 surfaces are the post-commit emails — that is what
the ≥100-example Property 27 below exercises (patching the email senders to
raise). A separate deterministic test
(``test_in_transaction_notification_raise_rolls_back_submit``) documents the
boundary: if the helper's contract were violated and
``create_in_app_notification`` actually raised, the exception would propagate to
the handler boundary and roll the submit back (500, nothing persisted/consumed).
This is a faithful record of current behaviour, not a patch to the impl.

Validates: Requirements 15.4, 16.6
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
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

from app.core.database import get_db_session
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember, StaffOnboardingToken
from app.modules.staff.public_router import onboarding_public_router

# Distinct marker so parallel/interleaved runs never trample each other.
_ORG_MARKER = "TEST_8_14_sfx_isolation"

_ORIG_FIRST_NAME = "Onboarding"
_ORIG_EMAIL = "onboard-sfx@example.com"

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
                name="Onboarding SFX Staff",
                first_name=_ORIG_FIRST_NAME,
                last_name="OriginalLast",
                email=_ORIG_EMAIL,
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
# Generators — VALID submitted values (same constraints as the persist test).
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
        return st.integers(min_value=0, max_value=10**n - 1).map(
            lambda x: str(x).zfill(n)
        )

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
        # Whether to pre-seed a saved draft (so we can prove it is purged).
        "save_prior_draft": st.booleans(),
    }
)


def _to_form(submission: dict) -> dict:
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
    """Seed, mint, (optionally) draft, then submit with BOTH email surfaces
    raising; assert the submit is fully isolated from those failures."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # Mint a pending token; optionally save a prior draft so we can later
        # assert the consume-time purge ran even though side effects blew up.
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )
                if submission["save_prior_draft"]:
                    row = await onboarding_tokens.resolve(session, raw)
                    await onboarding_tokens.save_draft(
                        session,
                        row,
                        {"last_name": "PriorDraft", "phone": "0000000"},
                    )

        app = _build_app(factory)
        form = _to_form(submission)

        # Patch BOTH genuinely handler-isolated post-commit completion-email
        # surfaces to RAISE, and force real recipients so the wrapped per-
        # recipient send loop is actually exercised. The in-app notification is
        # the in-transaction path (isolated by the helper's never-raises
        # contract, exercised separately below) — here we keep it a no-op so we
        # isolate exactly the email-failure behaviour under test.
        with patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.staff.onboarding_delivery.send_onboarding_confirmation_email",
            new=AsyncMock(side_effect=RuntimeError("staff confirmation email boom")),
        ), patch(
            "app.modules.staff.onboarding_delivery.resolve_org_notification_recipients",
            new=AsyncMock(return_value=["admin1@example.com", "admin2@example.com"]),
        ), patch(
            "app.modules.staff.onboarding_delivery.send_email",
            new=AsyncMock(side_effect=RuntimeError("org completion email boom")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=form
                )

        # 1. Submit still SUCCEEDS despite both completion emails raising
        #    (R15.4, R16.6) — including the on-screen thank-you confirmation.
        assert resp.status_code == 200, (
            f"completion-email failures must not block submit, got "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("ok") is True, f"submit not ok: {resp.text}"
        assert "thank" in (body.get("message") or "").lower() or "thanks" in (
            body.get("message") or ""
        ).lower(), f"missing thank-you confirmation message: {body!r}"

        # 2/3/4. Re-query from a FRESH session: fields persisted, token
        #         consumed, draft purged — i.e. nothing rolled back (R15.4/R16.6).
        async with factory() as session:
            staff = await session.get(StaffMember, staff_id)
            assert staff is not None, "staff row vanished after submit"
            assert staff.last_name == submission["last_name"]
            assert staff.phone == submission["phone"]
            assert staff.tax_code == submission["tax_code"]
            assert staff.residency_type == submission["residency_type"]
            assert staff.visa_expiry_date == submission["visa_expiry_date"]
            assert staff.kiwisaver_employee_rate is not None
            assert Decimal(staff.kiwisaver_employee_rate) == Decimal(
                submission["kiwisaver_employee_rate"]
            )
            # Identity preserved (never mutated even on the side-effect path).
            assert staff.first_name == _ORIG_FIRST_NAME
            assert staff.email == _ORIG_EMAIL

            token_row = (
                await session.execute(
                    sa_text(
                        "SELECT status, consumed_at, draft_data_encrypted, "
                        "draft_updated_at FROM staff_onboarding_tokens "
                        "WHERE staff_id = :sid"
                    ),
                    {"sid": str(staff_id)},
                )
            ).one()
            status, consumed_at, draft_blob, draft_updated_at = token_row
            assert status == "consumed", f"token not consumed: status={status!r}"
            assert consumed_at is not None, "consumed_at not set on consumed token"
            assert draft_blob is None, "draft not purged on submit (R12.8)"
            assert draft_updated_at is None, "draft_updated_at not purged on submit"
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 27: Completion side-effect failures never roll back or block a
# submission.
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
def test_completion_sfx_failures_never_block_submit(submission: dict):
    """Property 27: Completion side-effect failures never roll back or block a submission.

    Driving the real ``POST /api/v2/public/staff-onboarding/{token}`` endpoint
    with BOTH post-commit completion-email surfaces (the staff Confirmation_Email
    and the per-recipient org completion email) patched to RAISE: the submit
    still returns ``200`` with the thank-you confirmation, the staff fields are
    persisted, the token is ``consumed`` (``consumed_at`` set), and the draft is
    purged — the side-effect failures are fully isolated from the durable submit.

    **Validates: Requirements 15.4, 16.6**
    """
    asyncio.run(_run_example(submission))


# ---------------------------------------------------------------------------
# Deterministic finding: the IN-TRANSACTION in-app notification is isolated by
# the helper's "never raises" contract, NOT by a handler-level try/except.
# This records current behaviour honestly (no impl patch): if the contract were
# violated and the helper raised, the submit would roll back (500, nothing
# persisted/consumed). It is intentionally NOT part of Property 27 above because
# it is not a genuinely handler-isolated path.
# ---------------------------------------------------------------------------


def test_in_transaction_notification_raise_rolls_back_submit():
    """Document the in-transaction in-app notification isolation boundary (R16.1/R16.4 vs R16.6).

    The handler calls ``create_in_app_notification`` in-transaction without its
    own try/except, relying on the helper's documented never-raises contract.
    Forcing the helper to raise (a contract violation) propagates to the handler
    boundary and rolls the submit back. This test pins that behaviour so any
    future change to either the contract or the handler isolation is surfaced.
    """

    async def _do() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            ids = await _seed_org_and_staff(factory)
            org_id = ids["org_id"]
            staff_id = ids["staff_id"]

            async with factory() as session:
                async with session.begin():
                    raw = await onboarding_tokens.mint(
                        session, org_id=org_id, staff_id=staff_id
                    )

            app = _build_app(factory)
            form = _to_form(
                {
                    "last_name": "Smith",
                    "phone": "0211234567",
                    "emergency_contact_name": "Jane",
                    "emergency_contact_phone": "0217654321",
                    "tax_code": "M",
                    "student_loan": False,
                    "kiwisaver_enrolled": True,
                    "kiwisaver_employee_rate": 3,
                    "residency_type": "citizen",
                    "visa_expiry_date": date.today() + timedelta(days=365),
                    "ird_number": "123456789",
                    "bank_account_number": "12-3456-7890123-00",
                }
            )

            with patch(
                "app.modules.staff.public_router.create_in_app_notification",
                new=AsyncMock(side_effect=RuntimeError("notification boom")),
            ), patch(
                "app.modules.staff.public_router._dispatch_completion_emails",
                new=AsyncMock(return_value=None),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        f"/api/v2/public/staff-onboarding/{raw}", data=form
                    )

            # FINDING: the in-transaction notification raising is NOT isolated at
            # the handler level — it propagates to the boundary → 500, and the
            # whole submit rolls back (fields not persisted, token still pending).
            assert resp.status_code == 500, (
                f"expected the in-transaction notification raise to surface as a "
                f"500 rollback, got {resp.status_code}: {resp.text}"
            )

            async with factory() as session:
                staff = await session.get(StaffMember, staff_id)
                assert staff is not None
                # Rolled back: the submitted last_name was NOT persisted.
                assert staff.last_name == "OriginalLast", (
                    "submit unexpectedly persisted despite the in-transaction "
                    "notification raising — handler isolation changed"
                )
                token_row = (
                    await session.execute(
                        sa_text(
                            "SELECT status FROM staff_onboarding_tokens "
                            "WHERE staff_id = :sid"
                        ),
                        {"sid": str(staff_id)},
                    )
                ).one()
                assert token_row[0] == "pending", (
                    "token should remain pending after a rolled-back submit"
                )
        finally:
            await _cleanup(factory)
            await engine.dispose()

    asyncio.run(_do())


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
