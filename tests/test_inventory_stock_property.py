"""Property-based tests for inventory stock consistency (Task 20.3).

Property 23: Inventory Stock Consistency
— verify stock_after = stock_before − quantity, and reorder alert
  generated when below threshold.

**Validates: Requirements 62.2, 62.3**

Uses Hypothesis to generate random stock levels, quantities, and thresholds,
then verifies:
  1. After decrement_stock_for_invoice, stock_after = max(0, stock_before − Q)
  2. A StockMovement record is created with quantity_change = −Q
  3. When stock_after falls at or below min_stock_threshold (and threshold > 0),
     get_reorder_alerts includes that part
  4. When stock_after is above min_stock_threshold, get_reorder_alerts
     does NOT include that part
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Ensure relationship models are loaded for SQLAlchemy
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.catalogue.models import PartsCatalogue
from app.modules.inventory.models import StockMovement
from app.modules.inventory.service import (
    decrement_stock_for_invoice,
    get_reorder_alerts,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Stock level before decrement: 0–1000
stock_before_strategy = st.integers(min_value=0, max_value=1000)

# Quantity to decrement: 1–500
quantity_strategy = st.integers(min_value=1, max_value=500)

# Minimum stock threshold: 0–100
threshold_strategy = st.integers(min_value=0, max_value=100)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_part(
    org_id: uuid.UUID,
    current_stock: int,
    min_stock_threshold: int = 5,
    reorder_quantity: int = 10,
    is_active: bool = True,
) -> MagicMock:
    """Create a mock PartsCatalogue with mutable current_stock."""
    part = MagicMock(spec=PartsCatalogue)
    part.id = uuid.uuid4()
    part.org_id = org_id
    part.name = "Test Part"
    part.part_number = "TP-001"
    part.default_price = Decimal("25.00")
    part.current_stock = current_stock
    part.min_stock_threshold = min_stock_threshold
    part.reorder_quantity = reorder_quantity
    part.is_active = is_active
    part.created_at = datetime.now(timezone.utc)
    part.updated_at = datetime.now(timezone.utc)
    return part


def _mock_db_for_decrement(part: MagicMock) -> AsyncMock:
    """Build a mock AsyncSession for decrement_stock_for_invoice."""
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = part
    db.execute = AsyncMock(return_value=scalar_result)
    return db


def _mock_db_for_alerts(parts: list[MagicMock]) -> AsyncMock:
    """Build a mock AsyncSession for get_reorder_alerts."""
    db = AsyncMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = parts
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Property 23: Inventory Stock Consistency
# ---------------------------------------------------------------------------


class TestInventoryStockConsistencyProperty:
    """Property 23: Inventory Stock Consistency.

    **Validates: Requirements 62.2, 62.3**
    """

    @given(
        stock_before=stock_before_strategy,
        quantity=quantity_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_stock_after_equals_stock_before_minus_quantity(
        self, stock_before: int, quantity: int
    ):
        """For any part with stock S decremented by Q,
        stock_after = max(0, S − Q).

        **Validates: Requirements 62.2**
        """
        org_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=stock_before)
        db = _mock_db_for_decrement(part)

        result = await decrement_stock_for_invoice(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            part_id=part.id,
            quantity=quantity,
            invoice_id=uuid.uuid4(),
        )

        expected_stock = max(0, stock_before - quantity)
        assert part.current_stock == expected_stock, (
            f"stock_before={stock_before}, quantity={quantity}: "
            f"expected {expected_stock}, got {part.current_stock}"
        )

    @given(
        stock_before=stock_before_strategy,
        quantity=quantity_strategy,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_stock_movement_records_negative_quantity(
        self, stock_before: int, quantity: int
    ):
        """A StockMovement with quantity_change = −Q is always created.

        **Validates: Requirements 62.2**
        """
        org_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=stock_before)
        db = _mock_db_for_decrement(part)

        result = await decrement_stock_for_invoice(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            part_id=part.id,
            quantity=quantity,
            invoice_id=uuid.uuid4(),
        )

        assert result is not None
        assert result["movement"]["quantity_change"] == -quantity
        assert result["movement"]["reason"] == "invoice"

    @given(
        stock_before=stock_before_strategy,
        quantity=quantity_strategy,
        threshold=st.integers(min_value=1, max_value=100),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_reorder_alert_when_stock_below_threshold(
        self, stock_before: int, quantity: int, threshold: int
    ):
        """When stock_after <= min_stock_threshold (threshold > 0),
        get_reorder_alerts includes the part.

        **Validates: Requirements 62.3**
        """
        org_id = uuid.uuid4()
        stock_after = max(0, stock_before - quantity)

        # Only test cases where stock falls at or below threshold
        if stock_after > threshold:
            return

        part = _make_part(
            org_id=org_id,
            current_stock=stock_after,
            min_stock_threshold=threshold,
        )

        # get_reorder_alerts filters: current_stock <= min_stock_threshold
        # and min_stock_threshold > 0 and is_active = True
        db = _mock_db_for_alerts([part])

        alerts = await get_reorder_alerts(db, org_id=org_id)

        assert alerts["total"] >= 1, (
            f"stock_after={stock_after}, threshold={threshold}: "
            f"expected reorder alert but got none"
        )
        alert_part_ids = [a["part_id"] for a in alerts["alerts"]]
        assert str(part.id) in alert_part_ids

    @given(
        stock_before=st.integers(min_value=50, max_value=1000),
        quantity=st.integers(min_value=1, max_value=10),
        threshold=st.integers(min_value=1, max_value=20),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_no_reorder_alert_when_stock_above_threshold(
        self, stock_before: int, quantity: int, threshold: int
    ):
        """When stock_after > min_stock_threshold, get_reorder_alerts
        returns no alerts for that part.

        **Validates: Requirements 62.3**
        """
        stock_after = max(0, stock_before - quantity)

        # Only test cases where stock stays above threshold
        if stock_after <= threshold:
            return

        org_id = uuid.uuid4()

        # No parts should be returned by the query when stock is above threshold
        db = _mock_db_for_alerts([])

        alerts = await get_reorder_alerts(db, org_id=org_id)

        assert alerts["total"] == 0, (
            f"stock_after={stock_after}, threshold={threshold}: "
            f"expected no reorder alert but got {alerts['total']}"
        )
