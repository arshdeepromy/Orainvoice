"""Property/integration test — the Documenso webhook reaches its handler
through the FULL middleware stack (task 12.10).

# Feature: esignature-integration, Property: Webhook reaches the handler through the middleware stack

Where the task-12.1 example test (``test_esign_webhook_routing_secret_example``)
and the task-12.3 property test (``test_esign_webhook_gate_properties``) exercise
the route handler in isolation, **this** test mounts the webhook router behind the
SAME middleware stack ``app/main.py`` applies — ``SecurityHeadersMiddleware``
(CSRF), ``AuthMiddleware`` (JWT), ``RBACMiddleware`` and ``ModuleMiddleware`` — in
the same execution order, and POSTs through a Starlette ``TestClient``.

The distinguishing assertions for 12.10 are that the inbound webhook is NOT
short-circuited by any of those gates:

* **Auth (JWT) bypass** — the per-org routing prefix ``/api/v2/esign/webhook/`` is
  in ``PUBLIC_PREFIXES``, so a webhook carrying NO ``Authorization`` header still
  reaches the handler. A non-public sibling path (``/api/v2/esign/envelopes``)
  POSTed with no JWT through the same stack is rejected 401 — proving the auth
  gate is genuinely active and the webhook is the exception (R8.1).
* **CSRF bypass** — the same prefix is in ``_CSRF_EXEMPT_PREFIXES``, so a webhook
  presenting a ``session`` cookie and no CSRF token is NOT 403. A non-exempt
  state-changing path (``/api/v1/invoices``) with the same cookie shape IS 403
  through the same stack — proving the CSRF gate is active and the webhook is the
  exception.
* **Module gate bypass** — the webhook carries no resolved ``org_id``, so
  ``ModuleMiddleware`` skips it (it only gates requests with an org context); the
  request reaches the handler even though it lives under the ``/api/v2/esign``
  module-gate prefix.

Having proven the request reaches the handler through the stack, the handler's
own per-org routing + shared-secret gate (R8.2) still applies: a valid signed
webhook for the resolved org returns 200 and invokes ``service.apply_webhook``,
while a wrong/absent ``X-Documenso-Secret`` or an unknown ``routing_id`` returns
401 and never invokes apply.

The stored webhook secret is **really** envelope-encrypted, so the handler's
``envelope_decrypt_str`` + constant-time ``secret_compare`` path runs end to end.

**Validates: Requirements 8.1, 8.2, 13.6**
"""

from __future__ import annotations

import uuid
from unittest import mock

