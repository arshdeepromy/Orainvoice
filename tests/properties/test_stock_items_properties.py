"""Property-based tests for stock items service.

Properties covered:
  P1  — Stock Items List Exclusivity
  P3  — Below-Threshold Flag Correctness
  P7  — Creation Produces Stock Item and Movement
  P8  — Creation Input Validation
  P9  — Uniqueness Constraint
  P10 — Invalid Catalogue Item Rejection
  P11 — Supplier Resolution from Catalogue

**Validates: Requirements 1.1, 1.2, 1.4, 5.2, 5.3, 5.5, 5.6, 6.1, 6.4,
             8.4, 9.1, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, assume, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.modules.inventory.models import StockItem
from app.modules.inventory.stock_items_schemas import CreateStockItemRequest
from app.modules.inventory.stock_items_service import (
    _build_stock_item_response,
    create_stock_item,
    list_stock_items,
)
from app.modules.catalogue.models import PartsCatalogue
from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.stock.models import StockMovement
from app.modules.suppliers.models import Supplier

# Import Organisation and User to ensure SQLAlchemy mapper can resolve relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

catalogue_type_st = st.sampled_from(["part", "tyre", "fluid"])

positive_quantity_st = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("99999"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

non_negative_quantity_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("99999"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

threshold_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

safe_text_st = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

reason_st = st.sampled_from([
    "Purchase Order received",
    "Initial stock count",
    "Transfer in",
    "Other",
])

barcode_st = st.one_of(
    st.none(),
    st.from_regex(r"[A-Z0-9]{6,20}", fullmatch=True),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeScalarResult:
    """Mimics SQLAlchemy scalar result for mocked db.execute()."""

    def __init__(self, value: Any = None, items: list | None = None):
        self._value = value
        self._items = items or []

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._value

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list:
        return self._items

    def __iter__(self):
        return iter(self._items)


def _make_db_with_defaults() -> AsyncMock:
    """Create a mock AsyncSession that applies server defaults on flush.

    StockItem has server_default values for min_threshold, reorder_quantity,
    and current_quantity that are only applied by the DB. This helper
    simulates that by setting None fields to their defaults on flush.
    """
    db = AsyncMock()
    added_objects: list[Any] = []

    def track_add(obj: Any) -> None:
        added_objects.append(obj)

    async def apply_defaults() -> None:
        for obj in added_objects:
            if isinstance(obj, StockItem):
                if obj.min_threshold is None:
                    obj.min_threshold = Decimal("0")
                if obj.reorder_quantity is None:
                    obj.reorder_quantity = Decimal("0")
                if obj.current_quantity is None:
                    obj.current_quantity = Decimal("0")
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
                if obj.updated_at is None:
                    obj.updated_at = datetime.now(timezone.utc)

    db.add = MagicMock(side_effect=track_add)
    db.flush = AsyncMock(side_effect=apply_defaults)
    db._added_objects = added_objects
    return db


def _make_parts_catalogue(
    org_id: uuid.UUID,
    part_type: str = "part",
    supplier_id: uuid.UUID | None = None,
    name: str = "Test Part",
    is_active: bool = True,
) -> MagicMock:
    """Build a mock PartsCatalogue object."""
    cat = MagicMock(spec=PartsCatalogue)
    cat.id = uuid.uuid4()
    cat.org_id = org_id
    cat.name = name
    cat.part_number = f"PN-{uuid.uuid4().hex[:6].upper()}"
    cat.brand = "TestBrand"
    cat.part_type = part_type
    cat.supplier_id = supplier_id
    cat.is_active = is_active
    cat.description = "Test description"
    return cat


def _make_fluid_product(
    org_id: uuid.UUID,
    supplier_id: uuid.UUID | None = None,
    oil_type: str | None = "Engine Oil",
    grade: str | None = "5W-30",
    product_name: str | None = None,
    is_active: bool = True,
) -> MagicMock:
    """Build a mock FluidOilProduct object."""
    fluid = MagicMock(spec=FluidOilProduct)
    fluid.id = uuid.uuid4()
    fluid.org_id = org_id
    fluid.oil_type = oil_type
    fluid.grade = grade
    fluid.product_name = product_name
    fluid.brand_name = "FluidBrand"
    fluid.supplier_id = supplier_id
    fluid.is_active = is_active
    fluid.description = "Test fluid"
    return fluid


def _make_stock_item(
    org_id: uuid.UUID,
    catalogue_item_id: uuid.UUID,
    catalogue_type: str = "part",
    current_quantity: Decimal = Decimal("10"),
    min_threshold: Decimal = Decimal("0"),
    reorder_quantity: Decimal = Decimal("0"),
    supplier_id: uuid.UUID | None = None,
    barcode: str | None = None,
) -> MagicMock:
    """Build a mock StockItem-like object without touching SQLAlchemy state."""
    si = MagicMock(spec=StockItem)
    si.id = uuid.uuid4()
    si.org_id = org_id
    si.catalogue_item_id = catalogue_item_id
    si.catalogue_type = catalogue_type
    si.current_quantity = current_quantity
    si.min_threshold = min_threshold
    si.reorder_quantity = reorder_quantity
    si.supplier_id = supplier_id
    si.barcode = barcode
    si.created_by = uuid.uuid4()
    si.created_at = datetime.now(timezone.utc)
    si.updated_at = datetime.now(timezone.utc)
    return si


# ===========================================================================
# Property 1: Stock Items List Exclusivity
# ===========================================================================
# Feature: inventory-stock-management, Property 1: Stock Items List Exclusivity


class TestP1StockItemsListExclusivity:
    """For any organisation with a set of catalogue items and a subset that
    have been added to stock_items, the stock items list should return exactly
    and only the items present in the stock_items table.

    **Validates: Requirements 1.1, 1.2, 1.4, 9.1**
    """

    @given(
        num_catalogue=st.integers(min_value=1, max_value=8),
        stocked_fraction=st.floats(min_value=0.0, max_value=1.0),
    )
    @PBT_SETTINGS
    def test_list_returns_exactly_stocked_subset(
        self,
        num_catalogue: int,
        stocked_fraction: float,
    ) -> None:
        """P1: list_stock_items returns only items in stock_items table."""
        org_id = uuid.uuid4()

        # Generate catalogue items (all parts for simplicity)
        catalogue_items = [
            _make_parts_catalogue(org_id, name=f"Part {i}")
            for i in range(num_catalogue)
        ]

        # Determine which ones are stocked
        num_stocked = max(0, int(num_catalogue * stocked_fraction))
        stocked_cats = catalogue_items[:num_stocked]

        # Create stock items for the stocked subset
        stock_items = [
            _make_stock_item(
                org_id=org_id,
                catalogue_item_id=cat.id,
                catalogue_type="part",
                current_quantity=Decimal("5"),
            )
            for cat in stocked_cats
        ]

        # Build parts_map for the batch-load
        parts_map = {cat.id: cat for cat in catalogue_items}

        # Mock DB
        db = AsyncMock()

        # The list_stock_items function does:
        # 1. count query (we skip since it fetches all)
        # 2. select StockItem query -> returns stock_items
        # 3. select PartsCatalogue batch -> returns all catalogue items
        # 4. select Supplier batch -> returns empty (no suppliers)
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=stock_items),  # stock items query
                _FakeScalarResult(items=list(parts_map.values())),  # parts batch
                # No fluids query needed since all are parts
                # No supplier query since no supplier_ids
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id)
            # Verify: returned IDs match exactly the stocked subset
            returned_ids = {si.catalogue_item_id for si in result.stock_items}
            expected_ids = {str(cat.id) for cat in stocked_cats}
            assert returned_ids == expected_ids, (
                f"Expected {expected_ids}, got {returned_ids}"
            )
            assert result.total == num_stocked

        asyncio.run(run())


# ===========================================================================
# Property 3: Below-Threshold Flag Correctness
# ===========================================================================
# Feature: inventory-stock-management, Property 3: Below-Threshold Flag Correctness


class TestP3BelowThresholdFlagCorrectness:
    """For any stock item, is_below_threshold should be true if and only if
    current_quantity <= min_threshold AND min_threshold > 0.

    **Validates: Requirements 9.5**
    """

    @given(
        current_quantity=non_negative_quantity_st,
        min_threshold=threshold_st,
    )
    @PBT_SETTINGS
    def test_below_threshold_flag_matches_formula(
        self,
        current_quantity: Decimal,
        min_threshold: Decimal,
    ) -> None:
        """P3: is_below_threshold == (current_quantity <= min_threshold AND min_threshold > 0)."""
        org_id = uuid.uuid4()
        cat_id = uuid.uuid4()

        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_id,
            current_quantity=current_quantity,
            min_threshold=min_threshold,
        )

        response = _build_stock_item_response(
            stock_item=stock_item,
            item_name="Test Item",
            part_number="PN-001",
            brand="TestBrand",
            supplier_name=None,
        )

        expected = float(current_quantity) <= float(min_threshold) and float(min_threshold) > 0
        assert response.is_below_threshold == expected, (
            f"qty={current_quantity}, threshold={min_threshold}: "
            f"expected is_below_threshold={expected}, got {response.is_below_threshold}"
        )

    @given(
        current_quantity=positive_quantity_st,
    )
    @PBT_SETTINGS
    def test_zero_threshold_never_below(
        self,
        current_quantity: Decimal,
    ) -> None:
        """P3: when min_threshold == 0, is_below_threshold is always False."""
        org_id = uuid.uuid4()
        cat_id = uuid.uuid4()

        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_id,
            current_quantity=current_quantity,
            min_threshold=Decimal("0"),
        )

        response = _build_stock_item_response(
            stock_item=stock_item,
            item_name="Test Item",
            part_number=None,
            brand=None,
            supplier_name=None,
        )

        assert response.is_below_threshold is False


# ===========================================================================
# Property 7: Creation Produces Stock Item and Movement
# ===========================================================================
# Feature: inventory-stock-management, Property 7: Creation Produces Stock Item and Movement


class TestP7CreationProducesStockItemAndMovement:
    """For any valid creation request (existing active catalogue item,
    quantity > 0, non-empty reason), the system should create exactly one
    stock_items record AND exactly one stock_movements record.

    **Validates: Requirements 5.5, 5.6, 10.1, 10.2**
    """

    @given(
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
        barcode=barcode_st,
        cat_type=catalogue_type_st,
    )
    @PBT_SETTINGS
    def test_valid_creation_produces_one_stock_item_and_one_movement(
        self,
        quantity: float,
        reason: str,
        barcode: str | None,
        cat_type: str,
    ) -> None:
        """P7: valid create_stock_item produces exactly 1 StockItem + 1 StockMovement."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Build catalogue mock
        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(org_id, part_type=cat_type)
        else:
            cat_item = _make_fluid_product(org_id)

        payload = CreateStockItemRequest(
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
            barcode=barcode,
        )

        added_objects: list[Any] = []

        db = _make_db_with_defaults()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(cat_item),   # catalogue item found
                _FakeScalarResult(None),        # no existing stock item
                _FakeScalarResult(None),        # supplier name lookup
            ]
        )

        async def run():
            result = await create_stock_item(db, org_id, user_id, payload)

            added_objects = db._added_objects
            # Verify exactly 2 objects added: 1 StockItem + 1 StockMovement
            assert len(added_objects) == 2, (
                f"Expected 2 added objects, got {len(added_objects)}: "
                f"{[type(o).__name__ for o in added_objects]}"
            )

            stock_items_added = [o for o in added_objects if isinstance(o, StockItem)]
            movements_added = [o for o in added_objects if isinstance(o, StockMovement)]

            assert len(stock_items_added) == 1, "Expected exactly 1 StockItem"
            assert len(movements_added) == 1, "Expected exactly 1 StockMovement"

            # Verify stock item fields
            si = stock_items_added[0]
            assert si.org_id == org_id
            assert si.catalogue_item_id == cat_item.id
            assert si.catalogue_type == cat_type
            assert si.current_quantity == Decimal(str(quantity))

            # Verify movement fields
            mv = movements_added[0]
            assert mv.org_id == org_id
            assert mv.quantity_change == Decimal(str(quantity))
            assert mv.notes == reason
            assert mv.performed_by == user_id

        asyncio.run(run())


