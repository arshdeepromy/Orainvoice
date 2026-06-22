"""Unit / smoke tests for the Employee Portal password-reset endpoint wiring.

Covers task 10.4 (``POST /e/api/auth/password/reset-request`` and
``POST /e/api/auth/password/reset``) at the level that does not require a live
database:

- both routes are registered under ``/e/api``;
- the request body schemas accept their fields, forbid unknown fields, and
  (for ``new_password``) do NOT constrain length so the documented
  ``422 password_length`` envelope is preserved on the service write path;
- the endpoints are public — neither carries the session / CSRF dependencies
  (reset-request is unauthenticated; reset is authenticated by the single-use
  reset token);
- ``reset-request`` returns the **byte-for-byte identical** ``200`` confirmation
  for a genuine match, a non-matching email, and an unknown slug
  (anti-enumeration, R14.1) — dispatching the reset email only on a match and
  building the branded ``/e/{slug}/reset/{token}`` URL;
- ``reset`` translates each ``AccountServiceError`` subclass to its documented
  ``{message, code}`` envelope and returns ``200 {ok: true}`` on success.

The DB-backed persistence behaviour (single-use consumption, 3600s validity,
session tear-down on success, no state change on failure) is covered by the
service tests; the anti-enumeration response identity across many inputs is
covered by the property test (task 10.6).

Implements: Organisation Employee Portal task 10.4 — Requirements 14.1, 14.5,
14.6, 14.7, 14.8, 15.5.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/e/api/auth/password/reset-request",
        "/e/api/auth/password/reset",
    ],
)
def test_app_factory_mounts_password_reset_routes(path) -> None:
    """Both password-reset routes are registered under /e/api as POST."""
    from app.main import create_app

    app = create_app()
    methods = {
        m
        for r in app.routes
        if getattr(r, "path", None) == path
        for m in r.methods
    }
    assert methods, f"{path} route is not registered"
    assert "POST" in methods


@pytest.mark.parametrize(
    "path",
    [
        "/e/api/auth/password/reset-request",
        "/e/api/auth/password/reset",
    ],
)
def test_password_reset_routes_have_no_session_or_csrf_dependency(path) -> None:
    """The reset endpoints are public (no session / CSRF gate).

    reset-request is unauthenticated by design; reset is authenticated by the
    single-use reset token itself (the user has no session yet), so neither must
    depend on ``require_portal_session`` or ``validate_emp_portal_csrf``.
    """
    from app.main import create_app
    from app.modules.employee_portal import router as R

    app = create_app()
    guarded = {R.require_portal_session, R.validate_emp_portal_csrf}
    for route in app.routes:
        if getattr(route, "path", None) != path:
            continue
        dep_calls = {
            d.call for d in route.dependant.dependencies if d.call is not None
        }
        assert not (dep_calls & guarded), (
            f"{path} must not require session/CSRF deps"
        )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


def test_reset_request_schema_accepts_fields_and_forbids_extras() -> None:
    """``PasswordResetRequest`` carries slug+email and forbids unknown fields."""
    from app.modules.employee_portal import schemas as S

    body = S.PasswordResetRequest(slug="kauri-auto", email="a@example.com")
    assert body.slug == "kauri-auto"
    assert body.email == "a@example.com"

    with pytest.raises(ValidationError):
        S.PasswordResetRequest(slug="x", email="a@b.com", unexpected="y")


def test_reset_complete_schema_accepts_fields_and_forbids_extras() -> None:
    """``PasswordResetCompleteRequest`` carries token+new_password, forbids extras."""
    from app.modules.employee_portal import schemas as S

    body = S.PasswordResetCompleteRequest(token="t", new_password="hunter2hunter2")
    assert body.token == "t"
    assert body.new_password == "hunter2hunter2"

    with pytest.raises(ValidationError):
        S.PasswordResetCompleteRequest(token="t", new_password="x", extra="y")


def test_reset_complete_schema_does_not_constrain_password_length() -> None:
    """Length is NOT enforced by the schema (service emits 422 password_length)."""
    from app.modules.employee_portal import schemas as S

    assert S.PasswordResetCompleteRequest(token="t", new_password="").new_password == ""
    assert (
        S.PasswordResetCompleteRequest(token="t", new_password="short").new_password
        == "short"
    )


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeDb:
    """AsyncSession stand-in returning a queued Organisation row (or None)."""

    def __init__(self, org):
        self._org = org

    async def execute(self, _query):
        return _FakeResult(self._org)


class _FakeRequest:
    def __init__(self, origin="https://portal.example.com"):
        self.headers = {"origin": origin}


def _body(resp: JSONResponse) -> dict:
    return json.loads(resp.body)


def _make_org():
    return SimpleNamespace(id=uuid.uuid4(), slug="kauri-auto", name="Kauri Auto")


@pytest.fixture()
def _patch_common(monkeypatch):
    """Patch RLS set + org settings; record dispatched reset emails."""
    sent: list[dict] = []

    async def _fake_set_rls(_db, _org_id):  # noqa: ANN001
        return None

    async def _fake_get_org_settings(_db, *, org_id):  # noqa: ANN001
        return {"org_name": "Kauri Auto"}

    async def _fake_send(_db, **kwargs):  # noqa: ANN001
        sent.append(kwargs)
        return SimpleNamespace(ok=True, error_code=None)

    from app.modules.employee_portal import router as R

    monkeypatch.setattr(R, "_set_rls_org_id", _fake_set_rls)
    monkeypatch.setattr(R, "get_org_settings", _fake_get_org_settings)
    monkeypatch.setattr(
        R.employee_portal_delivery, "send_password_reset_email", _fake_send
    )
    return sent


# ---------------------------------------------------------------------------
# reset-request — anti-enumeration response identity (R14.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_request_dispatches_email_on_match(_patch_common, monkeypatch) -> None:
    """A genuine match issues a token, builds /e/{slug}/reset/{token}, sends email."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    org = _make_org()
    user = SimpleNamespace(email="alice@example.com")

    async def _request_reset(_db, _org_id, _email):  # noqa: ANN001
        return user, "RAWTOKEN123"

    monkeypatch.setattr(R.account_service, "request_reset", _request_reset)

    resp = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="kauri-auto", email="alice@example.com"),
        request=_FakeRequest(origin="https://portal.example.com"),
        db=_FakeDb(org),
    )

    assert resp.status_code == 200
    assert _body(resp)["ok"] is True
    assert len(_patch_common) == 1
    call = _patch_common[0]
    assert call["staff_email"] == "alice@example.com"
    assert call["reset_url"] == "https://portal.example.com/e/kauri-auto/reset/RAWTOKEN123"
    assert call["org_id"] == org.id


