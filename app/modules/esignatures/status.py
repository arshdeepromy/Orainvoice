"""Pure envelope-status reducer for the e-signature lifecycle (R6).

This module is intentionally **pure**: it performs no I/O (no DB, no network, no
logging) so the envelope lifecycle rules can be exercised directly by
property-based tests (Tasks 3.2 / 3.3). The single entry point is
:func:`next_status`, which maps a *current* envelope status plus an inbound
Documenso webhook *event* (and the recipients' signed/unsigned state) to the
*next* envelope status, or ``None`` when no transition should occur.

The status literals here are kept consistent with the ``esign_envelopes`` table
``ck_esign_envelopes_status`` CHECK constraint (migration ``0232``) and with the
Pydantic schemas:

    draft, sent, viewed, partially_signed, completed, declined, voided, error

``completed``, ``declined`` and ``voided`` are **terminal** — once an envelope
reaches a terminal status no subsequent event transitions it out of that status
(R6.6 / R6.7). ``error`` is **not** terminal (a failed send can be voided/retried).

Transitions are driven by the **real** Documenso webhook event names (the
payload carries ``{ event, payload: { id, status, recipients[...] }, createdAt }``
and has no native event id):

    DOCUMENT_OPENED / DOCUMENT_VIEWED      -> viewed              (R6.2)
    DOCUMENT_RECIPIENT_COMPLETED           -> partially_signed    (R6.3)
                                              (or completed when every recipient
                                              has signed)
    DOCUMENT_COMPLETED                     -> completed           (R6.4)
    DOCUMENT_RECIPIENT_REJECTED            -> declined            (R6.5)
    DOCUMENT_CANCELLED                     -> voided              (R6.6)

The signed/unsigned state is read from ``recipients_state`` (derived from the
webhook payload's ``recipients[...]`` array) rather than a synthetic
"all signed" boolean, because that distinction is exactly what separates
``partially_signed`` from ``completed`` on a ``DOCUMENT_RECIPIENT_COMPLETED``
event (R6.3 / R6.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

__all__ = [
    "EnvelopeStatus",
    "TERMINAL_STATUSES",
    "RecipientState",
    "next_status",
    # Documenso event-name constants
    "EVENT_DOCUMENT_SENT",
    "EVENT_DOCUMENT_OPENED",
    "EVENT_DOCUMENT_VIEWED",
    "EVENT_DOCUMENT_RECIPIENT_COMPLETED",
    "EVENT_DOCUMENT_COMPLETED",
    "EVENT_DOCUMENT_RECIPIENT_REJECTED",
    "EVENT_DOCUMENT_CANCELLED",
]

# ---------------------------------------------------------------------------
# Status type — the 8 envelope statuses (mirrors the migration CHECK constraint).
# ---------------------------------------------------------------------------
EnvelopeStatus = Literal[
    "draft",
    "sent",
    "viewed",
    "partially_signed",
    "completed",
    "declined",
    "voided",
    "error",
]

#: The terminal statuses. Once an envelope is in one of these, ``next_status``
#: returns ``None`` for every event (R6.6 / R6.7).
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "declined", "voided"})

# ---------------------------------------------------------------------------
# Documenso webhook event names (uppercase, verbatim from Documenso).
# ---------------------------------------------------------------------------
EVENT_DOCUMENT_SENT = "DOCUMENT_SENT"
EVENT_DOCUMENT_OPENED = "DOCUMENT_OPENED"
EVENT_DOCUMENT_VIEWED = "DOCUMENT_VIEWED"
EVENT_DOCUMENT_RECIPIENT_COMPLETED = "DOCUMENT_RECIPIENT_COMPLETED"
EVENT_DOCUMENT_COMPLETED = "DOCUMENT_COMPLETED"
EVENT_DOCUMENT_RECIPIENT_REJECTED = "DOCUMENT_RECIPIENT_REJECTED"
EVENT_DOCUMENT_CANCELLED = "DOCUMENT_CANCELLED"


@dataclass(frozen=True)
class RecipientState:
    """Per-recipient signed/unsigned state, derived from the webhook payload's
    ``recipients[...]`` array.

    Only the ``signed`` flag matters to the reducer: it distinguishes
    ``partially_signed`` (at least one recipient still unsigned) from
    ``completed`` (every recipient has signed) on a
    ``DOCUMENT_RECIPIENT_COMPLETED`` event.
    """

    signed: bool


def _all_signed(recipients_state: Optional[Iterable[RecipientState]]) -> bool:
    """Return ``True`` only when there is at least one recipient and **every**
    recipient has signed.

    An empty or absent ``recipients_state`` cannot prove completion, so it is
    treated as "not all signed" (which keeps a ``DOCUMENT_RECIPIENT_COMPLETED``
    event at ``partially_signed`` rather than prematurely completing).
    """
    if recipients_state is None:
        return False
    states = list(recipients_state)
    if not states:
        return False
    return all(r.signed for r in states)


def next_status(
    current: EnvelopeStatus,
    event: str,
    recipients_state: Optional[Iterable[RecipientState]] = None,
) -> Optional[EnvelopeStatus]:
    """Compute the next envelope status for an inbound Documenso event.

    Pure function — no I/O. Returns the next :data:`EnvelopeStatus`, or ``None``
    when the event should not change the envelope's status.

    Args:
        current: The envelope's current status.
        event: The Documenso webhook event name (e.g. ``DOCUMENT_COMPLETED``).
        recipients_state: Per-recipient signed/unsigned state from the webhook
            payload's ``recipients[...]`` array. Used only to distinguish
            ``partially_signed`` from ``completed`` on a
            ``DOCUMENT_RECIPIENT_COMPLETED`` event.

    Returns:
        The next status, or ``None`` when no transition applies.

    Behaviour:
        * **Terminal immutability (R6.6 / R6.7):** if ``current`` is terminal
          (``completed`` / ``declined`` / ``voided``), returns ``None`` for
          every event — terminal envelopes never transition out, and a
          ``DOCUMENT_CANCELLED`` only voids a *non-terminal* envelope.
        * ``DOCUMENT_OPENED`` / ``DOCUMENT_VIEWED`` -> ``viewed`` (R6.2).
        * ``DOCUMENT_RECIPIENT_COMPLETED`` -> ``partially_signed`` while at least
          one recipient is still unsigned; ``completed`` once every recipient has
          signed (R6.3 / R6.4).
        * ``DOCUMENT_COMPLETED`` -> ``completed``, including the all-at-once and
          single-recipient cases with no intervening ``partially_signed`` (R6.4).
        * ``DOCUMENT_RECIPIENT_REJECTED`` -> ``declined`` (R6.5).
        * ``DOCUMENT_CANCELLED`` (from a non-terminal envelope) -> ``voided``
          (R6.6).
        * Any other event (e.g. ``DOCUMENT_SENT``) or unrecognised event ->
          ``None`` (no transition).
    """
    # Terminal envelopes are immutable: no event transitions them out, and a
    # cancel only applies to a non-terminal envelope (R6.6 / R6.7).
    if current in TERMINAL_STATUSES:
        return None

    if event in (EVENT_DOCUMENT_OPENED, EVENT_DOCUMENT_VIEWED):
        return "viewed"

    if event == EVENT_DOCUMENT_RECIPIENT_COMPLETED:
        # All recipients done -> completed; otherwise at least one is still
        # outstanding -> partially_signed (R6.3 / R6.4).
        return "completed" if _all_signed(recipients_state) else "partially_signed"

    if event == EVENT_DOCUMENT_COMPLETED:
        return "completed"

    if event == EVENT_DOCUMENT_RECIPIENT_REJECTED:
        return "declined"

    if event == EVENT_DOCUMENT_CANCELLED:
        return "voided"

    # DOCUMENT_SENT and any unrecognised event are no-ops.
    return None
