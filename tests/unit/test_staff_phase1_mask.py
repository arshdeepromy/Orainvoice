"""Unit + property tests for staff PII masking helpers.

Covers ``mask_ird``, ``mask_bank_account``, ``is_masked_ird`` and
``is_masked_bank`` from ``app/modules/staff/security.py``.

The property tests are the primary safety net: for any input string,
``mask_ird`` must never expose more than 3 digits, and ``mask_bank_account``
must never expose more than 4 digits — those bounds are what the masked
output is designed to enforce.

**Validates: Requirements R2** (Phase 1 Staff Management — IRD/bank masking).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.security import (
    is_masked_bank,
    is_masked_ird,
    mask_bank_account,
    mask_ird,
)


# ---------------------------------------------------------------------------
# Unit tests — concrete examples + edge cases
# ---------------------------------------------------------------------------


class TestMaskIrdExamples:
    """Concrete examples for ``mask_ird``."""

    def test_none_returns_none(self):
        assert mask_ird(None) is None

    def test_empty_string_returns_none(self):
        assert mask_ird("") is None

    def test_whitespace_only_returns_no_digit_placeholder(self):
        # No digits → fewer than 3 → all-stars placeholder.
        assert mask_ird("   ") == "***"

    def test_one_digit_returns_no_digit_placeholder(self):
        assert mask_ird("9") == "***"

    def test_two_digits_returns_no_digit_placeholder(self):
        assert mask_ird("99") == "***"

    def test_three_digits_returns_three_digit_suffix(self):
        assert mask_ird("123") == "***123"

    def test_typical_ird_returns_last_three(self):
        # Canonical NZ IRD format with hyphens, 9 digits.
        assert mask_ird("123-456-789") == "***789"

    def test_strips_non_digits(self):
        assert mask_ird("IRD: 12 34 56 789!") == "***789"


class TestMaskBankAccountExamples:
    """Concrete examples for ``mask_bank_account``."""

    def test_none_returns_none(self):
        assert mask_bank_account(None) is None

    def test_empty_string_returns_none(self):
        assert mask_bank_account("") is None

    def test_no_digits_returns_no_digit_placeholder(self):
        assert mask_bank_account("XX-XXXX-XXXXXXXX-XX") == "**-****-****-**"

    def test_three_digits_returns_no_digit_placeholder(self):
        # Fewer than 4 digits → no-digit placeholder.
        assert mask_bank_account("123") == "**-****-****-**"

    def test_four_digits_returns_canonical_mask(self):
        # ``digits[-4:-2]`` of "1234" is "12".
        assert mask_bank_account("1234") == "**-****-****12-**"

    def test_typical_nz_bank_account(self):
        # 02-1234-5678901-23: digits "0212345678901" + "23" = ...
        # Last 4 digits are "0123", -4:-2 slice is "01".
        result = mask_bank_account("02-1234-56789012-23")
        # 16 digits → digits[-4:-2] is digits at index -4 and -3.
        # The string has digits: 0,2,1,2,3,4,5,6,7,8,9,0,1,2,2,3 (16 digits)
        # Last 4 = "1223", slice [-4:-2] = "12".
        assert result == "**-****-****12-**"


class TestIsMaskedIrd:
    """Concrete examples for ``is_masked_ird`` round-trip detection."""

    def test_none_is_not_masked(self):
        assert is_masked_ird(None) is False

    def test_empty_string_is_not_masked(self):
        assert is_masked_ird("") is False

    def test_plaintext_ird_is_not_masked(self):
        assert is_masked_ird("123-456-789") is False

    def test_three_digit_mask_round_trips(self):
        assert is_masked_ird("***789") is True

    def test_four_star_mask_round_trips(self):
        # ``mask_ird`` always emits exactly 3 stars, but legacy logs may
        # have used a longer prefix. The regex tolerates 1+ stars.
        assert is_masked_ird("****789") is True

    def test_no_digit_placeholder_is_not_full_mask(self):
        # ``"***"`` has no digits — regex requires at least 2 digits, so
        # this is treated as "skip detection failed, plaintext path".
        # That's fine: the service wouldn't overwrite ciphertext with
        # ``"***"`` anyway because the value is empty after digit-strip.
        assert is_masked_ird("***") is False

    def test_strips_surrounding_whitespace(self):
        assert is_masked_ird("  ***789  ") is True


class TestIsMaskedBank:
    """Concrete examples for ``is_masked_bank``."""

    def test_none_is_not_masked(self):
        assert is_masked_bank(None) is False

    def test_empty_string_is_not_masked(self):
        assert is_masked_bank("") is False

    def test_plaintext_bank_is_not_masked(self):
        assert is_masked_bank("02-1234-56789012-23") is False

    def test_canonical_mask_round_trips(self):
        assert is_masked_bank("**-****-****12-**") is True

    def test_strips_surrounding_whitespace(self):
        assert is_masked_bank("  **-****-****12-**  ") is True


# ---------------------------------------------------------------------------
# Property tests — bound-on-leak invariants over arbitrary input
# ---------------------------------------------------------------------------


@given(plaintext=st.text(max_size=64))
@settings(max_examples=300, deadline=None)
def test_mask_ird_never_leaks_more_than_three_digits(plaintext: str) -> None:
    """Property: for any input string, ``mask_ird`` output contains ≤ 3 digits.

    This is the core privacy guarantee — regardless of what the caller
    passes (a real IRD, a malformed string, embedded ASCII art, etc.),
    the masked output must never expose more than the trailing 3 digits.
    """
    masked = mask_ird(plaintext)
    if masked is None:
        # ``None``/empty inputs short-circuit; nothing to leak.
        return
    digit_count = sum(1 for c in masked if c.isdigit())
    assert digit_count <= 3, (
        f"mask_ird leaked {digit_count} digits from {plaintext!r}: {masked!r}"
    )


@given(plaintext=st.text(max_size=64))
@settings(max_examples=300, deadline=None)
def test_mask_bank_account_never_leaks_more_than_four_digits(
    plaintext: str,
) -> None:
    """Property: for any input string, ``mask_bank_account`` output contains ≤ 4 digits.

    The canonical mask leaks exactly 2 digits (``digits[-4:-2]``) — this
    test allows up to 4 to give the implementation room to evolve the
    format slightly without weakening the privacy bound.
    """
    masked = mask_bank_account(plaintext)
    if masked is None:
        return
    digit_count = sum(1 for c in masked if c.isdigit())
    assert digit_count <= 4, (
        f"mask_bank_account leaked {digit_count} digits from {plaintext!r}: {masked!r}"
    )


@given(plaintext=st.text(max_size=64))
@settings(max_examples=300, deadline=None)
def test_mask_ird_output_is_round_trippable(plaintext: str) -> None:
    """Property: when ``mask_ird`` returns a non-trivial mask, ``is_masked_ird`` agrees.

    A "non-trivial mask" means the input had at least 3 ASCII digits —
    that's the case where the service actually needs the round-trip
    detection to work (so it can skip the field on update). For inputs
    with fewer ASCII digits, the mask is the no-digit placeholder
    ``"***"`` which deliberately fails ``is_masked_ird`` because the
    value is essentially empty plaintext from the service's point of
    view.

    Only ASCII digits are counted because :func:`mask_ird` itself only
    counts ASCII (Unicode "digit" glyphs like superscripts ``¹`` are
    not numerals you'd find in an IRD number on a tax form).
    """
    masked = mask_ird(plaintext)
    digits = "".join(c for c in plaintext if "0" <= c <= "9")
    if len(digits) >= 3:
        assert is_masked_ird(masked) is True, (
            f"is_masked_ird({masked!r}) was False for plaintext {plaintext!r}"
        )


@given(plaintext=st.text(max_size=64))
@settings(max_examples=300, deadline=None)
def test_mask_bank_account_output_is_round_trippable(plaintext: str) -> None:
    """Property: when ``mask_bank_account`` returns a non-trivial mask, ``is_masked_bank`` agrees.

    Same ASCII-only semantics as :func:`test_mask_ird_output_is_round_trippable`.
    """
    masked = mask_bank_account(plaintext)
    digits = "".join(c for c in plaintext if "0" <= c <= "9")
    if len(digits) >= 4:
        assert is_masked_bank(masked) is True, (
            f"is_masked_bank({masked!r}) was False for plaintext {plaintext!r}"
        )
