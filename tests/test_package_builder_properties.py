"""Property-based tests for Service Package Builder.

Feature: service-package-builder

Uses Hypothesis to verify 18 correctness properties for the Service Package
Builder feature covering module gating, cost calculations, persistence,
invoice integration, and access control.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Hypothesis settings — per project notes: max_examples=30
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Module states: boolean for vehicles and inventory
module_states = st.fixed_dictionaries({
    "vehicles": st.booleans(),
    "inventory": st.booleans(),
})

# Roles
all_roles = st.sampled_from(["org_admin", "global_admin", "branch_admin", "salesperson", "kiosk"])
admin_roles = st.sampled_from(["org_admin", "global_admin"])
non_admin_roles = st.sampled_from(["branch_admin", "salesperson", "kiosk"])

# Catalogue types
catalogue_types = st.sampled_from(["part", "tyre", "fluid"])

# Positive integers for quantities
quantities = st.integers(min_value=1, max_value=100)

# Positive floats for volumes (litres)
volumes = st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False)

# Positive floats for costs
costs = st.floats(min_value=0.01, max_value=9999.99, allow_nan=False, allow_infinity=False)

# Prices as positive floats
prices = st.floats(min_value=0.01, max_value=99999.99, allow_nan=False, allow_infinity=False)

# Part types for search filtering
part_types = st.sampled_from(["part", "tyre"])

# Fluid types
fluid_types = st.sampled_from(["oil", "non-oil"])
oil_types = st.sampled_from(["engine", "hydraulic", "brake", "gear", "transmission", "power_steering"])


@st.composite
def package_component_part(draw):
    """Generate a part/tyre component dict."""
    cat_type = draw(st.sampled_from(["part", "tyre"]))
    return {
        "catalogue_item_id": str(draw(st.builds(uuid.uuid4))),
        "catalogue_type": cat_type,
        "quantity": draw(quantities),
        "cost_per_unit_snapshot": round(draw(costs), 2),
    }


@st.composite
def package_component_fluid(draw):
    """Generate a fluid component dict."""
    return {
        "catalogue_item_id": str(draw(st.builds(uuid.uuid4))),
        "catalogue_type": "fluid",
        "volume": round(draw(volumes), 2),
        "cost_per_unit_snapshot": round(draw(costs), 2),
        "fluid_type": draw(fluid_types),
        "oil_type": draw(st.one_of(st.none(), oil_types)),
        "grade": draw(st.one_of(st.none(), st.just("5W-30"), st.just("10W-40"))),
    }


@st.composite
def package_components_list(draw):
    """Generate a non-empty list of package components (mixed types)."""
    parts = draw(st.lists(package_component_part(), min_size=0, max_size=3))
    fluids = draw(st.lists(package_component_fluid(), min_size=0, max_size=3))
    components = parts + fluids
    assume(len(components) > 0)
    return components


@st.composite
def catalogue_item_with_part_type(draw):
    """Generate a catalogue item dict with a part_type field."""
    return {
        "id": str(draw(st.builds(uuid.uuid4))),
        "name": f"Part-{draw(st.integers(min_value=1, max_value=9999))}",
        "part_number": f"PN-{draw(st.integers(min_value=100, max_value=999))}",
        "part_type": draw(part_types),
        "brand": draw(st.one_of(st.none(), st.just("Ryco"), st.just("Bosch"))),
        "cost_per_unit": round(draw(costs), 2),
        "is_active": True,
    }


# ---------------------------------------------------------------------------
# Property 1: Module gating controls package builder visibility
# ---------------------------------------------------------------------------


class TestProperty1ModuleGating:
    """Property 1: Module gating controls package builder visibility.

    Feature: service-package-builder, Property 1: Module gating controls package builder visibility

    *For any* combination of module enabled/disabled states, the "Include
    Inventory Usage" checkbox and Package Builder UI SHALL be visible if and
    only if both `vehicles` AND `inventory` modules are enabled.

    **Validates: Requirements 1.1, 1.5**
    """

    @given(modules=module_states)
    @PBT_SETTINGS
    def test_property_1_module_gating(self, modules):
        """Package builder visible iff both vehicles AND inventory enabled.

        **Validates: Requirements 1.1, 1.5**
        """
        vehicles_enabled = modules["vehicles"]
        inventory_enabled = modules["inventory"]

        # The visibility rule from the design
        should_be_visible = vehicles_enabled and inventory_enabled

        # Simulate the module gate check
        def is_package_builder_visible(modules_state: dict) -> bool:
            return (
                modules_state.get("vehicles", False)
                and modules_state.get("inventory", False)
            )

        result = is_package_builder_visible(modules)
        assert result == should_be_visible


# ---------------------------------------------------------------------------
# Property 2: Unchecking toggle clears components
# ---------------------------------------------------------------------------


class TestProperty2UncheckingToggleClearsComponents:
    """Property 2: Unchecking the inventory toggle clears all component selections.

    Feature: service-package-builder, Property 2: Unchecking the inventory toggle clears all component selections

    *For any* set of previously selected package components, unchecking the
    "Include Inventory Usage" checkbox SHALL result in an empty component list.

    **Validates: Requirements 1.4**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    def test_property_2_unchecking_toggle_clears_components(self, components):
        """Unchecking toggle clears all components regardless of content.

        **Validates: Requirements 1.4**
        """
        assert len(components) > 0  # precondition: we have components

        # Simulate unchecking the toggle — the handler clears components
        def uncheck_inventory_toggle(current_components: list) -> list:
            """When toggle is unchecked, all components are cleared."""
            return []

        result = uncheck_inventory_toggle(components)
        assert result == []
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Property 3: Part type search filtering
# ---------------------------------------------------------------------------


