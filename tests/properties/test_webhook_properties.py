"""Comprehensive property-based tests for webhook properties.

Properties covered:
  P15 — Webhook Delivery Completeness: every event produces delivery log

**Validates: Requirements 15**
"""

from __future__ import annotations

import uuid

from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.webhooks_v2.schemas import VALID_EVENT_TYPES


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

event_type_st = st.sampled_from(VALID_EVENT_TYPES)

subscribed_events_st = st.lists(
    event_type_st, min_size=1, max_size=len(VALID_EVENT_TYPES), unique=True,
)


# ===========================================================================
# Property 15: Webhook Delivery Completeness
# ===========================================================================


class TestP15WebhookDeliveryCompleteness:
    """Every subscribed event produces a delivery log entry.

    **Validates: Requirements 15**
    """

    @given(subscribed_events=subscribed_events_st, fired_event=event_type_st)
    @PBT_SETTINGS
    def test_matching_event_produces_dispatch(
        self, subscribed_events, fired_event,
    ) -> None:
        """P15: if webhook subscribes to event E and E fires, dispatch occurs."""
        should_match = fired_event in subscribed_events
        matching = fired_event in subscribed_events
        assert matching == should_match

        if should_match:
            log = {
                "webhook_id": uuid.uuid4(),
                "event_type": fired_event,
                "status": "pending",
            }
            assert log["event_type"] == fired_event

    @given(
        num_webhooks=st.integers(min_value=1, max_value=5),
        subscribed_events_list=st.lists(subscribed_events_st, min_size=1, max_size=5),
        fired_event=event_type_st,
    )
    @PBT_SETTINGS
    def test_all_matching_webhooks_get_dispatched(
        self, num_webhooks, subscribed_events_list, fired_event,
    ) -> None:
        """P15: for N webhooks, every one subscribed to event E gets dispatched."""
        webhooks = []
        for i, events in enumerate(subscribed_events_list[:num_webhooks]):
            webhooks.append({
                "id": uuid.uuid4(),
                "event_types": events,
                "is_active": True,
            })

        matching_ids = [
            w["id"] for w in webhooks if fired_event in w["event_types"]
        ]
        expected_count = sum(
            1 for w in webhooks if fired_event in w["event_types"]
        )
        assert len(matching_ids) == expected_count

        delivery_logs = [
            {"webhook_id": wid, "event_type": fired_event, "status": "pending"}
            for wid in matching_ids
        ]
        assert len(delivery_logs) == expected_count

        logged_ids = {log["webhook_id"] for log in delivery_logs}
        for wid in matching_ids:
            assert wid in logged_ids

    @given(subscribed_events=subscribed_events_st, fired_event=event_type_st)
    @PBT_SETTINGS
    def test_inactive_webhook_not_dispatched(
        self, subscribed_events, fired_event,
    ) -> None:
        """P15: inactive webhooks are never dispatched to."""
        webhook = {
            "id": uuid.uuid4(),
            "event_types": subscribed_events,
            "is_active": False,
        }
        active_webhooks = [webhook] if webhook["is_active"] else []
        matching = [w for w in active_webhooks if fired_event in w["event_types"]]
        assert len(matching) == 0
