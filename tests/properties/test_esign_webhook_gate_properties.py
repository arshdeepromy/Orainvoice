"""Property-based test for the per-org-routed, shared-secret-gated Documenso
webhook (task 12.3).

# Feature: esignature-integration, Property 13: Per-org webhook routing and shared-secret verification gates all processing

For any webhook POSTed to ``/api/v2/esign/webhook/{routing_id}``, the handler
:func:`app.modules.esignatures.webhook_router.documenso_webhook` ONLY proceeds
to apply state changes when BOTH conditions hold:

  1. the ``routing_id`` resolves to an organisation's ``esign_org_connections``
     row, AND
  2. the ``X-Documenso-Secret`` header matches that organisation's stored
     webhook secret under a constant-time compare.

If EITHER condition fails — an unknown ``routing_id`` (maps to no org), a secret
mismatch, or a missing header — the request is rejected with HTTP 401 and
**nothing is modified**: ``service.apply_webhook`` (which owns every dedupe /
recipient / envelope / event write) is NEVER invoked, and the session is never
scoped away from system context (no ``set_config`` issued).

The test drives the real route through a Starlette ``TestClient`` over a
lightweight fake async session that serves the cross-org
``esign_org_connections`` lookup (the stored secret is **really**
envelope-encrypted, so the handler's ``envelope_decrypt_str`` +
``secret_compare`` path runs end to end), with ``service.apply_webhook`` spied
to a recorder so we can assert it is invoked on — and only on — the
authenticated path.

**Validates: Requirements 8.1, 8.2**
"""

from __future__ import annotations

import uuid

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from unittest import mock

from fastapi import FastAPI
from starlette.testclient import TestClient

# Pre-load the full model graph so SQLAlchemy can resolve every string-based
# relationship reference when EsignOrgConnection is instantiated (mirrors the
# task 12.1 example test and the other esign property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_encrypt  # noqa: E402
from app.modules.esignatures import service  # noqa: E402
from app.modules.esignatures import webhook_router as wr  # noqa: E402
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

# Printable-ASCII secrets: latin-1 encodable (so they survive an HTTP header)
# and non-empty (an empty secret is not a meaningful stored secret).
secret_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=48,
)

# Opaque, URL-safe routing ids.
routing_id_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_",
    ),
    min_size=1,
    max_size=32,
)

# The four routing/secret scenarios under test.
case_strategy = st.sampled_from(
    ["valid", "unknown_routing", "secret_mismatch", "missing_header"]
)


# ---------------------------------------------------------------------------
# Fake async session — serves the connection SELECT and records every executed
# statement/params so we can assert the system-context RESET happened and that
# NO org-scoping write (set_config) occurred on a rejected request.
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

    Its presence on the call path is the proof that processing (and therefore
    any dedupe/recipient/envelope/event write) was reached. On the rejected
    paths it must never be called.
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


def _build_client(row: EsignOrgConnection | None):
    session = _FakeSession(row)
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app), session


# ---------------------------------------------------------------------------
# Property 13
# ---------------------------------------------------------------------------


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
def test_routing_and_secret_gate_all_processing(
    stored_secret: str, routing_id: str, other_secret: str, case: str
) -> None:
    """BOTH a resolvable routing id AND a matching per-org secret are required
    before any processing; otherwise 401 and nothing is modified."""
    org_id = uuid.uuid4()

    # Build the scenario: which row the lookup serves, which header to send, and
    # the expected outcome.
    if case == "valid":
        row: EsignOrgConnection | None = _connection_row(org_id, routing_id, stored_secret)
        headers = {"X-Documenso-Secret": stored_secret}
        expect_status = 200
        expect_applied = True
    elif case == "unknown_routing":
        # routing id maps to no org → lookup returns None.
        row = None
        headers = {"X-Documenso-Secret": stored_secret}
        expect_status = 401
        expect_applied = False
    elif case == "secret_mismatch":
        row = _connection_row(org_id, routing_id, stored_secret)
        # Guarantee a mismatching (non-empty) secret string.
        wrong = other_secret if other_secret != stored_secret else stored_secret + "_x"
        headers = {"X-Documenso-Secret": wrong}
        expect_status = 401
        expect_applied = False
    else:  # missing_header
        row = _connection_row(org_id, routing_id, stored_secret)
        headers = {}
        expect_status = 401
        expect_applied = False

    client, session = _build_client(row)
    spy = _ApplySpy()

    with mock.patch.object(wr, "async_session_factory", lambda: session), \
            mock.patch.object(service, "apply_webhook", spy):
        resp = client.post(
            f"/api/v2/esign/webhook/{routing_id}",
            headers=headers,
            json={"event": "DOCUMENT_COMPLETED", "payload": {"id": "doc-1"}},
        )

    # --- Status -----------------------------------------------------------
    assert resp.status_code == expect_status, (
        f"case={case}: expected {expect_status}, got {resp.status_code}"
    )

    # --- Processing gate: apply_webhook only on the authenticated path ----
    assert (len(spy.calls) == 1) is expect_applied, (
        f"case={case}: apply_webhook invocation={len(spy.calls)} "
        f"but expected_applied={expect_applied}"
    )

    # --- The cross-org lookup always runs in system context (R8.1) --------
    assert any("RESET app.current_org_id" in s for s in session.statements)

    if expect_applied:
        # Authenticated: session scoped to the resolved org before apply, and
        # apply received that org_id.
        assert any("set_config" in s for s in session.statements)
        scoped = [p for p in session.params if p and p.get("oid") == str(org_id)]
        assert scoped, "valid webhook must scope the session to the resolved org"
        assert spy.calls[0]["org_id"] == org_id
    else:
        # Rejected: nothing modified — the session was never scoped away from
        # system context, so no org-scoping/write statement was issued (R8.2).
        assert not any("set_config" in s for s in session.statements), (
            f"case={case}: a rejected webhook must not scope/modify any state"
        )