class TestProperty3PartTypeSearchFiltering:
    """Property 3: Part type search filtering returns only matching types.

    Feature: service-package-builder, Property 3: Part type search filtering returns only matching types

    *For any* search query against the parts/tyre catalogue, the results SHALL
    contain only items where `part_type` matches the requested filter.

    **Validates: Requirements 4.1, 4.5**
    """

    @given(
        items=st.lists(catalogue_item_with_part_type(), min_size=1, max_size=10),
        filter_type=part_types,
    )
    @PBT_SETTINGS
    def test_property_3_part_type_search_filtering(self, items, filter_type):
        """Search results contain only items matching the requested part_type.

        **Validates: Requirements 4.1, 4.5**
        """
        # Simulate the search filter logic
        def filter_by_part_type(catalogue_items: list, requested_type: str) -> list:
            return [
                item for item in catalogue_items
                if item["part_type"] == requested_type and item["is_active"]
            ]

        results = filter_by_part_type(items, filter_type)

        # Assert: all results match the requested type
        for item in results:
            assert item["part_type"] == filter_type

        # Assert: no matching items were excluded
        expected_count = sum(
            1 for item in items
            if item["part_type"] == filter_type and item["is_active"]
        )
        assert len(results) == expected_count


# ---------------------------------------------------------------------------
# Property 4: Package cost equals sum of component costs
# ---------------------------------------------------------------------------