@pytest.mark.asyncio
async def test_reset_request_identical_body_when_email_not_matched(
    _patch_common, monkeypatch
) -> None:
    """A non-matching email sends no email but returns the identical body."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    org = _make_org()

    async def _no_match(_db, _org_id, _email):  # noqa: ANN001
        return None

    monkeypatch.setattr(R.account_service, "request_reset", _no_match)

    matched = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="kauri-auto", email="ghost@example.com"),
        request=_FakeRequest(),
        db=_FakeDb(org),
    )

    assert matched.status_code == 200
    assert _patch_common == []  # no email dispatched
    # Body equals the canonical confirmation constant.
    assert _body(matched) == {"ok": True, "message": R._RESET_REQUEST_CONFIRMATION}


@pytest.mark.asyncio
async def test_reset_request_identical_body_when_slug_unknown(_patch_common) -> None:
    """An unknown slug never queries users / sends mail but returns identical body."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    resp = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="nope", email="alice@example.com"),
        request=_FakeRequest(),
        db=_FakeDb(None),  # org not found
    )

    assert resp.status_code == 200
    assert _patch_common == []
    assert _body(resp) == {"ok": True, "message": R._RESET_REQUEST_CONFIRMATION}


@pytest.mark.asyncio
async def test_reset_request_response_is_byte_identical_across_outcomes(
    _patch_common, monkeypatch
) -> None:
    """Match, non-match, and unknown-slug responses are byte-for-byte identical."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    org = _make_org()

    async def _match(_db, _org_id, _email):  # noqa: ANN001
        return SimpleNamespace(email="alice@example.com"), "RAW"

    async def _no_match(_db, _org_id, _email):  # noqa: ANN001
        return None

    monkeypatch.setattr(R.account_service, "request_reset", _match)
    r_match = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="kauri-auto", email="alice@example.com"),
        request=_FakeRequest(),
        db=_FakeDb(org),
    )

    monkeypatch.setattr(R.account_service, "request_reset", _no_match)
    r_nomatch = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="kauri-auto", email="ghost@example.com"),
        request=_FakeRequest(),
        db=_FakeDb(org),
    )

    r_unknown = await R.request_password_reset(
        body=S.PasswordResetRequest(slug="missing", email="alice@example.com"),
        request=_FakeRequest(),
        db=_FakeDb(None),
    )

    assert r_match.status_code == r_nomatch.status_code == r_unknown.status_code == 200
    assert bytes(r_match.body) == bytes(r_nomatch.body) == bytes(r_unknown.body)


# ---------------------------------------------------------------------------
# reset (complete) — success + error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_reset_returns_ok_on_success(monkeypatch) -> None:
    """A successful reset returns ``200 {ok: true}``."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    async def _ok(_db, _token, _pw):  # noqa: ANN001
        return object()

    monkeypatch.setattr(R.account_service, "complete_reset", _ok)
    resp = await R.complete_password_reset(
        body=S.PasswordResetCompleteRequest(token="t", new_password="goodpassword"),
        db=object(),
    )
    assert resp.status_code == 200
    assert _body(resp) == {"ok": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_name,status_code,code",
    [
        ("ResetTokenInvalid", 400, "reset_token_invalid"),
        ("PasswordLengthError", 422, "password_length"),
    ],
)
async def test_complete_reset_maps_service_errors_to_envelope(
    monkeypatch, error_name, status_code, code
) -> None:
    """Each ``AccountServiceError`` subclass maps to its documented envelope."""
    from fastapi import HTTPException

    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S
    from app.modules.employee_portal.services import account_service

    exc_cls = getattr(account_service, error_name)

    async def _raise(_db, _token, _pw):  # noqa: ANN001
        raise exc_cls("boom")

    monkeypatch.setattr(R.account_service, "complete_reset", _raise)

    with pytest.raises(HTTPException) as caught:
        await R.complete_password_reset(
            body=S.PasswordResetCompleteRequest(token="t", new_password="x"),
            db=object(),
        )

    assert caught.value.status_code == status_code
    assert caught.value.detail["code"] == code
    assert "message" in caught.value.detail
