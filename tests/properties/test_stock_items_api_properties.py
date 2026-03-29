"""Property-based tests for stock items API endpoints.

Properties covered:
  P2  — Response Data Correctness
  P5  — Multi-Field Search
  P12 — Barcode Update Round-Trip

**Validates: Requirements 1.3, 4.2, 7.2, 7.3, 7.4, 9.3, 9.4**
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
from app.modules.inventory.stock_items_schemas import UpdateStockItemRequest
from app.modules.inventory.stock_items_service import (
    _build_stock_item_response,
    list_stock_items,
    update_stock_item,
)
from app.modules.catalogue.models import PartsCatalogue
from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.suppliers.models import Supplier

# Import to ensure SQLAlchemy mapper can resolve relationships
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

barcode_st = st.one_of(
    st.none(),
    st.from_regex(r"[A-Z0-9]{6,20}", fullmatch=True),
)

non_empty_barcode_st = st.from_regex(r"[A-Z0-9]{6,20}", fullmatch=True)


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


class _MutableStockItem:
    """Plain object that mimics StockItem but allows attribute assignment.

    MagicMock(spec=StockItem) blocks __setattr__ override, so we use a
    simple class for tests that need to mutate stock item fields (e.g. update).
    """

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)


def _make_parts_catalogue(
    org_id: uuid.UUID,
    part_type: str = "part",
    supplier_id: uuid.UUID | None = None,
    name: str = "Test Part",
    part_number: str | None = None,
    brand: str | None = None,
    is_active: bool = True,
) -> MagicMock:
    """Build a mock PartsCatalogue object."""
    cat = MagicMock(spec=PartsCatalogue)
    cat.id = uuid.uuid4()
    cat.org_id = org_id
    cat.name = name
    cat.part_number = part_number or f"PN-{uuid.uuid4().hex[:6].upper()}"
    cat.brand = brand or "TestBrand"
    cat.part_type = part_type
    cat.supplier_id = supplier_id
    cat.is_active = is_active
    cat.description = "Test description"
    # Packaging fields that should NOT appear in stock response
    cat.qty_per_pack = 48
    cat.current_stock = 999
    return cat


def _make_fluid_product(
    org_id: uuid.UUID,
    supplier_id: uuid.UUID | None = None,
    oil_type: str | None = "Engine Oil",
    grade: str | None = "5W-30",
    product_name: str | None = None,
    brand_name: str | None = None,
    is_active: bool = True,
) -> MagicMock:
    """Build a mock FluidOilProduct object."""
    fluid = MagicMock(spec=FluidOilProduct)
    fluid.id = uuid.uuid4()
    fluid.org_id = org_id
    fluid.oil_type = oil_type
    fluid.grade = grade
    fluid.product_name = product_name
    fluid.brand_name = brand_name or "FluidBrand"
    fluid.supplier_id = supplier_id
    fluid.is_active = is_active
    fluid.description = "Test fluid"
    # Packaging fields that should NOT appear in stock response
    fluid.total_volume = Decimal("48.0")
    fluid.current_stock = 999
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
# Property 2: Response Data Correctness
# ===========================================================================
# Feature: inventory-stock-management, Property 2: Response Data Correctness


class TestP2ResponseDataCorrectness:
    """For any stock item returned by the API, the current_quantity field should
    equal the stock_items.current_quantity value (not the catalogue's qty_per_pack,
    total_volume, or current_stock), the item_name/part_number/brand fields should
    match the joined catalogue record, and the barcode field should match the
    stock_items.barcode value.

    **Validates: Requirements 1.3, 9.3, 9.4, 7.2**
    """

    @given(
        stock_qty=positive_quantity_st,
        cat_name=safe_text_st,
        cat_part_number=safe_text_st,
        cat_brand=safe_text_st,
        barcode=barcode_st,
    )
    @PBT_SETTINGS
    def test_parts_response_uses_stock_quantity_not_packaging(
        self,
        stock_qty: Decimal,
        cat_name: str,
        cat_part_number: str,
        cat_brand: str,
        barcode: str | None,
    ) -> None:
        """P2: For parts, response current_quantity comes from stock_items, not catalogue packaging."""
        org_id = uuid.uuid4()
        supplier_id = uuid.uuid4()
        supplier_name = "Acme Supplier"

        cat_item = _make_parts_catalogue(
            org_id,
            part_type="part",
            name=cat_name,
            part_number=cat_part_number,
            brand=cat_brand,
            supplier_id=supplier_id,
        )

        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
            current_quantity=stock_qty,
            supplier_id=supplier_id,
            barcode=barcode,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),       # stock items query
                _FakeScalarResult(items=[cat_item]),          # parts batch load
                _FakeScalarResult(items=[(supplier_id, supplier_name)]),  # suppliers batch
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id)
            assert result.total == 1
            resp = result.stock_items[0]

            # current_quantity must come from stock_items, NOT catalogue packaging
            assert resp.current_quantity == float(stock_qty), (
                f"Expected stock qty {float(stock_qty)}, got {resp.current_quantity}. "
                f"Catalogue qty_per_pack={cat_item.qty_per_pack} should NOT be used."
            )

            # Catalogue fields must match
            assert resp.item_name == cat_name
            assert resp.part_number == cat_part_number
            assert resp.brand == cat_brand

            # Barcode must come from stock_items
            assert resp.barcode == barcode

            # Supplier name must be resolved
            assert resp.supplier_name == supplier_name

        asyncio.run(run())

    @given(
        stock_qty=positive_quantity_st,
        oil_type=st.sampled_from(["Engine Oil", "Transmission Fluid", "Brake Fluid"]),
        grade=st.one_of(st.none(), st.sampled_from(["5W-30", "10W-40", "ATF"])),
        fluid_brand=safe_text_st,
        barcode=barcode_st,
    )
    @PBT_SETTINGS
    def test_fluids_response_uses_stock_quantity_not_volume(
        self,
        stock_qty: Decimal,
        oil_type: str,
        grade: str | None,
        fluid_brand: str,
        barcode: str | None,
    ) -> None:
        """P2: For fluids, response current_quantity comes from stock_items, not total_volume."""
        org_id = uuid.uuid4()

        cat_fluid = _make_fluid_product(
            org_id,
            oil_type=oil_type,
            grade=grade,
            brand_name=fluid_brand,
        )

        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_fluid.id,
            catalogue_type="fluid",
            current_quantity=stock_qty,
            barcode=barcode,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),       # stock items query
                _FakeScalarResult(items=[cat_fluid]),         # fluids batch load
                # No suppliers batch (no supplier_id)
            ]
        )

        expected_name = f"{oil_type} {grade}".strip() if grade else oil_type

        async def run():
            result = await list_stock_items(db, org_id)
            assert result.total == 1
            resp = result.stock_items[0]

            # current_quantity must come from stock_items, NOT catalogue total_volume
            assert resp.current_quantity == float(stock_qty), (
                f"Expected stock qty {float(stock_qty)}, got {resp.current_quantity}. "
                f"Catalogue total_volume={cat_fluid.total_volume} should NOT be used."
            )

            # Catalogue fields must match
            assert resp.item_name == expected_name
            assert resp.part_number is None  # fluids don't have part numbers
            assert resp.brand == fluid_brand

            # Barcode must come from stock_items
            assert resp.barcode == barcode

        asyncio.run(run())

    @given(
        stock_qty=positive_quantity_st,
        min_thresh=threshold_st,
        reorder_qty=non_negative_quantity_st,
    )
    @PBT_SETTINGS
    def test_response_fields_from_stock_items_table(
        self,
        stock_qty: Decimal,
        min_thresh: Decimal,
        reorder_qty: Decimal,
    ) -> None:
        """P2: Verify threshold and reorder fields come from stock_items, not catalogue."""
        org_id = uuid.uuid4()

        cat_item = _make_parts_catalogue(org_id, name="Threshold Test Part")
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
            current_quantity=stock_qty,
            min_threshold=min_thresh,
            reorder_quantity=reorder_qty,
        )

        # Use _build_stock_item_response directly to verify field mapping
        resp = _build_stock_item_response(
            stock_item=stock_item,
            item_name="Threshold Test Part",
            part_number=cat_item.part_number,
            brand=cat_item.brand,
            supplier_name=None,
        )

        assert resp.current_quantity == float(stock_qty)
        assert resp.min_threshold == float(min_thresh)
        assert resp.reorder_quantity == float(reorder_qty)
        assert resp.id == str(stock_item.id)
        assert resp.catalogue_item_id == str(stock_item.catalogue_item_id)


# ===========================================================================
# Property 5: Multi-Field Search
# ===========================================================================
# Feature: inventory-stock-management, Property 5: Multi-Field Search


class TestP5MultiFieldSearch:
    """For any search query string q and any stock item, the item should appear
    in search results if and only if q is a case-insensitive substring of at
    least one of: item name, part number, brand, or barcode.

    **Validates: Requirements 4.2, 7.3**
    """

    @given(
        cat_name=safe_text_st,
        cat_part_number=safe_text_st,
        cat_brand=safe_text_st,
        item_barcode=non_empty_barcode_st,
    )
    @PBT_SETTINGS
    def test_search_by_name_matches(
        self,
        cat_name: str,
        cat_part_number: str,
        cat_brand: str,
        item_barcode: str,
    ) -> None:
        """P5: searching by a substring of item_name returns the item."""
        assume(len(cat_name) >= 2)
        org_id = uuid.uuid4()

        cat_item = _make_parts_catalogue(
            org_id, name=cat_name, part_number=cat_part_number, brand=cat_brand,
        )
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
            barcode=item_barcode,
        )

        # Use a substring of the name as search query
        search_query = cat_name[:max(1, len(cat_name) // 2)]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),
                _FakeScalarResult(items=[cat_item]),
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id, search=search_query)
            returned_ids = {si.catalogue_item_id for si in result.stock_items}
            assert str(cat_item.id) in returned_ids, (
                f"Search '{search_query}' should match item name '{cat_name}'"
            )

        asyncio.run(run())

    @given(
        cat_part_number=safe_text_st,
    )
    @PBT_SETTINGS
    def test_search_by_part_number_matches(
        self,
        cat_part_number: str,
    ) -> None:
        """P5: searching by a substring of part_number returns the item."""
        assume(len(cat_part_number) >= 2)
        org_id = uuid.uuid4()

        cat_item = _make_parts_catalogue(
            org_id, name="Some Part", part_number=cat_part_number, brand="SomeBrand",
        )
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
        )

        search_query = cat_part_number[:max(1, len(cat_part_number) // 2)]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),
                _FakeScalarResult(items=[cat_item]),
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id, search=search_query)
            returned_ids = {si.catalogue_item_id for si in result.stock_items}
            assert str(cat_item.id) in returned_ids, (
                f"Search '{search_query}' should match part_number '{cat_part_number}'"
            )

        asyncio.run(run())

    @given(
        cat_brand=safe_text_st,
    )
    @PBT_SETTINGS
    def test_search_by_brand_matches(
        self,
        cat_brand: str,
    ) -> None:
        """P5: searching by a substring of brand returns the item."""
        assume(len(cat_brand) >= 2)
        org_id = uuid.uuid4()

        cat_item = _make_parts_catalogue(
            org_id, name="Some Part", part_number="PN-001", brand=cat_brand,
        )
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
        )

        search_query = cat_brand[:max(1, len(cat_brand) // 2)]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),
                _FakeScalarResult(items=[cat_item]),
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id, search=search_query)
            returned_ids = {si.catalogue_item_id for si in result.stock_items}
            assert str(cat_item.id) in returned_ids, (
                f"Search '{search_query}' should match brand '{cat_brand}'"
            )

        asyncio.run(run())

    @given(
        item_barcode=non_empty_barcode_st,
    )
    @PBT_SETTINGS
    def test_search_by_barcode_matches(
        self,
        item_barcode: str,
    ) -> None:
        """P5: searching by a substring of barcode returns the item."""
        assume(len(item_barcode) >= 2)
        org_id = uuid.uuid4()

        cat_item = _make_parts_catalogue(
            org_id, name="Barcode Part", part_number="PN-BC", brand="BCBrand",
        )
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
            barcode=item_barcode,
        )

        search_query = item_barcode[:max(1, len(item_barcode) // 2)]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),
                _FakeScalarResult(items=[cat_item]),
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id, search=search_query)
            returned_ids = {si.catalogue_item_id for si in result.stock_items}
            assert str(cat_item.id) in returned_ids, (
                f"Search '{search_query}' should match barcode '{item_barcode}'"
            )

        asyncio.run(run())

    @given(
        cat_name=safe_text_st,
        cat_part_number=safe_text_st,
        cat_brand=safe_text_st,
        item_barcode=barcode_st,
    )
    @PBT_SETTINGS
    def test_non_matching_search_excludes_item(
        self,
        cat_name: str,
        cat_part_number: str,
        cat_brand: str,
        item_barcode: str | None,
    ) -> None:
        """P5: a search query that doesn't match any field excludes the item."""
        org_id = uuid.uuid4()

        # Use a search string guaranteed not to match any field
        non_matching = "ZZZZXQJK9999NOMATCH"
        assume(non_matching.lower() not in cat_name.lower())
        assume(non_matching.lower() not in cat_part_number.lower())
        assume(non_matching.lower() not in cat_brand.lower())
        assume(item_barcode is None or non_matching.lower() not in item_barcode.lower())

        cat_item = _make_parts_catalogue(
            org_id, name=cat_name, part_number=cat_part_number, brand=cat_brand,
        )
        stock_item = _make_stock_item(
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type="part",
            barcode=item_barcode,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(items=[stock_item]),
                _FakeScalarResult(items=[cat_item]),
            ]
        )

        async def run():
            result = await list_stock_items(db, org_id, search=non_matching)
            assert result.total == 0, (
                f"Search '{non_matching}' should not match item with "
                f"name='{cat_name}', pn='{cat_part_number}', brand='{cat_brand}', "
                f"barcode='{item_barcode}'"
            )

        asyncio.run(run())


