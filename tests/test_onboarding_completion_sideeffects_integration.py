"""Integration test for onboarding completion email side-effects (Task 12.3).

Feature: staff-onboarding-link
Requirements: 15.3, 16.3

This is an INTEGRATION test (NOT a property-based test). It drives the REAL
public submit endpoint ``POST /api/v2/public/staff-onboarding/{token}``
(``onboarding_submit`` in ``app/modules/staff/public_router.py``) end-to-end
through an in-process ASGI client (``httpx.AsyncClient`` + ``ASGITransport``).
The route is public (the auth middleware bypasses ``/api/v2/public/``) so no JWT
is required. The DB harness mirrors ``tests/test_onboarding_persist_identity_property.py``
(``_build_app`` with an auto-commit ``get_db_session`` override, a per-example
``NullPool`` async engine, the full ORM import block, ``_ORG_MARKER`` cleanup,
and the ``DATABASE_URL`` env override exposed via ``app.config.settings``).

Two parts:

1. ``test_successful_submit_returns_200_and_attempts_completion_emails`` —
   asserts a successful submit returns the ``200`` thank-you AND attempts the
   staff confirmation email exactly once (R15.3), plus one org-completion email
   per resolved active ``org_admin`` / ``branch_admin`` recipient (R16.3). The
   real ``send_onboarding_confirmation_email`` runs (so the staff confirmation
   genuinely flows into ``send_email``); only the unified ``send_email`` is
   replaced with a recording mock.

2. ``test_completion_emails_flow_through_multi_provider_dispatch`` — the
   multi-provider dispatch integration. It seeds an active ``email_providers``
   row and patches the LOW-LEVEL per-provider send
   (``app.integrations.email_sender.dispatch_one_provider``) to a recording mock
   while letting the REAL ``send_email`` orchestration run (payload pre-check,
   bounce-blocklist lookup, active-provider load, failover loop). This proves
   that both completion emails — the staff confirmation (R15.3) and each
   org-completion email (R16.3) — actually flow through the unified
   ``send_email`` multi-provider dispatch with a composed ``EmailMessage``,
   asserting on the dispatched message subjects.

Seam choice (documented):
- ``send_email`` is imported into ``app.modules.staff.onboarding_delivery`` and
  used there for BOTH the staff confirmation (inside
  ``send_onboarding_confirmation_email``) and the org-completion loop (called as
  ``onboarding_delivery.send_email`` from the submit handler's
  ``_dispatch_completion_emails``). Patching ``onboarding_delivery.send_email``
  (Part 1) therefore records every completion email at the dispatch boundary
  without touching the provider/network layer.
- For Part 2 the faithful low-level network/provider seam is
  ``email_sender.dispatch_one_provider`` — the single point ``send_email`` calls
  per provider in its failover loop. Mocking it (and seeding one active
  provider so the loop is entered) exercises the real dispatch wiring while
  stubbing only the actual network send.

The in-transaction in-app notification (``create_in_app_notification``) is
patched to a no-op in both tests so they focus on the completion EMAIL dispatch
that Task 12.3 targets (the in-app notification is covered by Property 26 /
Task 8.13). The recipient resolution, message composition, and (Part 2) the
``send_email`` orchestration all run REAL against the DB.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
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
from app.integrations.email_sender import EmailAttempt, SendResult
from app.modules.admin.models import EmailProvider, Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.staff import onboarding_delivery, onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.public_router import onboarding_public_router

# Marker baked into seeded org names + a provider-key prefix so cleanup can find
# orphans even when a test aborts mid-way. Distinct from the other onboarding DB
# tests so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_12_3_completion"
_PROVIDER_KEY_PREFIX = "test_12_3_onboarding_"

# Seeded staff identity — the submit must never mutate these.
_STAFF_FIRST_NAME = "Onboarding"
_STAFF_EMAIL = "staff-12-3@example.com"


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per test — bound to the run loop).
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
    """Delete every row created by the seeders (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in (
                "audit_log",
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
            # Remove any active provider rows seeded by Part 2.
            await session.execute(
                sa_text(
                    "DELETE FROM email_providers WHERE provider_key LIKE :pkey"
                ),
                {"pkey": f"{_PROVIDER_KEY_PREFIX}%"},
            )


async def _seed(factory) -> dict:
    """Seed an org + active staff + admin users (with negative controls).

    Recipients that MUST receive an org-completion email: two active
    ``org_admin`` users in the target org. Negative controls that MUST NOT be
    emailed: an inactive ``org_admin``, an active ``salesperson``, and an active
    ``org_admin`` in a DIFFERENT org.

    (The ``users.role`` CHECK constraint does not include ``branch_admin`` — it
    is modelled as a custom role — so the resolvable built-in admin role here is
    ``org_admin``; the resolver query targets ``org_admin``/``branch_admin`` and
    org-scopes the result, which this seed exercises via ``org_admin``.)
    """
    suffix = uuid.uuid4().hex[:8]
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan",
                monthly_price_nzd=0,
                user_seats=10,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            org = Organisation(
                name=f"{_ORG_MARKER}_{suffix}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            other_org = Organisation(
                name=f"{_ORG_MARKER}_other_{suffix}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add_all([org, other_org])
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Onboarding Test Staff",
                first_name=_STAFF_FIRST_NAME,
                last_name="OriginalLast",
                email=_STAFF_EMAIL,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            recipient_1 = f"admin1-{suffix}@test12-3.example"
            recipient_2 = f"admin2-{suffix}@test12-3.example"

            users = [
                # Two ACTIVE org_admins in the target org → expected recipients.
                User(
                    org_id=org.id,
                    email=recipient_1,
                    role="org_admin",
                    is_active=True,
                    first_name="Admin",
                    last_name="One",
                ),
                User(
                    org_id=org.id,
                    email=recipient_2,
                    role="org_admin",
                    is_active=True,
                    first_name="Admin",
                    last_name="Two",
                ),
                # INACTIVE org_admin in the target org → excluded.
                User(
                    org_id=org.id,
                    email=f"inactive-{suffix}@test12-3.example",
                    role="org_admin",
                    is_active=False,
                    first_name="Inactive",
                    last_name="Admin",
                ),
                # ACTIVE non-admin in the target org → excluded.
                User(
                    org_id=org.id,
                    email=f"sales-{suffix}@test12-3.example",
                    role="salesperson",
                    is_active=True,
                    first_name="Sales",
                    last_name="Person",
                ),
                # ACTIVE org_admin in a DIFFERENT org → excluded (org scope).
                User(
                    org_id=other_org.id,
                    email=f"otherorg-{suffix}@test12-3.example",
                    role="org_admin",
                    is_active=True,
                    first_name="Other",
                    last_name="Org",
                ),
            ]
            session.add_all(users)
            await session.flush()

            return {
                "org_id": org.id,
                "org_name": org.name,
                "staff_id": staff.id,
                "staff_email": _STAFF_EMAIL,
                "expected_recipients": {recipient_1, recipient_2},
            }


async def _seed_active_provider(factory) -> None:
    """Seed ONE active email provider so ``send_email``'s failover loop runs.

    ``dispatch_one_provider`` is mocked in Part 2, so the provider's transport /
    credentials are never actually used — only its presence (``is_active`` +
    ``credentials_set``) matters so ``_load_active_providers`` returns a
    non-empty list and the dispatch loop is entered.
    """
    async with factory() as session:
        async with session.begin():
            provider = EmailProvider(
                provider_key=f"{_PROVIDER_KEY_PREFIX}{uuid.uuid4().hex[:8]}",
                display_name="Test 12.3 Provider",
                priority=0,
                is_active=True,
                credentials_set=True,
                credentials_encrypted=b"unused-by-mocked-dispatch",
            )
            session.add(provider)
            await session.flush()


def _build_app(factory) -> FastAPI:
    """Expose ONLY the public onboarding router at the production mount point."""
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


# A minimal, fully-valid submission: only the personal fields are supplied.
# Emergency contact is omitted on both sides (valid pairing), no bank / IRD /
# documents, so the submit succeeds with no field errors.
_SUBMIT_FORM = {
    "last_name": "Onboarded",
    "phone": "0211234567",
}


def _ok_send_result() -> SendResult:
    return SendResult(
        success=True,
        provider_key="mock",
        transport="mock",
        message_id="mock-message-id",
        attempts=[],
    )


def _ok_attempt() -> EmailAttempt:
    return EmailAttempt(
        provider_key="mock",
        transport="mock",
        success=True,
        message_id="mock-message-id",
        duration_ms=1,
    )


# ---------------------------------------------------------------------------
# Part 1 — submit returns 200 + attempts staff confirmation + org emails.
# ---------------------------------------------------------------------------


async def _run_part1() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed(factory)
        org_name = seed["org_name"]
        staff_email = seed["staff_email"]
        expected_recipients = seed["expected_recipients"]

        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=seed["org_id"], staff_id=seed["staff_id"]
                )

        app = _build_app(factory)

        confirmation_subject = f"Thanks for completing your onboarding — {org_name}"

        # Record every completion email at the unified send_email boundary while
        # letting the real send_onboarding_confirmation_email + org loop run.
        send_email_mock = AsyncMock(return_value=_ok_send_result())
        confirm_spy = AsyncMock(
            wraps=onboarding_delivery.send_onboarding_confirmation_email
        )

        with patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.staff.onboarding_delivery.send_email",
            new=send_email_mock,
        ), patch(
            "app.modules.staff.onboarding_delivery.send_onboarding_confirmation_email",
            new=confirm_spy,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=_SUBMIT_FORM
                )

        # --- The submit returns the 200 thank-you (R15.3). ---
        assert resp.status_code == 200, (
            f"expected 200 from submit, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("ok") is True, f"submit not ok: {resp.text}"
        assert "thank" in (body.get("message") or "").lower(), (
            f"expected a thank-you message, got: {body.get('message')!r}"
        )

        # --- The staff confirmation email was attempted exactly once (R15.3). ---
        assert confirm_spy.await_count == 1, (
            f"staff confirmation email should be attempted exactly once, "
            f"got {confirm_spy.await_count}"
        )
        confirm_kwargs = confirm_spy.await_args.kwargs
        assert confirm_kwargs.get("staff_email") == staff_email
        assert confirm_kwargs.get("org_name") == org_name

        # --- Inspect every message dispatched through send_email. ---
        dispatched = [call.args[1] for call in send_email_mock.await_args_list]
        confirmation_msgs = [
            m for m in dispatched if m.subject == confirmation_subject
        ]
        org_msgs = [m for m in dispatched if "completed onboarding" in m.subject]

        # Exactly one staff confirmation email to the staff member (R15.3).
        assert len(confirmation_msgs) == 1, (
            f"expected exactly one staff confirmation email, "
            f"got {len(confirmation_msgs)} (subjects: "
            f"{[m.subject for m in dispatched]})"
        )
        assert confirmation_msgs[0].to_email == staff_email

        # Exactly one org-completion email per resolved active org_admin (R16.3),
        # addressed to exactly the expected recipients and no one else.
        assert len(org_msgs) == len(expected_recipients), (
            f"expected {len(expected_recipients)} org-completion emails, "
            f"got {len(org_msgs)}"
        )
        assert {m.to_email for m in org_msgs} == expected_recipients, (
            "org-completion emails went to the wrong recipient set"
        )
        for m in org_msgs:
            assert org_name in m.subject
            assert _STAFF_FIRST_NAME in m.subject

        # Total: one staff confirmation + one per recipient — nothing else.
        assert send_email_mock.await_count == 1 + len(expected_recipients)
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_successful_submit_returns_200_and_attempts_completion_emails():
    """A successful submit returns 200 thank-you and attempts the completion emails.

    Drives the real ``POST /api/v2/public/staff-onboarding/{token}``: the
    response is the ``200`` thank-you, the staff confirmation email is attempted
    exactly once to the staff address (R15.3), and one org-completion email is
    sent per resolved active ``org_admin``/``branch_admin`` recipient (R16.3) —
    never to the inactive admin, the non-admin, or another org's admin.

    Requirements: 15.3, 16.3
    """
    asyncio.run(_run_part1())


# ---------------------------------------------------------------------------
# Part 2 — completion emails flow through the real multi-provider dispatch.
# ---------------------------------------------------------------------------


async def _run_part2() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed(factory)
        await _seed_active_provider(factory)
        org_name = seed["org_name"]
        staff_email = seed["staff_email"]
        expected_recipients = seed["expected_recipients"]

        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=seed["org_id"], staff_id=seed["staff_id"]
                )

        app = _build_app(factory)

        confirmation_subject = f"Thanks for completing your onboarding — {org_name}"

        # Mock ONLY the low-level per-provider network send; let the real
        # send_email orchestration (precheck → blocklist → provider load →
        # failover loop) run so we exercise the multi-provider dispatch wiring.
        dispatch_mock = AsyncMock(return_value=_ok_attempt())

        with patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.integrations.email_sender.dispatch_one_provider",
            new=dispatch_mock,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=_SUBMIT_FORM
                )

        assert resp.status_code == 200, (
            f"expected 200 from submit, got {resp.status_code}: {resp.text}"
        )
        assert resp.json().get("ok") is True, f"submit not ok: {resp.text}"

        # Each completion email reached the low-level dispatch via send_email's
        # real failover loop. dispatch_one_provider(db, provider, message, ...) —
        # the composed EmailMessage is the 3rd positional argument.
        assert dispatch_mock.await_count >= 1, (
            "no email reached the low-level provider dispatch — the completion "
            "emails did not flow through the unified send_email path"
        )
        dispatched = [call.args[2] for call in dispatch_mock.await_args_list]

        confirmation_msgs = [
            m for m in dispatched if m.subject == confirmation_subject
        ]
        org_msgs = [m for m in dispatched if "completed onboarding" in m.subject]

        # Staff confirmation (R15.3) flowed through the multi-provider dispatch.
        assert len(confirmation_msgs) == 1, (
            f"expected exactly one staff confirmation dispatched, got "
            f"{len(confirmation_msgs)} (subjects: {[m.subject for m in dispatched]})"
        )
        assert confirmation_msgs[0].to_email == staff_email

        # One org-completion email per recipient (R16.3) flowed through dispatch.
        assert len(org_msgs) == len(expected_recipients), (
            f"expected {len(expected_recipients)} org-completion emails "
            f"dispatched, got {len(org_msgs)}"
        )
        assert {m.to_email for m in org_msgs} == expected_recipients
        for m in org_msgs:
            assert org_name in m.subject
            assert _STAFF_FIRST_NAME in m.subject

        # Each send_email call succeeds on the first provider, so total dispatch
        # calls == one per completion email (staff + one per recipient).
        assert dispatch_mock.await_count == 1 + len(expected_recipients)
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_completion_emails_flow_through_multi_provider_dispatch():
    """Both completion emails actually flow through the unified send_email dispatch.

    Seeds one active provider and patches the low-level
    ``email_sender.dispatch_one_provider`` (the network/provider seam) while the
    real ``send_email`` orchestration runs. Asserts the staff confirmation
    (R15.3) and each org-completion email (R16.3) reach the per-provider
    dispatch as composed ``EmailMessage`` objects with the expected subjects.

    Requirements: 15.3, 16.3
    """
    asyncio.run(_run_part2())


