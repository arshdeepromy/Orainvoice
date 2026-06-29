"""Property-based test for the Editable_State gate (task 16.2).

# Feature: esignature-field-placement, Property 18: Editable_State gate is exactly "sent and unsigned"

**Validates: Requirements 13.1, 13.4, 13.6**

The pure predicate under test is
:func:`app.modules.esignatures.field_validation.editable_state`. A sent
envelope's Field_Set may be edited in place only while the envelope is in the
Editable_State (R13.1):

    ``editable_state(status, recipients)`` is ``True``
        **iff** ``status == "sent"`` AND no recipient has signed.

Every other condition is a Non_Editable_State and returns ``False`` (R13.4,
R13.6):

* any non-``sent`` envelope status — ``draft``, ``viewed``,
  ``partially_signed``, ``completed``, ``declined``, ``voided``, ``error``; or
* a ``sent`` envelope where at least one recipient has signed.

The "signed" recipient_status value is aligned with ``status.py`` — the webhook
handler persists ``"signed"`` (alongside ``"pending"`` / ``"viewed"`` /
``"declined"``), so only ``"signed"`` (case/whitespace-insensitively) counts as
having signed.

This property generates arbitrary envelope statuses drawn from the full set of
8 :data:`EnvelopeStatus` values and recipient lists with varied
``recipient_status`` values, then asserts the biconditional against an
independent oracle. The function is pure and deterministic (no I/O), so it is
exercised directly over many generated inputs.
"""

from __future__ import annotations

from typing import get_args

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.field_validation import (
    SIGNED_RECIPIENT_STATUSES,
    editable_state,
)
from app.modules.esignatures.status import EnvelopeStatus

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure, in-memory predicate.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# The full set of 8 envelope statuses (mirrors the migration CHECK constraint).
ALL_STATUSES = list(get_args(EnvelopeStatus))
assert set(ALL_STATUSES) == {
    "draft",
    "sent",
    "viewed",
    "partially_signed",
    "completed",
    "declined",
    "voided",
    "error",
}

# A pool of recipient_status values: the canonical signed value, the other
# values the webhook handler writes, plus case/whitespace variants of "signed"
# (which must still count as signed) and some clearly-unsigned noise.
SIGNED_STATUS_VALUES = ["signed", "Signed", "SIGNED", "  signed  "]
UNSIGNED_STATUS_VALUES = ["pending", "viewed", "declined", "error", "", "sign", "completed"]
ALL_RECIPIENT_STATUSES = SIGNED_STATUS_VALUES + UNSIGNED_STATUS_VALUES


def _is_signed(status_value: str) -> bool:
    """Independent oracle mirroring the spec's signed-recipient rule."""
    return status_value.strip().lower() in SIGNED_RECIPIENT_STATUSES


# A recipient is either a mapping (the persisted-row shape the service uses) or
# an attribute-bearing object, both carrying a ``recipient_status``. Covering
# both shapes exercises the predicate's mapping/attribute accessor.
class _RecipientObj:
    def __init__(self, recipient_status: str) -> None:
        self.recipient_status = recipient_status


@st.composite
def recipients(draw):
    """Generate a recipient list (possibly empty) with varied signed states.

    Each recipient is randomly a dict or an attribute object so the predicate's
    accessor is exercised for both shapes.
    """
    values = draw(st.lists(st.sampled_from(ALL_RECIPIENT_STATUSES), max_size=6))
    result = []
    for value in values:
        if draw(st.booleans()):
            result.append({"recipient_status": value})
        else:
            result.append(_RecipientObj(value))
    return result


def _recipient_status_of(recipient) -> str:
    if isinstance(recipient, dict):
        return recipient["recipient_status"]
    return recipient.recipient_status


@given(status=st.sampled_from(ALL_STATUSES), recps=recipients())
@PBT_SETTINGS
def test_editable_state_is_exactly_sent_and_unsigned(status, recps):
    """Property 18: the gate is true iff status is ``sent`` AND nobody signed."""
    expected = status == "sent" and not any(
        _is_signed(_recipient_status_of(r)) for r in recps
    )

    assert editable_state(status, recps) is expected
