"""Integration tests for Service Package Builder lifecycle.

Tests cover the full lifecycle of package items including CRUD operations,
invoice integration, quote handling, unavailable component handling, and
access control.

Requirements: 7.1, 7.4, 7.5, 8.1, 8.2, 8.4, 8.5, 9.4, 10.1, 10.2, 10.3, 11.1, 11.3
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
BRANCH_ID = uuid.uuid4()


def _make_part_component(
    *,
    catalogue_item_id: uuid.UUID | None = None,
    quantity: int = 1,
    cost: float = 25.00,
) -> dict:
    """Create a part component dict for testing."""
    return {
        "catalogue_item_id": str(catalogue_item_id or uuid.uuid4()),
        "catalogue_type": "part",
        "quantity": quantity,
        "cost_per_unit_snapshot": cost,
    }


def _make_fluid_component(
    *,
    catalogue_item_id: uuid.UUID | None = None,
    volume: float = 4.5,
    cost: float = 8.75,
    fluid_type: str = "oil",
    oil_type: str | None = "engine",
    grade: str | None = "5W-30",
) -> dict:
    """Create a fluid component dict for testing."""
    return {
        "catalogue_item_id": str(catalogue_item_id or uuid.uuid4()),
        "catalogue_type": "fluid",
        "volume": volume,
        "cost_per_unit_snapshot": cost,
        "fluid_type": fluid_type,
        "oil_type": oil_type,
        "grade": grade,
    }


def _make_tyre_component(
    *,
    catalogue_item_id: uuid.UUID | None = None,
    quantity: int = 4,
    cost: float = 85.00,
) -> dict:
    """Create a tyre component dict for testing."""
    return {
        "catalogue_item_id": str(catalogue_item_id or uuid.uuid4()),
        "catalogue_type": "tyre",
        "quantity": quantity,
        "cost_per_unit_snapshot": cost,
    }


def _mock_db_for_create(components: list[dict]) -> AsyncMock:
    """Create a mock DB session configured for create_item with component validation."""
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    execute_results = []
    for comp in components:
        # Catalogue lookup
        cat_mock = MagicMock()
        cat_row = MagicMock()
        cat_row.id = uuid.UUID(comp["catalogue_item_id"])
        cat_row.cost_per_unit = Decimal(str(comp.get("cost_per_unit_snapshot", 10.0)))
        cat_mock.one_or_none.return_value = cat_row
        execute_results.append(cat_mock)

        # Stock item lookup (None = use catalogue cost)
        stock_mock = MagicMock()
        stock_mock.one_or_none.return_value = None
        execute_results.append(stock_mock)

    mock_db.execute = AsyncMock(side_effect=execute_results)
    return mock_db


def _make_mock_item(
    *,
    item_id: uuid.UUID | None = None,
    name: str = "Full Service - 5W30",
    price: str = "120.00",
    is_package: bool = True,
    package_components: list[dict] | None = None,
) -> MagicMock:
    """Create a mock ItemsCatalogue ORM object."""
    item = MagicMock()
    item.id = item_id or uuid.uuid4()
    item.org_id = ORG_ID
    item.name = name
    item.description = "Full service package"
    item.default_price = Decimal(price)
    item.is_gst_exempt = False
    item.gst_inclusive = False
    item.category = "service"
    item.is_active = True
    item.is_package = is_package
    item.package_components = package_components
    item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return item


# ===========================================================================
# 16.1 Full lifecycle: create -> edit -> duplicate -> delete package item
# Requirements: 7.1, 7.4, 7.5, 9.4
# ===========================================================================


class TestPackageLifecycleCRUD:
    """Integration test: full lifecycle create -> edit -> duplicate -> delete.

    Validates that all CRUD operations work correctly and maintain data integrity
    throughout the package item lifecycle.

    Requirements: 7.1, 7.4, 7.5, 9.4
    """

    @pytest.mark.asyncio
    async def test_create_package_with_all_component_types(self):
        """Create a package with parts + fluids + tyres and verify persistence.

        Requirements: 7.1
        """
        from app.modules.catalogue.service import create_item

        part_id = uuid.uuid4()
        fluid_id = uuid.uuid4()
        tyre_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
            _make_fluid_component(catalogue_item_id=fluid_id, volume=4.5, cost=8.75),
            _make_tyre_component(catalogue_item_id=tyre_id, quantity=4, cost=85.00),
        ]

        mock_db = _mock_db_for_create(components)

        # Track what gets persisted via the ORM constructor
        created_item = _make_mock_item(package_components=None)

        def fake_constructor(**kwargs):
            for k, v in kwargs.items():
                setattr(created_item, k, v)
            return created_item

        with patch(
            "app.modules.catalogue.service.ItemsCatalogue",
            side_effect=fake_constructor,
        ), patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_item(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                name="Full Service - 5W30",
                default_price="120.00",
                category="service",
                is_package=True,
                package_components=components,
            )

        # Verify the item was created as a package
        assert created_item.is_package is True
        assert created_item.package_components is not None
        assert len(created_item.package_components) == 3

        # Verify component types are preserved
        types = [c["catalogue_type"] for c in created_item.package_components]
        assert "part" in types
        assert "fluid" in types
        assert "tyre" in types

        # Verify quantities/volumes preserved
        part_comp = next(c for c in created_item.package_components if c["catalogue_type"] == "part")
        assert part_comp["quantity"] == 2
        assert part_comp["catalogue_item_id"] == str(part_id)

        fluid_comp = next(c for c in created_item.package_components if c["catalogue_type"] == "fluid")
        assert fluid_comp["volume"] == 4.5
        assert fluid_comp["catalogue_item_id"] == str(fluid_id)

        tyre_comp = next(c for c in created_item.package_components if c["catalogue_type"] == "tyre")
        assert tyre_comp["quantity"] == 4
        assert tyre_comp["catalogue_item_id"] == str(tyre_id)

    @pytest.mark.asyncio
    async def test_edit_package_replaces_components(self):
        """Edit a package: update quantities and replace component set.

        Requirements: 7.4, 7.5
        """
        from app.modules.catalogue.service import update_item

        item_id = uuid.uuid4()
        original_part_id = uuid.uuid4()
        new_part_id = uuid.uuid4()

        original_components = [
            _make_part_component(catalogue_item_id=original_part_id, quantity=1, cost=10.00),
        ]
        new_components = [
            _make_part_component(catalogue_item_id=new_part_id, quantity=3, cost=15.00),
            _make_fluid_component(volume=5.0, cost=9.00),
        ]

        # Mock existing item
        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=original_components,
        )

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # First execute returns the existing item, then validation queries
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        validation_results = []
        for comp in new_components:
            cat_mock = MagicMock()
            cat_row = MagicMock()
            cat_row.id = uuid.UUID(comp["catalogue_item_id"])
            cat_row.cost_per_unit = Decimal(str(comp.get("cost_per_unit_snapshot", 10.0)))
            cat_mock.one_or_none.return_value = cat_row
            validation_results.append(cat_mock)

            stock_mock = MagicMock()
            stock_mock.one_or_none.return_value = None
            validation_results.append(stock_mock)

        mock_db.execute = AsyncMock(side_effect=[item_result] + validation_results)

        with patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_item(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                item_id=item_id,
                is_package=True,
                package_components=new_components,
            )

        # Verify components were replaced (not merged)
        assert mock_item.package_components is not None
        assert len(mock_item.package_components) == 2

        # Original component should NOT be present
        final_ids = {c["catalogue_item_id"] for c in mock_item.package_components}
        assert str(original_part_id) not in final_ids
        assert str(new_part_id) in final_ids

    @pytest.mark.asyncio
    async def test_duplicate_package_preserves_components(self):
        """Duplicate a package: new ID but identical components.

        Requirements: 9.4
        """
        from app.modules.catalogue.service import duplicate_item
        from app.modules.catalogue.models import ItemsCatalogue

        item_id = uuid.uuid4()
        duplicate_id = uuid.uuid4()
        part_id = uuid.uuid4()
        fluid_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
            _make_fluid_component(catalogue_item_id=fluid_id, volume=4.5, cost=8.75),
        ]

        # Mock existing item
        mock_item = _make_mock_item(
            item_id=item_id,
            name="Full Service - 5W30",
            package_components=components,
        )

        # Create a mock duplicate that will be returned by the constructor
        mock_duplicate = _make_mock_item(
            item_id=duplicate_id,
            name="Full Service - 5W30 (Copy)",
            package_components=copy.deepcopy(components),
        )

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # First execute returns the original item
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=item_result)

        # Patch select to avoid ORM registry issues, and patch ItemsCatalogue constructor
        real_select = __import__("sqlalchemy", fromlist=["select"]).select

        def patched_select(*args, **kwargs):
            """Return a mock select statement that chains .where()."""
            mock_stmt = MagicMock()
            mock_stmt.where = MagicMock(return_value=mock_stmt)
            return mock_stmt

        with patch(
            "app.modules.catalogue.service.select",
            side_effect=patched_select,
        ), patch(
            "app.modules.catalogue.service.ItemsCatalogue",
            return_value=mock_duplicate,
        ), patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await duplicate_item(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                item_id=item_id,
            )

        # Verify duplicate has different ID
        assert result["id"] == str(duplicate_id)
        assert result["id"] != str(item_id)

        # Verify components are preserved in the duplicate
        assert mock_duplicate.package_components is not None
        assert len(mock_duplicate.package_components) == 2

        # Verify component data is identical
        for orig, dup_comp in zip(components, mock_duplicate.package_components):
            assert dup_comp["catalogue_item_id"] == orig["catalogue_item_id"]
            assert dup_comp["catalogue_type"] == orig["catalogue_type"]
            if orig["catalogue_type"] in ("part", "tyre"):
                assert dup_comp["quantity"] == orig["quantity"]
            elif orig["catalogue_type"] == "fluid":
                assert dup_comp["volume"] == orig["volume"]
            assert dup_comp["cost_per_unit_snapshot"] == orig["cost_per_unit_snapshot"]

        # Verify name has " (Copy)" suffix
        assert result["name"] == "Full Service - 5W30 (Copy)"

    @pytest.mark.asyncio
    async def test_delete_original_after_duplicate(self):
        """After duplicating, the original can be deleted (set inactive).

        Requirements: 7.4
        """
        from app.modules.catalogue.service import update_item

        item_id = uuid.uuid4()
        components = [_make_part_component(quantity=1, cost=10.00)]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item
        mock_db.execute = AsyncMock(return_value=item_result)

        with patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_item(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                item_id=item_id,
                is_active=False,
            )

        # Verify item was deactivated
        assert mock_item.is_active is False
        # Package data remains intact (soft delete)
        assert mock_item.is_package is True
        assert mock_item.package_components == components


# ===========================================================================
# 16.2 Package item on invoice: cost calculation + inventory deduction
# Requirements: 8.1, 8.2, 8.4
# ===========================================================================


class TestPackageOnInvoice:
    """Integration test: package item on invoice with cost calc and deduction.

    Validates that cost_price matches live component costs, stock is decremented
    correctly, and fluid_usage entries are written.

    Requirements: 8.1, 8.2, 8.4
    """

    @pytest.mark.asyncio
    async def test_resolve_package_cost_from_live_stock_prices(self):
        """cost_price matches sum of live component costs from stock_items.

        Requirements: 8.1
        """
        from app.modules.invoices.package_service import resolve_package_line_item

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()
        fluid_id = uuid.uuid4()
        tyre_id = uuid.uuid4()
        stock_part_id = uuid.uuid4()
        stock_fluid_id = uuid.uuid4()
        stock_tyre_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
            _make_fluid_component(catalogue_item_id=fluid_id, volume=4.5, cost=8.75),
            _make_tyre_component(catalogue_item_id=tyre_id, quantity=4, cost=85.00),
        ]

        # Mock the catalogue item
        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        # Mock stock items with live prices (different from snapshot)
        live_part_cost = Decimal("14.00")
        live_fluid_cost = Decimal("9.50")
        live_tyre_cost = Decimal("90.00")

        mock_db = AsyncMock()

        # Build execute side effects:
        # 1. Fetch the catalogue item
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # For each component: catalogue check + stock item lookup
        # Part component
        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.id = part_id
        part_cat_row.is_active = True
        part_cat_row.name = "Oil Filter"
        part_cat_row.cost_per_unit = Decimal("12.50")
        part_cat_result.one_or_none.return_value = part_cat_row

        part_stock_item = MagicMock()
        part_stock_item.id = stock_part_id
        part_stock_item.purchase_price = live_part_cost
        part_stock_item.cost_per_unit = live_part_cost
        part_stock_item.current_quantity = Decimal("15")
        part_stock_result = MagicMock()
        part_stock_result.scalar_one_or_none.return_value = part_stock_item

        # Fluid component
        fluid_cat_result = MagicMock()
        fluid_cat_row = MagicMock()
        fluid_cat_row.id = fluid_id
        fluid_cat_row.is_active = True
        fluid_cat_row.product_name = "Penrite HPR 5W-30"
        fluid_cat_row.cost_per_unit = Decimal("8.75")
        fluid_cat_result.one_or_none.return_value = fluid_cat_row

        fluid_stock_item = MagicMock()
        fluid_stock_item.id = stock_fluid_id
        fluid_stock_item.purchase_price = live_fluid_cost
        fluid_stock_item.cost_per_unit = live_fluid_cost
        fluid_stock_item.current_quantity = Decimal("22.5")
        fluid_stock_result = MagicMock()
        fluid_stock_result.scalar_one_or_none.return_value = fluid_stock_item

        # Tyre component
        tyre_cat_result = MagicMock()
        tyre_cat_row = MagicMock()
        tyre_cat_row.id = tyre_id
        tyre_cat_row.is_active = True
        tyre_cat_row.name = "Bridgestone RE003"
        tyre_cat_row.cost_per_unit = Decimal("85.00")
        tyre_cat_result.one_or_none.return_value = tyre_cat_row

        tyre_stock_item = MagicMock()
        tyre_stock_item.id = stock_tyre_id
        tyre_stock_item.purchase_price = live_tyre_cost
        tyre_stock_item.cost_per_unit = live_tyre_cost
        tyre_stock_item.current_quantity = Decimal("8")
        tyre_stock_result = MagicMock()
        tyre_stock_result.scalar_one_or_none.return_value = tyre_stock_item

        mock_db.execute = AsyncMock(side_effect=[
            item_result,           # Fetch catalogue item
            part_cat_result,       # Part catalogue check
            part_stock_result,     # Part stock lookup
            fluid_cat_result,      # Fluid catalogue check
            fluid_stock_result,    # Fluid stock lookup
            tyre_cat_result,       # Tyre catalogue check
            tyre_stock_result,     # Tyre stock lookup
        ])

        result = await resolve_package_line_item(
            mock_db,
            org_id=ORG_ID,
            catalogue_item_id=item_id,
        )

        # Verify it's recognized as a package
        assert result["is_package"] is True

        # Calculate expected cost from live prices
        # Part: 14.00 * 2 = 28.00
        # Fluid: 9.50 * 4.5 = 42.75
        # Tyre: 90.00 * 4 = 360.00
        # Total: 430.75
        expected_cost = Decimal("28.00") + Decimal("42.75") + Decimal("360.00")
        assert result["cost_price"] == expected_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Verify components are resolved
        assert len(result["components"]) == 3

    @pytest.mark.asyncio
    async def test_deduct_inventory_on_invoice_issue(self):
        """Stock decremented correctly for each component on invoice issue.

        Requirements: 8.2
        """
        from app.modules.invoices.package_service import deduct_package_inventory

        invoice_id = uuid.uuid4()
        stock_part_id = uuid.uuid4()
        stock_fluid_id = uuid.uuid4()
        stock_tyre_id = uuid.uuid4()

        # Resolved components (as returned by resolve_package_line_item)
        resolved_components = [
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "part",
                "name": "Oil Filter",
                "quantity": 2,
                "volume": None,
                "unit_cost": Decimal("14.00"),
                "line_cost": Decimal("28.00"),
                "stock_item_id": stock_part_id,
                "is_available": True,
            },
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "fluid",
                "name": "Penrite HPR 5W-30",
                "quantity": None,
                "volume": 4.5,
                "unit_cost": Decimal("9.50"),
                "line_cost": Decimal("42.75"),
                "stock_item_id": stock_fluid_id,
                "is_available": True,
            },
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "tyre",
                "name": "Bridgestone RE003",
                "quantity": 4,
                "volume": None,
                "unit_cost": Decimal("90.00"),
                "line_cost": Decimal("360.00"),
                "stock_item_id": stock_tyre_id,
                "is_available": True,
            },
        ]

        mock_db = AsyncMock()

        # Mock stock quantity checks (all have sufficient stock)
        part_stock_row = MagicMock()
        part_stock_row.current_quantity = Decimal("15")
        part_stock_check = MagicMock()
        part_stock_check.one_or_none.return_value = part_stock_row

        fluid_stock_row = MagicMock()
        fluid_stock_row.current_quantity = Decimal("22.5")
        fluid_stock_check = MagicMock()
        fluid_stock_check.one_or_none.return_value = fluid_stock_row

        tyre_stock_row = MagicMock()
        tyre_stock_row.current_quantity = Decimal("8")
        tyre_stock_check = MagicMock()
        tyre_stock_check.one_or_none.return_value = tyre_stock_row

        mock_db.execute = AsyncMock(side_effect=[
            part_stock_check,
            fluid_stock_check,
            tyre_stock_check,
        ])

        # Track deduction calls
        deduction_calls = []

        async def mock_decrement(db, *, org_id, user_id, stock_item_id, quantity, invoice_id):
            deduction_calls.append({
                "stock_item_id": stock_item_id,
                "quantity": quantity,
                "invoice_id": invoice_id,
            })
            return {"id": str(stock_item_id)}

        with patch(
            "app.modules.inventory.stock_items_service.decrement_stock_for_invoice_v2",
            side_effect=mock_decrement,
        ):
            warnings = await deduct_package_inventory(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                invoice_id=invoice_id,
                components=resolved_components,
            )

        # No warnings (sufficient stock)
        assert warnings == []

        # Verify correct deductions were made
        assert len(deduction_calls) == 3

        # Part: deduct quantity 2
        part_deduction = next(d for d in deduction_calls if d["stock_item_id"] == stock_part_id)
        assert part_deduction["quantity"] == 2.0

        # Fluid: deduct volume 4.5
        fluid_deduction = next(d for d in deduction_calls if d["stock_item_id"] == stock_fluid_id)
        assert fluid_deduction["quantity"] == 4.5

        # Tyre: deduct quantity 4
        tyre_deduction = next(d for d in deduction_calls if d["stock_item_id"] == stock_tyre_id)
        assert tyre_deduction["quantity"] == 4.0

        # All deductions reference the same invoice
        for d in deduction_calls:
            assert d["invoice_id"] == invoice_id

    @pytest.mark.asyncio
    async def test_fluid_usage_entries_written(self):
        """fluid_usage entries written to invoice_data_json for fluid components.

        Requirements: 8.4
        """
        from app.modules.invoices.package_service import write_package_fluid_usage

        stock_fluid_id = uuid.uuid4()
        fluid_catalogue_id = str(uuid.uuid4())

        resolved_components = [
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "part",
                "name": "Oil Filter",
                "quantity": 1,
                "volume": None,
                "unit_cost": Decimal("14.00"),
                "line_cost": Decimal("14.00"),
                "stock_item_id": uuid.uuid4(),
                "is_available": True,
            },
            {
                "catalogue_item_id": fluid_catalogue_id,
                "catalogue_type": "fluid",
                "name": "Penrite HPR 5W-30",
                "quantity": None,
                "volume": 4.5,
                "unit_cost": Decimal("9.50"),
                "line_cost": Decimal("42.75"),
                "stock_item_id": stock_fluid_id,
                "is_available": True,
            },
        ]

        # Mock invoice object
        mock_invoice = MagicMock()
        mock_invoice.invoice_data_json = {}

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()

        await write_package_fluid_usage(
            mock_db,
            invoice=mock_invoice,
            components=resolved_components,
        )

        # Verify fluid_usage was written
        data_json = mock_invoice.invoice_data_json
        assert "fluid_usage" in data_json
        assert len(data_json["fluid_usage"]) == 1

        fluid_entry = data_json["fluid_usage"][0]
        assert fluid_entry["stock_item_id"] == str(stock_fluid_id)
        assert fluid_entry["litres"] == 4.5
        assert fluid_entry["cost_per_litre"] == 9.50
        assert fluid_entry["total_cost"] == round(9.50 * 4.5, 2)
        assert fluid_entry["catalogue_item_id"] == fluid_catalogue_id
        assert fluid_entry["item_name"] == "Penrite HPR 5W-30"


# ===========================================================================
# 16.3 Package item on quote: no inventory deduction
# Requirements: 8.5
# ===========================================================================


class TestPackageOnQuote:
    """Integration test: package item on quote does NOT deduct inventory.

    Validates that stock quantities remain unchanged when a package item
    is added to a quote.

    Requirements: 8.5
    """

    @pytest.mark.asyncio
    async def test_quote_does_not_deduct_inventory(self):
        """Adding a package to a quote does not change stock quantities.

        Requirements: 8.5
        """
        from app.modules.invoices.package_service import handle_quote_package_item

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()
        fluid_id = uuid.uuid4()
        stock_part_id = uuid.uuid4()
        stock_fluid_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
            _make_fluid_component(catalogue_item_id=fluid_id, volume=4.5, cost=8.75),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        # Mock stock items with known quantities
        initial_part_qty = Decimal("15")
        initial_fluid_qty = Decimal("22.5")

        mock_db = AsyncMock()

        # Build execute side effects for resolve_package_line_item (called internally)
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # Part catalogue check
        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.id = part_id
        part_cat_row.is_active = True
        part_cat_row.name = "Oil Filter"
        part_cat_row.cost_per_unit = Decimal("12.50")
        part_cat_result.one_or_none.return_value = part_cat_row

        # Part stock item
        part_stock_item = MagicMock()
        part_stock_item.id = stock_part_id
        part_stock_item.purchase_price = Decimal("12.50")
        part_stock_item.cost_per_unit = Decimal("12.50")
        part_stock_item.current_quantity = initial_part_qty
        part_stock_result = MagicMock()
        part_stock_result.scalar_one_or_none.return_value = part_stock_item

        # Fluid catalogue check
        fluid_cat_result = MagicMock()
        fluid_cat_row = MagicMock()
        fluid_cat_row.id = fluid_id
        fluid_cat_row.is_active = True
        fluid_cat_row.product_name = "Penrite HPR 5W-30"
        fluid_cat_row.cost_per_unit = Decimal("8.75")
        fluid_cat_result.one_or_none.return_value = fluid_cat_row

        # Fluid stock item
        fluid_stock_item = MagicMock()
        fluid_stock_item.id = stock_fluid_id
        fluid_stock_item.purchase_price = Decimal("8.75")
        fluid_stock_item.cost_per_unit = Decimal("8.75")
        fluid_stock_item.current_quantity = initial_fluid_qty
        fluid_stock_result = MagicMock()
        fluid_stock_result.scalar_one_or_none.return_value = fluid_stock_item

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            part_cat_result,
            part_stock_result,
            fluid_cat_result,
            fluid_stock_result,
        ])

        result = await handle_quote_package_item(
            mock_db,
            org_id=ORG_ID,
            catalogue_item_id=item_id,
        )

        # Verify it returns cost preview
        assert result["is_package"] is True
        assert result["cost_price"] is not None
        assert result["cost_price"] > 0

        # Verify stock quantities are UNCHANGED (no deduction occurred)
        # The mock stock items should not have been modified
        assert part_stock_item.current_quantity == initial_part_qty
        assert fluid_stock_item.current_quantity == initial_fluid_qty

    @pytest.mark.asyncio
    async def test_quote_returns_cost_preview(self):
        """Quote handler returns cost/profit preview data.

        Requirements: 8.5
        """
        from app.modules.invoices.package_service import handle_quote_package_item

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=1, cost=25.00),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            price="100.00",
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.id = part_id
        part_cat_row.is_active = True
        part_cat_row.name = "Brake Pad Set"
        part_cat_row.cost_per_unit = Decimal("25.00")
        part_cat_result.one_or_none.return_value = part_cat_row

        part_stock_item = MagicMock()
        part_stock_item.id = uuid.uuid4()
        part_stock_item.purchase_price = Decimal("25.00")
        part_stock_item.cost_per_unit = Decimal("25.00")
        part_stock_item.current_quantity = Decimal("10")
        part_stock_result = MagicMock()
        part_stock_result.scalar_one_or_none.return_value = part_stock_item

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            part_cat_result,
            part_stock_result,
        ])

        result = await handle_quote_package_item(
            mock_db,
            org_id=ORG_ID,
            catalogue_item_id=item_id,
        )

        assert result["is_package"] is True
        assert result["cost_price"] == Decimal("25.00")
        assert result["components"] is not None
        assert len(result["components"]) == 1
        assert result["warnings"] == []


# ===========================================================================
# 16.4 Unavailable component handling
# Requirements: 11.1, 11.3
# ===========================================================================


class TestUnavailableComponentHandling:
    """Integration test: unavailable (deactivated) component handling.

    Validates that warnings are displayed for unavailable components and
    that invoice uses snapshot cost for deactivated components.

    Requirements: 11.1, 11.3
    """

    @pytest.mark.asyncio
    async def test_warning_displayed_for_deactivated_component(self):
        """Warning generated when a component is deactivated.

        Requirements: 11.1
        """
        from app.modules.invoices.package_service import handle_quote_package_item

        item_id = uuid.uuid4()
        active_part_id = uuid.uuid4()
        inactive_part_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=active_part_id, quantity=1, cost=12.50),
            _make_part_component(catalogue_item_id=inactive_part_id, quantity=1, cost=20.00),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # Active part
        active_cat_result = MagicMock()
        active_cat_row = MagicMock()
        active_cat_row.id = active_part_id
        active_cat_row.is_active = True
        active_cat_row.name = "Oil Filter"
        active_cat_row.cost_per_unit = Decimal("12.50")
        active_cat_result.one_or_none.return_value = active_cat_row

        active_stock_item = MagicMock()
        active_stock_item.id = uuid.uuid4()
        active_stock_item.purchase_price = Decimal("12.50")
        active_stock_item.cost_per_unit = Decimal("12.50")
        active_stock_item.current_quantity = Decimal("10")
        active_stock_result = MagicMock()
        active_stock_result.scalar_one_or_none.return_value = active_stock_item

        # Inactive (deactivated) part
        inactive_cat_result = MagicMock()
        inactive_cat_row = MagicMock()
        inactive_cat_row.id = inactive_part_id
        inactive_cat_row.is_active = False  # DEACTIVATED
        inactive_cat_row.name = "Discontinued Filter"
        inactive_cat_row.cost_per_unit = Decimal("20.00")
        inactive_cat_result.one_or_none.return_value = inactive_cat_row

        # No stock lookup for inactive component (skipped in resolve logic)
        inactive_stock_result = MagicMock()
        inactive_stock_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            active_cat_result,
            active_stock_result,
            inactive_cat_result,
            inactive_stock_result,
        ])

        result = await handle_quote_package_item(
            mock_db,
            org_id=ORG_ID,
            catalogue_item_id=item_id,
        )

        # Verify warning is generated for unavailable component
        assert len(result["warnings"]) > 0
        assert any("unavailable" in w.lower() or "Discontinued Filter" in w for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_invoice_uses_snapshot_cost_for_unavailable(self):
        """Invoice uses cost_per_unit_snapshot for deactivated components.

        Requirements: 11.3
        """
        from app.modules.invoices.package_service import resolve_package_line_item

        item_id = uuid.uuid4()
        active_part_id = uuid.uuid4()
        inactive_part_id = uuid.uuid4()
        stock_active_id = uuid.uuid4()

        snapshot_cost = 20.00  # The cost stored at package creation time

        components = [
            _make_part_component(catalogue_item_id=active_part_id, quantity=1, cost=12.50),
            _make_part_component(catalogue_item_id=inactive_part_id, quantity=1, cost=snapshot_cost),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # Active part
        active_cat_result = MagicMock()
        active_cat_row = MagicMock()
        active_cat_row.id = active_part_id
        active_cat_row.is_active = True
        active_cat_row.name = "Oil Filter"
        active_cat_row.cost_per_unit = Decimal("12.50")
        active_cat_result.one_or_none.return_value = active_cat_row

        active_stock_item = MagicMock()
        active_stock_item.id = stock_active_id
        active_stock_item.purchase_price = Decimal("14.00")
        active_stock_item.cost_per_unit = Decimal("14.00")
        active_stock_item.current_quantity = Decimal("10")
        active_stock_result = MagicMock()
        active_stock_result.scalar_one_or_none.return_value = active_stock_item

        # Inactive part — is_active = False
        inactive_cat_result = MagicMock()
        inactive_cat_row = MagicMock()
        inactive_cat_row.id = inactive_part_id
        inactive_cat_row.is_active = False
        inactive_cat_row.name = "Discontinued Filter"
        inactive_cat_row.cost_per_unit = Decimal("20.00")
        inactive_cat_result.one_or_none.return_value = inactive_cat_row

        # No stock lookup needed for inactive (the service skips it)
        inactive_stock_result = MagicMock()
        inactive_stock_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            active_cat_result,
            active_stock_result,
            inactive_cat_result,
            inactive_stock_result,
        ])

        result = await resolve_package_line_item(
            mock_db,
            org_id=ORG_ID,
            catalogue_item_id=item_id,
        )

        assert result["is_package"] is True

        # Find the unavailable component in results
        unavailable_comp = next(
            c for c in result["components"] if not c["is_available"]
        )
        assert unavailable_comp["name"] == "Discontinued Filter"

        # Verify snapshot cost is used: 20.00 * 1 = 20.00
        assert unavailable_comp["unit_cost"] == Decimal("20.00")
        assert unavailable_comp["line_cost"] == Decimal("20.00")

        # Total cost includes both: active (14.00 * 1) + inactive (20.00 * 1) = 34.00
        expected_total = Decimal("14.00") + Decimal("20.00")
        assert result["cost_price"] == expected_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @pytest.mark.asyncio
    async def test_deduction_skipped_for_unavailable_component(self):
        """Inventory deduction is skipped for unavailable components.

        Requirements: 11.3
        """
        from app.modules.invoices.package_service import deduct_package_inventory

        invoice_id = uuid.uuid4()
        stock_active_id = uuid.uuid4()

        resolved_components = [
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "part",
                "name": "Oil Filter",
                "quantity": 1,
                "volume": None,
                "unit_cost": Decimal("14.00"),
                "line_cost": Decimal("14.00"),
                "stock_item_id": stock_active_id,
                "is_available": True,
            },
            {
                "catalogue_item_id": str(uuid.uuid4()),
                "catalogue_type": "part",
                "name": "Discontinued Filter",
                "quantity": 1,
                "volume": None,
                "unit_cost": Decimal("20.00"),
                "line_cost": Decimal("20.00"),
                "stock_item_id": None,  # No stock item for unavailable
                "is_available": False,  # UNAVAILABLE
            },
        ]

        mock_db = AsyncMock()

        # Only the active component gets a stock check
        active_stock_row = MagicMock()
        active_stock_row.current_quantity = Decimal("10")
        active_stock_check = MagicMock()
        active_stock_check.one_or_none.return_value = active_stock_row

        mock_db.execute = AsyncMock(side_effect=[active_stock_check])

        deduction_calls = []

        async def mock_decrement(db, *, org_id, user_id, stock_item_id, quantity, invoice_id):
            deduction_calls.append({
                "stock_item_id": stock_item_id,
                "quantity": quantity,
            })
            return {"id": str(stock_item_id)}

        with patch(
            "app.modules.inventory.stock_items_service.decrement_stock_for_invoice_v2",
            side_effect=mock_decrement,
        ):
            warnings = await deduct_package_inventory(
                mock_db,
                org_id=ORG_ID,
                user_id=USER_ID,
                invoice_id=invoice_id,
                components=resolved_components,
            )

        # Only 1 deduction (the active component)
        assert len(deduction_calls) == 1
        assert deduction_calls[0]["stock_item_id"] == stock_active_id
        assert deduction_calls[0]["quantity"] == 1.0


# ===========================================================================
# 16.5 Access control: non-admin cannot see cost data
# Requirements: 10.1, 10.2, 10.3
# ===========================================================================


class TestAccessControlCostData:
    """Integration test: non-admin roles cannot see cost data.

    Validates that cost fields are omitted from responses for non-admin roles
    (branch_admin, salesperson).

    Requirements: 10.1, 10.2, 10.3
    """

    @pytest.mark.asyncio
    async def test_salesperson_cannot_see_cost_fields(self):
        """Salesperson role: cost fields omitted from package cost response.

        Requirements: 10.1, 10.2, 10.3
        """
        from app.modules.catalogue.service import resolve_package_costs

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()
        stock_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # Part catalogue lookup
        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.name = "Oil Filter"
        part_cat_row.cost_per_unit = Decimal("12.50")
        part_cat_row.is_active = True
        part_cat_result.one_or_none.return_value = part_cat_row

        # Stock items query (returns list via scalars().all())
        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_id
        mock_stock_item.purchase_price = Decimal("14.00")
        mock_stock_item.cost_per_unit = Decimal("14.00")
        mock_stock_item.current_quantity = Decimal("15")
        mock_stock_item.branch_id = BRANCH_ID
        mock_stock_item.location = "Rack A"

        stock_scalars = MagicMock()
        stock_scalars.all.return_value = [mock_stock_item]
        stock_result = MagicMock()
        stock_result.scalars.return_value = stock_scalars

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            part_cat_result,
            stock_result,
        ])

        # Request as salesperson (non-admin)
        result = await resolve_package_costs(
            mock_db,
            org_id=ORG_ID,
            item_id=item_id,
            user_role="salesperson",
        )

        # Verify cost fields are NOT present in response
        assert "total_cost" not in result
        assert "profit" not in result
        assert "sell_price" not in result

        # Components should still be returned (names, availability)
        assert "components" in result
        assert len(result["components"]) == 1

        # Individual component cost fields should be omitted
        comp = result["components"][0]
        assert "cost_per_unit" not in comp
        assert "line_total" not in comp
        assert comp["name"] == "Oil Filter"
        assert comp["is_available"] is True

    @pytest.mark.asyncio
    async def test_admin_can_see_cost_fields(self):
        """Admin role: cost fields included in package cost response.

        Requirements: 10.1, 10.3
        """
        from app.modules.catalogue.service import resolve_package_costs

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()
        stock_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=2, cost=12.50),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.name = "Oil Filter"
        part_cat_row.cost_per_unit = Decimal("12.50")
        part_cat_row.is_active = True
        part_cat_result.one_or_none.return_value = part_cat_row

        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_id
        mock_stock_item.purchase_price = Decimal("14.00")
        mock_stock_item.cost_per_unit = Decimal("14.00")
        mock_stock_item.current_quantity = Decimal("15")
        mock_stock_item.branch_id = BRANCH_ID
        mock_stock_item.location = "Rack A"

        stock_scalars = MagicMock()
        stock_scalars.all.return_value = [mock_stock_item]
        stock_result = MagicMock()
        stock_result.scalars.return_value = stock_scalars

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            part_cat_result,
            stock_result,
        ])

        # Request as org_admin
        result = await resolve_package_costs(
            mock_db,
            org_id=ORG_ID,
            item_id=item_id,
            user_role="org_admin",
        )

        # Verify cost fields ARE present
        assert "total_cost" in result
        assert "profit" in result
        assert "sell_price" in result
        assert result["total_cost"] == 28.00  # 14.00 * 2
        assert result["sell_price"] == 120.00
        assert result["profit"] == 92.00  # 120 - 28

        # Component cost fields should be present
        comp = result["components"][0]
        assert "cost_per_unit" in comp
        assert "line_total" in comp
        assert comp["cost_per_unit"] == 14.00
        assert comp["line_total"] == 28.00

    @pytest.mark.asyncio
    async def test_branch_admin_cannot_see_cost_fields(self):
        """Branch admin role: cost fields omitted (same as salesperson).

        Requirements: 10.2, 10.3
        """
        from app.modules.catalogue.service import resolve_package_costs

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()
        stock_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=1, cost=50.00),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        part_cat_result = MagicMock()
        part_cat_row = MagicMock()
        part_cat_row.name = "Brake Disc"
        part_cat_row.cost_per_unit = Decimal("50.00")
        part_cat_row.is_active = True
        part_cat_result.one_or_none.return_value = part_cat_row

        mock_stock_item = MagicMock()
        mock_stock_item.id = stock_id
        mock_stock_item.purchase_price = Decimal("55.00")
        mock_stock_item.cost_per_unit = Decimal("55.00")
        mock_stock_item.current_quantity = Decimal("6")
        mock_stock_item.branch_id = BRANCH_ID
        mock_stock_item.location = "Shelf B"

        stock_scalars = MagicMock()
        stock_scalars.all.return_value = [mock_stock_item]
        stock_result = MagicMock()
        stock_result.scalars.return_value = stock_scalars

        mock_db.execute = AsyncMock(side_effect=[
            item_result,
            part_cat_result,
            stock_result,
        ])

        # Request as branch_admin (non-admin for cost purposes)
        result = await resolve_package_costs(
            mock_db,
            org_id=ORG_ID,
            item_id=item_id,
            user_role="branch_admin",
        )

        # Cost fields omitted
        assert "total_cost" not in result
        assert "profit" not in result
        assert "sell_price" not in result

        # Components returned without cost data
        assert len(result["components"]) == 1
        comp = result["components"][0]
        assert "cost_per_unit" not in comp
        assert "line_total" not in comp
        assert comp["name"] == "Brake Disc"

    @pytest.mark.asyncio
    async def test_list_items_cost_hidden_for_non_admin(self):
        """list_items omits package_cost/package_profit for non-admin roles.

        Requirements: 10.3
        """
        from app.modules.catalogue.service import list_items

        item_id = uuid.uuid4()
        part_id = uuid.uuid4()

        components = [
            _make_part_component(catalogue_item_id=part_id, quantity=1, cost=10.00),
        ]

        mock_item = _make_mock_item(
            item_id=item_id,
            package_components=components,
        )

        mock_db = AsyncMock()

        # Count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        # Items query
        items_scalars = MagicMock()
        items_scalars.all.return_value = [mock_item]
        items_result = MagicMock()
        items_result.scalars.return_value = items_scalars

        # _check_unavailable_components query for the part component
        avail_check_result = MagicMock()
        avail_check_row = MagicMock()
        avail_check_row.is_active = True
        avail_check_result.one_or_none.return_value = avail_check_row

        mock_db.execute = AsyncMock(side_effect=[
            count_result,
            items_result,
            avail_check_result,  # availability check for the part component
        ])

        # Request as salesperson
        result = await list_items(
            mock_db,
            org_id=ORG_ID,
            user_role="salesperson",
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1

        item_response = result["items"][0]
        # Cost fields should be None for non-admin
        assert item_response["package_cost"] is None
        assert item_response["package_profit"] is None
        # Package flag and badge info still visible
        assert item_response["is_package"] is True
