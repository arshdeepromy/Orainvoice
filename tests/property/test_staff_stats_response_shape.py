"""Property-based test for the ``StaffMonthStatsResponse`` serialized shape.

Covers task **5.3** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 10: Stats endpoint returns a structured object**

*For any* computed stats, the ``GET /api/v2/staff/{id}/stats`` response
body SHALL be a JSON object carrying the named keys ``hours_logged``,
``jobs_completed``, ``billable_ratio``, ``on_time_rate``, and
``last_sign_in``, and SHALL NOT be a bare array.

**Feature: staff-redesign, Property 10**

**Validates: Requirements 11.1, 14.5**

This is a pure schema-serialisation property — it needs no database. It
constructs a ``StaffMonthStatsResponse`` from arbitrary valid field
values (random staff UUID, each metric a ``StaffMetricValue`` with an
arbitrary Decimal value + boolean ``has_data``, an optional
``last_sign_in`` datetime, an optional ``user_role`` string) and asserts
that the JSON serialisation (Pydantic v2 ``model_dump(mode="json")`` /
``model_dump_json()``) is a JSON object (``dict``), never a bare array,
with the five required keys present and each metric itself a nested
object carrying ``value`` and ``has_data``.

Run via: ``docker compose exec app python -m pytest \
tests/property/test_staff_stats_response_shape.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings as h_settings
from hypothesis import strategies as st

from app.modules.staff.schemas import StaffMetricValue, StaffMonthStatsResponse


# ---------------------------------------------------------------------------
# Hypothesis configuration
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(max_examples=100, deadline=None)

# The five keys the response body MUST carry (Property 10 / R14.5). Note
# ``staff_id``, ``period``, and ``user_role`` are also present but the
# property specifically names these five.
_REQUIRED_KEYS = (
    "hours_logged",
    "jobs_completed",
    "billable_ratio",
    "on_time_rate",
    "last_sign_in",
)

_METRIC_KEYS = ("hours_logged", "jobs_completed", "billable_ratio", "on_time_rate")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A finite, JSON-serialisable Decimal value for a metric.
_decimal_value = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


@st.composite
def _metric(draw) -> StaffMetricValue:
    return StaffMetricValue(
        value=draw(_decimal_value),
        has_data=draw(st.booleans()),
    )


# last_sign_in: None or a timezone-aware datetime.
_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
_last_sign_in = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=10 * 365 * 24 * 3600).map(
        lambda secs: _EPOCH + timedelta(seconds=secs)
    ),
)

# user_role: None or an arbitrary short string (users.role is String(20)).
_user_role = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=20),
)


@st.composite
def _response(draw) -> StaffMonthStatsResponse:
    return StaffMonthStatsResponse(
        staff_id=uuid.uuid4(),
        period="this_month",
        hours_logged=draw(_metric()),
        jobs_completed=draw(_metric()),
        billable_ratio=draw(_metric()),
        on_time_rate=draw(_metric()),
        last_sign_in=draw(_last_sign_in),
        user_role=draw(_user_role),
    )


# ===========================================================================
# Property 10 — structured-object response shape
# ===========================================================================


class TestStatsResponseShapeProperty:
    """**Feature: staff-redesign, Property 10**

    The serialised stats body is a JSON object (never a bare array) with
    the five named keys, each metric a nested object with ``value`` and
    ``has_data``.

    **Validates: Requirements 11.1, 14.5**
    """

    @PBT_SETTINGS
    @given(response=_response())
    def test_serialized_body_is_structured_object(
        self, response: StaffMonthStatsResponse,
    ) -> None:
        # Two serialisation paths: model_dump(mode="json") and the JSON
        # string round-tripped through json.loads. Both must agree the
        # body is a dict (JSON object), never a list/array.
        dumped = response.model_dump(mode="json")
        loaded = json.loads(response.model_dump_json())

        for body in (dumped, loaded):
            # Structured object, never a bare array.
            assert isinstance(body, dict), (
                f"stats body must be a JSON object, got {type(body).__name__}"
            )
            assert not isinstance(body, list)

            # All five named keys present.
            for key in _REQUIRED_KEYS:
                assert key in body, f"missing required key {key!r} in {body!r}"

            # Each metric is itself a nested object with value + has_data.
            for metric_key in _METRIC_KEYS:
                metric = body[metric_key]
                assert isinstance(metric, dict), (
                    f"metric {metric_key!r} must be a nested object, "
                    f"got {type(metric).__name__}"
                )
                assert "value" in metric
                assert "has_data" in metric
                assert isinstance(metric["has_data"], bool)
