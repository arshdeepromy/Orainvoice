"""Property-based tests for the pure esignatures send validators (task 4.2).

The functions under test live in ``app.modules.esignatures.validation`` and are
all **pure** (no DB, no network, no global state):

  * ``is_pdf(data)`` — content sniff on the leading ``%PDF`` magic bytes (R3.4).
  * ``validate_recipients(recipients)`` — atomic, all-or-nothing recipient
    validation: rejects the empty list (code ``no_recipients``) and identifies
    the FIRST recipient with a syntactically invalid email
    (code ``invalid_recipient_email``); ``ok=True`` only when there is at least
    one recipient and every email is valid (R3.3, R4.2, R4.3, R4.6).

This module exercises the **pure-core portion** of Property 8 — the send
validation is atomic (any invalid email OR an empty list rejects the whole
send) and side-effect-free (pure, deterministic, no I/O).

# Feature: esignature-integration, Property 8: Send validation is atomic and side-effect-free

**Validates: Requirements 3.3, 3.4, 4.2, 4.3, 4.6**
"""

from __future__ import annotations

import copy

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.validation import (
    CODE_INVALID_RECIPIENT_EMAIL,
    CODE_NO_RECIPIENTS,
    is_pdf,
    is_valid_email,
    validate_recipients,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A syntactically VALID email per the validator's regex:
#   ^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$
_LOCAL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-"
_DOMAIN_LABEL_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
_TLD_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@st.composite
def valid_emails(draw) -> str:
    """Generate addresses that are guaranteed syntactically valid."""
    local = draw(st.text(alphabet=_LOCAL_CHARS, min_size=1, max_size=12))
    label = draw(st.text(alphabet=_DOMAIN_LABEL_CHARS, min_size=1, max_size=10))
    tld = draw(st.text(alphabet=_TLD_CHARS, min_size=2, max_size=6))
    return f"{local}@{label}.{tld}"


# Strings that are NOT syntactically valid emails. We sample from clearly
# malformed shapes and assert the validator agrees (filtering out any rare
# accidental valid value keeps the generator honest).
_invalid_email_shapes = st.one_of(
    st.just(""),
    st.just("   "),
    st.just("not-an-email"),
    st.just("missing@domain"),  # no dotted TLD
    st.just("@example.com"),  # empty local part
    st.just("a@b.c"),  # TLD too short
    st.just("spaces in@example.com"),
    st.just("two@@example.com"),
    st.text(alphabet="abc ", min_size=0, max_size=8),  # no '@'
).filter(lambda s: not is_valid_email(s))


@st.composite
def recipients_with_invalid(draw):
    """A recipient list with >=1 invalid email; returns (recipients, first_bad_index)."""
    n = draw(st.integers(min_value=1, max_value=6))
    # Decide which positions are invalid (at least one).
    invalid_flags = draw(
        st.lists(st.booleans(), min_size=n, max_size=n).filter(lambda fs: any(fs))
    )
    recipients = []
    first_bad = None
    for i, is_bad in enumerate(invalid_flags):
        if is_bad:
            email = draw(_invalid_email_shapes)
            if first_bad is None:
                first_bad = i
        else:
            email = draw(valid_emails())
        recipients.append({"name": f"R{i}", "email": email})
    return recipients, first_bad


@st.composite
def all_valid_recipients(draw):
    """A non-empty recipient list where every email is syntactically valid."""
    n = draw(st.integers(min_value=1, max_value=6))
    return [
        {"name": draw(st.text(max_size=10)), "email": draw(valid_emails())}
        for _ in range(n)
    ]


# ---------------------------------------------------------------------------
# Property 8 (pure core) — recipient validation is atomic
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(all_valid_recipients())
def test_nonempty_all_valid_is_accepted(recipients):
    """>=1 recipient AND every email valid => ok=True (no rejection code)."""
    result = validate_recipients(recipients)
    assert result.ok is True
    assert result.code is None


@settings(max_examples=200)
@given(recipients_with_invalid())
def test_any_invalid_email_rejects_and_identifies_first_offender(payload):
    """ANY invalid email rejects the WHOLE send and names the FIRST offender."""
    recipients, first_bad = payload
    result = validate_recipients(recipients)
    assert result.ok is False
    assert result.code == CODE_INVALID_RECIPIENT_EMAIL
    # Atomic: the first offending recipient is identified, not a later one.
    assert result.index == first_bad


@settings(max_examples=50)
@given(st.one_of(st.just([]), st.none()))
def test_empty_or_none_is_rejected_as_no_recipients(recipients):
    """An empty/None recipient list is rejected with the no_recipients code."""
    result = validate_recipients(recipients)
    assert result.ok is False
    assert result.code == CODE_NO_RECIPIENTS


@settings(max_examples=200)
@given(st.lists(st.dictionaries(st.just("email"), valid_emails(), min_size=1, max_size=1)
                | st.fixed_dictionaries({"name": st.text(max_size=8), "email": valid_emails()}),
                max_size=6))
def test_ok_iff_nonempty_and_all_emails_valid(recipients):
    """The core invariant: ok == (nonempty AND every email syntactically valid)."""
    result = validate_recipients(recipients)
    expected_ok = bool(recipients) and all(
        is_valid_email(r.get("email")) for r in recipients
    )
    assert result.ok is expected_ok


# ---------------------------------------------------------------------------
# Property 8 (pure core) — validation is deterministic and side-effect-free
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(st.one_of(recipients_with_invalid().map(lambda p: p[0]), all_valid_recipients()))
def test_validation_is_deterministic_and_does_not_mutate_input(recipients):
    """Same input => same result, and the input list is never mutated."""
    snapshot = copy.deepcopy(recipients)
    r1 = validate_recipients(recipients)
    r2 = validate_recipients(recipients)
    # Deterministic: identical outcome across repeated calls (pure function).
    assert (r1.ok, r1.code, r1.index, r1.name) == (r2.ok, r2.code, r2.index, r2.name)
    # Side-effect-free: the caller's list is untouched.
    assert recipients == snapshot


# ---------------------------------------------------------------------------
# Property 8 (pure core) — is_pdf is true only for the %PDF magic prefix
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(st.binary(max_size=64))
def test_is_pdf_true_iff_starts_with_pdf_magic(data):
    """is_pdf(data) is True exactly when data begins with b'%PDF'."""
    assert is_pdf(data) is data.startswith(b"%PDF")


@settings(max_examples=200)
@given(st.binary(min_size=0, max_size=32))
def test_pdf_magic_prefix_is_always_detected(suffix):
    """Any byte string prefixed with the magic marker is detected as a PDF."""
    assert is_pdf(b"%PDF" + suffix) is True


@settings(max_examples=200)
@given(st.binary(max_size=64).filter(lambda b: not b.startswith(b"%PDF")))
def test_non_pdf_bytes_are_rejected(data):
    """Bytes that do not start with the magic marker are never PDFs."""
    assert is_pdf(data) is False