from fastapi import FastAPI
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignOrgConnection is instantiated (mirrors the
# task 12.1 / 12.3 esign tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_encrypt  # noqa: E402
from app.middleware.auth import AuthMiddleware, PUBLIC_PREFIXES, _is_public  # noqa: E402
from app.middleware.modules import ModuleMiddleware  # noqa: E402
from app.middleware.rbac import RBACMiddleware  # noqa: E402
from app.middleware.security_headers import (  # noqa: E402
    SecurityHeadersMiddleware,
    _CSRF_EXEMPT_PREFIXES,
)
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures import webhook_router as wr  # noqa: E402
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402

_WEBHOOK_PREFIX = "/api/v2/esign/webhook/"


# ---------------------------------------------------------------------------
# Fake async session — serves the cross-org connection SELECT and records every
# executed statement/params so the system-context RESET and the post-verify org
# scoping can be asserted (mirrors the 12.1 / 12.3 fakes).
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, row: EsignOrgConnection | None):
        self._row = row
        self.statements: list[str] = []
        self.params: list[dict | None] = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        self.params.append(params)
        return _FakeResult(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _ApplySpy:
    """Async stand-in for ``service.apply_webhook`` that records invocations.

    Its presence on the call path is the proof the request reached the handler
    AND passed the per-org secret gate.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, db, *, org_id, raw_body, user_id=None):
        self.calls.append({"org_id": org_id, "raw_body": raw_body})
        return service.WebhookApplyResult(outcome="applied")


def _connection_row(org_id: uuid.UUID, routing_id: str, secret: str) -> EsignOrgConnection:
    return EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-xyz",
        service_token_encrypted=envelope_encrypt("tok"),
        webhook_secret_encrypted=envelope_encrypt(secret),
        webhook_routing_id=routing_id,
        is_verified=True,
    )


def _build_stack_app() -> FastAPI:
    """Build a FastAPI app with the SAME middleware stack (and execution order)
    that ``app/main.py`` applies, mounting the real esign webhook router plus two
    control routes used to prove the auth/CSRF gates are genuinely active.

    Starlette runs middleware in reverse registration order, so to obtain the
    main.py execution order  SecurityHeaders -> Auth -> RBAC -> Module -> route
    we register them bottom-up (innermost first).
    """
    app = FastAPI()
    app.include_router(wr.router)

    # Control route A: a non-public, module-gated sibling under /api/v2/esign —
    # used to prove AuthMiddleware blocks a no-JWT request that is NOT covered by
    # the public webhook prefix.
    @app.post("/api/v2/esign/envelopes")
    async def _envelopes_control():  # pragma: no cover - should be blocked by auth
        return JSONResponse({"status": "reached"})

    # Control route B: a non-CSRF-exempt state-changing path — used to prove
    # SecurityHeadersMiddleware enforces CSRF for a session-cookie request.
    @app.post("/api/v1/invoices")
    async def _invoices_control():  # pragma: no cover - should be blocked by CSRF
        return JSONResponse({"status": "reached"})

    # Innermost first → reverse of main.py declaration so execution order matches.
    app.add_middleware(ModuleMiddleware)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


# ---------------------------------------------------------------------------
# Static guard: the prefix membership the bypass relies on.
# ---------------------------------------------------------------------------


def test_webhook_prefix_is_public_and_csrf_exempt():
    """The bypass is structural — the prefix must be registered in BOTH the auth
    public-prefix set and the CSRF-exempt prefix set."""
    assert _WEBHOOK_PREFIX in PUBLIC_PREFIXES
    assert _WEBHOOK_PREFIX in _CSRF_EXEMPT_PREFIXES
    # And the predicate AuthMiddleware actually uses agrees for a concrete path.
    assert _is_public(f"{_WEBHOOK_PREFIX}route-abc-123") is True


# ---------------------------------------------------------------------------
# Control assertions: the same stack genuinely blocks auth/CSRF for non-exempt
# paths — so the webhook reaching the handler is a real bypass, not a stack that
# enforces nothing.
# ---------------------------------------------------------------------------


def test_stack_blocks_non_public_sibling_without_jwt():
    """A non-public sibling under /api/v2/esign with NO JWT is rejected 401 by
    AuthMiddleware in the same stack — proving the auth gate is active."""
    app = _build_stack_app()
    client = TestClient(app)

    resp = client.post("/api/v2/esign/envelopes", json={})

    assert resp.status_code == 401


def test_stack_enforces_csrf_for_non_exempt_path():
    """A non-CSRF-exempt POST presenting a session cookie and no CSRF token is
    rejected 403 by SecurityHeadersMiddleware in the same stack — proving the
    CSRF gate is active."""
    app = _build_stack_app()
    client = TestClient(app)
    client.cookies.set("session", "abc")

    resp = client.post("/api/v1/invoices", json={})

    assert resp.status_code == 403


def test_webhook_not_csrf_blocked_with_session_cookie():
    """The webhook prefix is CSRF-exempt: a webhook presenting a session cookie
    and no CSRF token is NOT 403 — it flows to the handler's own auth gate."""
    org_id = uuid.uuid4()
    routing_id = "route-csrf-1"
    secret = "whsec_csrf_value"
    session = _FakeSession(_connection_row(org_id, routing_id, secret))
    app = _build_stack_app()
    spy = _ApplySpy()

    with mock.patch.object(wr, "async_session_factory", lambda: session), \
            mock.patch.object(service, "apply_webhook", spy):
        client = TestClient(app)
        client.cookies.set("session", "abc")
        resp = client.post(
            f"{_WEBHOOK_PREFIX}{routing_id}",
            headers={"X-Documenso-Secret": secret},
            json={"event": "DOCUMENT_COMPLETED", "payload": {"id": "doc-1"}},
        )

    assert resp.status_code != 403
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Property: through the FULL stack, BOTH a resolvable routing id AND a matching
# per-org secret are required; the request always reaches the handler (no
# auth/CSRF/module short-circuit), then the handler's gate decides 200 vs 401.
# ---------------------------------------------------------------------------

secret_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=48,
)
routing_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    ),
    min_size=1,
    max_size=32,
)
case_strategy = st.sampled_from(
    ["valid", "unknown_routing", "secret_mismatch", "missing_header"]
)


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(
    stored_secret=secret_strategy,
    routing_id=routing_id_strategy,
    other_secret=secret_strategy,
    case=case_strategy,
)
def test_webhook_through_full_middleware_stack(
    stored_secret: str, routing_id: str, other_secret: str, case: str
) -> None:
    """A webhook POSTed to /api/v2/esign/webhook/{routing_id} traverses the full
    middleware stack (no JWT, no CSRF token) and reaches the handler; the handler
    then returns 200 + invokes apply ONLY for a resolvable routing id with a
    matching secret, else 401 with nothing modified (R8.1, R8.2, R13.6)."""
    org_id = uuid.uuid4()

    if case == "valid":
        row: EsignOrgConnection | None = _connection_row(org_id, routing_id, stored_secret)
        headers = {"X-Documenso-Secret": stored_secret}
        expect_status = 200
        expect_applied = True
    elif case == "unknown_routing":
        row = None
        headers = {"X-Documenso-Secret": stored_secret}
        expect_status = 401
        expect_applied = False
    elif case == "secret_mismatch":
        row = _connection_row(org_id, routing_id, stored_secret)
        wrong = other_secret if other_secret != stored_secret else stored_secret + "_x"
        headers = {"X-Documenso-Secret": wrong}
        expect_status = 401
        expect_applied = False
    else:  # missing_header
        row = _connection_row(org_id, routing_id, stored_secret)
        headers = {}
        expect_status = 401
        expect_applied = False

    session = _FakeSession(row)
    app = _build_stack_app()
    spy = _ApplySpy()

    # NO Authorization header and NO CSRF token are sent — proving the request is
    # not blocked by the auth or CSRF middleware in the stack.
    with mock.patch.object(wr, "async_session_factory", lambda: session), \
            mock.patch.object(service, "apply_webhook", spy):
        client = TestClient(app)
        resp = client.post(
            f"{_WEBHOOK_PREFIX}{routing_id}",
            headers=headers,
            json={"event": "DOCUMENT_COMPLETED", "payload": {"id": "doc-1"}},
        )

    # The request reached the handler through the stack (never a 401 "Missing
    # Authorization header" from AuthMiddleware, never a 403 CSRF from
    # SecurityHeaders, never a 403 module from ModuleMiddleware).
    assert resp.status_code == expect_status, (
        f"case={case}: expected {expect_status}, got {resp.status_code}"
    )

    # apply_webhook is reached on — and only on — the authenticated path.
    assert (len(spy.calls) == 1) is expect_applied, (
        f"case={case}: apply invocations={len(spy.calls)} expected={expect_applied}"
    )

    # The cross-org connection lookup always ran in system context (R8.1/R13.6).
    assert any("RESET app.current_org_id" in s for s in session.statements)

    if expect_applied:
        # Authenticated: session scoped to the resolved org before apply (R13.6).
        assert any("set_config" in s for s in session.statements)
        scoped = [p for p in session.params if p and p.get("oid") == str(org_id)]
        assert scoped, "valid webhook must scope the session to the resolved org"
        assert spy.calls[0]["org_id"] == org_id
    else:
        # Rejected at the handler gate: nothing scoped/modified (R8.2).
        assert not any("set_config" in s for s in session.statements), (
            f"case={case}: a rejected webhook must not scope/modify any state"
        )
