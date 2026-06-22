"""Property-based test: Employee Portal CSRF double-submit enforcement.

# Feature: organisation-employee-portal, Property 15: CSRF double-submit enforcement

**Validates: Requirements 6.7, 6.8**

R6.7 states: *WHEN state-changing Employee_Portal requests are received, THE
Employee_Portal SHALL require a valid double-submit CSRF token.*

R6.8 states: *IF a state-changing Employee_Portal request is missing the CSRF
token OR the submitted CSRF token does not match the CSRF cookie, THEN THE
Employee_Portal SHALL reject the request without performing the state change AND
SHALL return an error response indicating CSRF validation failed.*

The enforcement lives in the pure FastAPI dependency
``app.modules.employee_portal.router.validate_emp_portal_csrf``. This test wires
that exact dependency onto a state-changing route of a minimal FastAPI app and
drives it end-to-end through Starlette's ``TestClient`` (an integration-style
property), so it exercises the real cookie parsing, header extraction, the
``GET``/``HEAD``/``OPTIONS`` exemption, and the constant-time
header-equals-cookie comparison — not a re-implementation.

The guarded handler performs an observable **side effect** (it bumps a counter)
so the test can assert the strongest form of R6.8: a rejected request never
reaches the handler, i.e. **no state change** occurs. The central invariant is a
biconditional (R6.7 ∧ R6.8):

    a state-changing /e/api request is accepted (200, side effect runs)
        IFF  the X-CSRF-Token header is present AND equals the
             emp_portal_csrf cookie

Any missing / empty / mismatched combination on a state-changing method is
rejected with ``403 csrf_failed`` and the side effect never runs. Safe methods
(``GET``/``HEAD``/``OPTIONS``) are always allowed (they perform no state change).

The assertions use an **independent reference oracle** (`_oracle_accept`) that
restates the rule from the generated inputs rather than calling the code under
test, so the property checks behaviour, not a copy of the implementation.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.employee_portal.router import (
    _CSRF_COOKIE_NAME,
    _CSRF_HEADER_NAME,
    validate_emp_portal_csrf,
)

# ---------------------------------------------------------------------------
# Minimal app that mounts the REAL CSRF dependency on a state-changing route
# with an observable side effect, plus a safe (GET) route guarded identically.
# ---------------------------------------------------------------------------

# Mutable server-side "state" the guarded handler mutates. Reaching the handler
# is the only way to bump it, so its value is a faithful proxy for "a state
# change happened". Reset before every generated example.
_STATE = {"changes": 0}

_STATE_CHANGING_METHODS = ("POST", "PUT", "PATCH", "DELETE")
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _build_app() -> FastAPI:
    """A tiny app whose only routes are guarded by ``validate_emp_portal_csrf``."""
    app = FastAPI()

    async def guarded_handler(_: None = Depends(validate_emp_portal_csrf)):
        # Side effect: only runs if the CSRF gate let the request through.
        _STATE["changes"] += 1
        return JSONResponse(content={"ok": True})

    # One route handles every method so the same dependency guards all verbs,
    # mirroring how it is attached to the real /e/api state-changing endpoints.
    app.add_api_route(
        "/e/api/guarded",
        guarded_handler,
        methods=list(_STATE_CHANGING_METHODS) + ["GET", "OPTIONS"],
    )
    # A dedicated HEAD route (FastAPI does not auto-add HEAD for the above).
    app.add_api_route("/e/api/guarded-head", guarded_handler, methods=["HEAD"])
    return app


_APP = _build_app()
_CLIENT = TestClient(_APP)


# ---------------------------------------------------------------------------
# Independent reference oracle — restatement of R6.7 ∧ R6.8.
# ---------------------------------------------------------------------------


def _oracle_accept(method: str, cookie: str | None, header: str | None) -> bool:
    """Reference verdict for whether the request should reach the handler.

    Safe methods are always accepted (no state change to protect). State-changing
    methods are accepted iff both the cookie and header are present (non-empty)
    and exactly equal — a missing/empty/mismatched token is rejected.
    """
    if method.upper() in _SAFE_METHODS:
        return True
    return bool(cookie) and bool(header) and cookie == header


# ---------------------------------------------------------------------------
# Generators — methods × (cookie present/absent) × (header absent/match/mismatch)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# Non-empty, cookie-safe token text (avoids control/separator chars that an HTTP
# client would refuse to put in a cookie or header value).
_tokens = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    min_size=1,
    max_size=48,
)


@st.composite
def _csrf_case(draw):
    """Draw a (method, cookie, header) triple spanning every relevant branch.

    ``header`` is deliberately drawn to land on the cookie value some of the time
    (the only accepting branch for state-changing methods) and to diverge or be
    absent the rest of the time, so both sides of the biconditional are hit.
    """
    method = draw(st.sampled_from(_STATE_CHANGING_METHODS + _SAFE_METHODS))
    cookie = draw(st.one_of(st.none(), _tokens))
    header = draw(
        st.one_of(
            st.none(),            # header absent
            st.just(cookie),      # header mirrors the cookie (match when cookie set)
            _tokens,              # independent value (usually a mismatch)
        )
    )
    return method, cookie, header


# ---------------------------------------------------------------------------
# Property 15: CSRF double-submit enforcement
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(case=_csrf_case())
def test_csrf_double_submit_enforcement(case) -> None:
    """A state-changing /e/api request is processed iff header == cookie (R6.7, R6.8).

    Drives the real dependency through ``TestClient``: builds the cookie/header
    combination, dispatches the request, and asserts that the guarded handler's
    side effect runs exactly when (and only when) the double-submit token is
    present and matches — and that every rejection is ``403 csrf_failed`` with no
    state change.

    **Validates: Requirements 6.7, 6.8**
    """
    method, cookie, header = case

    # Fresh state for this example so the side-effect delta is unambiguous.
    _STATE["changes"] = 0

    # Set the cookie jar explicitly on the client (and clear it first) so an
    # "absent cookie" example can never inherit a cookie from a prior request.
    _CLIENT.cookies.clear()
    if cookie is not None:
        _CLIENT.cookies.set(_CSRF_COOKIE_NAME, cookie)
    headers = {_CSRF_HEADER_NAME: header} if header is not None else {}
    path = "/e/api/guarded-head" if method.upper() == "HEAD" else "/e/api/guarded"

    response = _CLIENT.request(method, path, headers=headers)

    expected_accept = _oracle_accept(method, cookie, header)

    if expected_accept:
        # Accepted: the handler ran exactly once (the state change happened).
        assert response.status_code == 200
        assert _STATE["changes"] == 1
    else:
        # Rejected: 403 csrf_failed and the side effect NEVER ran (no state change).
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "csrf_failed"
        assert _STATE["changes"] == 0


# ---------------------------------------------------------------------------
# Worked unit examples — concrete anchors for each branch.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", _STATE_CHANGING_METHODS)
def test_matching_double_submit_is_accepted(method: str) -> None:
    """A state-changing request with header == cookie reaches the handler (R6.7)."""
    _STATE["changes"] = 0
    _CLIENT.cookies.clear()
    _CLIENT.cookies.set(_CSRF_COOKIE_NAME, "tok-123")
    resp = _CLIENT.request(
        method,
        "/e/api/guarded",
        headers={_CSRF_HEADER_NAME: "tok-123"},
    )
    assert resp.status_code == 200
    assert _STATE["changes"] == 1


@pytest.mark.parametrize("method", _STATE_CHANGING_METHODS)
def test_mismatched_token_is_rejected_without_state_change(method: str) -> None:
    """A mismatched header/cookie pair is rejected and never mutates state (R6.8)."""
    _STATE["changes"] = 0
    _CLIENT.cookies.clear()
    _CLIENT.cookies.set(_CSRF_COOKIE_NAME, "tok-123")
    resp = _CLIENT.request(
        method,
        "/e/api/guarded",
        headers={_CSRF_HEADER_NAME: "tok-xyz"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf_failed"
    assert _STATE["changes"] == 0


@pytest.mark.parametrize("method", _STATE_CHANGING_METHODS)
def test_missing_header_is_rejected_without_state_change(method: str) -> None:
    """A present cookie but no header is rejected with no state change (R6.8)."""
    _STATE["changes"] = 0
    _CLIENT.cookies.clear()
    _CLIENT.cookies.set(_CSRF_COOKIE_NAME, "tok-123")
    resp = _CLIENT.request(method, "/e/api/guarded")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf_failed"
    assert _STATE["changes"] == 0


@pytest.mark.parametrize("method", _STATE_CHANGING_METHODS)
def test_missing_cookie_is_rejected_without_state_change(method: str) -> None:
    """A present header but no cookie is rejected with no state change (R6.8)."""
    _STATE["changes"] = 0
    _CLIENT.cookies.clear()
    resp = _CLIENT.request(
        method,
        "/e/api/guarded",
        headers={_CSRF_HEADER_NAME: "tok-123"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf_failed"
    assert _STATE["changes"] == 0


def test_safe_get_is_always_allowed_without_token() -> None:
    """A GET passes the gate with no CSRF token (safe method, no state change)."""
    _STATE["changes"] = 0
    _CLIENT.cookies.clear()
    resp = _CLIENT.get("/e/api/guarded")
    assert resp.status_code == 200
    assert _STATE["changes"] == 1
