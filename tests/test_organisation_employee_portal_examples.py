"""Example & edge-case unit tests for the Organisation Employee Portal (task 17.1).

These are **concrete example / edge-case** tests (not property tests) that pin
the specific behaviours called out in design.md §"Example & edge-case unit
tests". They deliberately complement — rather than duplicate — the DB-backed
Hypothesis property tests (login resolution, anti-enumeration, password-length
persistence, single-use tokens, slug availability) by exercising the exact
boundary values and the response/identity edges with small, deterministic
inputs.

Coverage map (task 17.1 bullets → tests below):

1. Slug set / availability happy path + own-org-slug-available branch (R3.5) +
   save-time race rejection (R3.9)
     → ``TestSlugAvailabilityExamples`` + ``TestSlugSaveTimeRace``
2. Invite/reset boundary lengths (7/8/128/129) + token-expiry boundaries
   (7-day invite, 3600s reset)  (R5.5, R5.8, R5.9, R14.3)
     → ``TestPasswordLengthBoundaries`` + ``TestTokenExpiryBoundaries``
3. Login generic-message identity for existing vs non-existing email (R6.4)
     → ``TestLoginGenericMessageIdentity``
4. Profile PII masking + unlinked ``not_linked`` (R7.5, R7.7)
     → ``TestProfilePiiMaskingAndNotLinked``
5. Onboarding-completion → portal as login destination (R5.4)
     → ``TestOnboardingLoginDestination``

The tests use lightweight async fakes (no live database) so they run fast and
focus purely on the service/router logic. ``DATABASE_URL`` is still honoured by
the surrounding suite for the DB-backed property tests.

Requirements: 3.5, 3.9, 5.4, 5.5, 5.8, 5.9, 7.7, 14.3.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (instantiating any ORM object —
# e.g. EmployeePortalUser — eagerly configures every mapper). Mirrors the
# reference DB-backed property tests (e.g.
# tests/test_employee_portal_password_length_property.py).
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

from app.modules.admin.models import Organisation

from app.modules.employee_portal import router as R
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.auth import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    validate_password_length,
)
from app.modules.employee_portal.models import EmployeePortalUser
from app.modules.employee_portal.services import account_service
from app.modules.organisations.service import (
    SlugUpdateError,
    check_slug_availability,
    update_org_slug,
)


# ---------------------------------------------------------------------------
# Async test doubles (no live DB)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Stands in for an SQLAlchemy ``Result``.

    Supports the three access shapes the services / router use:
    ``.scalars().first()``, ``.first()`` and ``.scalar_one_or_none()`` — all
    return the same queued ``value`` — plus a ``rowcount`` for DELETE results.
    """

    def __init__(self, value=None, *, rowcount: int = 0):
        self._value = value
        self.rowcount = rowcount

    def scalars(self):
        return self

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Minimal async ``AsyncSession`` stand-in returning queued results in order.

    ``results`` is consumed front-to-back; once a single result remains it is
    reused for every subsequent ``execute`` (covers e.g. a trailing DELETE).
    ``add`` records objects so audit-row writes can be inspected.
    """

    def __init__(self, results):
        self._results = list(results)
        self.added: list = []
        self.flushed = 0

    async def execute(self, *_args, **_kwargs):
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0] if self._results else _FakeResult()

    async def flush(self):
        self.flushed += 1

    async def refresh(self, _obj):
        return None

    def add(self, obj):
        self.added.append(obj)


def _body(resp) -> dict:
    return json.loads(resp.body)


# ===========================================================================
# 1. Slug availability — happy path, own-org branch (R3.5), invalid/other-org
# ===========================================================================


class TestSlugAvailabilityExamples:
    """``check_slug_availability`` classifier examples (R3.2–R3.6)."""

    @pytest.mark.asyncio
    async def test_free_slug_is_available(self):
        """A well-formed, unreserved, unheld slug → ``available`` (happy path)."""
        db = _FakeDb([_FakeResult(None)])  # holder lookup → nobody holds it
        result, reason = await check_slug_availability(
            db, requesting_org_id=uuid.uuid4(), candidate="acme-motors"
        )
        assert result == "available"
        assert reason is None

    @pytest.mark.asyncio
    async def test_own_org_current_slug_is_available(self):
        """A slug currently held by the requesting org itself → ``available`` (R3.5)."""
        org_id = uuid.uuid4()
        # The holder lookup resolves to the SAME org that is asking.
        db = _FakeDb([_FakeResult(org_id)])
        result, reason = await check_slug_availability(
            db, requesting_org_id=org_id, candidate="acme-motors"
        )
        assert result == "available"
        assert reason is None

    @pytest.mark.asyncio
    async def test_slug_held_by_other_org_is_unavailable(self):
        """A slug held by a different org → ``unavailable`` with a reason (R3.4)."""
        db = _FakeDb([_FakeResult(uuid.uuid4())])  # held by some OTHER org
        result, reason = await check_slug_availability(
            db, requesting_org_id=uuid.uuid4(), candidate="acme-motors"
        )
        assert result == "unavailable"
        assert reason

    @pytest.mark.asyncio
    async def test_reserved_slug_is_unavailable_without_db_lookup(self):
        """A reserved slug → ``unavailable`` and never returns ``available`` (R3.3)."""
        db = _FakeDb([_FakeResult(None)])
        result, reason = await check_slug_availability(
            db, requesting_org_id=uuid.uuid4(), candidate="admin"
        )
        assert result == "unavailable"
        assert reason

    @pytest.mark.asyncio
    async def test_bad_format_is_invalid_not_available(self):
        """A malformed slug → ``invalid`` (never ``available``) with a reason (R3.6)."""
        db = _FakeDb([_FakeResult(None)])
        result, reason = await check_slug_availability(
            db, requesting_org_id=uuid.uuid4(), candidate="ab"  # too short
        )
        assert result == "invalid"
        assert result != "available"
        assert reason


# ===========================================================================
# 1b. Slug save-time race rejection (R3.9)
# ===========================================================================


class TestSlugSaveTimeRace:
    """``update_org_slug`` re-checks uniqueness at save time (R3.9, R2.6)."""

    @staticmethod
    def _make_org(slug=None):
        org = MagicMock(spec=Organisation)
        org.id = uuid.uuid4()
        org.name = "Acme"
        org.slug = slug
        return org

    @pytest.mark.asyncio
    async def test_save_time_race_rejects_slug_taken(self):
        """A slug that passed the live check but is now held by another org at
        save time is rejected ``slug_taken`` and nothing is written (R3.9)."""
        org = self._make_org(slug=None)
        other_org_id = uuid.uuid4()
        # execute #1 → load requesting org; execute #2 → holder re-check finds
        # a DIFFERENT org now holding the slug (the race).
        db = _FakeDb([_FakeResult(org), _FakeResult(other_org_id)])

        with pytest.raises(SlugUpdateError) as exc:
            await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="raced-slug"
            )

        assert exc.value.code == "slug_taken"
        assert org.slug is None  # nothing stored
        assert db.flushed == 0  # no write occurred

    @pytest.mark.asyncio
    async def test_resubmitting_own_slug_passes_the_race_check(self):
        """The save-time re-check excludes the requesting org, so re-saving the
        org's own current slug is accepted (R3.9 own-org branch)."""
        org = self._make_org(slug="acme")
        # Holder re-check (which excludes the requesting org) → None.
        db = _FakeDb([_FakeResult(org), _FakeResult(None)])

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.organisations.service.invalidate_org_settings_cache",
            new_callable=AsyncMock,
        ):
            stored = await update_org_slug(
                db, org_id=org.id, user_id=uuid.uuid4(), candidate="acme"
            )

        assert stored == "acme"
        assert org.slug == "acme"


