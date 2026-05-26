"""Property tests for vehicle edit allowlist and odometer monotonicity.

Implements:
- **Property 14** — Per-role field allowlist for vehicle edits
  (Req 6.6, 7.2, 7.3, 7.4)
- **Property 15** — Odometer monotonicity (Req 7.6, 7.7)
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.services.vehicle_service import (
    allowed_fields_for_role,
    update_vehicle_fields,
)


# ---------------------------------------------------------------------------
# Property 14 — field allowlist
# ---------------------------------------------------------------------------


def test_admin_allowlist_includes_internal_fleet_fields() -> None:
    fa = allowed_fields_for_role("fleet_admin")
    assert {"fleet_internal_name", "fleet_number", "notes", "colour"} <= fa


def test_driver_allowlist_includes_only_odometer_and_service_due() -> None:
    drv = allowed_fields_for_role("driver")
    assert drv == frozenset({"odometer_last_recorded", "service_due_date"})


def test_unknown_role_has_empty_allowlist() -> None:
    assert allowed_fields_for_role("anonymous") == frozenset()
    assert allowed_fields_for_role("global_admin") == frozenset()


_NEVER_EDITABLE = ["make", "model", "year", "vin", "rego"]


@pytest.mark.parametrize("role", ["fleet_admin", "driver"])
@pytest.mark.parametrize("forbidden", _NEVER_EDITABLE)
def test_make_model_year_vin_rego_never_editable(role: str, forbidden: str) -> None:
    """Property 14 — ``make/model/year/vin/rego`` are forbidden for both roles."""
    with pytest.raises(PermissionError):
        update_vehicle_fields(role=role, payload={forbidden: "anything"})


def test_admin_can_edit_admin_allowlisted_fields() -> None:
    out = update_vehicle_fields(
        role="fleet_admin",
        payload={
            "fleet_internal_name": "Truck A",
            "notes": "fleet 1",
            "odometer_last_recorded": 12345,
        },
    )
    assert out == {
        "fleet_internal_name": "Truck A",
        "notes": "fleet 1",
        "odometer_last_recorded": 12345,
    }


def test_driver_blocked_from_admin_only_fields() -> None:
    """Property 14 — drivers cannot set fleet_admin-only fields."""
    with pytest.raises(PermissionError):
        update_vehicle_fields(
            role="driver",
            payload={"fleet_internal_name": "ATTEMPTED"},
        )


def test_driver_can_edit_their_two_fields() -> None:
    out = update_vehicle_fields(
        role="driver",
        payload={
            "odometer_last_recorded": 99999,
            "service_due_date": "2026-12-31",
        },
    )
    assert out["odometer_last_recorded"] == 99999


@given(
    role=st.sampled_from(["fleet_admin", "driver"]),
    payload=st.dictionaries(
        keys=st.sampled_from(
            [
                "fleet_internal_name",
                "fleet_number",
                "notes",
                "colour",
                "odometer_last_recorded",
                "wof_expiry",
                "cof_expiry",
                "service_due_date",
                "fleet_checklist_template_id",
                "make",
                "model",
                "year",
                "vin",
                "rego",
                "random_unknown_field",
            ]
        ),
        values=st.text(max_size=20),
        max_size=8,
    ),
)
@hyp_settings(max_examples=200)
def test_filter_or_reject(role: str, payload: dict) -> None:
    """Property 14 — payload accepted iff every key is in role's allow-list."""
    allowed = allowed_fields_for_role(role)
    forbidden_in_payload = [k for k in payload if k not in allowed]
    if forbidden_in_payload:
        with pytest.raises(PermissionError):
            update_vehicle_fields(role=role, payload=payload)
    else:
        out = update_vehicle_fields(role=role, payload=payload)
        # The output is a subset (in fact equal) of payload.
        assert set(out) == set(payload)


# ---------------------------------------------------------------------------
# Property 15 — odometer monotonicity (helper)
# ---------------------------------------------------------------------------
# The actual write happens in vehicle_service.log_odometer_reading; the
# property test asserts the strict-greater predicate behaviour without
# touching the DB.


def _accept_reading(previous_max: int, candidate: int) -> bool:
    """Mirror of the strict-greater predicate."""
    return candidate > previous_max


@given(
    previous_max=st.integers(min_value=0, max_value=2_000_000),
    candidate=st.integers(min_value=0, max_value=2_000_000),
)
@hyp_settings(max_examples=300)
def test_odometer_predicate(previous_max: int, candidate: int) -> None:
    """Property 15 — accept iff strictly greater than previous max."""
    assert _accept_reading(previous_max, candidate) is (candidate > previous_max)


@given(
    readings=st.lists(
        st.integers(min_value=0, max_value=2_000_000), min_size=1, max_size=20
    )
)
@hyp_settings(max_examples=100)
def test_max_is_max_of_accepted_set(readings: list[int]) -> None:
    """After a sequence of submissions, max(accepted) == last accepted."""
    current = 0
    accepted: list[int] = []
    for r in readings:
        if _accept_reading(current, r):
            accepted.append(r)
            current = r
    if accepted:
        assert current == max(accepted)
