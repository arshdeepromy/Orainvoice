"""Unit tests for ``auto_provision_connection`` (task 14.9).

Covers the optional best-effort auto-provisioning orchestration in
``app/modules/esignatures/connection_service.py``:

* mode ``off`` → humanized "unavailable" result, manual path untouched (R20.5);
* success → Team/token/webhook created, secrets persisted encrypted, connection
  test run and ``is_verified`` reflected (R20.1, R20.2);
* failure at any step → humanized error, partial progress preserved, manual
  path never corrupted (R20.3, R20.4);
* re-run reuses an already-created Team rather than duplicating it.

Exercised with lightweight fakes (no real DB / Documenso) and real envelope
encryption so the persist-encrypted path is genuinely validated.

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

# Import the full app so SQLAlchemy can configure the Organisation mapper
# (its relationships reference models — e.g. User — only registered once the
# whole model graph is imported). The service queries Organisation by id.
import app.main  # noqa: F401,E402

from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.integrations.documenso_provisioning import (
    ProvisionedTeam,
    ProvisionedToken,
    ProvisioningError,
)
from app.modules.esignatures import connection_service as cs
from app.modules.esignatures.errors import (
    CODE_AUTO_PROVISION_FAILED,
    CODE_AUTO_PROVISION_UNAVAILABLE,
)
from app.modules.esignatures.models import EsignOrgConnection


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Routes ``execute`` to the connection row or org row by target table."""

    def __init__(self, conn_row, org_row):
        self.conn_row = conn_row
        self.org_row = org_row
        self.added: list = []

    async def execute(self, stmt):
        text = str(stmt)
        if "esign_org_connections" in text:
            return _FakeResult(self.conn_row)
        if "organisations" in text:
            return _FakeResult(self.org_row)
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        # A freshly added connection row becomes the one subsequent loads see.
        if isinstance(obj, EsignOrgConnection):
            self.conn_row = obj

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
        return None


class _RecordingAdapter:
    def __init__(self, *, fail_on: str | None = None):
        self.calls: list = []
        self._fail_on = fail_on

    async def create_team(self, *, org):
        self.calls.append("create_team")
        if self._fail_on == "create_team":
            raise ProvisioningError("team boom")
        return ProvisionedTeam(team_id="team-xyz")

    async def mint_team_token(self, *, team_id):
        self.calls.append(("mint_team_token", team_id))
        if self._fail_on == "mint_team_token":
            raise ProvisioningError("token boom")
        return ProvisionedToken(token="raw-token-123")

    async def ensure_webhook(self, *, team_id, routing_url, secret):
        self.calls.append(("ensure_webhook", team_id, routing_url, secret))
        if self._fail_on == "ensure_webhook":
            raise ProvisioningError("webhook boom")


def _org():
    return SimpleNamespace(id=uuid.uuid4(), name="Acme Ltd", slug="acme")


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(cs, "write_audit_log", _noop)


# ---------------------------------------------------------------------------
# Mode off → unavailable (R20.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_returns_unavailable(monkeypatch):
    monkeypatch.setattr(cs, "get_provisioning_adapter", lambda: None)
    org_id = uuid.uuid4()
    session = _FakeSession(conn_row=None, org_row=_org())

    result = await cs.auto_provision_connection(session, org_id)

    assert result["status"] == "unavailable"
    assert result["code"] == CODE_AUTO_PROVISION_UNAVAILABLE
    assert result["error"]  # non-empty humanized message
    assert result["connection"] is None  # nothing created — manual path intact


