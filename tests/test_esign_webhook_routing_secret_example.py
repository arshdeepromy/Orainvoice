"""Example tests for per-org-routed, shared-secret-gated webhook ingestion (task 12.1).

Covers the routing + per-org secret gate of
``app/modules/esignatures/webhook_router.py`` (R8.1, R8.2) without a live DB by
monkeypatching ``async_session_factory`` with a stateful fake session that
serves the cross-org ``esign_org_connections`` lookup. The stored webhook
secret is **really** envelope-encrypted, so the handler's
``envelope_decrypt_str`` + constant-time ``secret_compare`` path is exercised
end to end.

Asserted behaviour:

1. Unknown ``routing_id`` (maps to no org) → HTTP 401, nothing modified.
2. Known org but mismatched ``X-Documenso-Secret`` → HTTP 401, nothing modified.
3. Known org + matching secret → HTTP 200 (handed off to the task-12.2 apply
   seam, which is a no-op in 12.1), and the session RLS context is scoped to the
   resolved org.

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# Pre-load the model graph so SQLAlchemy can resolve string relationships when
# EsignOrgConnection is instantiated (mirrors the other esign tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_encrypt  # noqa: E402
from app.modules.esignatures import webhook_router as wr  # noqa: E402
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402

_ROUTING_ID = "route-abc-123"
_SECRET = "whsec_super_secret_value"


# ---------------------------------------------------------------------------
# Fake async session — serves the connection SELECT and records executed SQL so
# we can assert the system-context RESET and the post-verify org scoping.
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
        # Any SELECT against the connection table returns the preset row; the
        # RESET / set_config statements ignore the result.
        return _FakeResult(self._row)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _row(org_id: uuid.UUID) -> EsignOrgConnection:
    return EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        service_token_encrypted=envelope_encrypt("tok"),
        webhook_secret_encrypted=envelope_encrypt(_SECRET),
        webhook_routing_id=_ROUTING_ID,
        is_verified=True,
    )


def _client(monkeypatch, row: EsignOrgConnection | None) -> tuple[TestClient, _FakeSession]:
    session = _FakeSession(row)
    monkeypatch.setattr(wr, "async_session_factory", lambda: session)
    app = FastAPI()
    app.include_router(wr.router)
    return TestClient(app), session


# ---------------------------------------------------------------------------
# 1. Unknown routing id → 401, nothing modified.
# ---------------------------------------------------------------------------


def test_unknown_routing_id_returns_401(monkeypatch):
    client, session = _client(monkeypatch, row=None)

    resp = client.post(
        f"/api/v2/esign/webhook/{_ROUTING_ID}",
        headers={"X-Documenso-Secret": _SECRET},
        json={"event": "DOCUMENT_COMPLETED"},
    )

    assert resp.status_code == 401
    # Cross-org lookup ran in system context (RESET) but no org scoping / write.
    assert any("RESET app.current_org_id" in s for s in session.statements)
    assert not any("set_config" in s for s in session.statements)


# ---------------------------------------------------------------------------
# 2. Known org, wrong secret → 401, nothing modified.
# ---------------------------------------------------------------------------


def test_secret_mismatch_returns_401(monkeypatch):
    org_id = uuid.uuid4()
    client, session = _client(monkeypatch, row=_row(org_id))

    resp = client.post(
        f"/api/v2/esign/webhook/{_ROUTING_ID}",
        headers={"X-Documenso-Secret": "wrong-secret"},
        json={"event": "DOCUMENT_COMPLETED"},
    )

    assert resp.status_code == 401
    # Verified BEFORE any org scoping → no set_config issued (modify nothing).
    assert not any("set_config" in s for s in session.statements)


def test_missing_secret_header_returns_401(monkeypatch):
    org_id = uuid.uuid4()
    client, session = _client(monkeypatch, row=_row(org_id))

    resp = client.post(
        f"/api/v2/esign/webhook/{_ROUTING_ID}",
        json={"event": "DOCUMENT_COMPLETED"},
    )

    assert resp.status_code == 401
    assert not any("set_config" in s for s in session.statements)


# ---------------------------------------------------------------------------
# 3. Known org + matching secret → 200, session scoped to the resolved org.
# ---------------------------------------------------------------------------


def test_valid_secret_returns_200_and_scopes_to_org(monkeypatch):
    org_id = uuid.uuid4()
    client, session = _client(monkeypatch, row=_row(org_id))

    resp = client.post(
        f"/api/v2/esign/webhook/{_ROUTING_ID}",
        headers={"X-Documenso-Secret": _SECRET},
        json={"event": "DOCUMENT_COMPLETED"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # System-context lookup ran first, then the session was scoped to the
    # resolved org for the (task 12.2) apply seam.
    assert any("RESET app.current_org_id" in s for s in session.statements)
    assert any("set_config" in s for s in session.statements)
    scope_params = [p for p in session.params if p and p.get("oid") == str(org_id)]
    assert scope_params, "session must be scoped to the resolved org_id"


def test_org_with_no_secret_configured_returns_401(monkeypatch):
    org_id = uuid.uuid4()
    row = _row(org_id)
    row.webhook_secret_encrypted = None  # connection exists but no secret yet
    client, session = _client(monkeypatch, row=row)

    resp = client.post(
        f"/api/v2/esign/webhook/{_ROUTING_ID}",
        headers={"X-Documenso-Secret": _SECRET},
        json={"event": "DOCUMENT_COMPLETED"},
    )

    assert resp.status_code == 401
    assert not any("set_config" in s for s in session.statements)