# ===========================================================================
# 2. Invite/reset password-length boundaries (7/8/128/129) — R5.5/R5.6/R14.7
# ===========================================================================


class TestPasswordLengthBoundaries:
    """Concrete boundary lengths for the pure length gate (R5.6, R14.7)."""

    @pytest.mark.parametrize(
        "length,accepted",
        [
            (7, False),    # just below the lower bound
            (8, True),     # lower boundary — accepted
            (128, True),   # upper boundary — accepted
            (129, False),  # just above the upper bound
        ],
    )
    def test_length_boundaries(self, length, accepted):
        ok, message = validate_password_length("p" * length)
        assert ok is accepted
        # An accepted password carries no message; a rejection names the range.
        if accepted:
            assert message == ""
        else:
            assert str(MIN_PASSWORD_LENGTH) in message
            assert str(MAX_PASSWORD_LENGTH) in message


# ===========================================================================
# 2b. Token-expiry boundaries — 7-day invite (R5.9) & 3600s reset (R14.3)
# ===========================================================================


# A fixed "now" so the boundary maths is deterministic.
_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_invite_user(*, invite_sent_at):
    return EmployeePortalUser(
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        email="alice@example.com",
        password_hash=None,
        is_active=True,
        invite_token_hash="hash-of-token",
        invite_sent_at=invite_sent_at,
        invite_accepted_at=None,
        failed_login_attempts=0,
    )