# ---------------------------------------------------------------------------
# Success (R20.1, R20.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_creates_and_persists_encrypted(monkeypatch):
    adapter = _RecordingAdapter()
    monkeypatch.setattr(cs, "get_provisioning_adapter", lambda: adapter)

    async def _fake_test_connection(db, org_id, **_kwargs):
        return {"is_verified": True, "valid": True}

    monkeypatch.setattr(cs, "test_connection", _fake_test_connection)

    org_id = uuid.uuid4()
    session = _FakeSession(conn_row=None, org_row=_org())

    result = await cs.auto_provision_connection(session, org_id)

    assert result["status"] == "provisioned"
    assert result["error"] is None
    assert result["is_verified"] is True
    assert "/api/v2/esign/webhook/" in result["webhook_url"]

    row = session.conn_row
    assert row.documenso_team_id == "team-xyz"
    # Token + secret persisted ENCRYPTED (never plaintext on the row).
    assert row.service_token_encrypted is not None
    assert envelope_decrypt_str(row.service_token_encrypted) == "raw-token-123"
    assert row.webhook_secret_encrypted is not None
    # Orchestration order: team → token → webhook.
    assert adapter.calls[0] == "create_team"
    assert adapter.calls[1][0] == "mint_team_token"
    assert adapter.calls[2][0] == "ensure_webhook"
    # Masked projection never leaks plaintext secrets.
    assert "service_token_last4" in result["connection"]
    assert "service_token" not in result["connection"]


# ---------------------------------------------------------------------------
# Failure recovers to manual, preserving partial progress (R20.3, R20.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_after_team_preserves_partial_state(monkeypatch):
    adapter = _RecordingAdapter(fail_on="mint_team_token")
    monkeypatch.setattr(cs, "get_provisioning_adapter", lambda: adapter)

    org_id = uuid.uuid4()
    session = _FakeSession(conn_row=None, org_row=_org())

    result = await cs.auto_provision_connection(session, org_id)

    assert result["status"] == "partial"
    assert result["code"] == CODE_AUTO_PROVISION_FAILED
    assert result["error"]
    # The successfully-created Team is preserved for reuse / manual completion.
    row = session.conn_row
    assert row.documenso_team_id == "team-xyz"
    assert row.service_token_encrypted is None  # never minted
    assert row.is_verified is False


@pytest.mark.asyncio
async def test_non_provisioning_exception_is_isolated(monkeypatch):
    class _BoomAdapter(_RecordingAdapter):
        async def create_team(self, *, org):
            raise RuntimeError("raw internal detail")

    monkeypatch.setattr(cs, "get_provisioning_adapter", lambda: _BoomAdapter())

    org_id = uuid.uuid4()
    session = _FakeSession(conn_row=None, org_row=_org())

    result = await cs.auto_provision_connection(session, org_id)

    assert result["status"] == "partial"
    assert result["code"] == CODE_AUTO_PROVISION_FAILED
    # Raw adapter internals never surface in the humanized message.
    assert "raw internal detail" not in result["error"]


# ---------------------------------------------------------------------------
# Re-run reuses an already-created Team (idempotent / re-runnable)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerun_reuses_existing_team(monkeypatch):
    adapter = _RecordingAdapter()
    monkeypatch.setattr(cs, "get_provisioning_adapter", lambda: adapter)

    async def _fake_test_connection(db, org_id, **_kwargs):
        return {"is_verified": True, "valid": True}

    monkeypatch.setattr(cs, "test_connection", _fake_test_connection)

    org_id = uuid.uuid4()
    existing = EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-existing",
        service_token_encrypted=None,
        webhook_secret_encrypted=envelope_encrypt("whsec-existing"),
        webhook_routing_id="route-existing",
        is_verified=False,
    )
    session = _FakeSession(conn_row=existing, org_row=_org())

    result = await cs.auto_provision_connection(session, org_id)

    assert result["status"] == "provisioned"
    # Team creation skipped — reused the recorded team id.
    assert "create_team" not in adapter.calls
    assert existing.documenso_team_id == "team-existing"
    # Existing webhook secret reused (registered, not regenerated).
    assert adapter.calls[-1][0] == "ensure_webhook"
    assert adapter.calls[-1][3] == "whsec-existing"
    assert "route-existing" in result["webhook_url"]