# ---------------------------------------------------------------------------
# Part 3 — successful submit writes the onboarding.completed audit row (R9.9).
# ---------------------------------------------------------------------------

# A submission that DOES supply IRD + bank so the "no plaintext in the audit
# row" assertion is meaningful (both are envelope-encrypted at rest and must
# never appear in the audit after_value).
_AUDIT_SUBMIT_FORM = {
    "last_name": "Onboarded",
    "phone": "0211234567",
    "bank_account_number": "01-0234-0567890-00",
    "ird_number": "123456789",
}


async def _run_part3() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed(factory)
        staff_id = seed["staff_id"]
        org_id = seed["org_id"]

        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        app = _build_app(factory)

        # Stub the completion side-effects (in-app + emails) so this test
        # focuses solely on the in-transaction audit row (R9.9).
        with patch(
            "app.modules.staff.public_router.create_in_app_notification",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.modules.staff.onboarding_delivery.send_email",
            new=AsyncMock(return_value=_ok_send_result()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{raw}", data=_AUDIT_SUBMIT_FORM
                )

        assert resp.status_code == 200, (
            f"expected 200 from submit, got {resp.status_code}: {resp.text}"
        )

        # Exactly one onboarding.completed audit row for this org, scoped to the
        # staff member, with the submitter IP captured and NO plaintext secrets.
        async with factory() as session:
            rows = (
                await session.execute(
                    sa_text(
                        """
                        SELECT entity_type, entity_id, ip_address,
                               after_value::text AS after_text
                        FROM audit_log
                        WHERE org_id = :org_id
                          AND action = 'onboarding.completed'
                        """
                    ),
                    {"org_id": str(org_id)},
                )
            ).mappings().all()

        assert len(rows) == 1, (
            f"expected exactly one onboarding.completed audit row, got {len(rows)}"
        )
        row = rows[0]
        assert row["entity_type"] == "staff_member"
        assert str(row["entity_id"]) == str(staff_id)
        assert row["ip_address"] is not None, "submitter IP should be captured"

        after_text = row["after_text"] or ""
        # The plaintext IRD / bank account must NEVER appear in the audit row.
        assert "123456789" not in after_text, "IRD plaintext leaked into audit row"
        assert "0567890" not in after_text, "bank plaintext leaked into audit row"
        # The non-sensitive summary flags ARE recorded.
        assert "ird_provided" in after_text
        assert "bank_provided" in after_text
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_successful_submit_writes_completion_audit_row():
    """A successful submit writes exactly one ``onboarding.completed`` audit row.

    Drives the real public submit with an IRD + bank account supplied, then
    asserts a single org-scoped ``onboarding.completed`` ``audit_log`` row exists
    for the staff member with the submitter IP captured, and that the row's
    ``after_value`` contains only the non-sensitive summary — never the
    plaintext IRD or bank account number (R9.9).

    Requirements: 9.9
    """
    asyncio.run(_run_part3())


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted test."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