# ===========================================================================
# Property 8: Creation Input Validation
# ===========================================================================
# Feature: inventory-stock-management, Property 8: Creation Input Validation


class TestP8CreationInputValidation:
    """For any creation request where quantity <= 0 OR reason is empty/missing,
    the request should be rejected with a validation error and no records created.

    **Validates: Requirements 5.2, 5.3, 10.5**
    """

    @given(
        quantity=st.floats(min_value=-9999.0, max_value=0.0, allow_nan=False, allow_infinity=False),
        cat_type=catalogue_type_st,
    )
    @PBT_SETTINGS
    def test_non_positive_quantity_rejected(
        self,
        quantity: float,
        cat_type: str,
    ) -> None:
        """P8: quantity <= 0 is rejected by Pydantic validation."""
        import pydantic

        cat_id = uuid.uuid4()
        try:
            CreateStockItemRequest(
                catalogue_item_id=cat_id,
                catalogue_type=cat_type,
                quantity=quantity,
                reason="Test reason",
            )
            # If we get here, validation didn't reject it
            assert False, f"Expected validation error for quantity={quantity}"
        except pydantic.ValidationError:
            pass  # Expected

    @given(cat_type=catalogue_type_st)
    @PBT_SETTINGS
    def test_empty_reason_rejected(
        self,
        cat_type: str,
    ) -> None:
        """P8: empty reason is rejected by Pydantic validation."""
        import pydantic

        cat_id = uuid.uuid4()
        try:
            CreateStockItemRequest(
                catalogue_item_id=cat_id,
                catalogue_type=cat_type,
                quantity=1.0,
                reason="",
            )
            assert False, "Expected validation error for empty reason"
        except pydantic.ValidationError:
            pass  # Expected

    @given(
        quantity=st.floats(min_value=-9999.0, max_value=0.0, allow_nan=False, allow_infinity=False),
        cat_type=catalogue_type_st,
    )
    @PBT_SETTINGS
    def test_no_records_created_on_invalid_input(
        self,
        quantity: float,
        cat_type: str,
    ) -> None:
        """P8: invalid payloads never reach the service layer (Pydantic rejects first)."""
        import pydantic

        cat_id = uuid.uuid4()
        db = AsyncMock()
        added_objects: list[Any] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        try:
            payload = CreateStockItemRequest(
                catalogue_item_id=cat_id,
                catalogue_type=cat_type,
                quantity=quantity,
                reason="Test",
            )
            # Should not reach here
            assert False, "Expected validation error"
        except pydantic.ValidationError:
            # Confirm no DB objects were added
            assert len(added_objects) == 0


