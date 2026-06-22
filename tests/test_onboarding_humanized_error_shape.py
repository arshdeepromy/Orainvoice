"""Integration test for humanized error-shape across onboarding endpoints (Task 12.2).

Feature: staff-onboarding-link
Requirements: 14.1 (public errors carry a human message), 14.2 (admin errors
carry a human message), 14.5 (no raw DB/exception text in error responses).

This is an EXAMPLE / INTEGRATION test (not a property test). It drives every
error path of the public onboarding endpoints end-to-end through an in-process
ASGI client (``httpx.AsyncClient`` + ``ASGITransport``) and asserts each error
response body carries:

1. a NON-EMPTY human-readable ``message``; and
2. a machine ``code``; and
3. NO raw database / exception text (case-insensitive scan for ``traceback``,
   ``psycopg``, ``sqlalchemy``, ``asyncpg``, ``File "``, ``integrityerror``).

Public error paths driven against ``onboarding_public_router`` (mounted at the
prod path ``/api/v2/public/staff-onboarding``):

- **token-state rejections** — not-found (404, ``onboarding_token_not_found``),
  revoked / consumed / expired / staff-inactive (410 with the matching code),
  asserted on the GET prefill route and (for not-found) the POST submit route.
  Body shape: ``{"detail": {"message", "code"}}``.
- **validation failure** — POST submit with an invalid bank account format →
  422 ``{ok:false, message, errors:{field:{message, code}}}``.
- **encryption failure** — POST submit with valid IRD/bank but
  ``public_router.envelope_encrypt`` patched to raise → 422
  ``{ok:false, message, errors:{_global:{code:"encryption_failed"}}}``.
- **server error** — ``public_router.get_org_settings`` patched to raise an
  unexpected error AFTER token validation + RLS → 500
  ``{detail:{message, code:"server_error"}}`` (the handler's ``except Exception``
  boundary).

Admin error path (R14.2): the resend endpoint
``POST /api/v2/staff/{staff_id}/onboarding-link/resend`` returns 422
``{detail:{message, code:"onboarding_email_required"}}`` when the staff member
has no email. The admin router requires auth + org context, so the harness
injects ``request.state.org_id``/``user_id``/``client_ip`` and stubs the
``staff_management`` module gate (a no-op) — the email-required check fires
BEFORE any revoke/mint/audit, so this exercises the real humanized mapping. We
ALSO assert the underlying ``humanize_onboarding_error("onboarding_email_required")``
mapping is non-empty as a belt-and-braces unit check.

Validates: Requirements 14.1, 14.2, 14.5

Notes:
- Runs against the local dev Postgres via the ``DATABASE_URL`` override exposed
  by ``app.config.settings`` (postgresql+asyncpg://...:5434/workshoppro).
- A fresh async engine is created per scenario (asyncpg connections are bound
  to the event loop ``asyncio.run`` creates), mirroring the reference DB-backed
  onboarding tests in this repo.
- Email-send failure as a *public* error path does not surface as an HTTP error
  body (R3.6/R15.4/R16.6 make sends best-effort and swallowed). Its humanized
  shape is covered by the admin ``onboarding_email_required`` gate (R14.2) and by
  the ``send_failed`` code in the humanized-error mapping (asserted directly).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
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
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember
from app.modules.staff.onboarding_validation import humanize_onboarding_error
from app.modules.staff.public_router import onboarding_public_router
from app.modules.staff.router import router as staff_admin_router

# Marker baked into seeded org names so cleanup can find orphans even when a
# scenario aborts mid-way. Distinct from the other onboarding DB tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_12_2_humanized"

# Raw DB / exception markers that MUST NOT appear in any error response (R14.5).
_FORBIDDEN_MARKERS = (
    "traceback",
    "psycopg",
    "sqlalchemy",
    "asyncpg",
    'file "',
    "integrityerror",
)


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per scenario — bound to the run loop).
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


async def _seed_org_and_staff(factory, *, email: str | None = "onboard-12-2@example.com") -> dict:
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
                first_name="Onboarding",
                last_name="OriginalLast",
                email=email,
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


async def _mint_token(factory, *, org_id, staff_id) -> str:
    async with factory() as session:
        async with session.begin():
            return await onboarding_tokens.mint(session, org_id=org_id, staff_id=staff_id)


def _build_public_app(factory) -> FastAPI:
    """App exposing ONLY the public onboarding router at the prod path."""
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
    app.include_router(onboarding_public_router, prefix="/api/v2/public/staff-onboarding")
    return app


def _build_admin_app(factory, *, org_id) -> FastAPI:
    """App exposing the authenticated staff admin router at the prod path.

    Injects the org/user context the handler reads from ``request.state`` so the
    org-scoped resend endpoint is reachable without the full auth middleware.
    """
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        request.state.org_id = str(org_id)
        request.state.user_id = str(uuid.uuid4())
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    async def _override_db():
        async with factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(staff_admin_router, prefix="/api/v2/staff")
    return app


# ---------------------------------------------------------------------------
# Assertion helpers.
# ---------------------------------------------------------------------------


def _assert_no_raw_error_text(raw_body: str) -> None:
    """Assert the serialized body contains no raw DB/exception markers (R14.5)."""
    haystack = raw_body.lower()
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in haystack, (
            f"error response leaked raw DB/exception text ({marker!r}): {raw_body}"
        )


def _assert_message_and_code(obj: dict, *, expected_code: str | None = None) -> None:
    """Assert ``obj`` carries a non-empty human message + a machine code."""
    assert isinstance(obj, dict), f"expected an object with message/code, got {obj!r}"
    message = obj.get("message")
    code = obj.get("code")
    assert isinstance(message, str) and message.strip(), (
        f"error object missing a non-empty human-readable message: {obj!r}"
    )
    assert isinstance(code, str) and code.strip(), (
        f"error object missing a machine-readable code: {obj!r}"
    )
    if expected_code is not None:
        assert code == expected_code, f"expected code={expected_code!r}, got {code!r}"


# ---------------------------------------------------------------------------
# Token-state mutation helpers (drive the rejecting states).
# ---------------------------------------------------------------------------


async def _set_token_status(factory, *, token: str, status: str) -> None:
    async with factory() as session:
        async with session.begin():
            row = await onboarding_tokens.resolve(session, token)
            assert row is not None
            row.status = status


async def _expire_token(factory, *, token: str) -> None:
    async with factory() as session:
        async with session.begin():
            row = await onboarding_tokens.resolve(session, token)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)


async def _deactivate_staff(factory, *, staff_id) -> None:
    async with factory() as session:
        async with session.begin():
            staff = await session.get(StaffMember, staff_id)
            assert staff is not None
            staff.is_active = False


# ---------------------------------------------------------------------------
# Scenario drivers.
# ---------------------------------------------------------------------------

_VALID_SUBMIT_FORM = {
    "last_name": "Smith",
    "phone": "0211234567",
    "emergency_contact_name": "Jane",
    "emergency_contact_phone": "0217654321",
    "tax_code": "M",
    "student_loan": "false",
    "kiwisaver_enrolled": "false",
    "residency_type": "citizen",
    "ird_number": "123456789",
    "bank_account_number": "12-3456-7890123-00",
}


async def _drive_public_token_state_errors() -> None:
    """Every token-state rejection on the public GET (and not-found on POST)."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id, staff_id = ids["org_id"], ids["staff_id"]
        app = _build_public_app(factory)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # --- not-found: GET + POST with a token that was never issued ---
            bogus = uuid.uuid4().hex + uuid.uuid4().hex
            for resp in (
                await client.get(f"/api/v2/public/staff-onboarding/{bogus}"),
                await client.post(
                    f"/api/v2/public/staff-onboarding/{bogus}", data=_VALID_SUBMIT_FORM
                ),
            ):
                assert resp.status_code == 404, resp.text
                _assert_no_raw_error_text(resp.text)
                _assert_message_and_code(
                    resp.json()["detail"], expected_code="onboarding_token_not_found"
                )

            # --- revoked / consumed / expired / staff_inactive -> 410 ---
            cases = [
                ("revoked", "onboarding_token_revoked", "status"),
                ("consumed", "onboarding_token_consumed", "status"),
                ("expired", "onboarding_token_expired", "expiry"),
                ("staff_inactive", "onboarding_token_staff_inactive", "inactive"),
            ]
            for _label, expected_code, mutation in cases:
                # Fresh staff (re-activate) + fresh token per case.
                await _reactivate_staff(factory, staff_id=staff_id)
                token = await _mint_token(factory, org_id=org_id, staff_id=staff_id)
                if mutation == "status":
                    await _set_token_status(factory, token=token, status=_label_to_status(_label))
                elif mutation == "expiry":
                    await _expire_token(factory, token=token)
                elif mutation == "inactive":
                    await _deactivate_staff(factory, staff_id=staff_id)

                resp = await client.get(f"/api/v2/public/staff-onboarding/{token}")
                assert resp.status_code == 410, (
                    f"{expected_code}: expected 410, got {resp.status_code}: {resp.text}"
                )
                _assert_no_raw_error_text(resp.text)
                _assert_message_and_code(resp.json()["detail"], expected_code=expected_code)
    finally:
        await _cleanup(factory)
        await engine.dispose()