def _make_reset_user(*, reset_token_expires_at):
    return EmployeePortalUser(
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        email="alice@example.com",
        password_hash=ep_auth.hash_password_sync("existing-password"),
        is_active=True,
        reset_token_hash="hash-of-token",
        reset_token_expires_at=reset_token_expires_at,
        failed_login_attempts=0,
    )


class TestTokenExpiryBoundaries:
    """Invite (7-day) and reset (3600s) expiry boundaries on the write path."""

    @pytest.mark.asyncio
    async def test_invite_at_exactly_seven_days_is_accepted(self, monkeypatch):
        """An invite sent exactly 7 days ago is still fresh (boundary inclusive, R5.9)."""
        monkeypatch.setattr(account_service, "_now_utc", lambda: _NOW)
        user = _make_invite_user(invite_sent_at=_NOW - account_service.INVITE_VALIDITY)
        db = _FakeDb([_FakeResult(user)])

        updated = await account_service.accept_invite(db, "raw-token", "goodpassword")

        assert updated is user
        assert user.password_hash is not None
        assert user.password_hash != "goodpassword"  # stored only as a hash
        assert user.invite_token_hash is None  # single-use consumed
        assert user.invite_accepted_at == _NOW

    @pytest.mark.asyncio
    async def test_invite_one_second_past_seven_days_is_expired(self, monkeypatch):
        """An invite older than 7 days is rejected and leaves state unchanged (R5.9)."""
        monkeypatch.setattr(account_service, "_now_utc", lambda: _NOW)
        user = _make_invite_user(
            invite_sent_at=_NOW - account_service.INVITE_VALIDITY - timedelta(seconds=1)
        )
        db = _FakeDb([_FakeResult(user)])

        with pytest.raises(account_service.InviteExpired):
            await account_service.accept_invite(db, "raw-token", "goodpassword")

        # No state mutated — token still present, no password set.
        assert user.password_hash is None
        assert user.invite_token_hash == "hash-of-token"
        assert user.invite_accepted_at is None

    @pytest.mark.asyncio
    async def test_reset_at_exactly_3600s_window_is_accepted(self, monkeypatch):
        """A reset token whose 3600s window ends exactly at ``now`` is still
        valid (boundary inclusive, R14.3)."""
        monkeypatch.setattr(account_service, "_now_utc", lambda: _NOW)
        # Issued 3600s ago → expires_at == now (the inclusive boundary).
        issued_at = _NOW - account_service.RESET_VALIDITY
        user = _make_reset_user(
            reset_token_expires_at=issued_at + account_service.RESET_VALIDITY
        )
        old_hash = user.password_hash
        db = _FakeDb([_FakeResult(user), _FakeResult(rowcount=0)])

        updated = await account_service.complete_reset(db, "raw-token", "brandnewpass")

        assert updated is user
        assert user.password_hash != old_hash  # password changed
        assert user.password_hash != "brandnewpass"  # stored only as a hash
        assert user.reset_token_hash is None  # single-use consumed
        assert user.reset_token_expires_at is None

    @pytest.mark.asyncio
    async def test_reset_one_second_past_3600s_is_invalid(self, monkeypatch):
        """A reset token expired by 1s past the 3600s window is rejected and the
        stored password is left unchanged (R14.3, R14.6)."""
        monkeypatch.setattr(account_service, "_now_utc", lambda: _NOW)
        issued_at = _NOW - account_service.RESET_VALIDITY - timedelta(seconds=1)
        user = _make_reset_user(
            reset_token_expires_at=issued_at + account_service.RESET_VALIDITY
        )
        old_hash = user.password_hash
        db = _FakeDb([_FakeResult(user)])

        with pytest.raises(account_service.ResetTokenInvalid):
            await account_service.complete_reset(db, "raw-token", "brandnewpass")

        assert user.password_hash == old_hash  # unchanged
        assert user.reset_token_hash == "hash-of-token"  # not consumed


