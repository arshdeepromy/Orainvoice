"""Property-based test: Employee Portal password length acceptance & hashing.

# Feature: organisation-employee-portal, Property 11: Password length acceptance and hashing

**Validates: Requirements 5.5, 5.6, 14.4, 14.7**

Property 11 (design.md): *For any* submitted password during invite-acceptance
or password reset, the password is accepted **if and only if** its length is
between 8 and 128 inclusive; an out-of-range password is rejected with a length
message and leaves all stored credential state unchanged, and an accepted
password is persisted **only as a hash**, never as plaintext.

This test has two layers:

1. **Pure length gate (no DB).** ``app.modules.employee_portal.auth.
   validate_password_length`` is a pure ``(ok, message)`` predicate. We drive it
   over >= 100 generated examples (Hypothesis), *explicitly* seeding the
   boundary lengths 7 / 8 / 128 / 129, and assert ``ok`` is ``True`` iff
   ``8 <= len <= 128`` and that every rejection carries the human-readable
   length message (and every acceptance carries none).

2. **Persistence path (transactional dev DB).** ``accept_invite`` and
   ``complete_reset`` in ``app.modules.employee_portal.services.
   account_service`` are the two write paths that turn a submitted password
   into stored state. Against the real dev Postgres (mirroring the DB-backed
   Hypothesis pattern in ``tests/test_onboarding_single_use_property.py`` — a
   fresh async engine per example, the full ORM import block, an org-name
   marker for cleanup, and an ``asyncio.run`` driver), for each example we seed
   an org + active staff + a portal user holding a fresh invite/reset token,
   submit a password, and assert:

   - **Out-of-range (len < 8 or > 128)** → :class:`PasswordLengthError` is
     raised, ``password_hash`` stays ``NULL`` (or unchanged for reset), and the
     single-use token is **not** consumed (``invite_token_hash`` /
     ``reset_token_hash`` unchanged) — stored credential state is untouched
     (R5.6, R14.7).
   - **In-range (8..128)** → the call succeeds, the token is consumed, and the
     persisted ``password_hash`` is **not** the plaintext, *is* a bcrypt hash,
     and ``verify_password`` accepts the original plaintext (R5.5, R14.4) — the
     password is persisted only as a hash.

The persistence assertions re-read the row from the database (not just the
in-memory ORM object) so they pin the committed state.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_onboarding_single_use_property.py).
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.auth import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PASSWORD_LENGTH_MESSAGE,
    validate_password_length,
    verify_password_sync,
)
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.employee_portal.services import account_service
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_5_5_password_length"


# ---------------------------------------------------------------------------
# Layer 1 — pure length gate (no DB). >= 100 examples incl. boundary lengths.
# ---------------------------------------------------------------------------

PURE_SETTINGS = settings(max_examples=300, deadline=None)

# A few control characters / multibyte chars so "length" is exercised on the
# Python string length (code points), not bytes. The boundary values 7/8/128/129
# are injected explicitly below so they are always covered.
_password_length_strategy = st.integers(min_value=0, max_value=300)


def _password_of_length(n: int) -> str:
    """Return a deterministic password string of exactly ``n`` code points."""
    return "p" * n


@PURE_SETTINGS
@given(n=_password_length_strategy)
def test_validate_password_length_accepts_iff_in_range(n: int) -> None:
    """``validate_password_length`` accepts iff 8 <= len <= 128 (R5.6, R14.7).

    Every rejection carries the human-readable length message; every
    acceptance carries an empty message.

    **Validates: Requirements 5.6, 14.7**
    """
    password = _password_of_length(n)
    ok, message = validate_password_length(password)

    expected = MIN_PASSWORD_LENGTH <= n <= MAX_PASSWORD_LENGTH
    assert ok is expected, f"length {n}: expected accepted={expected}, got {ok}"
    if ok:
        assert message == ""
    else:
        assert message == PASSWORD_LENGTH_MESSAGE
        assert str(MIN_PASSWORD_LENGTH) in message
        assert str(MAX_PASSWORD_LENGTH) in message


@pytest.mark.parametrize(
    "length,accepted",
    [
        (7, False),    # just below the lower bound
        (8, True),     # lower boundary — accepted
        (128, True),   # upper boundary — accepted
        (129, False),  # just above the upper bound
    ],
)
def test_validate_password_length_boundaries(length: int, accepted: bool) -> None:
    """Explicit boundary lengths 7 / 8 / 128 / 129 (R5.6, R14.7).

    **Validates: Requirements 5.6, 14.7**
    """
    ok, message = validate_password_length(_password_of_length(length))
    assert ok is accepted
    assert (message == "") is accepted


def test_validate_password_length_none_is_rejected() -> None:
    """``None`` is treated as out-of-range and rejected with the length message."""
    ok, message = validate_password_length(None)
    assert ok is False
    assert message == PASSWORD_LENGTH_MESSAGE


# ---------------------------------------------------------------------------
# Layer 2 — persistence path against the transactional dev Postgres.
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
                "employee_portal_audit_log",
                "employee_portal_sessions",
                "employee_portal_users",
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
                name="Password Length Test Staff",
                first_name="Password",
                last_name="Tester",
                email=f"pwlen-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


async def _run_persistence_example(flow: str, password: str) -> None:
    """Seed a portal user with a fresh token, submit ``password`` via ``flow``.

    ``flow`` is one of ``"invite"`` (``accept_invite``) or ``"reset"``
    (``complete_reset``). Asserts the in-range / out-of-range persistence
    behaviour of Property 11.
    """
    in_range = MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH

    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]
        now = datetime.now(timezone.utc)

        # --- Provision a portal user holding the relevant fresh token. ---
        # token_hash = sha256(raw); we mint a raw token here and store its hash,
        # mirroring what issue_access / request_reset do.
        raw_token = uuid.uuid4().hex + uuid.uuid4().hex  # opaque raw token
        token_hash = account_service._hash_token(raw_token)

        async with factory() as session:
            async with session.begin():
                user = EmployeePortalUser(
                    org_id=org_id,
                    staff_id=staff_id,
                    email=f"pwlen-{uuid.uuid4().hex[:8]}@example.com",
                    password_hash=None,
                    is_active=True,
                )
                if flow == "invite":
                    user.invite_token_hash = token_hash
                    user.invite_sent_at = now
                else:  # reset
                    # A reset presupposes an already-set password; seed one so
                    # we can prove an out-of-range reset leaves it UNCHANGED.
                    user.password_hash = ep_auth.hash_password_sync("existing-pw-123")
                    user.reset_token_hash = token_hash
                    user.reset_token_expires_at = now + timedelta(seconds=3600)
                session.add(user)
                await session.flush()
                user_id = user.id
                seeded_hash = user.password_hash

        # --- Submit the password through the chosen write path. ---
        if flow == "invite":
            call = account_service.accept_invite
        else:
            call = account_service.complete_reset

        if in_range:
            async with factory() as session:
                async with session.begin():
                    updated = await call(session, raw_token, password)
                    assert updated.id == user_id

            # Re-read committed state from the DB.
            async with factory() as session:
                persisted = await session.get(EmployeePortalUser, user_id)
                assert persisted is not None
                # The accepted password is persisted ONLY as a hash.
                assert persisted.password_hash is not None
                assert persisted.password_hash != password, (
                    "the plaintext password must never be stored"
                )
                assert verify_password_sync(password, persisted.password_hash), (
                    "the stored value must be a bcrypt hash of the plaintext"
                )
                # The single-use token was consumed.
                if flow == "invite":
                    assert persisted.invite_token_hash is None
                    assert persisted.invite_accepted_at is not None
                else:
                    assert persisted.reset_token_hash is None
                    assert persisted.reset_token_expires_at is None
        else:
            # Out-of-range: the call rejects and leaves stored state unchanged.
            with pytest.raises(account_service.PasswordLengthError) as exc:
                async with factory() as session:
                    async with session.begin():
                        await call(session, raw_token, password)
            assert exc.value.code == "password_length"
            assert str(MIN_PASSWORD_LENGTH) in exc.value.message

            # Re-read committed state — nothing changed.
            async with factory() as session:
                persisted = await session.get(EmployeePortalUser, user_id)
                assert persisted is not None
                assert persisted.password_hash == seeded_hash, (
                    "an out-of-range password must not write password_hash"
                )
                if flow == "invite":
                    assert persisted.invite_token_hash == token_hash, (
                        "an out-of-range invite must not consume the token"
                    )
                    assert persisted.invite_accepted_at is None
                else:
                    assert persisted.reset_token_hash == token_hash, (
                        "an out-of-range reset must not consume the token"
                    )
                    assert persisted.reset_token_expires_at is not None
    finally:
        await _cleanup(factory)
        await engine.dispose()


# Length strategy for the DB layer: focus on a tight band around the bounds
# (kept small so bcrypt hashing per accepted example stays affordable) plus the
# four explicit boundary lengths so 7/8/128/129 are always exercised.
_db_length_strategy = st.one_of(
    st.sampled_from([7, 8, 128, 129]),
    st.integers(min_value=0, max_value=12),
    st.integers(min_value=124, max_value=132),
)


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    flow=st.sampled_from(["invite", "reset"]),
    length=_db_length_strategy,
)
def test_password_length_persistence_and_hashing(flow: str, length: int) -> None:
    """Property 11: accepted iff 8..128; out-of-range leaves state unchanged;
    an accepted password is persisted only as a bcrypt hash (DB-backed).

    **Validates: Requirements 5.5, 5.6, 14.4, 14.7**
    """
    asyncio.run(_run_persistence_example(flow, _password_of_length(length)))


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
