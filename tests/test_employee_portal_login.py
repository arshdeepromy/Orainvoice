"""Unit / smoke tests for the Employee Portal login endpoint wiring.

Covers task 10.1 (``POST /e/api/auth/login``) at the level that does not require
a live database: the router is mounted under ``/e/api``, the request/response
schemas load and enforce their contracts, the cookie-scoping helpers produce
``/e``-scoped ``emp_portal_session`` (HttpOnly) + ``emp_portal_csrf`` (readable)
cookies, and the ``Secure`` flag is environment-gated.

The DB-backed behavioural properties for login (single-org resolution,
anti-enumeration response invariance, CSRF double-submit) are covered by the
dedicated property tests in tasks 10.5 / 10.6 / 10.7.

Implements: Organisation Employee Portal task 10.1 — Requirements 4.5, 6.1,
6.2, 6.3, 6.4.
"""

from __future__ import annotations

import pytest
from fastapi.responses import JSONResponse
from pydantic import ValidationError


def test_app_factory_mounts_employee_portal_login() -> None:
    """The employee portal router is registered under ``/e/api``."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/e/api/auth/login" in paths


def test_login_request_schema_normalises_and_rejects_unknown_fields() -> None:
    """``LoginRequest`` accepts the documented body and forbids extras."""
    from app.modules.employee_portal import schemas as S

    body = S.LoginRequest(slug="acme", email="Alice@Example.com", password="secret123")
    assert body.slug == "acme"
    # email is kept verbatim on the model; the endpoint lowercases at lookup time.
    assert body.email == "Alice@Example.com"

    with pytest.raises(ValidationError):
        S.LoginRequest(
            slug="acme",
            email="a@b.com",
            password="secret123",
            unexpected="x",  # extra="forbid" → 422
        )


def test_login_response_schema_shape() -> None:
    """``LoginResponse`` exposes only the portal user's own identity."""
    import uuid

    from app.modules.employee_portal import schemas as S

    resp = S.LoginResponse(
        portal_user_id=uuid.uuid4(),
        email="alice@example.com",
        first_name="Alice",
        staff_id=uuid.uuid4(),
    )
    assert set(resp.model_dump().keys()) == {
        "portal_user_id",
        "email",
        "first_name",
        "staff_id",
    }


def test_cookie_helper_sets_scoped_session_and_csrf_cookies() -> None:
    """``_set_session_cookies`` sets HttpOnly session + readable CSRF on /e."""
    from app.modules.employee_portal import router as R

    resp = JSONResponse(content={"ok": True})
    R._set_session_cookies(resp, session_token="raw-sess", csrf_token="raw-csrf")

    set_cookie_headers = [
        v.decode() if isinstance(v, bytes) else v
        for (k, v) in resp.raw_headers
        if (k.decode() if isinstance(k, bytes) else k).lower() == "set-cookie"
    ]
    joined = "\n".join(set_cookie_headers)

    # Both cookies are present and scoped to /e.
    assert "emp_portal_session=raw-sess" in joined
    assert "emp_portal_csrf=raw-csrf" in joined
    assert joined.count("Path=/e") == 2

    # The session cookie is HttpOnly; the CSRF cookie is readable by JS.
    session_line = next(c for c in set_cookie_headers if "emp_portal_session=" in c)
    csrf_line = next(c for c in set_cookie_headers if "emp_portal_csrf=" in c)
    assert "HttpOnly" in session_line
    assert "HttpOnly" not in csrf_line


def test_secure_origin_is_environment_gated(monkeypatch) -> None:
    """Cookies are Secure in staging/production and not in development."""
    from app.config import settings as app_settings
    from app.modules.employee_portal import router as R

    monkeypatch.setattr(app_settings, "environment", "development", raising=False)
    assert R._is_secure_origin() is False

    monkeypatch.setattr(app_settings, "environment", "production", raising=False)
    assert R._is_secure_origin() is True

    monkeypatch.setattr(app_settings, "environment", "staging", raising=False)
    assert R._is_secure_origin() is True


def test_invalid_credentials_message_is_a_single_constant() -> None:
    """The generic 401 text is one shared constant (anti-enumeration, R6.4)."""
    from app.modules.employee_portal import router as R

    # Identical text regardless of whether the email matched — Property 13 is
    # exercised end-to-end in task 10.6; here we assert the source of truth.
    assert R._INVALID_CREDENTIALS_MESSAGE == "Invalid email or password"