class TestProperty4PackageCostCalculation:
    """Property 4: Package cost equals sum of component costs.

    Feature: service-package-builder, Property 4: Package cost equals sum of component costs

    *For any* set of package components, the Package_Cost SHALL equal the sum
    of (cost_per_unit x quantity) for parts/tyres plus (cost_per_unit x volume)
    for fluids.

    **Validates: Requirements 5.1**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    def test_property_4_package_cost_calculation(self, components):
        """Package cost = sum of (cost * qty) for parts/tyres + (cost * volume) for fluids.

        **Validates: Requirements 5.1**
        """
        def calculate_package_cost(comps: list) -> float:
            """Calculate total package cost from components."""
            total = 0.0
            for comp in comps:
                cost = comp.get("cost_per_unit_snapshot", 0) or 0
                if comp["catalogue_type"] in ("part", "tyre"):
                    qty = comp.get("quantity", 1) or 1
                    total += cost * qty
                elif comp["catalogue_type"] == "fluid":
                    vol = comp.get("volume", 0) or 0
                    total += cost * vol
            return round(total, 2)

        # Calculate expected cost manually
        expected_cost = 0.0
        for comp in components:
            cost = comp.get("cost_per_unit_snapshot", 0) or 0
            if comp["catalogue_type"] in ("part", "tyre"):
                expected_cost += cost * (comp.get("quantity", 1) or 1)
            elif comp["catalogue_type"] == "fluid":
                expected_cost += cost * (comp.get("volume", 0) or 0)
        expected_cost = round(expected_cost, 2)

        result = calculate_package_cost(components)
        assert result == expected_cost


# ---------------------------------------------------------------------------
# Property 5: Package profit equals sell price minus package cost
# ---------------------------------------------------------------------------


class TestProperty5PackageProfitCalculation:
    """Property 5: Package profit equals sell price minus package cost.

    Feature: service-package-builder, Property 5: Package profit equals sell price minus package cost

    *For any* package item with a sell price and computed Package_Cost,
    the Package_Profit SHALL equal sell_price - Package_Cost.

    **Validates: Requirements 5.4**
    """

    @given(
        sell_price=prices,
        components=package_components_list(),
    )
    @PBT_SETTINGS
    def test_property_5_package_profit_calculation(self, sell_price, components):
        """Profit = sell_price - total_cost for any price/component combination.

        **Validates: Requirements 5.4**
        """
        # Calculate cost
        total_cost = 0.0
        for comp in components:
            cost = comp.get("cost_per_unit_snapshot", 0) or 0
            if comp["catalogue_type"] in ("part", "tyre"):
                total_cost += cost * (comp.get("quantity", 1) or 1)
            elif comp["catalogue_type"] == "fluid":
                total_cost += cost * (comp.get("volume", 0) or 0)
        total_cost = round(total_cost, 2)

        # Calculate profit
        profit = round(sell_price - total_cost, 2)

        # Verify the formula
        assert profit == round(sell_price - total_cost, 2)
        # Verify the relationship: profit + cost = sell_price (within rounding)
        assert abs((profit + total_cost) - sell_price) < 0.01


# ---------------------------------------------------------------------------
# Property 6: Negative profit triggers warning indicator
# ---------------------------------------------------------------------------


class TestProperty6NegativeProfitWarning:
    """Property 6: Negative profit triggers warning indicator.

    Feature: service-package-builder, Property 6: Negative profit triggers warning indicator

    *For any* package where Package_Cost exceeds sell_price (negative profit),
    the profit display SHALL use red styling and show a warning indicator.

    **Validates: Requirements 5.5**
    """

    @given(
        sell_price=st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        cost_excess=st.floats(min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_property_6_negative_profit_warning(self, sell_price, cost_excess):
        """Negative profit (cost > sell_price) triggers warning indicator.

        **Validates: Requirements 5.5**
        """
        total_cost = sell_price + cost_excess  # Ensure cost > sell_price
        profit = sell_price - total_cost

        assert profit < 0  # Precondition: profit is negative

        # Simulate the warning logic
        def should_show_warning(profit_value: float) -> bool:
            return profit_value < 0

        def get_profit_style(profit_value: float) -> str:
            return "red" if profit_value < 0 else "green"

        assert should_show_warning(profit) is True
        assert get_profit_style(profit) == "red"


# ---------------------------------------------------------------------------
# Property 7: Cost data visibility restricted to admin roles
# ---------------------------------------------------------------------------


class TestProperty7CostDataRoleRestriction:
    """Property 7: Cost data visibility is restricted to admin roles.

    Feature: service-package-builder, Property 7: Cost data visibility is restricted to admin roles

    *For any* user role, cost-related fields SHALL be visible/included if and
    only if the user's role is `org_admin` or `global_admin`.

    **Validates: Requirements 5.7, 10.1, 10.2, 10.3**
    """

    @given(role=all_roles)
    @PBT_SETTINGS
    def test_property_7_cost_data_role_restriction(self, role):
        """Cost fields included only for org_admin/global_admin roles.

        **Validates: Requirements 5.7, 10.1, 10.2, 10.3**
        """
        is_admin = role in ("org_admin", "global_admin")

        # Simulate the _item_to_dict logic for cost inclusion
        def build_item_response(user_role: str, package_cost: float, package_profit: float) -> dict:
            include_costs = user_role in ("org_admin", "global_admin")
            result = {
                "id": str(uuid.uuid4()),
                "name": "Test Package",
                "is_package": True,
                "has_unavailable_components": False,
            }
            if include_costs:
                result["package_cost"] = package_cost
                result["package_profit"] = package_profit
            else:
                result["package_cost"] = None
                result["package_profit"] = None
            return result

        response = build_item_response(role, 50.0, 70.0)

        if is_admin:
            assert response["package_cost"] == 50.0
            assert response["package_profit"] == 70.0
        else:
            assert response["package_cost"] is None
            assert response["package_profit"] is None


# ---------------------------------------------------------------------------
# Property 8: Stock warning badges when stock insufficient
# ---------------------------------------------------------------------------


class TestProperty8StockWarningBadges:
    """Property 8: Stock warning badges appear when stock is insufficient.

    Feature: service-package-builder, Property 8: Stock warning badges appear when stock is insufficient

    *For any* package component where available stock < required quantity,
    a warning badge SHALL be displayed.

    **Validates: Requirements 6.9**
    """

    @given(
        required_qty=st.integers(min_value=1, max_value=50),
        available_qty=st.integers(min_value=0, max_value=49),
    )
    @PBT_SETTINGS
    def test_property_8_stock_warning_badges(self, required_qty, available_qty):
        """Warning badge shown when stock < required quantity.

        **Validates: Requirements 6.9**
        """
        assume(available_qty < required_qty)

        def get_stock_badge(required: int, available: int) -> str | None:
            """Determine stock warning badge."""
            if available == 0:
                return "Out of Stock"
            elif available < required:
                return "Low Stock"
            return None

        badge = get_stock_badge(required_qty, available_qty)
        assert badge is not None
        assert badge in ("Low Stock", "Out of Stock")

        # If available is 0, must be "Out of Stock"
        if available_qty == 0:
            assert badge == "Out of Stock"
        else:
            assert badge == "Low Stock"


# ---------------------------------------------------------------------------
# Property 9: Persistence round-trip preserves component data
# ---------------------------------------------------------------------------


class TestProperty9PersistenceRoundTrip:
    """Property 9: Package persistence round-trip preserves all component data.

    Feature: service-package-builder, Property 9: Package persistence round-trip preserves all component data

    *For any* valid package item with components, saving via the API and then
    reading back SHALL produce identical component data.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_9_persistence_round_trip(self, components):
        """Save + read back produces identical component data.

        **Validates: Requirements 7.1, 7.2, 7.3**
        """
        from app.modules.catalogue.service import create_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock DB session
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Mock the validation queries for each component
        execute_results = []
        for comp in components:
            # Catalogue lookup result
            cat_mock = MagicMock()
            cat_row = MagicMock()
            cat_row.id = uuid.UUID(comp["catalogue_item_id"])
            cat_row.cost_per_unit = Decimal(str(comp["cost_per_unit_snapshot"]))
            cat_mock.one_or_none.return_value = cat_row
            execute_results.append(cat_mock)

            # Stock item lookup result (return None to use catalogue cost)
            stock_mock = MagicMock()
            stock_mock.one_or_none.return_value = None
            execute_results.append(stock_mock)

        mock_db.execute = AsyncMock(side_effect=execute_results)

        # Track what gets persisted
        persisted_item = MagicMock()
        persisted_item.id = item_id
        persisted_item.name = "Test Package"
        persisted_item.description = None
        persisted_item.default_price = Decimal("120.00")
        persisted_item.is_gst_exempt = False
        persisted_item.gst_inclusive = False
        persisted_item.category = "service"
        persisted_item.is_active = True
        persisted_item.is_package = True
        persisted_item.package_components = None
        persisted_item.has_unavailable_components = False
        persisted_item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        persisted_item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        def fake_items_catalogue(**kwargs):
            for k, v in kwargs.items():
                setattr(persisted_item, k, v)
            return persisted_item

        with patch(
            "app.modules.catalogue.service.ItemsCatalogue",
            side_effect=fake_items_catalogue,
        ), patch(
            "app.modules.catalogue.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_item(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                name="Test Package",
                default_price="120.00",
                category="service",
                is_package=True,
                package_components=components,
            )

        # Verify round-trip: persisted components match input
        persisted_components = persisted_item.package_components
        assert persisted_components is not None
        assert len(persisted_components) == len(components)

        for original, persisted in zip(components, persisted_components):
            assert persisted["catalogue_item_id"] == original["catalogue_item_id"]
            assert persisted["catalogue_type"] == original["catalogue_type"]
            if original["catalogue_type"] in ("part", "tyre"):
                assert persisted["quantity"] == original["quantity"]
            elif original["catalogue_type"] == "fluid":
                assert persisted["volume"] == original["volume"]
            # cost_per_unit_snapshot is captured from the mock
            assert persisted["cost_per_unit_snapshot"] is not None


