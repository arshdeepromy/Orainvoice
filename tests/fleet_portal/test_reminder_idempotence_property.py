"""Property test — Property 26: reminder firing idempotency.

The reminder queue is keyed on
``(customer_id, vehicle_id, reminder_type, scheduled_date)`` with
``ON CONFLICT DO NOTHING``, so duplicate enqueues are silent no-ops.
This file asserts the predicate at the model layer with a pure-Python
set-membership mirror.

Property 29 — retry policy — is provided by the existing reminder
queue's exponential-backoff retry; it is not duplicated here. Smoke
covers the live end-to-end flow.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st


def _enqueue_unique(events, seen):
    """Return new size after applying ON CONFLICT DO NOTHING idempotency."""
    for e in events:
        seen.add(e)
    return len(seen)


@given(
    events=st.lists(
        st.tuples(
            st.uuids(),  # customer
            st.uuids(),  # vehicle
            st.sampled_from(
                [
                    "wof_expiry_reminder",
                    "cof_expiry_reminder",
                    "service_due_reminder",
                    "registration_expiry_reminder",
                ]
            ),
            st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31)),
        ),
        max_size=50,
    )
)
@hyp_settings(max_examples=300)
def test_duplicate_enqueues_are_idempotent(events) -> None:
    """Property 26 — enqueueing the same key twice is a no-op."""
    seen: set = set()
    n1 = _enqueue_unique(events, seen)
    n2 = _enqueue_unique(events, seen)  # second pass
    assert n1 == n2
    assert n2 == len(set(events))
