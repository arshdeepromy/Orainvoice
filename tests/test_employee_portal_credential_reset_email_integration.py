"""Integration test — credential-setup + password-reset email dispatch (R15).

Feature: organisation-employee-portal
Task 17.4 — Requirements 15.1, 15.3, 15.5

This is an INTEGRATION test (NOT a property-based test). It wires the REAL
employee-portal credential lifecycle (``account_service.issue_access`` /
``request_reset``) and the REAL email-delivery helpers
(``employee_portal_delivery.send_credential_setup_email`` /
``send_password_reset_email``) against the transactional dev Postgres, and lets
the REAL unified ``send_email`` orchestration run (payload pre-check →
bounce-blocklist lookup → active-provider load → multi-provider failover loop).
Only the LOW-LEVEL per-provider network send
(``app.integrations.email_sender.dispatch_one_provider``) is mocked — exactly
the seam used by ``tests/test_onboarding_completion_sideeffects_integration.py``
Part 2 — so the failover wiring is exercised end-to-end without touching the
network.

Three things are verified:

1. ``test_credential_email_dispatched_through_send_email_failover`` (R15.1) —
   issuing a credential (``issue_access`` creates the Portal_User) and then
   dispatching ``send_credential_setup_email`` drives a composed
   ``EmailMessage`` (naming the Organisation) through the real ``send_email``
   provider chain; the first provider accepts and the helper returns ``ok``.
2. ``test_reset_email_dispatched_through_send_email_failover`` (R15.5) —
   requesting a reset (``request_reset`` mints a single-use token) and then
   dispatching ``send_password_reset_email`` flows through the same
   ``send_email`` failover path and returns ``ok``.
3. ``test_all_providers_fail_preserves_portal_user`` (R15.3) — with EVERY
   provider attempt failing (soft provider error), the real failover loop tries
   each seeded provider in turn and the helper returns ``ok=False`` /
   ``error_code='send_failed'`` WITHOUT raising; the Portal_User created and
   committed before the (after-commit) dispatch is still present and active —
   the total email failure never rolled back or destroyed the credential.

DB harness mirrors the established portal DB tests
(``tests/test_employee_portal_anti_enumeration_property.py``): a fresh async
engine per run, the full ORM import block so SQLAlchemy can configure mappers,
an org-name + provider-key marker for orphan cleanup, and an ``asyncio.run``
driver. ``DATABASE_URL`` must point at the transactional dev Postgres
(``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

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
from app.modules.employee_portal import models as _emp_portal_models  # noqa: F401

from app.integrations.email_sender import EmailAttempt, FailureKind
from app.modules.admin.models import EmailProvider, Organisation, SubscriptionPlan
from app.modules.employee_portal import employee_portal_delivery as epd
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.employee_portal.services import account_service
from app.modules.staff.models import StaffMember

# Markers baked into seeded rows so cleanup can find orphans even when a run
# aborts mid-way. Distinct from the other portal DB tests so parallel /
# interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_17_4_cred_reset_email"
_PROVIDER_KEY_PREFIX = "test_17_4_emp_portal_"

_KNOWN_EMAIL = "worker@example.test"


# ---------------------------------------------------------------------------
# Engine / cleanup / seed helpers (fresh engine per run).
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
    """Delete every row created by the seeder (keyed on the markers)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in (
                "employee_portal_audit_log",
                "employee_portal_sessions",
                "employee_portal_users",
                "staff_members",
                "dead_letter_queue",
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
            await session.execute(
                sa_text(
                    "DELETE FROM email_providers WHERE provider_key LIKE :pfx"
                ),
                {"pfx": f"{_PROVIDER_KEY_PREFIX}%"},
            )


async def _seed_org_and_staff(factory) -> dict:
    """Seed one org + one active Staff_Member. Returns ids + org name."""
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

            org_name = f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}"
            org = Organisation(
                name=org_name,
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                slug=f"epp{uuid.uuid4().hex[:18]}",
                settings={"employee_portal_enabled": True},
            )
            session.add(org)
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Credential Reset Staff",
                first_name="Credential",
                last_name="Staff",
                email=_KNOWN_EMAIL,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {
                "org_id": org.id,
                "org_name": org_name,
                "staff_id": staff.id,
            }


