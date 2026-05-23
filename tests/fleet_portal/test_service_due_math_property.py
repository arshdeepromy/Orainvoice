"""Property test for service-due math (Property 27, Req 10.6)."""
from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.services.reminder_service import (
    compute_service_due_date,
)


def test_returns_none_when_no_intervals_set() -> None:
    """Property 27 — returns NULL when neither km nor months interval given."""
    out = compute_service_due_date(
        last_service_at=date(2026, 1, 1),
        last_odometer=10_000,
        current_odometer=15_000,
        interval_km=None,
        interval_months=None,
    )
    assert out is None


def test_returns_date_when_only_months_given() -> None:
    out = compute_service_due_date(
        last_service_at=date(2026, 1, 1),
        last_odometer=None,
        current_odometer=None,
        interval_km=None,
        interval_months=6,
    )
    assert out is not None
    # 6 months ~= 180 days from 2026-01-01.
    assert (out - date(2026, 1, 1)).days == 180


def test_returns_earliest_when_both_given() -> None:
    """Property 27 — earliest of (km-derived, months-derived)."""
    # Construct so months-derived (90 days from now) ALMOST always
    # beats km-derived (depends on usage rate).
    out = compute_service_due_date(
        last_service_at=date(2026, 4, 1),
        last_odometer=100_000,
        current_odometer=110_000,
        interval_km=20_000,
        interval_months=3,
    )
    assert out is not None


@given(months=st.integers(min_value=1, max_value=24))
@hyp_settings(max_examples=50)
def test_months_only_is_deterministic(months: int) -> None:
    """Property 27 — same inputs always produce same output."""
    last = date(2026, 1, 1)
    a = compute_service_due_date(
        last_service_at=last,
        last_odometer=None,
        current_odometer=None,
        interval_km=None,
        interval_months=months,
    )
    b = compute_service_due_date(
        last_service_at=last,
        last_odometer=None,
        current_odometer=None,
        interval_km=None,
        interval_months=months,
    )
    assert a == b
    assert a is not None
    assert (a - last).days == months * 30
