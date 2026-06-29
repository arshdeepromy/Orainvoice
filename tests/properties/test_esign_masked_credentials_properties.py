"""Property-based test: masked credentials are never returned in plaintext (task 14.4).

The per-organisation Documenso connection (``esign_org_connections``) holds the
team-scoped ``service_token`` and the ``webhook_signing_secret`` envelope-encrypted
at rest. Whenever that connection is projected back to a caller — either as the
service-layer masked dict
(:func:`app.modules.esignatures.connection_service._masked_connection`, returned
by :func:`~app.modules.esignatures.connection_service.save_connection`) or as the
Global-Admin API response
(:class:`app.modules.esignatures.connection_router.ConnectionResponse`, built by
``_build_response``) — the plaintext ``service_token`` /
``webhook_signing_secret`` MUST NEVER appear. Only masked forms are surfaced:

  * the service projection exposes only ``service_token_last4`` /
    ``webhook_secret_last4`` (the trailing 4 chars) and **no** plaintext
    token/secret keys, and
  * the API response surfaces ``service_token`` / ``webhook_signing_secret``
    only as the asterisk mask ``********`` (when a secret is stored) or ``""``
    (when not) plus the ``*_last4`` projection — never plaintext. The asterisk
    mask additionally matches the connection service's ``_MASK_PATTERN`` so that
    a client echoing it back on save round-trips (retains the stored secret).

This exercises both projection layers over a lightweight fake async session
(the same fake-session + model-preload pattern used by
``tests/properties/test_esign_credential_storage_properties.py``) with **real**
envelope encryption, so the masking path is genuinely validated end to end.

To avoid false positives, the "plaintext leak" assertion treats the trailing
4 characters (the allowed ``*_last4`` projection) specially: for any secret
longer than 4 characters the full plaintext can never be a substring of a
4-char tail, so the full secret is asserted absent from the serialized
projection; for shorter secrets the only permitted occurrence is the
``*_last4`` field itself.

# Feature: esignature-integration, Property 2: Masked credentials are never returned in plaintext (per-org connection responses)

**Validates: Requirements 1.4, 15.3**
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the credential-storage
# property test) so SQLAlchemy can resolve every string-based relationship
# reference when ``EsignOrgConnection`` is instantiated and the whole mapper
# registry is configured.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.integrations.documenso import (  # noqa: E402
    invalidate_documenso_connection_cache,
)
from app.modules.esignatures.connection_router import (  # noqa: E402
    _SECRET_MASK,
    _build_response,
)
from app.modules.esignatures.connection_service import (  # noqa: E402
    _MASK_PATTERN,
    _is_masked,
    save_connection,
)
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402


# ---------------------------------------------------------------------------
# Fake async session — captures the persisted EsignOrgConnection row and serves
# both the initial SELECT and the audit-log INSERT (result ignored). Mirrors the
# fake-session pattern from the credential-storage property test. No DB needed.
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
        return _FakeResult(self._row)

    def add(self, obj):
        self.added.append(obj)
        self._row = obj

    async def flush(self):
        return None

    async def refresh(self, _obj):
        return None


# ---------------------------------------------------------------------------
# Fake Request — supplies only what ``_build_response`` /
# ``extract_request_base_url`` read: ``headers.get(...)`` and ``url.scheme``.
# ---------------------------------------------------------------------------


class _FakeURL:
    scheme = "https"


class _FakeHeaders:
    def __init__(self, mapping: dict[str, str]):
        self._m = {k.lower(): v for k, v in mapping.items()}

    def get(self, key, default=None):
        return self._m.get(key.lower(), default)


class _FakeRequest:
    def __init__(self, host: str = "app.example.test"):
        self.headers = _FakeHeaders({"host": host})
        self.url = _FakeURL()
        self.path_params: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


# Arbitrary unicode secret strings, excluding lone surrogates (not UTF-8
# encodable) and masked-placeholder echoes (those are intentionally skipped by
# ``save_connection`` — that retention behaviour is Property 3's concern, and a
# skipped secret would leave the column unset and break the last4 assertion).
_secret_strategy = st.text(
    alphabet=st.characters(blacklist_categories=["Cs"]),
    min_size=1,
    max_size=200,
).filter(lambda s: not _is_masked(s))


def _serialize(value) -> str:
    """Serialize a projection (dict or model) to a single string for scanning."""
    return json.dumps(value, default=str, ensure_ascii=False)


def _assert_no_plaintext_leak(serialized: str, secret: str) -> None:
    """Assert the full plaintext secret never appears in the serialized output.

    The trailing 4 chars are an allowed masked projection (``*_last4``). For a
    secret longer than 4 chars the full plaintext cannot be a substring of any
    4-char tail, so the full secret must be entirely absent. For a secret of 4
    or fewer chars, the whole value *is* its own ``*_last4`` so we cannot assert
    its absence here — that short-secret case is covered field-by-field by the
    caller (only the ``*_last4`` field may contain it).
    """
    if len(secret) > 4:
        assert secret not in serialized, (
            "plaintext secret leaked into the masked projection"
        )


# ---------------------------------------------------------------------------
# Property 2 — the masked projections never carry plaintext credentials.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(service_token=_secret_strategy, webhook_secret=_secret_strategy)
def test_masked_credentials_never_returned_in_plaintext(service_token, webhook_secret):
    invalidate_documenso_connection_cache()
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    # --- service-layer masked projection (returned by save_connection) -------
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

    # No plaintext token/secret KEYS exist on the service projection — only the
    # masked *_last4 forms.
    assert "service_token" not in masked
    assert "webhook_signing_secret" not in masked
    assert "webhook_secret" not in masked
    assert set(masked) >= {"service_token_last4", "webhook_secret_last4"}

    # The *_last4 fields expose exactly the trailing 4 chars (or the whole short
    # secret), never the full longer plaintext.
    assert masked["service_token_last4"] == service_token[-4:]
    assert masked["webhook_secret_last4"] == webhook_secret[-4:]

    # Serialized service projection contains no full plaintext secret.
    masked_serialized = _serialize(masked)
    _assert_no_plaintext_leak(masked_serialized, service_token)
    _assert_no_plaintext_leak(masked_serialized, webhook_secret)

    # --- API response projection (ConnectionResponse via _build_response) ----
    response = _build_response(masked, _FakeRequest())

    # Secrets are surfaced only as the asterisk mask (a secret IS stored here),
    # never plaintext.
    assert response.service_token == _SECRET_MASK
    assert response.webhook_signing_secret == _SECRET_MASK
    assert response.service_token != service_token
    assert response.webhook_signing_secret != webhook_secret

    # The asterisk mask matches the connection service's _MASK_PATTERN so an
    # echoed value round-trips (retains the stored secret on save).
    assert _MASK_PATTERN.match(response.service_token)
    assert _MASK_PATTERN.match(response.webhook_signing_secret)

    # *_last4 on the response mirrors the trailing 4 chars only.
    assert response.service_token_last4 == service_token[-4:]
    assert response.webhook_secret_last4 == webhook_secret[-4:]

    # Serialized full API response carries no full plaintext secret anywhere.
    response_serialized = _serialize(response.model_dump())
    _assert_no_plaintext_leak(response_serialized, service_token)
    _assert_no_plaintext_leak(response_serialized, webhook_secret)

    # Short-secret guard: when a secret is <= 4 chars its value equals its
    # *_last4 projection; assert that is the ONLY field carrying it (the
    # asterisk-masked secret field must not echo the plaintext).
    if len(service_token) <= 4:
        assert response.service_token != service_token
    if len(webhook_secret) <= 4:
        assert response.webhook_signing_secret != webhook_secret


# ---------------------------------------------------------------------------
# Example: an UNCONFIGURED org (no row) yields empty masks, never plaintext.
# ---------------------------------------------------------------------------


def test_unconfigured_connection_returns_empty_masks():
    request = _FakeRequest()
    request.path_params = {"org_id": str(uuid.uuid4())}

    response = _build_response(None, request)

    assert response.configured is False
    assert response.service_token == ""
    assert response.webhook_signing_secret == ""
    assert response.service_token_last4 == ""
    assert response.webhook_secret_last4 == ""