async def _seed_active_providers(factory, count: int = 2) -> None:
    """Seed ``count`` active email providers so ``send_email``'s failover loop
    iterates across multiple providers.

    ``dispatch_one_provider`` is mocked, so the providers' transport /
    credentials are never actually used — only their presence (``is_active`` +
    ``credentials_set``) matters so ``_load_active_providers`` returns a
    non-empty, multi-entry list and the failover loop is genuinely exercised.
    """
    async with factory() as session:
        async with session.begin():
            for i in range(count):
                session.add(
                    EmailProvider(
                        provider_key=f"{_PROVIDER_KEY_PREFIX}{uuid.uuid4().hex[:8]}",
                        display_name=f"Test 17.4 Provider {i}",
                        priority=i,
                        is_active=True,
                        credentials_set=True,
                        credentials_encrypted=b"unused-by-mocked-dispatch",
                    )
                )


def _ok_attempt() -> EmailAttempt:
    """A successful per-provider attempt (first provider accepts)."""
    return EmailAttempt(
        provider_key="mock",
        transport="rest_api",
        success=True,
        message_id="mock-message-id",
        duration_ms=1,
    )


def _soft_fail_attempt(db, provider, message, **kwargs) -> EmailAttempt:
    """A SOFT_PROVIDER failure for every provider so the failover loop tries
    each in turn and ultimately exhausts the chain (no provider succeeds).

    Signature matches ``dispatch_one_provider(db, provider, message, ...)`` so
    it can be used directly as the mock's ``side_effect``.
    """
    return EmailAttempt(
        provider_key=getattr(provider, "provider_key", "mock"),
        transport="rest_api",
        success=False,
        failure_kind=FailureKind.SOFT_PROVIDER,
        error="simulated provider outage",
        duration_ms=1,
    )


# ---------------------------------------------------------------------------
# (a) Credential-setup email dispatched through the real send_email failover.
# ---------------------------------------------------------------------------


async def _run_credential_email() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed_org_and_staff(factory)
        await _seed_active_providers(factory, count=2)
        org_name = seed["org_name"]

        # Issue the credential (creates + commits the Portal_User), then — as
        # the API layer does — dispatch the email AFTER commit.
        dispatch_mock = AsyncMock(return_value=_ok_attempt())
        with patch(
            "app.integrations.email_sender.dispatch_one_provider",
            new=dispatch_mock,
        ):
            async with factory() as session:
                async with session.begin():
                    staff = (
                        await session.execute(
                            select(StaffMember).where(
                                StaffMember.id == seed["staff_id"]
                            )
                        )
                    ).scalars().one()
                    user, raw_token = await account_service.issue_access(
                        session, seed["org_id"], staff
                    )
                    portal_user_id = user.id

                # After-commit dispatch through the REAL send_email failover.
                async with factory() as session:
                    result = await epd.send_credential_setup_email(
                        session,
                        staff_email=_KNOWN_EMAIL,
                        org_name=org_name,
                        set_password_url=(
                            f"https://x/e/slug/accept-invite/{raw_token}"
                        ),
                        org_id=seed["org_id"],
                    )

        # The helper reports success ...
        assert result.ok is True, f"credential email not ok: {result.error_code}"
        assert result.message_id == "mock-message-id"

        # ... and the email genuinely flowed through send_email's provider loop:
        # exactly one low-level dispatch (first provider accepts, loop stops).
        assert dispatch_mock.await_count == 1, (
            "credential email did not flow through the send_email provider "
            f"loop (dispatch calls={dispatch_mock.await_count})"
        )
        # The composed message names the Organisation (R15.1).
        dispatched_msg = dispatch_mock.await_args.args[2]
        assert org_name in dispatched_msg.subject
        assert dispatched_msg.to_email == _KNOWN_EMAIL

        # The Portal_User persisted.
        async with factory() as session:
            present = (
                await session.execute(
                    select(EmployeePortalUser.id).where(
                        EmployeePortalUser.id == portal_user_id
                    )
                )
            ).first()
        assert present is not None
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_credential_email_dispatched_through_send_email_failover():
    """Issuing a credential dispatches the credential-setup email through the
    real ``send_email`` multi-provider failover path (R15.1).

    Requirements: 15.1
    """
    asyncio.run(_run_credential_email())


# ---------------------------------------------------------------------------
# (b) Password-reset email dispatched through the real send_email failover.
# ---------------------------------------------------------------------------


