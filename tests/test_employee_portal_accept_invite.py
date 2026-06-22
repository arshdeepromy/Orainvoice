"""Unit / smoke tests for the Employee Portal accept-invite endpoint wiring.

Covers task 10.3 (``GET``/``POST /e/api/auth/accept-invite/{token}``) at the
level that does not require a live database:

- both routes are registered under ``/e/api``;
- the ``AcceptInviteRequest`` body schema accepts an unconstrained
  ``new_password`` (length is enforced by ``account_service`` so the documented
  ``422 password_length`` envelope is preserved) and rejects unknown fields;
- the GET status-preview classifier maps row state → ``valid|used|expired`` and
  an unknown token → a neutral ``not_found`` body;
- the POST translates each ``AccountServiceError`` subclass to its documented
  ``{message, code}`` envelope with the right status code, and returns
  ``200 {ok: true}`` on success;
- the endpoints are public — neither carries the session / CSRF dependencies
  (the single-use invite token authenticates the POST).

The DB-backed persistence behaviour (single-use consumption, 7-day validity,
8..128 length on the write path, no state change on failure) is covered by the
service tests and the password-length property test (task 10.x).

Implements: Organisation Employee Portal task 10.3 — Requirements 5.5, 5.6,
5.8, 5.9.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.responses import JSONResponse
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


def test_app_factory_mounts_accept_invite_routes() -> None:
    """Both the GET and POST accept-invite routes are registered under /e/api."""
    from app.main import create_app

    app = create_app()
    routes = [
        (r.path, tuple(sorted(r.methods)))
        for r in app.routes
        if hasattr(r, "path") and r.path == "/e/api/auth/accept-invite/{token}"
    ]
    methods = {m for _, ms in routes for m in ms}
    assert routes, "accept-invite route is not registered"
    assert "GET" in methods
    assert "POST" in methods


def test_accept_invite_routes_have_no_session_or_csrf_dependency() -> None:
    """The accept-invite endpoints are public (no session / CSRF gate).

    The POST is state-changing but predates the user having any session — it is
    authenticated by the single-use invite token itself, so it must NOT depend
    on ``require_portal_session`` or ``validate_emp_portal_csrf``.
    """
    from app.main import create_app
    from app.modules.employee_portal import router as R

    app = create_app()
    guarded = {R.require_portal_session, R.validate_emp_portal_csrf}
    for route in app.routes:
        if getattr(route, "path", None) != "/e/api/auth/accept-invite/{token}":
            continue
        dep_calls = {
            d.call for d in route.dependant.dependencies if d.call is not None
        }
        assert not (dep_calls & guarded), (
            f"accept-invite {route.methods} must not require session/CSRF deps"
        )


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------


def test_accept_invite_request_schema_accepts_password_and_forbids_extras() -> None:
    """``AcceptInviteRequest`` carries ``new_password`` and forbids unknown fields."""
    from app.modules.employee_portal import schemas as S

    body = S.AcceptInviteRequest(new_password="hunter2hunter2")
    assert body.new_password == "hunter2hunter2"

    with pytest.raises(ValidationError):
        S.AcceptInviteRequest(new_password="x", unexpected="y")  # extra="forbid"


def test_accept_invite_request_does_not_constrain_length() -> None:
    """Length is NOT enforced by the schema (service emits 422 password_length).

    A too-short / empty password must reach the service so it maps to the
    documented ``password_length`` envelope rather than a generic Pydantic 422.
    """
    from app.modules.employee_portal import schemas as S

    assert S.AcceptInviteRequest(new_password="").new_password == ""
    assert S.AcceptInviteRequest(new_password="short").new_password == "short"


# ---------------------------------------------------------------------------
# GET status preview classifier
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeDb:
    """Minimal AsyncSession stand-in returning a queued user, no-op RLS set."""

    def __init__(self, user):
        self._user = user

    async def execute(self, _query):
        return _FakeResult(self._user)


@pytest.fixture()
def _patch_org_settings(monkeypatch):
    async def _fake_get_org_settings(_db, *, org_id):  # noqa: ANN001
        return {"org_name": "Kauri Auto"}

    async def _fake_set_rls(_db, _org_id):  # noqa: ANN001
        return None

    from app.modules.employee_portal import router as R

    monkeypatch.setattr(R, "get_org_settings", _fake_get_org_settings)
    monkeypatch.setattr(R, "_set_rls_org_id", _fake_set_rls)


def _make_user(*, invite_sent_at, invite_accepted_at=None, email="alice@example.com"):
    from app.modules.employee_portal.models import EmployeePortalUser

    return EmployeePortalUser(
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        email=email,
        invite_token_hash="abc",
        invite_sent_at=invite_sent_at,
        invite_accepted_at=invite_accepted_at,
    )


def _body(resp: JSONResponse) -> dict:
    import json

    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_get_status_not_found_is_neutral(_patch_org_settings) -> None:
    """An unknown token → ``200`` neutral ``not_found`` with no org/email leak."""
    from app.modules.employee_portal import router as R

    resp = await R.accept_invite_status(token="nope", db=_FakeDb(None))
    assert resp.status_code == 200
    assert _body(resp) == {"status": "not_found", "org_name": None, "email": None}


@pytest.mark.asyncio
async def test_get_status_valid_for_fresh_unaccepted_invite(_patch_org_settings) -> None:
    """A fresh, unaccepted invite within 7 days → ``valid`` + org_name + email."""
    from app.modules.employee_portal import router as R

    now = datetime.now(timezone.utc)
    user = _make_user(invite_sent_at=now - timedelta(days=1))
    resp = await R.accept_invite_status(token="t", db=_FakeDb(user))
    assert _body(resp) == {
        "status": "valid",
        "org_name": "Kauri Auto",
        "email": "alice@example.com",
    }


@pytest.mark.asyncio
async def test_get_status_used_when_already_accepted(_patch_org_settings) -> None:
    """An accepted invite → ``used``."""
    from app.modules.employee_portal import router as R

    now = datetime.now(timezone.utc)
    user = _make_user(
        invite_sent_at=now - timedelta(days=1), invite_accepted_at=now
    )
    resp = await R.accept_invite_status(token="t", db=_FakeDb(user))
    assert _body(resp)["status"] == "used"


@pytest.mark.asyncio
async def test_get_status_expired_after_seven_days(_patch_org_settings) -> None:
    """An invite older than 7 days → ``expired`` (R5.9)."""
    from app.modules.employee_portal import router as R

    now = datetime.now(timezone.utc)
    user = _make_user(invite_sent_at=now - timedelta(days=8))
    resp = await R.accept_invite_status(token="t", db=_FakeDb(user))
    assert _body(resp)["status"] == "expired"


# ---------------------------------------------------------------------------
# POST error mapping + success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_returns_ok_on_success(monkeypatch) -> None:
    """A successful accept returns ``200 {ok: true}``."""
    from app.modules.employee_portal import router as R
    from app.modules.employee_portal import schemas as S

    async def _ok(_db, _token, _pw):  # noqa: ANN001
        return object()

    monkeypatch.setattr(R.account_service, "accept_invite", _ok)
    resp = await R.accept_invite(
        token="t", body=S.AcceptInviteRequest(new_password="goodpassword"), db=object()
    )
    assert resp.status_code == 200
    assert _body(resp) == {"ok": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_name,status_code,code",
    [
        ("InviteExpired", 410, "invite_expired"),
        ("PasswordLengthError", 422, "password_length"),
        ("InviteNotFound", 404, "invite_not_found"),
    ],
)
async def test_post_maps_service_errors_to_envelope(
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

    monkeypatch.setattr(R.account_service, "accept_invite", _raise)

    with pytest.raises(HTTPException) as caught:
        await R.accept_invite(
            token="t", body=S.AcceptInviteRequest(new_password="x"), db=object()
        )

    assert caught.value.status_code == status_code
    assert caught.value.detail["code"] == code
    assert "message" in caught.value.detail
