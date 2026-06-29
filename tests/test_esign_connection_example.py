"""Example/integration tests for the per-org Documenso connection (task 14.6).

These are concrete *example* tests (not Hypothesis property tests) covering the
per-organisation connection-management surface (R1), exercised against the
service layer + the loader/client with lightweight fakes and a real envelope
encryption + ``httpx.MockTransport`` spy (no FastAPI/DB stack needed):

1. **Connection UI/API round-trip** — the masked GET projection
   (``connection_router._build_response``) hides secrets and surfaces
   ``base_url``/``documenso_team_id``; a save-then-reload round-trips the
   non-secret fields and the secret last-4 (R1.1, R1.4, R1.8).
2. **``documenso_team_id`` round-trip + scoping** — the saved team id is stored,
   returned, and is the team the org's Documenso calls are scoped to (R1.8,
   R13.7).
3. **Connection test** — a 200 marks the org ``is_verified``; a 401 marks it
   unverified; an unconfigured org is rejected before any Documenso call (R1.6,
   R1.10, R19.2).
4. **Credential-source guard** — Documenso API credentials come *only* from the
   per-org DB connection (``get_documenso_connection``), never from
   ``.env``/``settings``: the API-call path defines no global
   ``get_documenso_*`` env helpers and reads no env/settings, and the loader
   raises ``DocumensoNotConfiguredError`` (it does not silently read env) when no
   row exists (R1.3).

Requirements: 1.1, 1.3, 1.6, 1.8, 19.2
"""

from __future__ import annotations

import uuid

import httpx
import pytest

# Pre-load the model graph so SQLAlchemy can resolve string-based relationships
# when EsignOrgConnection / Organisation are instantiated (mirrors the other
# esign unit/property tests).
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_encrypt  # noqa: E402
from app.integrations import documenso as documenso_mod  # noqa: E402
from app.integrations.documenso import (  # noqa: E402
    DocumensoClient,
    DocumensoConnection,
    DocumensoNotConfiguredError,
    get_documenso_connection,
    invalidate_documenso_connection_cache,
)
from app.modules.esignatures import connection_service as cs  # noqa: E402
from app.modules.esignatures import connection_router as cr  # noqa: E402
from app.modules.esignatures.connection_service import (  # noqa: E402
    _load_row,
    _masked_connection,
    save_connection,
)
from app.modules.esignatures.connection_service import (  # noqa: E402
    test_connection as svc_test_connection,
)
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402

# Capture the real AsyncClient class BEFORE any monkeypatch so the mock factory
# below never recurses into a patched ``httpx.AsyncClient``.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ---------------------------------------------------------------------------
# Fakes — a stateful async session that captures the persisted connection row
# and serves the connection SELECT, the audit-log INSERT, and re-loads.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal stand-in for AsyncSession used by the connection service."""

    def __init__(self, existing_row: EsignOrgConnection | None = None):
        self._row = existing_row
        self.added: list[EsignOrgConnection] = []

    async def execute(self, _stmt, _params=None):
        # Connection SELECT reads the row; the audit-log INSERT ignores the
        # result, so a single behaviour serves both.
        return _FakeResult(self._row)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._row = obj  # subsequent _load_row / refresh observe it

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
        return None


class _FakeURL:
    scheme = "https"


class _FakeRequest:
    """Minimal stand-in for a FastAPI Request used by ``_build_response``."""

    def __init__(self, *, host: str, org_id: uuid.UUID):
        self.headers = {"host": host}
        self.url = _FakeURL()
        self.path_params = {"org_id": str(org_id)}


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    """Silence the audit log — its DB INSERT is irrelevant to these examples."""

    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(cs, "write_audit_log", _noop)


