"""Property-based test for per-org Documenso credential storage round-trip (task 14.3).

The per-organisation connection service
(:func:`app.modules.esignatures.connection_service.save_connection`)
envelope-encrypts an organisation's ``service_token`` and
``webhook_signing_secret`` into the ``esign_org_connections``
``service_token_encrypted`` / ``webhook_secret_encrypted`` BYTEA columns (R1.2,
R15.1). The guarantee under test is a faithful round-trip with no plaintext at
rest:

  * any secret string saved decrypts back — via
    :func:`app.core.encryption.envelope_decrypt_str` — to the **exact** original
    plaintext, and
  * the stored BYTEA blob is **never** the plaintext bytes (the secret is
    genuinely encrypted at rest, not merely stashed verbatim).

Two layers are exercised:

  1. The pure encryption primitive — ``envelope_decrypt_str(envelope_encrypt(s)) == s``
     and the blob ``!= s.encode()`` — across arbitrary unicode secrets.
  2. The connection service ``save_connection`` itself, driven over a lightweight
     fake async session that captures the persisted row (the same fake-session
     pattern used by ``tests/test_documenso_connection_loader.py``) with **real**
     envelope encryption, so the decrypt-at-rest path is genuinely validated end
     to end.

# Feature: esignature-integration, Property 1: Credential storage round-trip — a service_token / webhook_signing_secret saved (envelope-encrypted) decrypts back to the original plaintext, and is never stored in plaintext in the column

**Validates: Requirements 1.2, 15.1**
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + tests/fleet_portal/conftest.py)
# so SQLAlchemy can resolve every string-based relationship reference (e.g.
# Organisation -> 'User') when ``EsignOrgConnection`` is instantiated and the
# whole mapper registry is configured. Without this, constructing a single ORM
# model can raise InvalidRequestError.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_decrypt_str, envelope_encrypt  # noqa: E402
from app.integrations.documenso import (  # noqa: E402
    invalidate_documenso_connection_cache,
)
from app.modules.esignatures.connection_service import (  # noqa: E402
    _is_masked,
    save_connection,
)
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402


# ---------------------------------------------------------------------------
# Fake async session — captures the persisted EsignOrgConnection row and serves
# both the initial SELECT (returns the row, or None on first create) and the
# audit-log INSERT (result ignored by write_audit_log). No real DB needed.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal stand-in for AsyncSession used by ``save_connection``."""

    def __init__(self, existing_row: EsignOrgConnection | None = None):
        self._row = existing_row
        self.added: list[EsignOrgConnection] = []

    async def execute(self, _stmt, _params=None):
        # The connection loader SELECT reads the row; the audit-log INSERT
        # (passes a params dict) ignores the returned result, so a single
        # behaviour serves both.
        return _FakeResult(self._row)

    def add(self, obj):
        self.added.append(obj)
        # So a subsequent _load_row / refresh observes the freshly-added row.
        self._row = obj

    async def flush(self):  # no-op — encryption already happened in-memory
        return None

    async def refresh(self, _obj):  # no-op — server defaults not needed here
        return None


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


# Arbitrary unicode secret strings, excluding lone surrogates (which cannot be
# UTF-8 encoded) and any value that looks like a masked placeholder echo (those
# are intentionally skipped by ``save_connection`` to retain the stored value —
# that is Property 3's concern, not this round-trip property).
_secret_strategy = st.text(
    alphabet=st.characters(blacklist_categories=["Cs"]),
    min_size=1,
    max_size=200,
).filter(lambda s: not _is_masked(s))


# ---------------------------------------------------------------------------
# Layer 1 — the pure envelope-encryption primitive round-trips and never
# stores the plaintext verbatim.
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(secret=_secret_strategy)
def test_envelope_encryption_round_trips_and_hides_plaintext(secret):
    blob = envelope_encrypt(secret)

    # Round-trip: decrypt recovers the exact original plaintext.
    assert envelope_decrypt_str(blob) == secret

    # No plaintext at rest: the stored blob is not the plaintext bytes.
    plaintext_bytes = secret.encode("utf-8")
    assert blob != plaintext_bytes


# ---------------------------------------------------------------------------
# Layer 2 — save_connection envelope-encrypts both secret columns so they
# decrypt back to the originals and are never stored as plaintext.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(service_token=_secret_strategy, webhook_secret=_secret_strategy)
def test_save_connection_credential_round_trip(service_token, webhook_secret):
    invalidate_documenso_connection_cache()
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    masked = asyncio.run(
        save_connection(
            session,
            org_id,
            base_url="https://documenso.example.test",
            documenso_team_id="team-xyz",
            service_token=service_token,
            webhook_signing_secret=webhook_secret,
        )
    )

    # A row was persisted for this org.
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, EsignOrgConnection)
    assert row.org_id == org_id

    # Round-trip: each stored BYTEA column decrypts to the exact original.
    assert row.service_token_encrypted is not None
    assert row.webhook_secret_encrypted is not None
    assert envelope_decrypt_str(row.service_token_encrypted) == service_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) == webhook_secret

    # No plaintext at rest: the columns are not the plaintext bytes.
    token_bytes = service_token.encode("utf-8")
    secret_bytes = webhook_secret.encode("utf-8")
    assert row.service_token_encrypted != token_bytes
    assert row.webhook_secret_encrypted != secret_bytes

    # The response projection exposes only the *_last4 masked forms (never the
    # full plaintext) — confirming the persisted secret was the original.
    assert masked["service_token_last4"] == service_token[-4:]
    assert masked["webhook_secret_last4"] == webhook_secret[-4:]