def _label_to_status(label: str) -> str:
    return {"revoked": "revoked", "consumed": "consumed"}[label]


async def _reactivate_staff(factory, *, staff_id) -> None:
    async with factory() as session:
        async with session.begin():
            staff = await session.get(StaffMember, staff_id)
            if staff is not None:
                staff.is_active = True


async def _drive_validation_failure() -> None:
    """POST submit with an invalid bank account format → 422 field error."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id, staff_id = ids["org_id"], ids["staff_id"]
        token = await _mint_token(factory, org_id=org_id, staff_id=staff_id)
        app = _build_public_app(factory)

        bad_form = dict(_VALID_SUBMIT_FORM)
        bad_form["bank_account_number"] = "not-a-valid-account"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/v2/public/staff-onboarding/{token}", data=bad_form
            )

        assert resp.status_code == 422, resp.text
        _assert_no_raw_error_text(resp.text)
        body = resp.json()
        assert body.get("ok") is False, body
        # Top-level human message present and non-empty.
        assert isinstance(body.get("message"), str) and body["message"].strip(), body
        # Each field error carries message + code.
        errors = body.get("errors")
        assert isinstance(errors, dict) and errors, f"expected field errors: {body}"
        assert "bank_account_number" in errors, body
        for _field, err in errors.items():
            _assert_message_and_code(err)
    finally:
        await _cleanup(factory)
        await engine.dispose()


async def _drive_encryption_failure() -> None:
    """POST submit with valid data but envelope_encrypt raising → 422 _global."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id, staff_id = ids["org_id"], ids["staff_id"]
        token = await _mint_token(factory, org_id=org_id, staff_id=staff_id)
        app = _build_public_app(factory)

        def _boom(*_a, **_k):
            raise RuntimeError("kms unavailable")

        with patch(
            "app.modules.staff.public_router.envelope_encrypt", side_effect=_boom
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{token}", data=_VALID_SUBMIT_FORM
                )

        assert resp.status_code == 422, resp.text
        _assert_no_raw_error_text(resp.text)
        body = resp.json()
        assert body.get("ok") is False, body
        assert isinstance(body.get("message"), str) and body["message"].strip(), body
        errors = body.get("errors")
        assert isinstance(errors, dict), body
        assert "_global" in errors, f"expected _global encryption error: {body}"
        _assert_message_and_code(errors["_global"], expected_code="encryption_failed")
    finally:
        await _cleanup(factory)
        await engine.dispose()


