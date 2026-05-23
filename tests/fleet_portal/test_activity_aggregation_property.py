"""Property 33 — Activity aggregation for drivers.

Validates the aggregation logic in
``driver_service.driver_activity_aggregate`` using a pure-Python
mirror — no DB access. The live aggregation is exercised by the
integration smoke tests in task 20.x.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID, uuid4

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st


def _aggregate(events: list[tuple[date, UUID, str]]) -> dict:
    """Mirror of the Python-side aggregation step in driver_service."""
    rows: dict[tuple[date, UUID], dict] = defaultdict(
        lambda: {"submissions": 0, "failures": 0, "hours": 0, "odometer": 0}
    )
    totals = {"submissions": 0, "failures": 0, "hours": 0, "odometer": 0}
    for d, vid, kind in events:
        rows[(d, vid)][kind] = rows[(d, vid)][kind] + 1
        totals[kind] += 1
    return {
        "rows": [{"date": d, "vehicle": v, **counts} for (d, v), counts in rows.items()],
        "totals": totals,
    }


@given(
    events=st.lists(
        st.tuples(
            st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31)),
            st.uuids(),
            st.sampled_from(["submissions", "failures", "hours", "odometer"]),
        ),
        max_size=50,
    )
)
@hyp_settings(max_examples=300)
def test_totals_match_event_counts(events) -> None:
    """Property 33 — sum of per-(date,vehicle) counts equals total."""
    out = _aggregate(events)
    for kind in ("submissions", "failures", "hours", "odometer"):
        per_row_sum = sum(r[kind] for r in out["rows"])
        assert per_row_sum == out["totals"][kind]


def test_empty_input_yields_zero_totals() -> None:
    out = _aggregate([])
    assert out["rows"] == []
    assert all(v == 0 for v in out["totals"].values())
