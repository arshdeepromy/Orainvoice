"""Property tests for booking and quote state machines.

Implements:
- **Property 30** — Booking/Quote request validation predicate
- **Property 31** — Status state machines
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.services.booking_service import (
    can_transition as booking_transition,
    validate_create as booking_validate,
)
from app.modules.fleet_portal.services.quote_service import (
    can_transition as quote_transition,
)


# ---------------------------------------------------------------------------
# Property 30 — booking validation
# ---------------------------------------------------------------------------


_today = date(2026, 5, 22)


def test_booking_create_rejects_past_date() -> None:
    with pytest.raises(ValueError, match="past"):
        booking_validate(
            preferred_date=_today - timedelta(days=1),
            preferred_slot="morning",
            service_description="Brake service please",
            today=_today,
        )


def test_booking_create_rejects_unknown_slot() -> None:
    with pytest.raises(ValueError, match="preferred_slot"):
        booking_validate(
            preferred_date=_today,
            preferred_slot="dawn",
            service_description="Brake service please",
            today=_today,
        )


def test_booking_create_rejects_short_description() -> None:
    with pytest.raises(ValueError, match="service_description"):
        booking_validate(
            preferred_date=_today,
            preferred_slot="morning",
            service_description="short",
            today=_today,
        )


def test_booking_create_accepts_today_or_later() -> None:
    booking_validate(
        preferred_date=_today,
        preferred_slot="all_day",
        service_description="Service the brakes please",
        today=_today,
    )
    booking_validate(
        preferred_date=_today + timedelta(days=14),
        preferred_slot="afternoon",
        service_description="Service the brakes please",
        today=_today,
    )


# ---------------------------------------------------------------------------
# Property 31 — booking state machine
# ---------------------------------------------------------------------------


_BOOKING_STATES = {"pending", "accepted", "declined", "completed", "cancelled"}
_BOOKING_ALLOWED = {
    ("pending", "accepted"),
    ("pending", "declined"),
    ("pending", "cancelled"),
    ("accepted", "completed"),
}


@given(
    src=st.sampled_from(sorted(_BOOKING_STATES)),
    dst=st.sampled_from(sorted(_BOOKING_STATES)),
)
@hyp_settings(max_examples=200)
def test_booking_transition_is_iff_in_allowed_set(src: str, dst: str) -> None:
    """Property 31 — booking transition allowed iff in the allowed set."""
    assert booking_transition(src, dst) is ((src, dst) in _BOOKING_ALLOWED)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for terminal in ("declined", "completed", "cancelled"):
        for any_state in _BOOKING_STATES:
            assert booking_transition(terminal, any_state) is False


# ---------------------------------------------------------------------------
# Property 31 — quote state machine
# ---------------------------------------------------------------------------


_QUOTE_STATES = {"pending", "quoted", "accepted", "declined", "expired", "cancelled"}
_QUOTE_ALLOWED = {
    ("pending", "quoted"),
    ("pending", "declined"),
    ("pending", "cancelled"),
    ("quoted", "accepted"),
    ("quoted", "declined"),
    ("quoted", "expired"),
}


@given(
    src=st.sampled_from(sorted(_QUOTE_STATES)),
    dst=st.sampled_from(sorted(_QUOTE_STATES)),
)
@hyp_settings(max_examples=200)
def test_quote_transition_is_iff_in_allowed_set(src: str, dst: str) -> None:
    assert quote_transition(src, dst) is ((src, dst) in _QUOTE_ALLOWED)