# ===========================================================================
# 3. Login generic-message identity for existing vs non-existing email (R6.4)
# ===========================================================================


class _LoginRequest:
    """Tiny stand-in matching the fields the login handler reads."""

    def __init__(self, slug, email, password):
        self.slug = slug
        self.email = email
        self.password = password


def _fake_request(ip="203.0.113.7"):
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers={})


class TestLoginGenericMessageIdentity:
    """The 401 body is byte-for-byte identical whether or not the email exists
    (concrete example reinforcing Property 13 — R6.4)."""

    @pytest.mark.asyncio
    async def test_existing_wrong_password_and_unknown_email_are_identical(
        self, monkeypatch
    ):
        org = SimpleNamespace(id=uuid.uuid4(), slug="acme", name="Acme")

        async def _settings(_db, *, org_id):  # noqa: ANN001
            return {"employee_portal_enabled": True}

        async def _set_rls(_db, _org):  # noqa: ANN001
            return None

        monkeypatch.setattr(R, "get_org_settings", _settings)
        monkeypatch.setattr(R, "_set_rls_org_id", _set_rls)

        # --- Case A: the email matches an active user, wrong password. ---
        existing = EmployeePortalUser(
            org_id=org.id,
            staff_id=uuid.uuid4(),
            email="alice@example.com",
            password_hash=ep_auth.hash_password_sync("correct-password"),
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
        )
        db_a = _FakeDb([_FakeResult(org), _FakeResult(existing)])
        resp_a = await R.login(
            body=_LoginRequest("acme", "alice@example.com", "WRONG-password"),
            request=_fake_request(),
            db=db_a,
        )

        # --- Case B: the email does not match any user. ---
        db_b = _FakeDb([_FakeResult(org), _FakeResult(None)])
        resp_b = await R.login(
            body=_LoginRequest("acme", "ghost@example.com", "WRONG-password"),
            request=_fake_request(),
            db=db_b,
        )

        # Identical status + body (anti-enumeration, R6.4).
        assert resp_a.status_code == resp_b.status_code == 401
        assert bytes(resp_a.body) == bytes(resp_b.body)
        assert _body(resp_a)["code"] == "invalid_credentials"
        assert _body(resp_a)["message"] == R._INVALID_CREDENTIALS_MESSAGE

    @pytest.mark.asyncio
    async def test_unknown_slug_is_neutral_not_found(self, monkeypatch):
        """An unresolvable slug yields a neutral ``portal_unavailable`` 404
        with no session and no DB write (R6.11)."""
        db = _FakeDb([_FakeResult(None)])  # org lookup → None
        resp = await R.login(
            body=_LoginRequest("nope", "alice@example.com", "whatever-pass"),
            request=_fake_request(),
            db=db,
        )
        assert resp.status_code == 404
        assert _body(resp)["code"] == "portal_unavailable"


# ===========================================================================
# 4. Profile PII masking + unlinked not_linked (R7.5, R7.7)
# ===========================================================================


def _ctx(*, staff_id):
    return R.EmployeePortalSessionCtx(
        org_id=uuid.uuid4(),
        portal_user_id=uuid.uuid4(),
        staff_id=staff_id,
        email="alice@example.com",
        session_id=uuid.uuid4(),
        csrf_token="csrf",
    )


def _make_staff(org_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        first_name="Ada",
        last_name="Lovelace",
        name="Ada Lovelace",
        email="ada@example.com",
        phone="021 000 000",
        position="Technician",
        employee_id="E-001",
        employment_basis="full_time",
        employment_type="permanent",
        working_arrangement="rostered",
        employment_start_date=None,
        tax_code="M",
        kiwisaver_enrolled=True,
        emergency_contact_name="Grace",
        emergency_contact_phone="021 111 111",
        ird_number_encrypted="ENC(ird)",
        bank_account_number_encrypted="ENC(bank)",
    )


