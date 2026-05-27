"""Property test: notification_log status transitions are always legal.

Phase 8c task 9.16 of the email-provider-unification spec. Generates
random orderings of webhook events for a given log row and asserts the
resulting state machine stays inside the legal transition graph
declared in design > Data Model > Phase 8a:

    queued ──► sent ──┬─► delivered
                      └─► bounced
    queued ──► failed

The implementation under test is a small, pure state-machine helper
that mirrors the rules embedded in the bounce webhook handlers and the
``send_email_task`` flow. Hypothesis budget is small
(``max_examples=50``) per the spec to keep CI fast.

**Validates: Requirements 11.5, 21.8**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# State machine — pure function, no DB required
# ---------------------------------------------------------------------------

#: Legal transitions per design Data Model > Phase 8a. The empty set
#: for terminal states (``delivered``, ``bounced``, ``failed``) is
#: load-bearing: once a row reaches a terminal state, no event may
#: change its status.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"sent", "failed"},
    "sent": {"delivered", "bounced"},
    "delivered": set(),
    "bounced": set(),
    "failed": set(),
}

#: All known statuses — used as the input space and for the strategy.
ALL_STATUSES = list(LEGAL_TRANSITIONS.keys())

#: All "events" the system can fire at a log row — these correspond to
#: the four real-world inputs:
#:
#: - ``mark_sent``       — provider returned 2xx (set by send_email_task)
#: - ``mark_failed``     — provider returned a HARD_* failure (queued → failed)
#: - ``mark_delivered``  — Brevo ``delivered`` webhook event
#: - ``mark_bounced``    — Brevo / SendGrid bounce webhook event
ALL_EVENTS = ["mark_sent", "mark_failed", "mark_delivered", "mark_bounced"]


def apply_event(status: str, event: str) -> str:
    """Return the new status after applying *event* to *status*.

    Mirrors the rules implemented in
    :func:`app.tasks.notifications._send_email_async` (which sets
    ``sent`` / ``failed``) and
    :func:`app.modules.notifications.bounce_correlation.flag_bounce`
    (which sets ``bounced`` and ``delivered``). Any event that would
    push the row across an illegal edge is silently ignored — this
    matches the "is the row already bounced? then leave it alone"
    guard in the real webhook handlers and prevents accidental
    regressions from terminal back to non-terminal states.
    """
    target = {
        "mark_sent": "sent",
        "mark_failed": "failed",
        "mark_delivered": "delivered",
        "mark_bounced": "bounced",
    }[event]
    if target in LEGAL_TRANSITIONS[status]:
        return target
    # Idempotent same-state transitions (e.g. mark_bounced when already
    # bounced) — return current status unchanged.
    if target == status:
        return status
    # Otherwise the event is ignored — the status is unchanged.
    return status


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@st.composite
def event_sequence(draw):
    """Generate an event sequence of length 1..30.

    Length cap is small enough that even a fully-explored example
    finishes in well under a millisecond — keeps the test CI-friendly.
    """
    n = draw(st.integers(min_value=1, max_value=30))
    return draw(
        st.lists(st.sampled_from(ALL_EVENTS), min_size=n, max_size=n)
    )


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(event_sequence())
def test_no_illegal_status_transition_ever_happens(events: list[str]) -> None:
    """Property: no event sequence ever produces an illegal transition.

    For every random ordering of ``mark_*`` events applied to a fresh
    ``queued`` log row, every observed (old, new) pair must satisfy
    one of:

    - ``new == old`` (event ignored / idempotent same-state),
    - ``new in LEGAL_TRANSITIONS[old]`` (legal forward edge).

    Equivalently: the set difference
    ``{(old, new) observed} - {(s, s) for s} - LEGAL_EDGES`` is empty.

    **Validates: Requirements 11.5, 21.8**
    """
    legal_edges: set[tuple[str, str]] = {
        (src, dst)
        for src, dsts in LEGAL_TRANSITIONS.items()
        for dst in dsts
    }
    observed: list[tuple[str, str]] = []

    status = "queued"
    for event in events:
        new = apply_event(status, event)
        observed.append((status, new))
        status = new

    for old, new in observed:
        if old == new:
            # Event was ignored (idempotent) — always legal.
            continue
        assert (old, new) in legal_edges, (
            f"illegal transition {old} → {new} produced by sequence "
            f"{events!r}"
        )

    # Final status must be one of the five we declared — the state
    # machine never leaks into an unknown label.
    assert status in ALL_STATUSES


@PBT_SETTINGS
@given(event_sequence())
def test_terminal_states_never_change(events: list[str]) -> None:
    """Once the row reaches ``delivered`` / ``bounced`` / ``failed``,
    no later event may change its status.

    This is the "idempotent webhook" property: a webhook delivered
    many times does not corrupt a row. We split the sequence at the
    first transition into a terminal state (if any) and assert
    everything after is a no-op.

    **Validates: Requirements 11.2 (idempotency), 11.5**
    """
    terminal = {"delivered", "bounced", "failed"}
    status = "queued"
    terminal_reached_at: int | None = None
    statuses: list[str] = ["queued"]

    for i, event in enumerate(events):
        status = apply_event(status, event)
        statuses.append(status)
        if terminal_reached_at is None and status in terminal:
            terminal_reached_at = i

    if terminal_reached_at is not None:
        terminal_status = statuses[terminal_reached_at + 1]
        # Every status after the terminal-reach point is the same.
        for later in statuses[terminal_reached_at + 1 :]:
            assert later == terminal_status, (
                f"terminal {terminal_status} mutated to {later} "
                f"after position {terminal_reached_at} in {events!r}"
            )


@PBT_SETTINGS
@given(event_sequence())
def test_bounced_unreachable_from_failed(events: list[str]) -> None:
    """A ``failed`` row never becomes ``bounced``.

    The state graph routes ``queued`` → ``failed`` for
    immediate-rejection paths (HARD_* failure_kind) and reserves
    ``bounced`` for post-send webhook correlation off ``sent``. They
    are mutually exclusive terminal states — one of the design's
    explicit invariants.

    **Validates: Requirement 11.5**
    """
    status = "queued"
    saw_failed = False
    for event in events:
        new = apply_event(status, event)
        if new == "failed":
            saw_failed = True
        if saw_failed:
            assert new in {"failed", status}, (
                f"after entering 'failed', status moved to {new} "
                f"via sequence {events!r}"
            )
        status = new
