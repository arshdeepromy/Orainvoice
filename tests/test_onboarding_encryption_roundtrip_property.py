"""Property-based test for IRD/bank encryption round-trip (Task 8.9).

Feature: staff-onboarding-link
Property 15: IRD and bank account encryption round-trip

After a successful onboarding submit, the IRD number and bank account number
are stored envelope-encrypted on ``staff_members``
(``ird_number_encrypted`` / ``bank_account_number_encrypted``). The submit
handler obtains those stored bytes by calling ``envelope_encrypt`` on the
validated plaintext (see ``app/modules/staff/public_router.py`` →
``onboarding_submit``, which mirrors ``StaffService.create_staff``).

This test exercises that encryption boundary **directly** — the tightest,
purest expression of Property 15's claim — for the full space of VALID IRD and
bank-account values:

1. **Ciphertext bytes are not the plaintext** — the stored bytes produced by
   ``envelope_encrypt`` do not contain the plaintext value (so a leaked column
   never reveals the secret in cleartext).
2. **Round-trip** — ``envelope_decrypt_str(envelope_encrypt(value)) == value``
   for every generated IRD / bank value, reproducing the original exactly.

The companion DB-backed test ``tests/test_onboarding_persist_identity_property.py``
(Property 14) already drives the real ``POST /api/v2/public/staff-onboarding/{token}``
endpoint and confirms the *stored columns* decrypt back to the submitted
values; this test isolates the encryption primitive itself across ≥100 valid
IRD/bank examples with no DB dependency.

Validates: Requirements 9.4
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.encryption import envelope_encrypt, envelope_decrypt_str


# ---------------------------------------------------------------------------
# Generators — VALID IRD / bank values (mirror the onboarding submit harness in
# tests/test_onboarding_persist_identity_property.py so the input space matches
# exactly what the validator accepts and the handler encrypts).
# ---------------------------------------------------------------------------


def _valid_ird() -> st.SearchStrategy[str]:
    """8- or 9-digit IRD strings (no separators)."""
    return st.one_of(
        st.text(alphabet="0123456789", min_size=8, max_size=8),
        st.text(alphabet="0123456789", min_size=9, max_size=9),
    )


def _valid_bank() -> st.SearchStrategy[str]:
    """Valid NZ bank account: 2-4-7-2 or 2-4-7-3 digit groups."""

    def _digits(n: int) -> st.SearchStrategy[str]:
        return st.integers(min_value=0, max_value=10**n - 1).map(
            lambda x: str(x).zfill(n)
        )

    return st.builds(
        lambda a, b, c, d: f"{a}-{b}-{c}-{d}",
        _digits(2),
        _digits(4),
        _digits(7),
        st.one_of(_digits(2), _digits(3)),
    )


# Either kind of secret exercises the same encryption boundary; sampling across
# both in one property keeps the IRD and bank claims under a single ≥100-example
# budget while covering every valid shape.
_secret_strategy = st.one_of(_valid_ird(), _valid_bank())


# ---------------------------------------------------------------------------
# Property 15: IRD and bank account encryption round-trip.
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(plaintext=_secret_strategy)
def test_ird_bank_encryption_round_trip(plaintext: str) -> None:
    """Property 15: IRD and bank account encryption round-trip.

    For any valid IRD / bank-account plaintext, the stored ciphertext bytes are
    not the plaintext, and ``envelope_decrypt_str`` reproduces the original
    value exactly.

    **Validates: Requirements 9.4**
    """
    stored = envelope_encrypt(plaintext)

    # Stored value is opaque ciphertext bytes, not the plaintext.
    assert isinstance(stored, bytes)
    assert len(stored) > 0
    assert plaintext.encode("utf-8") not in stored, (
        "stored ciphertext must not contain the plaintext secret in cleartext"
    )

    # Decryption reproduces the original submitted value exactly.
    assert envelope_decrypt_str(stored) == plaintext, (
        f"encryption round-trip failed: expected {plaintext!r}, "
        f"got {envelope_decrypt_str(stored)!r}"
    )
