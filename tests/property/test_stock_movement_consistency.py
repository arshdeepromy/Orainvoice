"""Property-based test: stock movement consistency.

**Validates: Requirements 9.3, 9.4, 9.7** — Property 3

For any product P, the sum of all stock_movement quantity_change values
equals the product's current stock_quantity. No stock operation can leave
the stock_quantity in a state inconsistent with the movement history.

Uses Hypothesis to generate random sequences of stock operations and
verifies the invariant holds after every operation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.products.models import Product
from app.modules.stock.models import StockMovement
from app.modules.stock.service import StockService


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategy for quantity changes: reasonable range, 3 decimal places
quantity_strategy = st.decimals(
    min_value=Decimal("-1000"),
    max_value=Decimal("1000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

positive_quantity_strategy = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("1000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

movement_type_strategy = st.sampled_from([
    "sale", "credit", "purchase", "adjustment", "transfer", "return", "stocktake",
])


def _make_product(initial_stock: Decimal = Decimal("0")) -> Product:
    """Create a Product instance with in-memory state (no DB session)."""
    product = Product(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="Test Product",
        stock_quantity=initial_stock,
        sale_price=Decimal("10.00"),
    )
    return product


def _make_movement(
    product: Product,
    quantity_change: Decimal,
    movement_type: str,
    resulting_quantity: Decimal,
) -> StockMovement:
    """Create a StockMovement instance with in-memory state."""
    return StockMovement(
        id=uuid.uuid4(),
        org_id=product.org_id,
        product_id=product.id,
        movement_type=movement_type,
        quantity_change=quantity_change,
        resulting_quantity=resulting_quantity,
    )


class TestStockMovementConsistency:
    """For any product P, the sum of all stock_movement quantity_change
    values equals the product's current stock_quantity.

    **Validates: Requirements 9.3, 9.4, 9.7**
    """

    @given(
        initial_stock=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("10000"),
            places=3, allow_nan=False, allow_infinity=False,
        ),
        operations=st.lists(
            st.tuples(movement_type_strategy, quantity_strategy),
            min_size=1,
            max_size=20,
        ),
    )
    @PBT_SETTINGS
    def test_movements_sum_equals_current_quantity(
        self, initial_stock: Decimal, operations: list[tuple[str, Decimal]],
    ) -> None:
        """After applying N stock operations, the sum of all quantity_changes
        (including the initial stock as an implicit adjustment) equals
        the product's current stock_quantity."""
        import asyncio

        product = _make_product(Decimal("0"))
        movements_created: list[StockMovement] = []

        # Mock DB session — track adds but don't persist
        mock_db = AsyncMock()
        added_objects: list = []

        async def fake_flush():
            pass

        def fake_add(obj):
            added_objects.append(obj)

        mock_db.flush = fake_flush
        mock_db.add = fake_add

        svc = StockService(mock_db)

        async def run():
            # First, set initial stock via an adjustment
            if initial_stock != Decimal("0"):
                m = await svc._create_movement(
                    product, initial_stock, "adjustment",
                    notes="Initial stock",
                )
                movements_created.append(m)

            # Apply each operation
            for move_type, qty in operations:
                if move_type == "sale":
                    m = await svc.decrement_stock(product, abs(qty))
                elif move_type in ("credit", "purchase", "return"):
                    m = await svc.increment_stock(
                        product, abs(qty), movement_type=move_type,
                    )
                elif move_type == "adjustment":
                    m = await svc.manual_adjustment(product, qty, "test adjustment")
                else:
                    # stocktake / transfer — use _create_movement directly
                    m = await svc._create_movement(product, qty, move_type)
                movements_created.append(m)

        asyncio.get_event_loop().run_until_complete(run())

        # Property: sum of all quantity_changes == product.stock_quantity
        total_change = sum(m.quantity_change for m in movements_created)
        assert product.stock_quantity == total_change, (
            f"Stock quantity {product.stock_quantity} != sum of movements {total_change}. "
            f"Movements: {[(m.movement_type, m.quantity_change) for m in movements_created]}"
        )

    @given(
        quantities=st.lists(
            positive_quantity_strategy,
            min_size=1,
            max_size=10,
        ),
    )
    @PBT_SETTINGS
    def test_decrement_then_increment_returns_to_original(
        self, quantities: list[Decimal],
    ) -> None:
        """Decrementing and then incrementing by the same amounts returns
        stock to the original level."""
        import asyncio

        product = _make_product(Decimal("1000"))
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        svc = StockService(mock_db)
        original = product.stock_quantity

        async def run():
            for qty in quantities:
                await svc.decrement_stock(product, qty)
            for qty in quantities:
                await svc.increment_stock(product, qty)

        asyncio.get_event_loop().run_until_complete(run())

        assert product.stock_quantity == original, (
            f"Expected {original}, got {product.stock_quantity} after "
            f"decrement+increment of {quantities}"
        )

    @given(
        initial_stock=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("10000"),
            places=3, allow_nan=False, allow_infinity=False,
        ),
        operations=st.lists(
            st.tuples(movement_type_strategy, quantity_strategy),
            min_size=1,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_resulting_quantity_matches_product_after_each_movement(
        self, initial_stock: Decimal, operations: list[tuple[str, Decimal]],
    ) -> None:
        """After each movement, the movement's resulting_quantity matches
        the product's stock_quantity."""
        import asyncio

        product = _make_product(initial_stock)
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        svc = StockService(mock_db)

        async def run():
            for move_type, qty in operations:
                m = await svc._create_movement(product, qty, move_type)
                assert m.resulting_quantity == product.stock_quantity, (
                    f"Movement resulting_quantity {m.resulting_quantity} != "
                    f"product.stock_quantity {product.stock_quantity}"
                )

        asyncio.get_event_loop().run_until_complete(run())