# ===========================================================================
# Property 9: Uniqueness Constraint
# ===========================================================================
# Feature: inventory-stock-management, Property 9: Uniqueness Constraint


class TestP9UniquenessConstraint:
    """For any organisation and catalogue item that already has a stock_items
    record, attempting to create a second stock_items record for the same
    catalogue item and organisation should return an error, and the existing
    record should remain unchanged.

    **Validates: Requirements 8.4, 10.3**
    """

    @given(
        cat_type=catalogue_type_st,
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_duplicate_creation_raises_error(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P9: creating a stock item for an already-stocked catalogue item raises ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(org_id, part_type=cat_type)
        else:
            cat_item = _make_fluid_product(org_id)

        # Existing stock item for this catalogue item
        existing_si = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            current_quantity=Decimal("50"),
        )
        original_qty = existing_si.current_quantity

        payload = CreateStockItemRequest(
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
        )

        db = AsyncMock()
        # execute calls:
        # 1. _resolve_catalogue_query -> returns catalogue item (active)
        # 2. uniqueness check -> returns existing stock item
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(cat_item),      # catalogue item found
                _FakeScalarResult(existing_si),    # existing stock item found
            ]
        )
        db.add = MagicMock()
        db.flush = AsyncMock()

        async def run():
            try:
                await create_stock_item(db, org_id, user_id, payload)
                assert False, "Expected ValueError for duplicate stock item"
            except ValueError as e:
                assert "already in stock" in str(e).lower()

            # Verify original stock item unchanged
            assert existing_si.current_quantity == original_qty
            # Verify no objects were added
            db.add.assert_not_called()

        asyncio.run(run())