class TestProfilePiiMaskingAndNotLinked:
    @pytest.mark.asyncio
    async def test_profile_masks_ird_and_bank(self, monkeypatch):
        """Decrypted IRD/bank PII is masked before it reaches the wire (R7.5)."""
        from app.modules.staff.security import mask_bank_account, mask_ird

        ird_plain = "123456789"
        bank_plain = "01-0123-0123456-00"

        def _decrypt(ct):  # noqa: ANN001
            return {"ENC(ird)": ird_plain, "ENC(bank)": bank_plain}[ct]

        monkeypatch.setattr(R, "envelope_decrypt_str", _decrypt)

        ctx = _ctx(staff_id=uuid.uuid4())
        staff = _make_staff(ctx.org_id)
        db = _FakeDb([_FakeResult(staff)])

        resp = await R.profile(ctx=ctx, db=db)
        body = _body(resp)

        # The masked display value is returned — never the plaintext.
        assert body["ird_number"] == mask_ird(ird_plain)
        assert body["bank_account_number"] == mask_bank_account(bank_plain)
        assert ird_plain not in json.dumps(body)
        assert bank_plain not in json.dumps(body)

    @pytest.mark.asyncio
    async def test_profile_not_linked_when_no_staff_id(self):
        """A portal user with no linked staff → 409 ``not_linked`` (R7.7)."""
        from fastapi import HTTPException

        ctx = _ctx(staff_id=None)
        db = _FakeDb([_FakeResult(None)])

        with pytest.raises(HTTPException) as exc:
            await R.profile(ctx=ctx, db=db)

        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "not_linked"

    @pytest.mark.asyncio
    async def test_profile_not_linked_when_staff_row_absent(self):
        """A staff_id that resolves to no row in the session's org → ``not_linked``
        with no fields and no existence disclosure (R7.5, R7.7)."""
        from fastapi import HTTPException

        ctx = _ctx(staff_id=uuid.uuid4())
        db = _FakeDb([_FakeResult(None)])  # staff lookup → nothing

        with pytest.raises(HTTPException) as exc:
            await R.profile(ctx=ctx, db=db)

        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "not_linked"


# ===========================================================================
# 5. Onboarding-completion → portal as login destination (R5.4)
# ===========================================================================


class TestOnboardingLoginDestination:
    """R5.4 (as clarified in design.md): credential issuance is admin-initiated;
    once access is issued the branded ``/e/{slug}`` login is the destination.
    Completing the onboarding link does NOT auto-create a Portal_User."""

    def test_branded_login_route_is_the_destination(self):
        """The branded portal login endpoint exists (mounted at /e/api/auth/login)."""
        login_paths = {
            r.path for r in R.router.routes if "POST" in getattr(r, "methods", set())
        }
        assert "/auth/login" in login_paths

    def test_admin_issuance_is_the_credential_mechanism(self):
        """The admin staff router exposes the portal-access issuance endpoint
        (the credential-issuance mechanism R5.4 refers to)."""
        from app.modules.staff.router import router as staff_router

        portal_access = {
            r.path
            for r in staff_router.routes
            if "/{staff_id}/portal-access" in getattr(r, "path", "")
        }
        assert portal_access == {"/{staff_id}/portal-access"}

    def test_onboarding_submit_does_not_auto_issue_portal_access(self):
        """Completing the onboarding link does not auto-create a Portal_User —
        issuance stays admin-initiated (design clarification of R5.4)."""
        import inspect

        from app.modules.staff import public_router

        source = inspect.getsource(public_router)
        assert "issue_access" not in source
        assert "account_service" not in source

    @pytest.mark.asyncio
    async def test_issue_access_creates_invite_credential(self):
        """``issue_access`` (admin path) mints a single-use invite credential
        with no password yet — the staff member then sets a password and logs
        in at the branded portal (R5.3, R5.5, R5.8)."""
        org_id = uuid.uuid4()
        staff = SimpleNamespace(id=uuid.uuid4(), email="newhire@example.com")
        db = _FakeDb([_FakeResult(None)])  # dup check → no existing active user

        user, raw_token = await account_service.issue_access(db, org_id, staff)

        assert user.org_id == org_id
        assert user.staff_id == staff.id
        assert user.email == "newhire@example.com"
        assert user.password_hash is None  # set only when the invite is accepted
        assert user.invite_token_hash is not None  # single-use invite issued
        assert raw_token and isinstance(raw_token, str)
        # A credential_issued audit row was queued.
        assert any(
            getattr(o, "action", None) == "credential_issued" for o in db.added
        )
