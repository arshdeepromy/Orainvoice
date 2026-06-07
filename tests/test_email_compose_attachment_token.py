"""Property test: Attachment_Token validation is entity- and org-scoped.

Feature: send-email-modal, Property 3: Attachment-token validation is entity-
and org-scoped.

The HMAC attachment token (``app.modules.email_compose.service``) defends the
override-send endpoints against IDOR: a token minted for one
``(org_id, entity_id, attachment_kind)`` triple must validate **only** when
presented with the *same* org and entity and while it is still within its
validity window. Any of the following must cause validation to fail
(``validate_attachment_token`` returns ``None``):

  * a different ``org_id``,
  * a different ``entity_id``,
  * an expiry in the past,
  * a tampered signature, or
  * a tampered payload.

The example-based tests below lock down a few concrete scenarios; the
Hypothesis property test exercises the same guarantees across a wide range of
org/entity id shapes (UUIDs — the real-world shape — plus integers and
constrained strings), every valid attachment kind, and a range of past/future
expiry offsets.

Design ref: ``.kiro/specs/send-email-modal/design.md`` →
Data Models §4 "Attachment_Token (HMAC) shape and signing key".

**Validates: Requirements 7.6**
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app.modules.email_compose.service import (
    ATTACHMENT_TOKEN_TTL,
    VALID_ATTACHMENT_KINDS,
    build_attachment_token,
    mint_attachment_token,
    validate_attachment_token,
)

# Sorted so Hypothesis sampling is deterministic across runs.
_KINDS = sorted(VALID_ATTACHMENT_KINDS)


# ---------------------------------------------------------------------------
# Example-based unit tests (concrete scenarios)
# ---------------------------------------------------------------------------


def test_round_trip_returns_original_kind():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    token = mint_attachment_token(org_id, entity_id, "invoice_pdf")
    assert validate_attachment_token(token, org_id, entity_id) == "invoice_pdf"


def test_wrong_org_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    token = mint_attachment_token(org_id, entity_id, "quote_pdf")
    assert validate_attachment_token(token, uuid.uuid4(), entity_id) is None


def test_wrong_entity_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    token = mint_attachment_token(org_id, entity_id, "quote_pdf")
    assert validate_attachment_token(token, org_id, uuid.uuid4()) is None


def test_past_expiry_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = build_attachment_token(org_id, entity_id, "invoice_pdf_paid", past)
    assert validate_attachment_token(token, org_id, entity_id) is None


def test_tampered_signature_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    token = mint_attachment_token(org_id, entity_id, "customer_statement_pdf")
    tampered = _tamper_signature(token)
    assert tampered != token
    assert validate_attachment_token(tampered, org_id, entity_id) is None


def test_tampered_payload_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    token = mint_attachment_token(org_id, entity_id, "invoice_pdf")
    tampered = _tamper_payload(token)
    assert tampered != token
    assert validate_attachment_token(tampered, org_id, entity_id) is None


def test_garbage_token_returns_none():
    org_id, entity_id = uuid.uuid4(), uuid.uuid4()
    assert validate_attachment_token("not-a-token", org_id, entity_id) is None
    assert validate_attachment_token("", org_id, entity_id) is None


# ---------------------------------------------------------------------------
# Tamper helpers — operate on the decoded "payload.signature" so each mutation
# is a *guaranteed* real change (avoids the base64 "unused trailing bits"
# corner case where a single ciphertext-char flip can decode unchanged).
# ---------------------------------------------------------------------------


def _decode(token: str) -> str:
    padded = token + "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode()


def _encode(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _flip_hex_char(c: str) -> str:
    return "0" if c != "0" else "1"


def _tamper_signature(token: str) -> str:
    """Flip the last character of the hex signature, then re-encode."""
    raw = _decode(token)
    payload, sep, sig = raw.rpartition(".")
    assert sep == "." and sig, f"unexpected token shape: {raw!r}"
    tampered_sig = sig[:-1] + _flip_hex_char(sig[-1])
    return _encode(f"{payload}{sep}{tampered_sig}")


def _tamper_payload(token: str) -> str:
    """Append a byte to the payload (keeping the old signature), re-encode.

    The recomputed HMAC over the changed payload will not match the retained
    signature, so validation must fail.
    """
    raw = _decode(token)
    payload, sep, sig = raw.rpartition(".")
    assert sep == "." and sig, f"unexpected token shape: {raw!r}"
    return _encode(f"{payload}X{sep}{sig}")


# ---------------------------------------------------------------------------
# Hypothesis strategies — id shapes constrained to the real input space.
#   * UUIDs are how org/entity ids appear in practice.
#   * Integers and strings broaden coverage.
#   * The payload is ":"-delimited and split into exactly four fields, so
#     string ids must not themselves contain ":". (Real ids never do.)
# ---------------------------------------------------------------------------

_id_strategy = st.one_of(
    st.uuids(),
    st.integers(min_value=0, max_value=2**63 - 1),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="-_.",
        ),
        min_size=1,
        max_size=24,
    ),
)


# ---------------------------------------------------------------------------
# Property 3 — Attachment-token validation is entity- and org-scoped.
# ---------------------------------------------------------------------------


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    org_id=_id_strategy,
    entity_id=_id_strategy,
    other_org=_id_strategy,
    other_entity=_id_strategy,
    kind=st.sampled_from(_KINDS),
    future_seconds=st.integers(min_value=120, max_value=30 * 24 * 3600),
    past_seconds=st.integers(min_value=60, max_value=30 * 24 * 3600),
)
def test_attachment_token_validation_is_entity_and_org_scoped(
    org_id,
    entity_id,
    other_org,
    other_entity,
    kind: str,
    future_seconds: int,
    past_seconds: int,
):
    """Feature: send-email-modal, Property 3: Attachment-token validation is
    entity- and org-scoped.

    A token validates (returns the original kind) only with the same
    org_id/entity_id and a future expiry; it is rejected (None) for any
    different org/entity, a tampered signature, a tampered payload, or a past
    expiry.

    **Validates: Requirements 7.6**
    """
    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=future_seconds)

    # ---- 1. Round-trip: same org + entity + future expiry -> original kind.
    token = build_attachment_token(org_id, entity_id, kind, future)
    assert validate_attachment_token(token, org_id, entity_id) == kind

    # ---- 2. Wrong org -> None (only meaningful when the string forms differ,
    # since validation compares the stringified ids).
    if str(other_org) != str(org_id):
        assert validate_attachment_token(token, other_org, entity_id) is None

    # ---- 3. Wrong entity -> None.
    if str(other_entity) != str(entity_id):
        assert validate_attachment_token(token, org_id, other_entity) is None

    # ---- 3b. Both wrong -> None.
    if str(other_org) != str(org_id) and str(other_entity) != str(entity_id):
        assert validate_attachment_token(token, other_org, other_entity) is None

    # ---- 4. Past expiry -> None even with the correct org + entity.
    past = now - timedelta(seconds=past_seconds)
    expired_token = build_attachment_token(org_id, entity_id, kind, past)
    assert validate_attachment_token(expired_token, org_id, entity_id) is None

    # ---- 5a. Tampered signature -> None.
    sig_tampered = _tamper_signature(token)
    assume(sig_tampered != token)
    assert validate_attachment_token(sig_tampered, org_id, entity_id) is None

    # ---- 5b. Tampered payload -> None.
    payload_tampered = _tamper_payload(token)
    assume(payload_tampered != token)
    assert validate_attachment_token(payload_tampered, org_id, entity_id) is None


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    org_id=_id_strategy,
    entity_id=_id_strategy,
    kind=st.sampled_from(_KINDS),
)
def test_mint_uses_default_ttl_window(org_id, entity_id, kind: str):
    """A freshly minted token (default 30-min TTL) validates immediately, and
    the TTL constant is the documented 30 minutes.

    **Validates: Requirements 7.6**
    """
    assert ATTACHMENT_TOKEN_TTL == timedelta(minutes=30)
    token = mint_attachment_token(org_id, entity_id, kind)
    assert validate_attachment_token(token, org_id, entity_id) == kind
