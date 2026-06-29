"""Unit tests for the optional Documenso provisioning adapters (task 5.6).

These tests verify the OPTIONAL, best-effort auto-provisioning layer (R20)
WITHOUT requiring a real Documenso instance:

* ``get_provisioning_adapter()`` returns ``None`` when the platform flag is
  ``off`` and the concrete adapter for ``trpc`` / ``db`` (R20.5 / factory);
* an unknown mode raises a humanized :class:`ProvisioningError`;
* the **isolation guarantee** — every adapter call surfaces ANY underlying
  failure (tRPC/HTTP error, DB error) as a :class:`ProvisioningError` and never
  lets a raw exception escape (R20.3/R20.4);
* the ``trpc`` adapter parses successful tRPC responses (team id / token);
* the ``db`` adapter stores only the token **hash** and returns the plaintext
  once, and writes the Team / TeamMember / Webhook rows.

External calls are mocked: ``httpx`` for the tRPC adapter and a fake async
connection for the db adapter.

Requirements: 20.1, 20.4, 20.5
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.integrations import documenso_provisioning as prov
from app.integrations.documenso_provisioning import (
    DbProvisioningAdapter,
    ProvisionedTeam,
    ProvisionedToken,
    ProvisioningAdapter,
    ProvisioningError,
    TrpcProvisioningAdapter,
    get_provisioning_adapter,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Org:
    def __init__(self, name="Acme Ltd", slug="acme", oid="org-1", owner=None):
        self.name = name
        self.slug = slug
        self.id = oid
        self.documenso_owner_user_id = owner


class _FakeConn:
    """A fake asyncpg-style connection recording statements it executes."""

    def __init__(self, *, fetchval_result=None, raise_on=None):
        self.fetchval_result = fetchval_result
        self.raise_on = raise_on  # substring; raise when a SQL contains it
        self.executed: list[tuple[str, tuple]] = []
        self.closed = False

    def _maybe_raise(self, sql: str) -> None:
        if self.raise_on and self.raise_on in sql:
            raise RuntimeError("boom: simulated documenso DB failure")

    async def fetchval(self, sql, *args):
        self._maybe_raise(sql)
        self.executed.append((sql, args))
        return self.fetchval_result

    async def execute(self, sql, *args):
        self._maybe_raise(sql)
        self.executed.append((sql, args))
        return "INSERT 0 1"

    async def close(self):
        self.closed = True


def _connect_factory(conn):
    async def _connect():
        return conn

    return _connect


# ---------------------------------------------------------------------------
# Factory: ESIGN_PROVISIONING_MODE selection
# ---------------------------------------------------------------------------


def test_get_provisioning_adapter_returns_none_when_off(monkeypatch):
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "off")
    assert get_provisioning_adapter() is None


def test_get_provisioning_adapter_defaults_to_off(monkeypatch):
    # Empty / unset behaves as disabled.
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "")
    assert get_provisioning_adapter() is None


def test_get_provisioning_adapter_trpc(monkeypatch):
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "trpc")
    monkeypatch.setattr(prov.settings, "esign_documenso_admin_url", "https://d.example")
    monkeypatch.setattr(prov.settings, "esign_documenso_admin_token", "admin-sess")
    adapter = get_provisioning_adapter()
    assert isinstance(adapter, TrpcProvisioningAdapter)
    # Honours the runtime-checkable protocol.
    assert isinstance(adapter, ProvisioningAdapter)


def test_get_provisioning_adapter_db(monkeypatch):
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "db")
    monkeypatch.setattr(
        prov.settings, "esign_documenso_db_url", "postgresql://x/docs"
    )
    adapter = get_provisioning_adapter()
    assert isinstance(adapter, DbProvisioningAdapter)
    assert isinstance(adapter, ProvisioningAdapter)


def test_get_provisioning_adapter_case_insensitive(monkeypatch):
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "  TRPC ")
    assert isinstance(get_provisioning_adapter(), TrpcProvisioningAdapter)


def test_get_provisioning_adapter_unknown_mode_raises(monkeypatch):
    monkeypatch.setattr(prov.settings, "esign_provisioning_mode", "wat")
    with pytest.raises(ProvisioningError):
        get_provisioning_adapter()


# ---------------------------------------------------------------------------
# Platform-secret loading (envelope-encrypted at rest)
# ---------------------------------------------------------------------------


def test_load_platform_secret_plaintext_passthrough():
    assert prov._load_platform_secret("plain-value") == "plain-value"
    assert prov._load_platform_secret("") == ""


def test_load_platform_secret_decrypts_enc_prefixed_value():
    import base64

    from app.core.encryption import envelope_encrypt

    blob = envelope_encrypt("super-secret-admin-session")
    encoded = "enc:" + base64.b64encode(blob).decode("ascii")
    assert prov._load_platform_secret(encoded) == "super-secret-admin-session"


def test_load_platform_secret_bad_encrypted_value_raises():
    with pytest.raises(ProvisioningError):
        prov._load_platform_secret("enc:not-valid-base64-or-blob!!!")


# ---------------------------------------------------------------------------
# tRPC adapter — success parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trpc_create_team_parses_team_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"data": {"json": {"teamId": "42"}}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        team = await adapter.create_team(org=_Org())
    finally:
        await http.aclose()
    assert team == ProvisionedTeam(team_id="42")


@pytest.mark.asyncio
async def test_trpc_mint_team_token_parses_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"data": {"json": {"token": "api_xyz"}}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        token = await adapter.mint_team_token(team_id="42")
    finally:
        await http.aclose()
    assert token == ProvisionedToken(token="api_xyz")


@pytest.mark.asyncio
async def test_trpc_ensure_webhook_succeeds_and_sends_credential_without_logging():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"result": {"data": {"json": {}}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        # Should not raise.
        await adapter.ensure_webhook(
            team_id="42", routing_url="https://ora/api/v2/esign/webhook/r1", secret="s"
        )
    finally:
        await http.aclose()
    assert seen["auth"] == "Bearer sess"


# ---------------------------------------------------------------------------
# tRPC adapter — ISOLATION: every failure surfaces as ProvisioningError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trpc_http_error_surfaces_as_provisioning_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "kaboom"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        with pytest.raises(ProvisioningError):
            await adapter.create_team(org=_Org())
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_trpc_transport_error_surfaces_as_provisioning_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        with pytest.raises(ProvisioningError):
            await adapter.mint_team_token(team_id="42")
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_trpc_malformed_payload_surfaces_as_provisioning_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # 200 OK but no team id in the payload.
        return httpx.Response(200, json={"result": {"data": {"json": {}}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = TrpcProvisioningAdapter(
        base_url="https://d.example", admin_token="sess", http=http
    )
    try:
        with pytest.raises(ProvisioningError):
            await adapter.create_team(org=_Org())
    finally:
        await http.aclose()


# ---------------------------------------------------------------------------
# db adapter — success: hashed token stored, plaintext returned once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_create_team_inserts_team_and_owner_member():
    conn = _FakeConn(fetchval_result=7)
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    team = await adapter.create_team(org=_Org(owner=99))
    assert team == ProvisionedTeam(team_id="7")
    sqls = " ".join(sql for sql, _ in conn.executed)
    assert '"Team"' in sqls
    assert '"TeamMember"' in sqls  # owner member inserted when owner id present
    assert conn.closed is True


@pytest.mark.asyncio
async def test_db_create_team_without_owner_skips_member():
    conn = _FakeConn(fetchval_result=7)
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    await adapter.create_team(org=_Org(owner=None))
    sqls = " ".join(sql for sql, _ in conn.executed)
    assert '"Team"' in sqls
    assert '"TeamMember"' not in sqls


@pytest.mark.asyncio
async def test_db_mint_team_token_stores_only_hash_and_returns_plaintext():
    conn = _FakeConn()
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    result = await adapter.mint_team_token(team_id="7")

    # The returned plaintext must hash to the value persisted in the DB.
    assert isinstance(result, ProvisionedToken)
    assert result.token  # plaintext returned once
    insert_sql, args = conn.executed[0]
    assert '"ApiToken"' in insert_sql
    stored = args[1]  # (name, token_hash, team_id)
    assert stored == hashlib.sha256(result.token.encode()).hexdigest()
    # The plaintext itself is NEVER what gets stored.
    assert stored != result.token


@pytest.mark.asyncio
async def test_db_ensure_webhook_inserts_webhook_row():
    conn = _FakeConn()
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    await adapter.ensure_webhook(
        team_id="7", routing_url="https://ora/api/v2/esign/webhook/r1", secret="s"
    )
    insert_sql, args = conn.executed[0]
    assert '"Webhook"' in insert_sql
    assert "https://ora/api/v2/esign/webhook/r1" in args
    assert "s" in args


# ---------------------------------------------------------------------------
# db adapter — ISOLATION: DB failures surface as ProvisioningError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_create_team_error_surfaces_as_provisioning_error():
    conn = _FakeConn(raise_on='"Team"')
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    with pytest.raises(ProvisioningError):
        await adapter.create_team(org=_Org())
    assert conn.closed is True  # connection still closed on failure


@pytest.mark.asyncio
async def test_db_mint_token_error_surfaces_as_provisioning_error():
    conn = _FakeConn(raise_on='"ApiToken"')
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    with pytest.raises(ProvisioningError):
        await adapter.mint_team_token(team_id="7")
    assert conn.closed is True


@pytest.mark.asyncio
async def test_db_ensure_webhook_error_surfaces_as_provisioning_error():
    conn = _FakeConn(raise_on='"Webhook"')
    adapter = DbProvisioningAdapter(db_url="x", connect=_connect_factory(conn))
    with pytest.raises(ProvisioningError):
        await adapter.ensure_webhook(team_id="7", routing_url="https://x/r", secret="s")
    assert conn.closed is True


@pytest.mark.asyncio
async def test_db_connect_failure_surfaces_as_provisioning_error():
    async def _boom():
        raise RuntimeError("cannot connect to documenso db")

    adapter = DbProvisioningAdapter(db_url="x", connect=_boom)
    with pytest.raises(ProvisioningError):
        await adapter.create_team(org=_Org())