# ===========================================================================
# Property 10: Invalid Catalogue Item Rejection
# ===========================================================================
# Feature: inventory-stock-management, Property 10: Invalid Catalogue Item Rejection


class TestP10InvalidCatalogueItemRejection:
    """For any creation request referencing a catalogue_item_id that does not
    exist or references an inactive catalogue item, the API should return an
    error and no records should be created.

    **Validates: Requirements 10.4**
    """

    @given(
        cat_type=catalogue_type_st,
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_nonexistent_catalogue_item_rejected(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P10: non-existent catalogue item ID raises ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        fake_cat_id = uuid.uuid4()  # Does not exist

        payload = CreateStockItemRequest(
            catalogue_item_id=fake_cat_id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
        )

        added_objects: list[Any] = []

        db = AsyncMock()
        # _resolve_catalogue_query returns None (not found)
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(None),  # catalogue item not found
            ]
        )
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.flush = AsyncMock()

        async def run():
            try:
                await create_stock_item(db, org_id, user_id, payload)
                assert False, "Expected ValueError for non-existent catalogue item"
            except ValueError as e:
                assert "not found" in str(e).lower() or "inactive" in str(e).lower()

            # No records created
            assert len(added_objects) == 0

        asyncio.run(run())

    @given(
        cat_type=st.sampled_from(["part", "tyre"]),
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_inactive_catalogue_item_rejected(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P10: inactive catalogue item is rejected (query filters by is_active)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # The _resolve_catalogue_query filters by is_active=True,
        # so an inactive item won't be returned — result is None
        payload = CreateStockItemRequest(
            catalogue_item_id=uuid.uuid4(),
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
        )

        added_objects: list[Any] = []

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(None),  # inactive item filtered out by query
            ]
        )
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        db.flush = AsyncMock()

        async def run():
            try:
                await create_stock_item(db, org_id, user_id, payload)
                assert False, "Expected ValueError for inactive catalogue item"
            except ValueError as e:
                assert "not found" in str(e).lower() or "inactive" in str(e).lower()

            assert len(added_objects) == 0

        asyncio.run(run())


