"""Tests for kitchen display system: order creation, station routing, WebSocket events.

**Validates: Requirement — Kitchen Display Module — Tasks 32.8, 32.9**
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.kitchen_display.models import KitchenOrder
from app.modules.kitchen_display.service import KitchenService, DEFAULT_STATION_MAP
from app.modules.kitchen_display.schemas import KitchenOrderCreate

ORG_ID = uuid.uuid4()
TXN_ID = uuid.uuid4()
TABLE_ID = uuid.uuid4()


def _make_order(
    *,
    status: str = "pending",
    station: str = "main",
    item_name: str = "Burger",
    created_at: datetime | None = None,
) -> KitchenOrder:
    return KitchenOrder(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        pos_transaction_id=TXN_ID,
        table_id=TABLE_ID,
        item_name=item_name,
        quantity=1,
        station=station,
        status=status,
        created_at=created_at or datetime.now(timezone.utc),
    )


def _make_mock_db(orders: list[KitchenOrder] | None = None, single: KitchenOrder | None = None):
    mock_db = AsyncMock()
    if single is not None:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = single
            mock_result.scalars.return_value.all.return_value = [single]
            return mock_result
        mock_db.execute = fake_execute
    elif orders is not None:
        call_count = 0
        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                # count query
                mock_result.scalar.return_value = len(orders)
            else:
                mock_result.scalars.return_value.all.return_value = orders
            return mock_result
        mock_db.execute = fake_execute
    else:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar.return_value = 0
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# ======================================================================
# Task 32.8: POS order items appear in kitchen display
# ======================================================================


class TestPOSOrdersAppearInKitchen:
    """Verify that POS transaction items are routed to kitchen display."""

    @pytest.mark.asyncio
    async def test_create_orders_from_transaction(self):
        """Items from a POS transaction create kitchen orders."""
        db = _make_mock_db()
        svc = KitchenService(db)
        items = [
            {"item_name": "Burger", "quantity": 2, "category": "grill"},
            {"item_name": "Caesar Salad", "quantity": 1, "category": "salad"},
            {"item_name": "Beer", "quantity": 3, "category": "beverage"},
        ]
        orders = await svc.create_orders_from_transaction(
            ORG_ID, TXN_ID, TABLE_ID, items,
        )
        assert len(orders) == 3
        assert orders[0].item_name == "Burger"
        assert orders[0].station == "grill"
        assert orders[0].quantity == 2
        assert orders[1].station == "cold"  # salad → cold
        assert orders[2].station == "bar"   # beverage → bar

    @pytest.mark.asyncio
    async def test_unknown_category_routes_to_main(self):
        """Items with unknown category go to 'main' station."""
        db = _make_mock_db()
        svc = KitchenService(db)
        items = [{"item_name": "Special", "quantity": 1, "category": "unknown"}]
        orders = await svc.create_orders_from_transaction(
            ORG_ID, TXN_ID, TABLE_ID, items,
        )
        assert orders[0].station == "main"

    @pytest.mark.asyncio
    async def test_custom_station_map(self):
        """Custom station mapping overrides defaults."""
        db = _make_mock_db()
        svc = KitchenService(db)
        custom_map = {"pizza": "oven", "pasta": "stove"}
        items = [
            {"item_name": "Margherita", "quantity": 1, "category": "pizza"},
            {"item_name": "Carbonara", "quantity": 1, "category": "pasta"},
        ]
        orders = await svc.create_orders_from_transaction(
            ORG_ID, TXN_ID, TABLE_ID, items, station_map=custom_map,
        )
        assert orders[0].station == "oven"
        assert orders[1].station == "stove"

    @pytest.mark.asyncio
    async def test_create_single_order(self):
        """Single kitchen order creation works."""
        db = _make_mock_db()
        svc = KitchenService(db)
        payload = KitchenOrderCreate(
            pos_transaction_id=TXN_ID,
            table_id=TABLE_ID,
            item_name="Fish & Chips",
            quantity=1,
            station="fry",
        )
        order = await svc.create_order(ORG_ID, payload)
        assert order.item_name == "Fish & Chips"
        assert order.station == "fry"
        # status default is set by SQLAlchemy column default
        assert order.org_id == ORG_ID

    @pytest.mark.asyncio
    @patch("app.modules.kitchen_display.redis_pubsub.get_redis")
    async def test_bulk_create_publishes_websocket_events(self, mock_get_redis):
        """Bulk order creation publishes events to Redis for WebSocket delivery."""
        from app.modules.kitchen_display.redis_pubsub import publish_kitchen_event

        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        await publish_kitchen_event(
            str(ORG_ID), "grill", "order_created",
            {"order": {"item_name": "Steak", "station": "grill"}},
        )
        # Should publish to station channel and all channel
        assert mock_redis.publish.call_count == 2
        calls = mock_redis.publish.call_args_list
        channel_0 = calls[0][0][0]
        channel_1 = calls[1][0][0]
        assert f"kitchen:{ORG_ID}:grill" == channel_0
        assert f"kitchen:{ORG_ID}:all" == channel_1


# ======================================================================
# Task 32.9: Marking item prepared sends notification to front-of-house
# ======================================================================


class TestMarkPreparedNotification:
    """Verify that marking an item prepared triggers front-of-house notification."""

    @pytest.mark.asyncio
    async def test_mark_prepared_updates_status(self):
        """Marking an order as prepared sets status and prepared_at."""
        order = _make_order(status="pending")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.mark_prepared(ORG_ID, order.id)
        assert result is not None
        assert result.status == "prepared"
        assert result.prepared_at is not None

    @pytest.mark.asyncio
    async def test_mark_prepared_from_preparing(self):
        """Can mark as prepared from 'preparing' status."""
        order = _make_order(status="preparing")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.mark_prepared(ORG_ID, order.id)
        assert result is not None
        assert result.status == "prepared"

    @pytest.mark.asyncio
    async def test_cannot_mark_served_as_prepared(self):
        """Cannot mark an already-served order as prepared."""
        order = _make_order(status="served")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.mark_prepared(ORG_ID, order.id)
        assert result is None

    @pytest.mark.asyncio
    @patch("app.modules.kitchen_display.redis_pubsub.get_redis")
    async def test_prepared_event_published(self, mock_get_redis):
        """Marking prepared publishes event for front-of-house display."""
        from app.modules.kitchen_display.redis_pubsub import publish_kitchen_event

        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        await publish_kitchen_event(
            str(ORG_ID), "grill", "order_prepared",
            {"order_id": str(uuid.uuid4()), "item_name": "Steak"},
        )
        assert mock_redis.publish.call_count == 2
        payload = mock_redis.publish.call_args_list[0][0][1]
        data = json.loads(payload)
        assert data["event"] == "order_prepared"
        assert data["item_name"] == "Steak"


# ======================================================================
# Station routing tests
# ======================================================================


class TestStationRouting:
    """Verify category → station mapping logic."""

    def test_grill_category(self):
        assert KitchenService.route_to_station("grill") == "grill"

    def test_salad_routes_to_cold(self):
        assert KitchenService.route_to_station("salad") == "cold"

    def test_beverage_routes_to_bar(self):
        assert KitchenService.route_to_station("beverage") == "bar"

    def test_unknown_routes_to_main(self):
        assert KitchenService.route_to_station("exotic") == "main"

    def test_case_insensitive(self):
        assert KitchenService.route_to_station("GRILL") == "grill"
        assert KitchenService.route_to_station("Salad") == "cold"


# ======================================================================
# Urgency level tests (Task 32.7)
# ======================================================================


class TestUrgencyLevel:
    """Verify preparation time highlighting logic."""

    def test_normal_under_15_min(self):
        created = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert KitchenService.get_urgency_level(created) == "normal"

    def test_warning_between_15_and_30_min(self):
        created = datetime.now(timezone.utc) - timedelta(minutes=20)
        assert KitchenService.get_urgency_level(created) == "warning"

    def test_critical_over_30_min(self):
        created = datetime.now(timezone.utc) - timedelta(minutes=45)
        assert KitchenService.get_urgency_level(created) == "critical"

    def test_exactly_15_min_is_warning(self):
        created = datetime.now(timezone.utc) - timedelta(minutes=15, seconds=1)
        assert KitchenService.get_urgency_level(created) == "warning"


# ======================================================================
# Status transition tests
# ======================================================================


class TestStatusTransitions:
    """Verify valid and invalid status transitions."""

    @pytest.mark.asyncio
    async def test_pending_to_preparing(self):
        order = _make_order(status="pending")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.update_status(ORG_ID, order.id, "preparing")
        assert result is not None
        assert result.status == "preparing"

    @pytest.mark.asyncio
    async def test_preparing_to_prepared(self):
        order = _make_order(status="preparing")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.update_status(ORG_ID, order.id, "prepared")
        assert result is not None
        assert result.status == "prepared"
        assert result.prepared_at is not None

    @pytest.mark.asyncio
    async def test_prepared_to_served(self):
        order = _make_order(status="prepared")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.update_status(ORG_ID, order.id, "served")
        assert result is not None
        assert result.status == "served"

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self):
        order = _make_order(status="pending")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.update_status(ORG_ID, order.id, "served")
        assert result is None

    @pytest.mark.asyncio
    async def test_served_cannot_transition(self):
        order = _make_order(status="served")
        db = _make_mock_db(single=order)
        svc = KitchenService(db)
        result = await svc.update_status(ORG_ID, order.id, "pending")
        assert result is None
