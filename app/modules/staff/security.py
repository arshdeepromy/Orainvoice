"""Masking helpers for staff PII (IRD number, bank account).

These helpers produce display-safe representations of sensitive numbers so
the API response and audit log never echo plaintext identifiers. Used by
``StaffService`` on outbound serialisation, and by inbound update validators
to detect when the client is re-submitting an already-masked value (in which
case the field is skipped on save so we don't overwrite real ciphertext with
the mask string).

Design reference: ``.kiro/specs/staff-management-p1/design.md`` §3.4.
"""

from __future__ import annotations

import re

# Matches the IRD output of ``mask_ird``: 1+ asterisks followed by 2-4 digits.
# The 2-4 range exists so payslips that show only the last 2 digits (older
# formats still in the wild) round-trip through ``is_masked_ird`` cleanly.
_MASKED_IRD_RE = re.compile(r"^\*+\d{2,4}$")

# Matches the bank-account output of ``mask_bank_account``. Two shapes are
# accepted:
#   ``**-****-****NN-**`` — the canonical 4-segment NZ bank account mask
#   ``****NN-**``        — a flatter legacy mask still present in some logs
_MASKED_BANK_RE = re.compile(r"^\*\*-\*+-\*+\d{2}-\*+$|^\*+\d{2}-\*+$")


def mask_ird(plaintext: str | None) -> str | None:
    """Mask an IRD number for outbound display.

    Returns ``None`` when the input is empty/None. When the input has fewer
    than 3 ASCII digits, returns ``"***"`` (no digits leaked). Otherwise
    returns ``"***" + <last 3 ASCII digits>``.

    Only ASCII digits 0-9 are counted; Unicode "digit" characters like
    superscripts (``¹``) or other-script digits are stripped because the
    mask output must round-trip through ``is_masked_ird``'s ``\\d`` regex
    (which in Python's default mode matches Unicode but the round-trip
    property holds reliably only for ASCII).
    """
    if not plaintext:
        return None
    digits = "".join(c for c in plaintext if "0" <= c <= "9")
    if len(digits) < 3:
        return "***"
    return "***" + digits[-3:]


def mask_bank_account(plaintext: str | None) -> str | None:
    """Mask a NZ bank account number for outbound display.

    Returns ``None`` when the input is empty/None. When the input has fewer
    than 4 ASCII digits, returns the no-digit placeholder
    ``**-****-****-**``. Otherwise returns ``**-****-****NN-**`` where
    ``NN`` are the 4th-and-3rd from-last digits of the input (the
    suffix-suffix segment of the canonical NZ 16-digit form).

    Only ASCII digits 0-9 are counted (see :func:`mask_ird` for rationale).
    """
    if not plaintext:
        return None
    digits = "".join(c for c in plaintext if "0" <= c <= "9")
    if len(digits) < 4:
        return "**-****-****-**"
    return f"**-****-****{digits[-4:-2]}-**"


def is_masked_ird(value: str | None) -> bool:
    """Return True when ``value`` looks like an output of :func:`mask_ird`.

    Used by inbound validators to skip a field when the client is re-posting
    the masked value they were just shown (rather than typing a new IRD).
    """
    return bool(value and _MASKED_IRD_RE.match(value.strip()))


def is_masked_bank(value: str | None) -> bool:
    """Return True when ``value`` looks like an output of :func:`mask_bank_account`."""
    return bool(value and _MASKED_BANK_RE.match(value.strip()))