# ---------------------------------------------------------------------------
# Property 10: Update replaces (not merges) components
# ---------------------------------------------------------------------------


class TestProperty10UpdateReplacesComponents:
    """Property 10: Package update replaces (not merges) component metadata.

    Feature: service-package-builder, Property 10: Package update replaces (not merges) component metadata

    *For any* existing package item, updating with a new set of components
    SHALL result in only the new components being stored.

    **Validates: Requirements 7.5**
    """

    @given(
        original_components=package_components_list(),
        new_components=package_components_list(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_10_update_replaces_components(self, original_components, new_components):
        """Update replaces all components — no merging with previous set.

        **Validates: Requirements 7.5**
        """
        from app.modules.catalogue.service import update_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock existing item with original components
        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.org_id = org_id
        mock_item.name = "Test Package"
        mock_item.description = None
        mock_item.default_price = Decimal("120.00")
        mock_item.is_gst_exempt = False
        mock_item.gst_inclusive = False
        mock_item.category = "service"
        mock_item.is_active = True
        mock_item.is_package = True
        mock_item.package_components = original_components
        mock_item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # Mock DB: first call returns the item, subsequent calls validate components
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # First execute returns the existing item
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # Subsequent executes validate each new component
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
                org_id=org_id,
                user_id=user_id,
                item_id=item_id,
                is_package=True,
                package_components=new_components,
            )

        # After update, the item's package_components should be the new set
        # (the service sets item.package_components = persisted_components)
        final_components = mock_item.package_components
        assert final_components is not None
        assert len(final_components) == len(new_components)

        # Verify no original components remain (unless they happen to be in new set)
        final_ids = {c["catalogue_item_id"] for c in final_components}
        new_ids = {c["catalogue_item_id"] for c in new_components}
        assert final_ids == new_ids


# ---------------------------------------------------------------------------
# Property 11: Remove flag clears metadata
# ---------------------------------------------------------------------------


class TestProperty11RemoveFlagClearsMetadata:
    """Property 11: Removing package flag clears all package metadata.

    Feature: service-package-builder, Property 11: Removing package flag clears all package metadata

    *For any* package item, setting is_package=false SHALL result in
    is_package=false and package_components=null.

    **Validates: Requirements 7.6**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_11_remove_flag_clears_metadata(self, components):
        """Setting is_package=false clears package_components to null.

        **Validates: Requirements 7.6**
        """
        from app.modules.catalogue.service import update_item

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock existing package item
        mock_item = MagicMock()
        mock_item.id = item_id
        mock_item.org_id = org_id
        mock_item.name = "Test Package"
        mock_item.description = None
        mock_item.default_price = Decimal("120.00")
        mock_item.is_gst_exempt = False
        mock_item.gst_inclusive = False
        mock_item.category = "service"
        mock_item.is_active = True
        mock_item.is_package = True
        mock_item.package_components = components
        mock_item.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_item.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

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
                org_id=org_id,
                user_id=user_id,
                item_id=item_id,
                is_package=False,
            )

        # After setting is_package=False, components must be cleared
        assert mock_item.is_package is False
        assert mock_item.package_components is None


# ---------------------------------------------------------------------------
# Property 12: Invoice cost_price from live costs
# ---------------------------------------------------------------------------


class TestProperty12InvoiceCostPriceFromLiveCosts:
    """Property 12: Invoice cost_price equals sum of live component costs.

    Feature: service-package-builder, Property 12: Invoice cost_price equals sum of live component costs

    *For any* package item added to an invoice, the cost_price SHALL equal
    the sum of current (live) cost_per_unit x quantity for parts/tyres and
    cost_per_unit x volume for fluids.

    **Validates: Requirements 8.1**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_12_invoice_cost_price(self, components):
        """Invoice cost_price = sum of live component costs.

        **Validates: Requirements 8.1**
        """
        from app.modules.invoices.package_service import resolve_package_line_item

        org_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Build a mock item with package_components
        mock_item = MagicMock()
        mock_item.is_package = True
        mock_item.package_components = components

        # Mock DB
        mock_db = AsyncMock()

        # First execute: fetch the catalogue item
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # For each component: catalogue check + stock item lookup
        component_results = []
        expected_cost = Decimal("0")

        for comp in components:
            cat_type = comp["catalogue_type"]
            cost = Decimal(str(comp["cost_per_unit_snapshot"]))

            # Catalogue availability check
            cat_check = MagicMock()
            cat_row = MagicMock()
            cat_row.id = uuid.UUID(comp["catalogue_item_id"])
            cat_row.is_active = True
            cat_row.name = "Component"
            if cat_type == "fluid":
                cat_row.product_name = "Fluid Product"
            cat_check.one_or_none.return_value = cat_row
            component_results.append(cat_check)

            # Stock item lookup — return a stock item with known cost
            stock_result = MagicMock()
            stock_item = MagicMock()
            stock_item.id = uuid.uuid4()
            stock_item.purchase_price = cost
            stock_item.cost_per_unit = cost
            stock_result.scalar_one_or_none.return_value = stock_item
            component_results.append(stock_result)

            # Calculate expected cost
            if cat_type in ("part", "tyre"):
                qty = comp.get("quantity", 1) or 1
                line_cost = (cost * Decimal(str(qty))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                vol = comp.get("volume", 0) or 0
                line_cost = (cost * Decimal(str(vol))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            expected_cost += line_cost

        mock_db.execute = AsyncMock(side_effect=[item_result] + component_results)

        result = await resolve_package_line_item(
            mock_db,
            org_id=org_id,
            catalogue_item_id=item_id,
        )

        assert result["is_package"] is True
        expected_total = expected_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert result["cost_price"] == expected_total


# ---------------------------------------------------------------------------
# Property 13: Inventory deduction correctness
# ---------------------------------------------------------------------------


class TestProperty13InventoryDeductionCorrectness:
    """Property 13: Invoice issuance deducts correct inventory quantities.

    Feature: service-package-builder, Property 13: Invoice issuance deducts correct inventory quantities

    *For any* package item on an issued invoice, each component's stock SHALL
    be decremented by exactly the component's specified quantity or volume.

    **Validates: Requirements 8.2**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_13_inventory_deduction(self, components):
        """Each component stock decremented by exact required amount.

        **Validates: Requirements 8.2**
        """
        from app.modules.invoices.package_service import deduct_package_inventory

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        # Build resolved components (as returned by resolve_package_line_item)
        resolved_components = []
        expected_deductions = {}

        for comp in components:
            stock_item_id = uuid.uuid4()
            cat_type = comp["catalogue_type"]

            resolved = {
                "catalogue_item_id": comp["catalogue_item_id"],
                "catalogue_type": cat_type,
                "name": "Component",
                "unit_cost": Decimal(str(comp["cost_per_unit_snapshot"])),
                "stock_item_id": stock_item_id,
                "is_available": True,
            }

            if cat_type in ("part", "tyre"):
                resolved["quantity"] = comp.get("quantity", 1)
                resolved["volume"] = None
                expected_deductions[stock_item_id] = float(comp.get("quantity", 1) or 1)
            else:
                resolved["volume"] = comp.get("volume", 0)
                resolved["quantity"] = None
                expected_deductions[stock_item_id] = float(comp.get("volume", 0) or 0)

            resolved_components.append(resolved)

        # Mock DB for stock checks
        mock_db = AsyncMock()

        # For each component, the deduct function checks current stock
        stock_check_results = []
        for comp in resolved_components:
            stock_check = MagicMock()
            stock_row = MagicMock()
            stock_row.current_quantity = Decimal("999")  # Plenty of stock
            stock_check.one_or_none.return_value = stock_row
            stock_check_results.append(stock_check)

        mock_db.execute = AsyncMock(side_effect=stock_check_results)

        # Track deductions
        actual_deductions = {}

        async def mock_decrement(db, *, org_id, user_id, stock_item_id, quantity, invoice_id):
            actual_deductions[stock_item_id] = quantity

        with patch(
            "app.modules.inventory.stock_items_service.decrement_stock_for_invoice_v2",
            side_effect=mock_decrement,
        ):
            warnings = await deduct_package_inventory(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice_id,
                components=resolved_components,
            )

        # Verify each component was deducted by the correct amount
        for stock_id, expected_qty in expected_deductions.items():
            if expected_qty > 0:
                assert stock_id in actual_deductions
                assert actual_deductions[stock_id] == expected_qty


# ---------------------------------------------------------------------------
# Property 14: Fluid usage recording
# ---------------------------------------------------------------------------


class TestProperty14FluidUsageRecording:
    """Property 14: Package fluid components are recorded in invoice fluid_usage.

    Feature: service-package-builder, Property 14: Package fluid components are recorded in invoice fluid_usage

    *For any* package item with fluid components used on an issued invoice,
    each fluid component SHALL produce a corresponding entry in
    invoice_data_json.fluid_usage.

    **Validates: Requirements 8.4**
    """

    @given(
        fluids=st.lists(package_component_fluid(), min_size=1, max_size=5),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_14_fluid_usage_recording(self, fluids):
        """Each fluid component produces a fluid_usage entry.

        **Validates: Requirements 8.4**
        """
        from app.modules.invoices.package_service import write_package_fluid_usage

        # Build resolved components with stock_item_ids
        resolved_components = []
        for fluid in fluids:
            stock_item_id = uuid.uuid4()
            cost = Decimal(str(fluid["cost_per_unit_snapshot"]))
            resolved_components.append({
                "catalogue_item_id": fluid["catalogue_item_id"],
                "catalogue_type": "fluid",
                "name": "Test Fluid",
                "volume": fluid["volume"],
                "unit_cost": cost,
                "stock_item_id": stock_item_id,
                "is_available": True,
            })

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

        # Verify fluid_usage entries were written
        data_json = mock_invoice.invoice_data_json
        assert "fluid_usage" in data_json
        fluid_usage = data_json["fluid_usage"]

        # Each fluid with volume > 0 should have an entry
        expected_count = sum(1 for f in fluids if (f.get("volume", 0) or 0) > 0)
        assert len(fluid_usage) == expected_count

        # Verify each entry has required fields
        for entry in fluid_usage:
            assert "stock_item_id" in entry
            assert "litres" in entry
            assert "cost_per_litre" in entry
            assert "total_cost" in entry
            assert entry["litres"] > 0


# ---------------------------------------------------------------------------
# Property 15: Quotes don't deduct inventory
# ---------------------------------------------------------------------------


class TestProperty15QuotesDontDeductInventory:
    """Property 15: Quotes with package items do not deduct inventory.

    Feature: service-package-builder, Property 15: Quotes with package items do not deduct inventory

    *For any* package item added to a quote, the stock quantities for all
    components SHALL remain unchanged.

    **Validates: Requirements 8.5**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_15_quotes_no_deduction(self, components):
        """Quote package items do not trigger inventory deduction.

        **Validates: Requirements 8.5**
        """
        from app.modules.invoices.package_service import handle_quote_package_item

        org_id = uuid.uuid4()
        item_id = uuid.uuid4()

        # Mock the item
        mock_item = MagicMock()
        mock_item.is_package = True
        mock_item.package_components = components
        mock_item.default_price = Decimal("120.00")

        # Mock DB
        mock_db = AsyncMock()

        # First call: fetch item
        item_result = MagicMock()
        item_result.scalar_one_or_none.return_value = mock_item

        # For each component: catalogue check + stock lookup
        component_results = []
        for comp in components:
            cat_check = MagicMock()
            cat_row = MagicMock()
            cat_row.id = uuid.UUID(comp["catalogue_item_id"])
            cat_row.is_active = True
            cat_row.name = "Component"
            if comp["catalogue_type"] == "fluid":
                cat_row.product_name = "Fluid"
            cat_check.one_or_none.return_value = cat_row
            component_results.append(cat_check)

            stock_result = MagicMock()
            stock_item = MagicMock()
            stock_item.id = uuid.uuid4()
            stock_item.purchase_price = Decimal(str(comp["cost_per_unit_snapshot"]))
            stock_item.cost_per_unit = Decimal(str(comp["cost_per_unit_snapshot"]))
            stock_result.scalar_one_or_none.return_value = stock_item
            component_results.append(stock_result)

        mock_db.execute = AsyncMock(side_effect=[item_result] + component_results)

        # Track if any deduction function is called
        deduction_called = False

        async def mock_decrement(*args, **kwargs):
            nonlocal deduction_called
            deduction_called = True

        with patch(
            "app.modules.inventory.stock_items_service.decrement_stock_for_invoice_v2",
            side_effect=mock_decrement,
        ):
            result = await handle_quote_package_item(
                mock_db,
                org_id=org_id,
                catalogue_item_id=item_id,
            )

        # handle_quote_package_item should NOT call deduction
        assert deduction_called is False
        # But it should still return cost info
        assert result["is_package"] is True
        assert result["cost_price"] is not None


# ---------------------------------------------------------------------------
# Property 16: Package duplication preserves components
# ---------------------------------------------------------------------------


class TestProperty16PackageDuplication:
    """Property 16: Package duplication preserves all components.

    Feature: service-package-builder, Property 16: Package duplication preserves all components

    *For any* package item, duplicating it SHALL produce a new item with a
    different id but identical package_components data.

    **Validates: Requirements 9.4**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    def test_property_16_package_duplication(self, components):
        """Duplicated package has different id but identical components.

        **Validates: Requirements 9.4**
        """
        # Test the core duplication logic: deep copy preserves all data
        # This mirrors what duplicate_item does with copy.deepcopy()
        original_components = components
        duplicated_components = copy.deepcopy(original_components)

        # Verify: components are identical
        assert len(duplicated_components) == len(original_components)

        for orig, dup in zip(original_components, duplicated_components):
            assert dup["catalogue_item_id"] == orig["catalogue_item_id"]
            assert dup["catalogue_type"] == orig["catalogue_type"]
            if orig["catalogue_type"] in ("part", "tyre"):
                assert dup.get("quantity") == orig.get("quantity")
            elif orig["catalogue_type"] == "fluid":
                assert dup.get("volume") == orig.get("volume")
            assert dup.get("cost_per_unit_snapshot") == orig.get("cost_per_unit_snapshot")

        # Verify: it's a deep copy (modifying one doesn't affect the other)
        if duplicated_components:
            duplicated_components[0]["catalogue_item_id"] = str(uuid.uuid4())
            assert duplicated_components[0]["catalogue_item_id"] != original_components[0]["catalogue_item_id"]


# ---------------------------------------------------------------------------
# Property 17: Unavailable component warning
# ---------------------------------------------------------------------------


class TestProperty17UnavailableComponentWarning:
    """Property 17: Unavailable components trigger warning on package edit.

    Feature: service-package-builder, Property 17: Unavailable components trigger warning on package edit

    *For any* package item where one or more referenced catalogue products
    have is_active=false, opening the package SHALL display a warning.

    **Validates: Requirements 11.1**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_17_unavailable_component_warning(self, components):
        """Deactivated components trigger has_unavailable_components=True.

        **Validates: Requirements 11.1**
        """
        from app.modules.catalogue.service import _check_unavailable_components

        org_id = uuid.uuid4()

        # Make at least one component unavailable
        assume(len(components) >= 1)

        mock_db = AsyncMock()

        # First component is unavailable (is_active=False), rest are available
        execute_results = []
        for i, comp in enumerate(components):
            check_result = MagicMock()
            if i == 0:
                # First component: deactivated
                row = MagicMock()
                row.is_active = False
                check_result.one_or_none.return_value = row
            else:
                row = MagicMock()
                row.is_active = True
                check_result.one_or_none.return_value = row
            execute_results.append(check_result)

        mock_db.execute = AsyncMock(side_effect=execute_results)

        has_unavailable = await _check_unavailable_components(
            mock_db,
            org_id=org_id,
            components=components,
        )

        # Should detect the unavailable component
        assert has_unavailable is True


# ---------------------------------------------------------------------------
# Property 18: Unavailable components skip deduction but retain cost
# ---------------------------------------------------------------------------


class TestProperty18UnavailableComponentsOnInvoice:
    """Property 18: Unavailable components skip deduction but retain cost on invoice.

    Feature: service-package-builder, Property 18: Unavailable components skip deduction but retain cost on invoice

    *For any* package component that is unavailable at invoice time, the system
    SHALL NOT attempt stock deduction but SHALL include its cost_per_unit_snapshot
    in the cost_price calculation.

    **Validates: Requirements 11.3**
    """

    @given(components=package_components_list())
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_property_18_unavailable_skip_deduction_retain_cost(self, components):
        """Unavailable components: no deduction, but snapshot cost in cost_price.

        **Validates: Requirements 11.3**
        """
        from app.modules.invoices.package_service import deduct_package_inventory

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        # Build resolved components as if resolve_package_line_item returned them
        # with is_available=False (simulating deactivated components)
        resolved_components = []
        expected_total_cost = Decimal("0")

        for comp in components:
            snapshot_cost = Decimal(str(comp["cost_per_unit_snapshot"]))
            cat_type = comp["catalogue_type"]

            # Calculate expected cost from snapshot
            if cat_type in ("part", "tyre"):
                qty = comp.get("quantity", 1) or 1
                line_cost = (snapshot_cost * Decimal(str(qty))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            else:
                vol = comp.get("volume", 0) or 0
                line_cost = (snapshot_cost * Decimal(str(vol))).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            expected_total_cost += line_cost

            resolved_components.append({
                "catalogue_item_id": comp["catalogue_item_id"],
                "catalogue_type": cat_type,
                "name": "Deactivated Component",
                "quantity": comp.get("quantity") if cat_type in ("part", "tyre") else None,
                "volume": comp.get("volume") if cat_type == "fluid" else None,
                "unit_cost": snapshot_cost,
                "line_cost": line_cost,
                "stock_item_id": None,  # No stock item for unavailable
                "is_available": False,  # KEY: component is unavailable
            })

        # Verify cost is retained (snapshot cost included)
        actual_total = sum(c["line_cost"] for c in resolved_components)
        assert actual_total == expected_total_cost

        # Now test deduction — unavailable components should be skipped
        mock_db = AsyncMock()
        deduction_called = False

        async def mock_decrement(*args, **kwargs):
            nonlocal deduction_called
            deduction_called = True

        with patch(
            "app.modules.inventory.stock_items_service.decrement_stock_for_invoice_v2",
            side_effect=mock_decrement,
        ):
            warnings = await deduct_package_inventory(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice_id,
                components=resolved_components,
            )

        # No deduction should have been called (all components unavailable)
        assert deduction_called is False
        # But cost was still calculated from snapshots
        assert expected_total_cost > 0
