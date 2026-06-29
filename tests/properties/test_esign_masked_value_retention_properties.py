"""Property-based test for masked-value retention on per-org connection save (task 14.5).

The per-organisation connection service
(:func:`app.modules.esignatures.connection_service.save_connection`) applies the
``_MASK_PATTERN`` round-trip heuristic when persisting an organisation's
``service_token`` / ``webhook_signing_secret``: a value that the GUI echoed back
as a *masked* placeholder (e.g. ``"********"`` or ``"ab****"``) must **NOT**
overwrite the real stored secret with the mask — the previously
envelope-encrypted secret is **retained** (R1.5). A *non-masked* value, by
contrast, replaces the stored secret.

This test drives the real service over the same lightweight fake async session
used by ``tests/properties/test_esign_credential_storage_properties.py`` (which
captures the persisted row so a second ``save_connection`` observes the first
save as an update, not a create), with **real** envelope encryption, so the
retain-vs-replace behaviour is validated end to end through the encrypt /
decrypt path.

# Feature: esignature-integration, Property 3: Saving a masked value retains the stored secret — saving back the masked representation of a field leaves the organisation's stored value unchanged (it still decrypts to the original), while saving a non-masked value replaces it

**Validates: Requirements 1.5**
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Pre-load the full model graph (mirrors app/main.py + the credential-storage
# property test) so SQLAlchemy can resolve every string-based relationship
# reference when ``EsignOrgConnection`` is instantiated and the whole mapper
# registry is configured. Without this, constructing a single ORM model can
# raise InvalidRequestError.
import app.modules.auth.models  # noqa: F401,E402
import app.modules.admin.models  # noqa: F401,E402
import app.modules.organisations.models  # noqa: F401,E402
import app.modules.customers.models  # noqa: F401,E402
import app.modules.staff.models  # noqa: F401,E402
import app.modules.in_app_notifications.models  # noqa: F401,E402
import app.modules.esignatures.models  # noqa: F401,E402

from app.core.encryption import envelope_decrypt_str  # noqa: E402
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
# both the SELECT (returns the current row, or None on first create) and the
# audit-log INSERT (result ignored by write_audit_log). After the first
# ``save_connection`` adds a row, subsequent ``_load_row`` SELECTs observe it,
# so the second/third saves are UPDATES (not creates) — exactly what this
# retain-vs-replace property needs. No real DB required.
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


# Arbitrary unicode plaintext secret strings, excluding lone surrogates (which
# cannot be UTF-8 encoded) and any value that *looks* masked (those are the
# retained case, not a genuine new plaintext secret).
_plaintext_strategy = st.text(
    alphabet=st.characters(blacklist_categories=["Cs"]),
    min_size=1,
    max_size=200,
).filter(lambda s: not _is_masked(s))


# Masked placeholder echoes matching ``_MASK_PATTERN`` (``^\*+$|^.{0,4}\*{4,}$``):
# either an all-asterisk run, or a short (0-4 char) prefix followed by >=4
# asterisks. Filtered through ``_is_masked`` so only genuine masks are used.
_all_asterisks = st.integers(min_value=1, max_value=24).map(lambda n: "*" * n)
_prefixed_mask = st.tuples(
    st.text(
        alphabet=st.characters(blacklist_categories=["Cs"], blacklist_characters="*"),
        min_size=0,
        max_size=4,
    ),
    st.integers(min_value=4, max_value=12),
).map(lambda t: t[0] + "*" * t[1])
_masked_strategy = st.one_of(_all_asterisks, _prefixed_mask).filter(_is_masked)


async def _save(session, org_id, **kwargs):
    return await save_connection(
        session,
        org_id,
        base_url="https://documenso.example.test",
        documenso_team_id="team-xyz",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Property 3 — saving a masked echo retains the stored secret; a non-masked
# value replaces it.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    original_token=_plaintext_strategy,
    original_secret=_plaintext_strategy,
    masked_token=_masked_strategy,
    masked_secret=_masked_strategy,
    new_token=_plaintext_strategy,
    new_secret=_plaintext_strategy,
)
def test_saving_masked_value_retains_stored_secret(
    original_token,
    original_secret,
    masked_token,
    masked_secret,
    new_token,
    new_secret,
):
    invalidate_documenso_connection_cache()
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    # 1) First save — store the REAL plaintext secrets (creates the row).
    asyncio.run(
        _save(
            session,
            org_id,
            service_token=original_token,
            webhook_signing_secret=original_secret,
        )
    )
    assert len(session.added) == 1
    row = session.added[0]
    assert row.org_id == org_id
    assert envelope_decrypt_str(row.service_token_encrypted) == original_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) == original_secret

    # Snapshot the encrypted blobs so we can prove they are byte-for-byte
    # unchanged after a masked save.
    token_blob_before = row.service_token_encrypted
    secret_blob_before = row.webhook_secret_encrypted

    # 2) Second save — echo back MASKED values for both secrets (an UPDATE on
    #    the same row). The previously stored secrets must be RETAINED.
    asyncio.run(
        _save(
            session,
            org_id,
            service_token=masked_token,
            webhook_signing_secret=masked_secret,
        )
    )
    # Still only one row — this was an update, not a create.
    assert len(session.added) == 1
    assert session.added[0] is row

    # The encrypted columns are untouched, and still decrypt to the ORIGINALS
    # (never the mask string).
    assert row.service_token_encrypted == token_blob_before
    assert row.webhook_secret_encrypted == secret_blob_before
    assert envelope_decrypt_str(row.service_token_encrypted) == original_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) == original_secret
    assert envelope_decrypt_str(row.service_token_encrypted) != masked_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) != masked_secret

    # 3) Control — saving a NEW non-masked value REPLACES the stored secret.
    asyncio.run(
        _save(
            session,
            org_id,
            service_token=new_token,
            webhook_signing_secret=new_secret,
        )
    )
    assert len(session.added) == 1
    assert envelope_decrypt_str(row.service_token_encrypted) == new_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) == new_secret


# ---------------------------------------------------------------------------
# Asymmetric case — only ONE field is echoed masked while the other gets a new
# plaintext value: the masked field is retained, the other is replaced. This
# guards against an "all or nothing" implementation mistake.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    original_token=_plaintext_strategy,
    original_secret=_plaintext_strategy,
    masked_token=_masked_strategy,
    new_secret=_plaintext_strategy,
)
def test_masked_field_retained_while_sibling_field_replaced(
    original_token,
    original_secret,
    masked_token,
    new_secret,
):
    invalidate_documenso_connection_cache()
    org_id = uuid.uuid4()
    session = _FakeSession(existing_row=None)

    asyncio.run(
        _save(
            session,
            org_id,
            service_token=original_token,
            webhook_signing_secret=original_secret,
        )
    )
    row = session.added[0]

    # Echo the token masked (retain) but give the webhook secret a new value.
    asyncio.run(
        _save(
            session,
            org_id,
            service_token=masked_token,
            webhook_signing_secret=new_secret,
        )
    )

    # Token retained (still the original), webhook secret replaced.
    assert envelope_decrypt_str(row.service_token_encrypted) == original_token
    assert envelope_decrypt_str(row.webhook_secret_encrypted) == new_secret
