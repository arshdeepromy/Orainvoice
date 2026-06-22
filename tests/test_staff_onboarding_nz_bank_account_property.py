"""Property-based tests for NZ bank account format validation (Task 3.4).

Feature: staff-onboarding-link
Property 8: NZ bank account format validation

Exercises ``validate_nz_bank_account`` from
``app.modules.staff.onboarding_validation`` across many generated inputs:

- well-formed 2-4-7-2 and 2-4-7-3 account numbers (optionally surrounded by
  whitespace, which the validator strips) MUST be accepted;
- malformed strings — wrong segment lengths, missing hyphens, embedded
  non-digit characters, and the empty string — MUST be rejected;
- non-string inputs MUST be rejected without raising.

Validates: Requirements 5.2
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import validate_nz_bank_account

# Mirror of the validator's pattern, used only to *construct* guaranteed-valid
# and guaranteed-invalid examples in the generators (not to assert behaviour).
_NZ_BANK_ACCOUNT_RE = re.compile(r"^\d{2}-\d{4}-\d{7}-\d{2,3}$")

_VALID_SEGMENT_LENGTHS = {(2, 4, 7, 2), (2, 4, 7, 3)}


def _digits(n: int) -> st.SearchStrategy[str]:
    """A strategy producing an ``n``-digit numeric string."""
    return st.text(alphabet="0123456789", min_size=n, max_size=n)


# ---------------------------------------------------------------------------
# Valid generators: 2-4-7-2 and 2-4-7-3 formatted account numbers
# ---------------------------------------------------------------------------

@st.composite
def valid_bank_accounts(draw: st.DrawFn) -> str:
    """Build a well-formed NZ bank account string (2-4-7-2 or 2-4-7-3)."""
    suffix_len = draw(st.sampled_from([2, 3]))
    bank = draw(_digits(2))
    branch = draw(_digits(4))
    account = draw(_digits(7))
    suffix = draw(_digits(suffix_len))
    return f"{bank}-{branch}-{account}-{suffix}"


@st.composite
def valid_bank_accounts_with_padding(draw: st.DrawFn) -> str:
    """A valid account number wrapped in outer whitespace (validator strips it)."""
    core = draw(valid_bank_accounts())
    lead = draw(st.text(alphabet=" \t\n\r", max_size=4))
    trail = draw(st.text(alphabet=" \t\n\r", max_size=4))
    return f"{lead}{core}{trail}"


# ---------------------------------------------------------------------------
# Malformed generators
# ---------------------------------------------------------------------------

@st.composite
def wrong_segment_lengths(draw: st.DrawFn) -> str:
    """Four hyphen-joined digit groups whose lengths are NOT a valid combo."""
    lengths = draw(
        st.tuples(
            st.integers(min_value=1, max_value=9),
            st.integers(min_value=1, max_value=9),
            st.integers(min_value=1, max_value=9),
            st.integers(min_value=1, max_value=9),
        ).filter(lambda t: t not in _VALID_SEGMENT_LENGTHS)
    )
    segments = [draw(_digits(n)) for n in lengths]
    return "-".join(segments)


@st.composite
def missing_hyphens(draw: st.DrawFn) -> str:
    """Valid digit segments joined with the wrong number of hyphens (or none)."""
    bank = draw(_digits(2))
    branch = draw(_digits(4))
    account = draw(_digits(7))
    suffix = draw(_digits(draw(st.sampled_from([2, 3]))))
    parts = [bank, branch, account, suffix]
    # Join with a separator that is never a single hyphen between every pair.
    sep = draw(st.sampled_from(["", " ", "--", "_", "/"]))
    return sep.join(parts)


@st.composite
def non_digit_corrupted(draw: st.DrawFn) -> str:
    """A valid account number with one character replaced by a letter."""
    core = draw(valid_bank_accounts())
    idx = draw(st.integers(min_value=0, max_value=len(core) - 1))
    letter = draw(st.text(alphabet="abcdefghijkABCDEFGHIJK", min_size=1, max_size=1))
    return core[:idx] + letter + core[idx + 1 :]


malformed_bank_accounts = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", max_size=5),  # whitespace-only → empty after strip
    wrong_segment_lengths(),
    missing_hyphens(),
    non_digit_corrupted(),
)


# ---------------------------------------------------------------------------
# Property 8: NZ bank account format validation
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(account=valid_bank_accounts())
def test_valid_nz_bank_accounts_accepted(account: str):
    """Every well-formed 2-4-7-2 / 2-4-7-3 account number is accepted.

    **Validates: Requirements 5.2**
    """
    assert validate_nz_bank_account(account) is True, (
        f"Expected valid account {account!r} to be accepted"
    )


@settings(max_examples=100)
@given(account=valid_bank_accounts_with_padding())
def test_valid_nz_bank_accounts_with_outer_whitespace_accepted(account: str):
    """Outer whitespace is stripped, so a padded valid number is still accepted.

    **Validates: Requirements 5.2**
    """
    assert validate_nz_bank_account(account) is True, (
        f"Expected padded valid account {account!r} to be accepted"
    )


@settings(max_examples=200)
@given(value=malformed_bank_accounts)
def test_malformed_nz_bank_accounts_rejected(value: str):
    """Malformed strings are rejected by the validator.

    The generators construct strings that are structurally invalid; this guard
    additionally skips the (vanishingly unlikely) case where a generator emits
    something that, after stripping, happens to match the NZ pattern.

    **Validates: Requirements 5.2**
    """
    if _NZ_BANK_ACCOUNT_RE.fullmatch(value.strip()):
        return  # not actually malformed after stripping — skip
    assert validate_nz_bank_account(value) is False, (
        f"Expected malformed value {value!r} to be rejected"
    )


@settings(max_examples=100)
@given(
    value=st.one_of(
        st.none(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.binary(max_size=20),
        st.lists(st.integers(), max_size=5),
    )
)
def test_non_string_inputs_rejected(value: object):
    """Non-string inputs are rejected without raising.

    **Validates: Requirements 5.2**
    """
    assert validate_nz_bank_account(value) is False, (
        f"Expected non-string input {value!r} to be rejected"
    )