async def _drive_server_error() -> None:
    """Force an unexpected error AFTER token validation/RLS → 500 server_error."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id, staff_id = ids["org_id"], ids["staff_id"]
        token = await _mint_token(factory, org_id=org_id, staff_id=staff_id)
        app = _build_public_app(factory)

        async def _boom(*_a, **_k):
            raise RuntimeError("unexpected downstream failure")

        # get_org_settings is called AFTER token re-validation + _set_rls_org_id,
        # so patching it to raise exercises the handler's except-Exception
        # boundary (R14.5) without coupling to any token-state branch.
        with patch(
            "app.modules.staff.public_router.get_org_settings", side_effect=_boom
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/public/staff-onboarding/{token}", data=_VALID_SUBMIT_FORM
                )

        assert resp.status_code == 500, resp.text
        _assert_no_raw_error_text(resp.text)
        _assert_message_and_code(resp.json()["detail"], expected_code="server_error")
    finally:
        await _cleanup(factory)
        await engine.dispose()


async def _drive_admin_email_required() -> None:
    """Admin resend with a no-email staff member → 422 onboarding_email_required."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory, email=None)
        org_id, staff_id = ids["org_id"], ids["staff_id"]
        app = _build_admin_app(factory, org_id=org_id)

        # The email-required gate fires BEFORE revoke/mint/audit; stub the
        # module gate so we reach it (module enablement is not under test here).
        with patch(
            "app.modules.staff.router._require_staff_management_module",
            new=AsyncMock(return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/v2/staff/{staff_id}/onboarding-link/resend"
                )

        assert resp.status_code == 422, resp.text
        _assert_no_raw_error_text(resp.text)
        _assert_message_and_code(
            resp.json()["detail"], expected_code="onboarding_email_required"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_public_token_state_errors_are_humanized():
    """Public token-state rejections carry {message, code} and no raw error text.

    **Validates: Requirements 14.1, 14.5**
    """
    asyncio.run(_drive_public_token_state_errors())


def test_public_validation_failure_is_humanized():
    """Submit validation failure → 422 with top-level message + per-field {message, code}.

    **Validates: Requirements 14.1, 14.5**
    """
    asyncio.run(_drive_validation_failure())


def test_public_encryption_failure_is_humanized():
    """Encryption failure → 422 with _global {message, code:"encryption_failed"}.

    **Validates: Requirements 14.1, 14.5**
    """
    asyncio.run(_drive_encryption_failure())


def test_public_server_error_is_humanized():
    """Unexpected handler error → 500 {message, code:"server_error"}, no raw text.

    **Validates: Requirements 14.1, 14.5**
    """
    asyncio.run(_drive_server_error())


def test_admin_email_required_is_humanized():
    """Admin resend with no email → 422 {message, code:"onboarding_email_required"}.

    **Validates: Requirements 14.2, 14.5**
    """
    asyncio.run(_drive_admin_email_required())


def test_admin_error_codes_have_nonempty_humanized_messages():
    """Belt-and-braces: the admin/email error codes map to non-empty messages.

    Covers the admin humanized mapping directly (R14.2) and the email-send
    failure code (R14.4) whose public surface is best-effort/swallowed.

    **Validates: Requirements 14.2**
    """
    for code in ("onboarding_email_required", "send_failed"):
        message = humanize_onboarding_error(code)
        assert isinstance(message, str) and message.strip(), (
            f"humanize_onboarding_error({code!r}) returned an empty message"
        )
        for marker in _FORBIDDEN_MARKERS:
            assert marker not in message.lower(), (
                f"humanized message for {code!r} leaked raw text ({marker!r})"
            )


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted scenario."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
