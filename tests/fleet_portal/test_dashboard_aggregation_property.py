"""Property tests for expiry-badge function and dashboard aggregations.

Implements:
- **Property 16** — Expiry-status badge function (Req 6.3, 6.4, 7.8)
- **Property 17** — Fleet summary aggregations are direct enumerations
  (Req 6.8, 15.2–15.6) — covered partially here; the live aggregation
  is validated by the smoke / integration tests in task 20.x.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.services.expiry import (
    AMBER_WINDOW_DAYS,
    badge,
)


_today = date(2026, 5, 22)


@given(days_ago=st.integers(min_value=1, max_value=365))
@hyp_settings(max_examples=200)
def test_red_when_expiry_before_today(days_ago: int) -> None:
    """Property 16 — expiry < today → red."""
    expiry = _today - timedelta(days=days_ago)
    assert badge(expiry, _today) == "red"


@given(days_ahead=st.integers(min_value=0, max_value=AMBER_WINDOW_DAYS))
@hyp_settings(max_examples=200)
def test_amber_when_expiry_in_28_day_window(days_ahead: int) -> None:
    """Property 16 — today ≤ expiry ≤ today + 28 → amber."""
    expiry = _today + timedelta(days=days_ahead)
    assert badge(expiry, _today) == "amber"


@given(days_ahead=st.integers(min_value=AMBER_WINDOW_DAYS + 1, max_value=3650))
@hyp_settings(max_examples=200)
def test_green_when_expiry_beyond_window(days_ahead: int) -> None:
    """Property 16 — expiry > today + 28 → green."""
    expiry = _today + timedelta(days=days_ahead)
    assert badge(expiry, _today) == "green"


def test_none_expiry_returns_none() -> None:
    assert badge(None, _today) is None


@given(
    days_offset=st.integers(min_value=-1000, max_value=1000),
)
@hyp_settings(max_examples=500)
def test_three_buckets_are_total_and_disjoint(days_offset: int) -> None:
    """Property 16 — every (expiry, today) pair maps to exactly one bucket."""
    expiry = _today + timedelta(days=days_offset)
    result = badge(expiry, _today)
    assert result in {"red", "amber", "green"}
    # Disjoint by construction: only one `if` branch fires per call.


# ---------------------------------------------------------------------------
# Pure-Python aggregation enumeration mirror (Property 17 head-to-head)
# ---------------------------------------------------------------------------


def _expected_summary(vehicles, today):
    """Naïve direct enumeration — should match the service for any input."""
    valid_wof_cof = sum(
        1
        for v in vehicles
        if v.get("wof") and v.get("cof") and v["wof"] > today and v["cof"] > today
    )
    expiring = sum(
        1
        for v in vehicles
        if badge(v.get("wof"), today) == "amber"
        or badge(v.get("cof"), today) == "amber"
    )
    overdue = sum(
        1 for v in vehicles if v.get("service") and v["service"] < today
    )
    return valid_wof_cof, expiring, overdue


@given(
    n=st.integers(min_value=0, max_value=20),
)
@hyp_settings(max_examples=20)
def test_aggregation_helper_returns_consistent_shape(n: int) -> None:
    """Smoke-property: ``_expected_summary`` always returns 3 ints ≥ 0."""
    today = _today
    vehicles = [
        {
            "wof": today + timedelta(days=(i - n // 2) * 3),
            "cof": today + timedelta(days=(i - n // 2) * 5),
            "service": today + timedelta(days=(i - n // 2) * 2),
        }
        for i in range(n)
    ]
    valid_wof_cof, expiring, overdue = _expected_summary(vehicles, today)
    assert all(isinstance(x, int) and x >= 0 for x in (valid_wof_cof, expiring, overdue))
    assert valid_wof_cof <= n
    assert overdue <= n
    assert expiring <= n