def _mock_http_factory(handler):
    """Return a ``httpx.AsyncClient`` factory wired to a MockTransport.

    Used to monkeypatch ``connection_service.httpx.AsyncClient`` so the real
    :class:`DocumensoClient` is exercised against a scripted Documenso response.
    """

    def _factory(*_args, **_kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

    return _factory


# ---------------------------------------------------------------------------
# 1. Connection UI/API round-trip — masked GET + save/reload round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_connection_returns_masked_projection():
    """GET returns a masked connection: no plaintext secrets, base_url/team_id shown."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        service_token="tok_super_secret_value",
        webhook_signing_secret="whsec_super_secret_value",
    )

    masked = _masked_connection(await _load_row(session, org_id))
    request = _FakeRequest(host="api.example.test", org_id=org_id)
    resp = cr._build_response(masked, request)

    assert resp.configured is True
    assert resp.base_url == "https://documenso.example.test"
    assert resp.documenso_team_id == "team-abc"
    # Secrets surfaced only as an asterisk mask + last-4 — never plaintext.
    assert resp.service_token == cr._SECRET_MASK
    assert "tok_super_secret_value" not in resp.service_token
    assert resp.service_token_last4 == "alue"
    assert resp.webhook_signing_secret == cr._SECRET_MASK
    assert resp.webhook_secret_last4 == "alue"
    # The org's webhook routing URL is surfaced (R18/R19.1).
    assert resp.webhook_routing_id
    assert resp.webhook_url == (
        f"https://api.example.test/api/v2/esign/webhook/{resp.webhook_routing_id}"
    )


@pytest.mark.asyncio
async def test_get_unconfigured_connection_returns_not_configured_shape():
    """GET on an org with no connection yields a stable 'not configured' shape."""
    org_id = uuid.uuid4()
    request = _FakeRequest(host="api.example.test", org_id=org_id)

    resp = cr._build_response(None, request)

    assert resp.configured is False
    assert resp.org_id == org_id
    assert resp.webhook_subscription_status == "not_configured"


@pytest.mark.asyncio
async def test_put_saves_then_get_reflects_changes():
    """PUT saves the connection; a subsequent reload reflects base_url/team_id."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    # Initial create.
    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-original",
        service_token="tok_one",
        webhook_signing_secret="whsec_one",
    )

    # Update base_url + team id (secrets echoed back masked → retained).
    updated = await save_connection(
        session,
        org_id,
        base_url="https://documenso2.example.test",
        documenso_team_id="team-updated",
        service_token="********",  # masked echo — retain stored token
        webhook_signing_secret="********",  # masked echo — retain stored secret
    )

    # The returned + reloaded projections reflect the new non-secret values.
    assert updated["base_url"] == "https://documenso2.example.test"
    assert updated["documenso_team_id"] == "team-updated"

    reloaded = _masked_connection(await _load_row(session, org_id))
    assert reloaded["base_url"] == "https://documenso2.example.test"
    assert reloaded["documenso_team_id"] == "team-updated"
    # Masked echo retained the original secrets (last-4 unchanged).
    assert reloaded["service_token_last4"] == "_one"
    assert reloaded["webhook_secret_last4"] == "_one"


