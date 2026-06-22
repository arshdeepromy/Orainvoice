"""Unit / smoke tests for the Employee Portal logout + /me wiring.

Covers task 10.2 at the level that does not require a live database:

- the router mounts ``POST /e/api/auth/logout`` and ``GET /e/api/auth/me``
  under ``/e/api``;
- the CSRF double-submit dependency (``validate_emp_portal_csrf``) exempts safe
  methods and rejects state-changing requests whose ``X-CSRF-Token`` header is
  missing or does not equal the ``emp_portal_csrf`` cookie (R6.7, R6.8);
- the neutral ``session_invalid`` 401 envelope is the single source of truth
  (R6.10);
- ``logout`` clears both ``/e``-scoped cookies (R6.9);
- ``session_service.hash_token`` is a deterministic, public alias of the
  canonical token hasher used by the session dependency.

The DB-backed behavioural property for CSRF (state-changing request processed
iff header == cookie) is covered by the dedicated property test in task 10.7.

Implements: Organisation Employee Portal task 10.2 — Requirements 6.7, 6.8,
6.9, 6.10.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request


def _make_request(method: str, headers: dict[str, str] | None = None) -> Request:
    """Build a minimal ASGI ``Request`` for dependency unit tests."""
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": method,
        "path": "/e/api/auth/logout",
        "query_string": b"",
        "headers": raw_headers,
    }
    return Request(scope)


def test_app_factory_mounts_logout_and_me() -> None:
    """Both ``/e/api/auth/logout`` and ``/e/api/auth/me`` are registered."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/e/api/auth/logout" in paths
    assert "/e/api/auth/me" in paths


def test_csrf_dependency_exempts_safe_methods() -> None:
    """GET/HEAD/OPTIONS never require a CSRF token (no state change)."""
    from app.modules.employee_portal import router as R

    for method in ("GET", "HEAD", "OPTIONS"):
        # No cookie, no header — still allowed because the method is safe.
        assert R.validate_emp_portal_csrf(_make_request(method), None) is None


def test_csrf_dependency_accepts_matching_double_submit() -> None:
    """A POST whose X-CSRF-Token header equals the cookie is allowed (R6.7)."""
    from app.modules.employee_portal import router as R

    request = _make_request("POST", {"X-CSRF-Token": "token-abc"})
    assert R.validate_emp_portal_csrf(request, "token-abc") is None


@pytest.mark.parametrize(
    "cookie,header",
    [
        (None, "token-abc"),       # missing cookie
        ("token-abc", None),       # missing header
        ("token-abc", "token-xyz"),  # mismatch
        (None, None),              # neither present
    ],
)
def test_csrf_dependency_rejects_missing_or_mismatched(cookie, header) -> None:
    """Missing/mismatched CSRF → 403 csrf_failed, no state change (R6.8)."""
    from app.modules.employee_portal import router as R

    headers = {"X-CSRF-Token": header} if header is not None else {}
    request = _make_request("POST", headers)
    with pytest.raises(HTTPException) as exc:
        R.validate_emp_portal_csrf(request, cookie)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "csrf_failed"


def test_session_invalid_envelope_is_the_single_source_of_truth() -> None:
    """The neutral 401 envelope carries the ``session_invalid`` code (R6.10)."""
    from app.modules.employee_portal import router as R

    exc = R._session_invalid_exc()
    assert exc.status_code == 401
    assert exc.detail["code"] == "session_invalid"
    assert exc.detail["message"] == R._SESSION_INVALID_MESSAGE


def test_clear_session_cookies_removes_both_scoped_cookies() -> None:
    """``logout`` clears the session + CSRF cookies on the /e path (R6.9)."""
    from app.modules.employee_portal import router as R

    resp = JSONResponse(content={"ok": True})
    R._clear_session_cookies(resp)

    set_cookie_headers = [
        v.decode() if isinstance(v, bytes) else v
        for (k, v) in resp.raw_headers
        if (k.decode() if isinstance(k, bytes) else k).lower() == "set-cookie"
    ]
    joined = "\n".join(set_cookie_headers)
    assert "emp_portal_session=" in joined
    assert "emp_portal_csrf=" in joined
    # Both deletions are scoped to /e so they target the cookies we set.
    assert joined.count("Path=/e") == 2


def test_hash_token_is_deterministic_public_alias() -> None:
    """``hash_token`` is a stable SHA-256 alias used by the session lookup."""
    import hashlib

    from app.modules.employee_portal.services import session_service

    raw = "some-raw-session-token"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert session_service.hash_token(raw) == expected
    # Deterministic across calls.
    assert session_service.hash_token(raw) == session_service.hash_token(raw)