async def _run_reset_email() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed_org_and_staff(factory)
        await _seed_active_providers(factory, count=2)
        org_name = seed["org_name"]

        dispatch_mock = AsyncMock(return_value=_ok_attempt())
        with patch(
            "app.integrations.email_sender.dispatch_one_provider",
            new=dispatch_mock,
        ):
            # Provision an active Portal_User, then request a reset token.
            async with factory() as session:
                async with session.begin():
                    staff = (
                        await session.execute(
                            select(StaffMember).where(
                                StaffMember.id == seed["staff_id"]
                            )
                        )
                    ).scalars().one()
                    await account_service.issue_access(
                        session, seed["org_id"], staff
                    )

            async with factory() as session:
                async with session.begin():
                    issued = await account_service.request_reset(
                        session, seed["org_id"], _KNOWN_EMAIL
                    )
                    assert issued is not None, "reset token was not issued"
                    _user, raw_reset = issued

            # After-commit dispatch through the REAL send_email failover.
            async with factory() as session:
                result = await epd.send_password_reset_email(
                    session,
                    staff_email=_KNOWN_EMAIL,
                    org_name=org_name,
                    reset_url=f"https://x/e/slug/reset/{raw_reset}",
                    org_id=seed["org_id"],
                )

        assert result.ok is True, f"reset email not ok: {result.error_code}"
        assert result.message_id == "mock-message-id"
        assert dispatch_mock.await_count == 1, (
            "reset email did not flow through the send_email provider loop "
            f"(dispatch calls={dispatch_mock.await_count})"
        )
        dispatched_msg = dispatch_mock.await_args.args[2]
        assert org_name in dispatched_msg.subject
        assert dispatched_msg.to_email == _KNOWN_EMAIL
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_reset_email_dispatched_through_send_email_failover():
    """Requesting a reset dispatches the reset email through the same real
    ``send_email`` multi-provider failover path (R15.5).

    Requirements: 15.5
    """
    asyncio.run(_run_reset_email())


# ---------------------------------------------------------------------------
# (c) All-providers-fail: failover exhausts the chain, Portal_User preserved.
# ---------------------------------------------------------------------------


async def _run_all_providers_fail_preserves_user() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed_org_and_staff(factory)
        await _seed_active_providers(factory, count=2)
        org_name = seed["org_name"]

        # Issue + COMMIT the credential first (this is what the API layer does
        # before it dispatches the email after commit).
        async with factory() as session:
            async with session.begin():
                staff = (
                    await session.execute(
                        select(StaffMember).where(
                            StaffMember.id == seed["staff_id"]
                        )
                    )
                ).scalars().one()
                user, raw_token = await account_service.issue_access(
                    session, seed["org_id"], staff
                )
                portal_user_id = user.id

        # EVERY provider attempt fails — the real failover loop tries each
        # seeded provider in turn and the chain is exhausted.
        dispatch_mock = AsyncMock(side_effect=_soft_fail_attempt)
        with patch(
            "app.integrations.email_sender.dispatch_one_provider",
            new=dispatch_mock,
        ):
            async with factory() as session:
                result = await epd.send_credential_setup_email(
                    session,
                    staff_email=_KNOWN_EMAIL,
                    org_name=org_name,
                    set_password_url=(
                        f"https://x/e/slug/accept-invite/{raw_token}"
                    ),
                    org_id=seed["org_id"],
                )

        # The helper reports failure WITHOUT raising (R15.3) ...
        assert result.ok is False
        assert result.error_code == epd.ERROR_SEND_FAILED

        # ... and the failover was genuinely exercised across multiple
        # providers (every one tried, since each soft-fails).
        assert dispatch_mock.await_count >= 2, (
            "all-providers-fail path did not exercise multi-provider failover "
            f"(dispatch calls={dispatch_mock.await_count})"
        )

        # CRITICAL (R15.3): the total email failure did NOT roll back or
        # destroy the committed Portal_User — it is still present and active.
        async with factory() as session:
            row = (
                await session.execute(
                    select(
                        EmployeePortalUser.id, EmployeePortalUser.is_active
                    ).where(EmployeePortalUser.id == portal_user_id)
                )
            ).first()
        assert row is not None, "Portal_User was destroyed by the email failure"
        assert row.is_active is True, "Portal_User was deactivated by email failure"
    finally:
        await _cleanup(factory)
        await engine.dispose()


def test_all_providers_fail_preserves_portal_user():
    """When every provider fails, the credential-setup send returns a failure
    result without raising and the created Portal_User is preserved (R15.3).

    Requirements: 15.3
    """
    asyncio.run(_run_all_providers_fail_preserves_user())