# ---------------------------------------------------------------------------
# 2. documenso_team_id round-trip + scoping (R1.8, R13.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_id_round_trips_and_scopes_documenso_calls():
    """The saved team id round-trips AND is the team the org's calls are scoped to."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-scoped-42",
        service_token="tok_team_scoped_raw",
        webhook_signing_secret="whsec",
    )

    # Round-trip: the team id is stored and returned via the loader.
    conn = await get_documenso_connection(session, org_id)
    assert conn.documenso_team_id == "team-scoped-42"
    assert conn.service_token == "tok_team_scoped_raw"  # decrypted from the DB row

    # Scoping: a client built from that connection uses the stored raw token on
    # every call (R13.7). The v2 RPC API scopes by the team-scoped token itself,
    # so NO ``teamId`` query param is sent on the wire.
    seen: list[tuple[str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (request.headers.get("Authorization"), request.url.params.get("teamId"))
        )
        return httpx.Response(200, json={})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        client = DocumensoClient.for_org(conn, http)
        await client.test_connection()
    finally:
        await http.aclose()

    assert seen == [("tok_team_scoped_raw", None)]


# ---------------------------------------------------------------------------
# 3. Connection test — valid/invalid + is_verified + unconfigured guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_test_marks_verified_on_200(monkeypatch):
    """A 200 from Documenso reports valid and sets the org is_verified=True (R19.2)."""
    org_id = uuid.uuid4()
    session = _FakeSession()
    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        service_token="tok",
        webhook_signing_secret="whsec",
    )
    # A save always clears verification until a fresh test (R19.5).
    assert (await _load_row(session, org_id)).is_verified is False

    monkeypatch.setattr(
        cs.httpx, "AsyncClient", _mock_http_factory(lambda r: httpx.Response(200, json={}))
    )

    result = await svc_test_connection(session, org_id)

    assert result == {"is_verified": True, "valid": True}
    assert (await _load_row(session, org_id)).is_verified is True


@pytest.mark.asyncio
async def test_connection_test_marks_unverified_on_401(monkeypatch):
    """A 401 from Documenso reports invalid and sets is_verified=False (R1.6/R19.2)."""
    org_id = uuid.uuid4()
    session = _FakeSession()
    await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-abc",
        service_token="bad-token",
        webhook_signing_secret="whsec",
    )

    monkeypatch.setattr(
        cs.httpx, "AsyncClient", _mock_http_factory(lambda r: httpx.Response(401))
    )

    result = await svc_test_connection(session, org_id)

    assert result == {"is_verified": False, "valid": False}
    assert (await _load_row(session, org_id)).is_verified is False


@pytest.mark.asyncio
async def test_connection_test_rejects_when_unconfigured():
    """Testing an org with no connection row is rejected before any call (R1.10)."""
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    with pytest.raises(DocumensoNotConfiguredError):
        await svc_test_connection(session, org_id)


# ---------------------------------------------------------------------------
# 4. Credential-source guard (R1.3) — credentials come ONLY from the DB
#    connection, never from .env / settings.
# ---------------------------------------------------------------------------


def _api_path_source() -> str:
    """Read the Documenso API-call path source (loader + client)."""
    import inspect

    return inspect.getsource(documenso_mod)


def test_no_global_env_credential_helpers_on_api_path():
    """The API-call path defines no global get_documenso_* env credential helpers."""
    src = _api_path_source()
    for banned in (
        "def get_documenso_base_url",
        "def get_documenso_service_token",
        "def get_documenso_webhook_secret",
        "def get_documenso_base_url_from_env",
        "def get_documenso_service_token_from_env",
        "def get_documenso_webhook_secret_from_env",
    ):
        assert banned not in src, f"unexpected env credential helper: {banned}"


def test_api_path_reads_no_env_or_settings():
    """The Documenso API-call path reads no env/settings for credentials (R1.3).

    Credentials for API calls are resolved exclusively from the per-org DB row
    via ``get_documenso_connection``; there is no ``.env``/``settings`` fallback.
    """
    src = _api_path_source()
    # Strip the module docstring (it legitimately mentions ``.env``/settings in
    # prose) so the assertion targets executable code only.
    body = src.split('"""', 2)[-1]
    # Credentials must never be read from environment variables.
    for banned in ("os.getenv", "os.environ"):
        assert banned not in body, f"API-call path must not read {banned} (R1.3)"
    # The API-call path may read non-credential ``settings.esign_*`` feature
    # flags (transport policy, capability-probe gates, public-URL override) —
    # these are NOT credentials. R1.3 only forbids sourcing *credentials*
    # (base URL/token/webhook secret) from settings; those still come solely
    # from the per-org DB connection row. Guard against credential-bearing
    # settings reads specifically.
    for banned in (
        "settings.documenso_base_url",
        "settings.documenso_service_token",
        "settings.documenso_token",
        "settings.documenso_webhook_secret",
        "settings.esign_base_url",
        "settings.esign_service_token",
        "settings.esign_token",
        "settings.esign_api_token",
        "settings.esign_webhook_secret",
    ):
        assert banned not in body, f"API-call path must not read credential {banned} (R1.3)"


@pytest.mark.asyncio
async def test_loader_is_sole_credential_source_and_raises_when_unconfigured():
    """The per-org loader is the credential source; it raises (not env-reads) when absent."""
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    # No row → raises rather than silently falling back to env/settings.
    with pytest.raises(DocumensoNotConfiguredError):
        await get_documenso_connection(session, org_id)


@pytest.mark.asyncio
async def test_test_connection_credentials_come_from_db_row(monkeypatch):
    """``test_connection`` builds the client from the DB row's decrypted secrets.

    Spies ``DocumensoClient.for_org`` to assert the connection it receives
    carries the saved row's base_url/token/team id — proving the credential
    source is the per-org DB connection, not env/settings (R1.3).
    """
    org_id = uuid.uuid4()
    session = _FakeSession(
        existing_row=EsignOrgConnection(
            id=uuid.uuid4(),
            org_id=org_id,
            base_url="https://documenso.db-source.test",
            documenso_team_id="team-from-db",
            service_token_encrypted=envelope_encrypt("tok-from-db"),
            webhook_secret_encrypted=envelope_encrypt("whsec-from-db"),
            webhook_routing_id="route-db",
            is_verified=False,
        )
    )

    captured: dict[str, DocumensoConnection] = {}
    real_for_org = DocumensoClient.for_org

    def _spy_for_org(conn: DocumensoConnection, http):
        captured["conn"] = conn
        return real_for_org(conn, http)

    monkeypatch.setattr(DocumensoClient, "for_org", staticmethod(_spy_for_org))
    monkeypatch.setattr(
        cs.httpx, "AsyncClient", _mock_http_factory(lambda r: httpx.Response(200, json={}))
    )

    await svc_test_connection(session, org_id)

    conn = captured["conn"]
    assert conn.base_url == "https://documenso.db-source.test"
    assert conn.service_token == "tok-from-db"  # decrypted from the DB column
    assert conn.documenso_team_id == "team-from-db"
