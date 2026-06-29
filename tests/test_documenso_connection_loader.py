"""Unit tests for the per-org Documenso connection loader (task 5.1).

Covers :func:`get_documenso_connection`, the :class:`DocumensoConnection`
value object, the per-org short-TTL cache (and its invalidation hook), and the
exception hierarchy (``DocumensoError`` / ``DocumensoNotConfiguredError`` /
``DocumensoApiError``).

The loader is exercised with a lightweight fake async session (no real DB
needed) and real envelope encryption so the decrypt-at-call-time path is
genuinely validated.

Requirements: 1.3, 1.9, 13.7, 15.1
"""

from __future__ import annotations

import uuid

import pytest

from app.core.encryption import envelope_encrypt
from app.integrations import documenso
from app.integrations.documenso import (
    DocumensoApiError,
    DocumensoConnection,
    DocumensoError,
    DocumensoNotConfiguredError,
    get_documenso_connection,
    invalidate_documenso_connection_cache,
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
    """Minimal stand-in for AsyncSession.execute(select(...))."""

    def __init__(self, row):
        self._row = row
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _FakeResult(self._row)


def _make_row(
    *,
    org_id: uuid.UUID,
    token: str = "tok_team_scoped_raw",
    secret: str = "whsec_per_org",
    team_id: str | None = "team-123",
    routing_id: str = "route-abc",
    is_verified: bool = True,
) -> EsignOrgConnection:
    return EsignOrgConnection(
        id=uuid.uuid4(),
        org_id=org_id,
        base_url="https://documenso.example.test",
        documenso_team_id=team_id,
        service_token_encrypted=envelope_encrypt(token) if token is not None else None,
        webhook_secret_encrypted=envelope_encrypt(secret) if secret is not None else None,
        webhook_routing_id=routing_id,
        is_verified=is_verified,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy():
    assert issubclass(DocumensoNotConfiguredError, DocumensoError)
    assert issubclass(DocumensoApiError, DocumensoError)


def test_api_error_carries_status():
    err = DocumensoApiError("upstream blew up", status=502)
    assert err.status == 502
    assert "upstream blew up" in str(err)


def test_api_error_status_defaults_none():
    assert DocumensoApiError("transport failure").status is None


# ---------------------------------------------------------------------------
# Loader — happy path + decryption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loader_returns_decrypted_connection():
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    conn = await get_documenso_connection(session, org_id)

    assert isinstance(conn, DocumensoConnection)
    assert conn.base_url == "https://documenso.example.test"
    assert conn.service_token == "tok_team_scoped_raw"  # decrypted at call time
    assert conn.webhook_secret == "whsec_per_org"
    assert conn.documenso_team_id == "team-123"
    assert conn.webhook_routing_id == "route-abc"
    assert conn.is_verified is True


@pytest.mark.asyncio
async def test_loader_accepts_string_org_id():
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    conn = await get_documenso_connection(session, str(org_id))
    assert conn.service_token == "tok_team_scoped_raw"


@pytest.mark.asyncio
async def test_loader_handles_absent_secret_columns():
    org_id = uuid.uuid4()
    row = _make_row(org_id=org_id)
    row.service_token_encrypted = None
    row.webhook_secret_encrypted = None
    session = _FakeSession(row)

    conn = await get_documenso_connection(session, org_id)
    assert conn.service_token == ""
    assert conn.webhook_secret == ""


# ---------------------------------------------------------------------------
# Loader — not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loader_raises_when_no_connection_row():
    session = _FakeSession(None)
    with pytest.raises(DocumensoNotConfiguredError):
        await get_documenso_connection(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# Cache behaviour — keyed by org_id, invalidation hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_avoids_second_db_read():
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    await get_documenso_connection(session, org_id)
    await get_documenso_connection(session, org_id)

    assert session.execute_calls == 1  # second call served from cache


@pytest.mark.asyncio
async def test_cache_is_keyed_per_org():
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    session_a = _FakeSession(_make_row(org_id=org_a, token="tok_A", team_id="team-A"))
    session_b = _FakeSession(_make_row(org_id=org_b, token="tok_B", team_id="team-B"))

    conn_a = await get_documenso_connection(session_a, org_a)
    conn_b = await get_documenso_connection(session_b, org_b)

    assert conn_a.service_token == "tok_A"
    assert conn_a.documenso_team_id == "team-A"
    assert conn_b.service_token == "tok_B"
    assert conn_b.documenso_team_id == "team-B"


@pytest.mark.asyncio
async def test_invalidation_forces_reload():
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    await get_documenso_connection(session, org_id)
    invalidate_documenso_connection_cache(org_id)
    await get_documenso_connection(session, org_id)

    assert session.execute_calls == 2  # cache cleared, re-read from DB


@pytest.mark.asyncio
async def test_invalidation_accepts_string_org_id():
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    await get_documenso_connection(session, org_id)
    invalidate_documenso_connection_cache(str(org_id))
    await get_documenso_connection(session, org_id)

    assert session.execute_calls == 2


@pytest.mark.asyncio
async def test_expired_cache_entry_reloads(monkeypatch):
    org_id = uuid.uuid4()
    session = _FakeSession(_make_row(org_id=org_id))

    # First load at t=1000.
    monkeypatch.setattr(documenso.time, "monotonic", lambda: 1000.0)
    await get_documenso_connection(session, org_id)

    # Jump past the TTL window — entry should be considered expired.
    monkeypatch.setattr(
        documenso.time, "monotonic", lambda: 1000.0 + documenso._CACHE_TTL + 1
    )
    await get_documenso_connection(session, org_id)

    assert session.execute_calls == 2