# ===========================================================================
# Property 11: Supplier Resolution from Catalogue
# ===========================================================================
# Feature: inventory-stock-management, Property 11: Supplier Resolution from Catalogue


class TestP11SupplierResolutionFromCatalogue:
    """For any catalogue item with an associated supplier_id, when a stock item
    is created without an explicit supplier_id in the request, the created
    stock_items record should have its supplier_id set to the catalogue item's
    supplier. For any catalogue item without a supplier, the supplier_id should
    be null unless explicitly provided.

    **Validates: Requirements 6.1, 6.4**
    """

    @given(
        cat_type=catalogue_type_st,
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_supplier_inherited_from_catalogue_when_not_provided(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P11: supplier_id defaults to catalogue item's supplier when not in request."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        catalogue_supplier_id = uuid.uuid4()

        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(
                org_id, part_type=cat_type, supplier_id=catalogue_supplier_id,
            )
        else:
            cat_item = _make_fluid_product(
                org_id, supplier_id=catalogue_supplier_id,
            )

        payload = CreateStockItemRequest(
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
            supplier_id=None,  # Not provided
        )

        db = _make_db_with_defaults()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(cat_item),   # catalogue item found
                _FakeScalarResult(None),        # no existing stock item
                _FakeScalarResult("Test Supplier"),  # supplier name lookup
            ]
        )

        async def run():
            result = await create_stock_item(db, org_id, user_id, payload)

            # Find the created StockItem
            stock_items_added = [o for o in db._added_objects if isinstance(o, StockItem)]
            assert len(stock_items_added) == 1
            si = stock_items_added[0]

            # Supplier should be inherited from catalogue
            assert si.supplier_id == catalogue_supplier_id, (
                f"Expected supplier_id={catalogue_supplier_id}, got {si.supplier_id}"
            )

        asyncio.run(run())

    @given(
        cat_type=catalogue_type_st,
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_no_supplier_when_catalogue_has_none(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P11: supplier_id is None when catalogue item has no supplier and none provided."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(
                org_id, part_type=cat_type, supplier_id=None,
            )
        else:
            cat_item = _make_fluid_product(
                org_id, supplier_id=None,
            )

        payload = CreateStockItemRequest(
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
            supplier_id=None,
        )

        db = _make_db_with_defaults()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(cat_item),   # catalogue item found
                _FakeScalarResult(None),        # no existing stock item
                # No supplier name lookup since supplier_id is None
            ]
        )

        async def run():
            result = await create_stock_item(db, org_id, user_id, payload)

            stock_items_added = [o for o in db._added_objects if isinstance(o, StockItem)]
            assert len(stock_items_added) == 1
            si = stock_items_added[0]

            assert si.supplier_id is None, (
                f"Expected supplier_id=None, got {si.supplier_id}"
            )

        asyncio.run(run())

    @given(
        cat_type=catalogue_type_st,
        quantity=st.floats(min_value=0.01, max_value=9999.0, allow_nan=False, allow_infinity=False),
        reason=reason_st,
    )
    @PBT_SETTINGS
    def test_explicit_supplier_overrides_catalogue(
        self,
        cat_type: str,
        quantity: float,
        reason: str,
    ) -> None:
        """P11: explicit supplier_id in request overrides catalogue supplier."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        catalogue_supplier_id = uuid.uuid4()
        override_supplier_id = uuid.uuid4()

        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(
                org_id, part_type=cat_type, supplier_id=catalogue_supplier_id,
            )
        else:
            cat_item = _make_fluid_product(
                org_id, supplier_id=catalogue_supplier_id,
            )

        payload = CreateStockItemRequest(
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            quantity=quantity,
            reason=reason,
            supplier_id=override_supplier_id,
        )

        db = _make_db_with_defaults()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(cat_item),   # catalogue item found
                _FakeScalarResult(None),        # no existing stock item
                _FakeScalarResult("Override Supplier"),  # supplier name lookup
            ]
        )

        async def run():
            result = await create_stock_item(db, org_id, user_id, payload)

            stock_items_added = [o for o in db._added_objects if isinstance(o, StockItem)]
            assert len(stock_items_added) == 1
            si = stock_items_added[0]

            # Explicit supplier should override catalogue supplier
            assert si.supplier_id == override_supplier_id, (
                f"Expected supplier_id={override_supplier_id}, got {si.supplier_id}"
            )

        asyncio.run(run())
