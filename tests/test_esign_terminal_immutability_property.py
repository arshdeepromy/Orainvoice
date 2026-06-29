"""Property-based test for envelope-status terminal immutability (Task 3.2).

# Feature: esignature-integration, Property 9: Terminal statuses are immutable under non-void events

**Validates: Requirements 6.1, 6.6**

The pure function under test is
:func:`app.modules.esignatures.status.next_status`, the e-signature lifecycle
reducer. ``completed``, ``declined`` and ``voided`` are the terminal statuses
(:data:`app.modules.esignatures.status.TERMINAL_STATUSES`).

Property 9 (design): *for any* envelope already in a terminal status and *for
any* sequence of webhook events, the resulting status is unchanged. The reducer
expresses "unchanged" by returning ``None`` (no transition) — so for any
terminal ``current`` and any event the reducer MUST return ``None``.

The task focuses on non-void events, but terminal immutability holds for **all**
Documenso events including ``DOCUMENT_CANCELLED`` (a cancel only voids a
*non-terminal* envelope), so this test exercises the full event set plus
arbitrary unrecognised event strings, against arbitrary ``recipients_state``.
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
    EVENT_DOCUMENT_SENT,
    EVENT_DOCUMENT_VIEWED,
    TERMINAL_STATUSES,
    RecipientState,
    next_status,
)

# ---------------------------------------------------------------------------
# Hypothesis settings — pure, in-memory reducer (>= 100 examples).
# ---------------------------------------------------------------------------
PBT_SETTINGS = settings(max_examples=300, deadline=None)

# The three terminal statuses (completed / declined / voided).
terminal_status_st = st.sampled_from(sorted(TERMINAL_STATUSES))

# The real Documenso event names the reducer recognises (incl. DOCUMENT_SENT
# and the void event DOCUMENT_CANCELLED), plus arbitrary unrecognised event
# strings, so immutability is exercised across the entire event space.
_KNOWN_EVENTS = [
    EVENT_DOCUMENT_SENT,
    EVENT_DOCUMENT_OPENED,
    EVENT_DOCUMENT_VIEWED,
    EVENT_DOCUMENT_RECIPIENT_COMPLETED,
    EVENT_DOCUMENT_COMPLETED,
    EVENT_DOCUMENT_RECIPIENT_REJECTED,
    EVENT_DOCUMENT_CANCELLED,
]
event_st = st.one_of(st.sampled_from(_KNOWN_EVENTS), st.text())

# Arbitrary per-recipient signed/unsigned state (including absent/empty).
recipients_state_st = st.one_of(
    st.none(),
    st.lists(st.builds(RecipientState, signed=st.booleans()), max_size=8),
)


class TestTerminalImmutability:
    """Property 9 — terminal statuses never transition out.

    **Validates: Requirements 6.1, 6.6**
    """

    @given(
        current=terminal_status_st,
        event=event_st,
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_terminal_status_yields_no_transition(
        self, current, event, recipients_state
    ):
        """For any terminal status + any event, ``next_status`` returns ``None``.

        **Validates: Requirements 6.1, 6.6**
        """
        assert next_status(current, event, recipients_state) is None

    @given(
        current=terminal_status_st,
        events=st.lists(event_st, min_size=1, max_size=10),
        recipients_state=recipients_state_st,
    )
    @PBT_SETTINGS
    def test_terminal_status_immutable_over_event_sequences(
        self, current, events, recipients_state
    ):
        """Across a *sequence* of events the terminal status stays unchanged.

        Each event applied to the terminal status produces no transition, so the
        status remains exactly the terminal value it started in.

        **Validates: Requirements 6.1, 6.6**
        """
        status = current
        for event in events:
            result = next_status(status, event, recipients_state)
            assert result is None
            # No transition -> the status is unchanged for the next event.
            assert status == current
