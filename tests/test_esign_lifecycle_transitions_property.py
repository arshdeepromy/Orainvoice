"""Property-based test for the e-signature status reducer (task 3.3).

# Feature: esignature-integration, Property 10: Lifecycle transitions are correct from non-terminal states

**Validates: Requirements 6.2, 6.3, 6.4, 6.5**

The pure function under test is
:func:`app.modules.esignatures.status.next_status`. From a *non-terminal*
envelope status (``draft`` / ``sent`` / ``viewed`` / ``partially_signed`` /
``error``) it maps the real Documenso webhook event names plus the per-recipient
signed/unsigned state to the next envelope status:

    DOCUMENT_OPENED / DOCUMENT_VIEWED      -> viewed              (R6.2)
    DOCUMENT_RECIPIENT_COMPLETED           -> partially_signed    (R6.3)
                                              (>= 1 recipient still unsigned)
                                           -> completed           (R6.4)
                                              (every recipient signed)
    DOCUMENT_COMPLETED                     -> completed           (R6.4)
    DOCUMENT_RECIPIENT_REJECTED            -> declined            (R6.5)
    DOCUMENT_CANCELLED                     -> voided              (R6.6)

``_all_signed`` semantics: an empty or ``None`` ``recipients_state`` is treated
as "not all signed", so a ``DOCUMENT_RECIPIENT_COMPLETED`` event with no known
recipient state stays at ``partially_signed`` rather than prematurely
completing.

The reducer is pure and deterministic (no I/O), so it is exercised directly over
many generated combinations of non-terminal status, event, and recipients list.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.esignatures.status import (
    EVENT_DOCUMENT_CANCELLED,
    EVENT_DOCUMENT_COMPLETED,
    EVENT_DOCUMENT_OPENED,
    EVENT_DOCUMENT_RECIPIENT_COMPLETED,
    EVENT_DOCUMENT_RECIPIENT_REJECTED,
    EVENT_DOCUMENT_VIEWED,
    RecipientState,
    next_status,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure, in-memory reducer.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# The five non-terminal statuses from which lifecycle transitions can occur.
NON_TERMINAL_STATUSES = ("draft", "sent", "viewed", "partially_signed", "error")

non_terminal_status_st = st.sampled_from(NON_TERMINAL_STATUSES)

recipient_st = st.builds(RecipientState, signed=st.booleans())

# An arbitrary recipients list (may be empty), plus None.
recipients_state_st = st.one_of(
    st.none(),
    st.lists(recipient_st, min_size=0, max_size=8),
)

# A non-empty recipients list with AT LEAST ONE unsigned recipient
# (a proper non-empty subset has signed) — the partially_signed case.
@st.composite
def recipients_with_unsigned(draw):
    others = draw(st.lists(recipient_st, min_size=0, max_size=7))
    # Guarantee at least one unsigned recipient somewhere in the list.
    unsigned = RecipientState(signed=False)
    insert_at = draw(st.integers(min_value=0, max_value=len(others)))
    return others[:insert_at] + [unsigned] + others[insert_at:]


# A non-empty recipients list where EVERY recipient has signed — completed case.
all_signed_recipients_st = st.lists(
    st.builds(RecipientState, signed=st.just(True)),
    min_size=1,
    max_size=8,
)


# ---------------------------------------------------------------------------
# Property 10 — lifecycle transitions from non-terminal states.
# ---------------------------------------------------------------------------
class TestLifecycleTransitions:
    """Property 10: Lifecycle transitions are correct from non-terminal states.

    **Validates: Requirements 6.2, 6.3, 6.4, 6.5**
    """

    @given(
        current=non_terminal_status_st,
        event=st.sampled_from([EVENT_DOCUMENT_OPENED, EVENT_DOCUMENT_VIEWED]),
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_opened_or_viewed_yields_viewed(self, current, event, recipients_state):
        """DOCUMENT_OPENED / DOCUMENT_VIEWED -> ``viewed`` (R6.2)."""
        assert next_status(current, event, recipients_state) == "viewed"

    @given(
        current=non_terminal_status_st,
        recipients_state=recipients_with_unsigned(),
    )
    @PBT_SETTINGS
    def test_recipient_completed_partial_yields_partially_signed(
        self, current, recipients_state
    ):
        """DOCUMENT_RECIPIENT_COMPLETED with >= 1 unsigned -> ``partially_signed`` (R6.3)."""
        result = next_status(
            current, EVENT_DOCUMENT_RECIPIENT_COMPLETED, recipients_state
        )
        assert result == "partially_signed"

    @given(
        current=non_terminal_status_st,
        recipients_state=st.one_of(st.none(), st.just([])),
    )
    @PBT_SETTINGS
    def test_recipient_completed_without_known_state_stays_partial(
        self, current, recipients_state
    ):
        """Empty/None recipients_state is "not all signed" -> ``partially_signed`` (R6.3)."""
        result = next_status(
            current, EVENT_DOCUMENT_RECIPIENT_COMPLETED, recipients_state
        )
        assert result == "partially_signed"

    @given(
        current=non_terminal_status_st,
        recipients_state=all_signed_recipients_st,
    )
    @PBT_SETTINGS
    def test_recipient_completed_all_signed_yields_completed(
        self, current, recipients_state
    ):
        """DOCUMENT_RECIPIENT_COMPLETED with every recipient signed -> ``completed`` (R6.4)."""
        result = next_status(
            current, EVENT_DOCUMENT_RECIPIENT_COMPLETED, recipients_state
        )
        assert result == "completed"

    @given(
        current=non_terminal_status_st,
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_document_completed_yields_completed(self, current, recipients_state):
        """DOCUMENT_COMPLETED -> ``completed`` regardless of recipients_state (R6.4).

        Covers the all-at-once and single-recipient cases with no intervening
        ``partially_signed``.
        """
        assert (
            next_status(current, EVENT_DOCUMENT_COMPLETED, recipients_state)
            == "completed"
        )

    @given(
        current=non_terminal_status_st,
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_recipient_rejected_yields_declined(self, current, recipients_state):
        """DOCUMENT_RECIPIENT_REJECTED -> ``declined`` (R6.5)."""
        assert (
            next_status(current, EVENT_DOCUMENT_RECIPIENT_REJECTED, recipients_state)
            == "declined"
        )

    @given(
        current=non_terminal_status_st,
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_document_cancelled_yields_voided(self, current, recipients_state):
        """DOCUMENT_CANCELLED from a non-terminal envelope -> ``voided`` (R6.6)."""
        assert (
            next_status(current, EVENT_DOCUMENT_CANCELLED, recipients_state)
            == "voided"
        )