# ===========================================================================
# Property 12: Barcode Update Round-Trip
# ===========================================================================
# Feature: inventory-stock-management, Property 12: Barcode Update Round-Trip


class TestP12BarcodeUpdateRoundTrip:
    """For any stock item and any valid barcode string, updating the barcode
    via the update endpoint and then retrieving the stock item should return
    the same barcode value.

    **Validates: Requirements 7.4**
    """

    @given(
        new_barcode=non_empty_barcode_st,
        cat_type=catalogue_type_st,
    )
    @PBT_SETTINGS
    def test_barcode_update_then_retrieve_matches(
        self,
        new_barcode: str,
        cat_type: str,
    ) -> None:
        """P12: update barcode via update_stock_item, then verify it persists."""
        org_id = uuid.uuid4()

        # Build catalogue item for the response resolution
        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(org_id, part_type=cat_type, name="Round Trip Part")
        else:
            cat_item = _make_fluid_product(org_id, oil_type="Engine Oil", grade="5W-30")

        # Use a simple namespace object that allows attribute assignment
        stock_item_id = uuid.uuid4()
        si = _MutableStockItem(
            id=stock_item_id,
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            current_quantity=Decimal("10"),
            min_threshold=Decimal("5"),
            reorder_quantity=Decimal("20"),
            supplier_id=None,
            barcode="OLD_BARCODE",
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        payload = UpdateStockItemRequest(barcode=new_barcode)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(si),              # find stock item
                _FakeScalarResult(cat_item),         # catalogue lookup for response
                # No supplier lookup (supplier_id is None)
            ]
        )
        db.flush = AsyncMock()

        async def run():
            result = await update_stock_item(db, org_id, stock_item_id, payload)

            # The barcode in the response should match what we set
            assert result.barcode == new_barcode, (
                f"Expected barcode '{new_barcode}', got '{result.barcode}'"
            )

        asyncio.run(run())

    @given(
        initial_barcode=non_empty_barcode_st,
        updated_barcode=non_empty_barcode_st,
        cat_type=catalogue_type_st,
    )
    @PBT_SETTINGS
    def test_barcode_overwrite_preserves_new_value(
        self,
        initial_barcode: str,
        updated_barcode: str,
        cat_type: str,
    ) -> None:
        """P12: overwriting an existing barcode with a new one returns the new value."""
        assume(initial_barcode != updated_barcode)
        org_id = uuid.uuid4()

        if cat_type in ("part", "tyre"):
            cat_item = _make_parts_catalogue(org_id, part_type=cat_type, name="Overwrite Part")
        else:
            cat_item = _make_fluid_product(org_id, oil_type="Brake Fluid", grade=None)

        stock_item_id = uuid.uuid4()
        si = _MutableStockItem(
            id=stock_item_id,
            org_id=org_id,
            catalogue_item_id=cat_item.id,
            catalogue_type=cat_type,
            current_quantity=Decimal("25"),
            min_threshold=Decimal("3"),
            reorder_quantity=Decimal("10"),
            supplier_id=None,
            barcode=initial_barcode,
            created_by=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        payload = UpdateStockItemRequest(barcode=updated_barcode)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(si),
                _FakeScalarResult(cat_item),
            ]
        )
        db.flush = AsyncMock()

        async def run():
            result = await update_stock_item(db, org_id, stock_item_id, payload)

            # Must be the NEW barcode, not the initial one
            assert result.barcode == updated_barcode, (
                f"Expected updated barcode '{updated_barcode}', "
                f"got '{result.barcode}' (initial was '{initial_barcode}')"
            )

        asyncio.run(run())
