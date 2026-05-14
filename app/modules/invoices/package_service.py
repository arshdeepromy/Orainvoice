"""Package invoice integration — resolve costs, deduct inventory, record fluid usage.

Handles service package items on invoices and quotes:
- resolve_package_line_item: calculates cost_price from live component costs
- deduct_package_inventory: decrements stock for each component on invoice issue
- write_package_fluid_usage: records fluid entries in invoice_data_json
- handle_quote_package_item: cost preview without inventory deduction

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 11.3
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.modules.catalogue.models import ItemsCatalogue, PartsCatalogue
from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.inventory.models import StockItem

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# 11.1 — resolve_package_line_item
# Requirements: 8.1, 11.3
# ---------------------------------------------------------------------------


async def resolve_package_line_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    catalogue_item_id: uuid.UUID,
) -> dict:
    """Resolve a package item's cost_price from live component costs.

    When a line item references a package catalogue_item_id:
    1. Fetch the ItemsCatalogue record and its package_components JSONB
    2. For each component, resolve live cost from stock_items (with catalogue fallback)
    3. For unavailable/deactivated components: use cost_per_unit_snapshot, skip stock deduction
    4. Return total cost_price and per-component details for deduction

    Returns:
        dict with keys:
        - cost_price: Decimal total cost for the package
        - components: list of resolved component dicts with stock info
        - is_package: True if the item is a package (False if not)
    """
    # Fetch the catalogue item
    result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == catalogue_item_id,
            ItemsCatalogue.org_id == org_id,
        )
    )
    item = result.scalar_one_or_none()

    if item is None or not item.is_package or not item.package_components:
        return {"is_package": False, "cost_price": None, "components": []}

    total_cost = Decimal("0")
    resolved_components = []

    for comp in item.package_components:
        comp_catalogue_id = comp.get("catalogue_item_id")
        catalogue_type = comp.get("catalogue_type")

        if isinstance(comp_catalogue_id, str):
            comp_catalogue_id = uuid.UUID(comp_catalogue_id)

        # Check if the component is still available (active)
        is_available = True
        component_name = "Unknown"

        if catalogue_type in ("part", "tyre"):
            cat_result = await db.execute(
                select(PartsCatalogue.id, PartsCatalogue.is_active, PartsCatalogue.name).where(
                    PartsCatalogue.id == comp_catalogue_id,
                    PartsCatalogue.org_id == org_id,
                )
            )
            cat_row = cat_result.one_or_none()
            if cat_row is None or not cat_row.is_active:
                is_available = False
            if cat_row:
                component_name = cat_row.name
        elif catalogue_type == "fluid":
            cat_result = await db.execute(
                select(FluidOilProduct.id, FluidOilProduct.is_active, FluidOilProduct.product_name).where(
                    FluidOilProduct.id == comp_catalogue_id,
                    FluidOilProduct.org_id == org_id,
                )
            )
            cat_row = cat_result.one_or_none()
            if cat_row is None or not cat_row.is_active:
                is_available = False
            if cat_row:
                component_name = cat_row.product_name or "Unknown Fluid"

        # Resolve cost: live stock price or catalogue fallback
        unit_cost = Decimal("0")
        stock_item_id = None

        if is_available:
            # Try stock_items for live cost
            stock_result = await db.execute(
                select(StockItem).where(
                    StockItem.catalogue_item_id == comp_catalogue_id,
                    StockItem.org_id == org_id,
                ).limit(1)
            )
            stock_item = stock_result.scalar_one_or_none()

            if stock_item is not None:
                stock_item_id = stock_item.id
                # Prefer cost_per_unit (per-unit cost), fall back to purchase_price (batch total)
                if stock_item.cost_per_unit is not None:
                    unit_cost = Decimal(str(stock_item.cost_per_unit))
                elif stock_item.purchase_price is not None:
                    unit_cost = Decimal(str(stock_item.purchase_price))
            else:
                # Catalogue fallback
                if catalogue_type in ("part", "tyre"):
                    fallback_result = await db.execute(
                        select(PartsCatalogue.cost_per_unit).where(
                            PartsCatalogue.id == comp_catalogue_id,
                        )
                    )
                    fallback_row = fallback_result.one_or_none()
                    if fallback_row and fallback_row.cost_per_unit:
                        unit_cost = Decimal(str(fallback_row.cost_per_unit))
                elif catalogue_type == "fluid":
                    fallback_result = await db.execute(
                        select(FluidOilProduct.cost_per_unit).where(
                            FluidOilProduct.id == comp_catalogue_id,
                        )
                    )
                    fallback_row = fallback_result.one_or_none()
                    if fallback_row and fallback_row.cost_per_unit:
                        unit_cost = Decimal(str(fallback_row.cost_per_unit))
        else:
            # Unavailable component: use snapshot cost
            snapshot_cost = comp.get("cost_per_unit_snapshot")
            if snapshot_cost is not None:
                unit_cost = Decimal(str(snapshot_cost))

        # Calculate line cost
        if catalogue_type in ("part", "tyre"):
            quantity = comp.get("quantity", 1) or 1
            line_cost = (unit_cost * Decimal(str(quantity))).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        elif catalogue_type == "fluid":
            volume = comp.get("volume", 0) or 0
            line_cost = (unit_cost * Decimal(str(volume))).quantize(
                TWO_PLACES, rounding=ROUND_HALF_UP
            )
        else:
            line_cost = Decimal("0")

        total_cost += line_cost

        resolved_components.append({
            "catalogue_item_id": str(comp_catalogue_id),
            "catalogue_type": catalogue_type,
            "name": component_name,
            "quantity": comp.get("quantity") if catalogue_type in ("part", "tyre") else None,
            "volume": comp.get("volume") if catalogue_type == "fluid" else None,
            "unit_cost": unit_cost,
            "line_cost": line_cost,
            "stock_item_id": stock_item_id,
            "is_available": is_available,
        })

    return {
        "is_package": True,
        "cost_price": total_cost.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        "components": resolved_components,
    }


# ---------------------------------------------------------------------------
# 11.2 — deduct_package_inventory
# Requirements: 8.2, 8.3, 11.3
# ---------------------------------------------------------------------------


async def deduct_package_inventory(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    components: list[dict],
) -> list[str]:
    """Deduct stock for each package component on invoice issue.

    Only called for issued invoices (not drafts or quotes).

    For each component:
    - Parts/tyres: decrement stock_items.current_quantity by component quantity
    - Fluids: decrement stock_items.current_quantity by component volume (litres)
    - Skip deduction for unavailable/deactivated components (is_available=False)
    - Warn (don't block) when stock is insufficient

    Args:
        db: Database session
        org_id: Organisation ID
        user_id: User performing the action
        invoice_id: Invoice ID for stock movement reference
        components: Resolved components from resolve_package_line_item()

    Returns:
        List of warning messages (empty if no issues)
    """
    from app.modules.inventory.stock_items_service import decrement_stock_for_invoice_v2

    warnings = []

    for comp in components:
        # Skip unavailable components
        if not comp.get("is_available", True):
            logger.info(
                "Skipping deduction for unavailable component %s on invoice %s",
                comp.get("catalogue_item_id"),
                invoice_id,
            )
            continue

        stock_item_id = comp.get("stock_item_id")
        if stock_item_id is None:
            # No stock item found — can't deduct
            logger.warning(
                "No stock item found for component %s — skipping deduction",
                comp.get("catalogue_item_id"),
            )
            continue

        catalogue_type = comp.get("catalogue_type")

        # Determine quantity to deduct
        if catalogue_type in ("part", "tyre"):
            deduct_qty = float(comp.get("quantity", 1) or 1)
        elif catalogue_type == "fluid":
            deduct_qty = float(comp.get("volume", 0) or 0)
        else:
            continue

        if deduct_qty <= 0:
            continue

        # Check current stock level and warn if insufficient
        if isinstance(stock_item_id, str):
            stock_item_id = uuid.UUID(stock_item_id)

        stock_result = await db.execute(
            select(StockItem.current_quantity).where(
                StockItem.id == stock_item_id,
                StockItem.org_id == org_id,
            )
        )
        stock_row = stock_result.one_or_none()

        if stock_row is not None:
            current_qty = float(stock_row.current_quantity)
            if current_qty < deduct_qty:
                comp_name = comp.get("name", "Unknown")
                warning_msg = (
                    f"Low stock for: {comp_name} "
                    f"({deduct_qty} needed, {current_qty} available). "
                    f"Invoice will proceed."
                )
                warnings.append(warning_msg)
                logger.warning(warning_msg)

        # Perform the deduction (allows going negative via max(0, ...))
        try:
            await decrement_stock_for_invoice_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                stock_item_id=stock_item_id,
                quantity=deduct_qty,
                invoice_id=invoice_id,
            )
        except Exception as e:
            comp_name = comp.get("name", "Unknown")
            warning_msg = f"Failed to deduct stock for {comp_name}: {e}"
            warnings.append(warning_msg)
            logger.exception(warning_msg)

    return warnings


# ---------------------------------------------------------------------------
# 11.3 — write_package_fluid_usage
# Requirements: 8.4
# ---------------------------------------------------------------------------


async def write_package_fluid_usage(
    db: AsyncSession,
    *,
    invoice: object,
    components: list[dict],
) -> None:
    """Write fluid usage entries to invoice_data_json for package fluid components.

    For each fluid component in the resolved components list:
    - Write an entry to invoice_data_json.fluid_usage
    - Include stock_item_id, litres, cost_per_litre, total_cost
    - Consistent with existing fluid usage behaviour

    Args:
        db: Database session
        invoice: The Invoice ORM object (must have invoice_data_json attribute)
        components: Resolved components from resolve_package_line_item()
    """
    fluid_entries = []

    for comp in components:
        if comp.get("catalogue_type") != "fluid":
            continue

        # Only record fluid usage for available components with stock items
        stock_item_id = comp.get("stock_item_id")
        if stock_item_id is None:
            continue

        volume = comp.get("volume", 0) or 0
        if volume <= 0:
            continue

        unit_cost = comp.get("unit_cost", Decimal("0"))
        cost_per_litre = float(unit_cost) if unit_cost else 0.0
        total_cost = round(cost_per_litre * float(volume), 2)

        fluid_entries.append({
            "stock_item_id": str(stock_item_id) if not isinstance(stock_item_id, str) else stock_item_id,
            "catalogue_item_id": comp.get("catalogue_item_id", ""),
            "item_name": comp.get("name", ""),
            "litres": float(volume),
            "cost_per_litre": cost_per_litre,
            "total_cost": total_cost,
        })

    if not fluid_entries:
        return

    # Merge with existing fluid_usage in invoice_data_json
    data_json = dict(getattr(invoice, "invoice_data_json", None) or {})
    existing_fluid_usage = data_json.get("fluid_usage", [])
    if existing_fluid_usage is None:
        existing_fluid_usage = []

    existing_fluid_usage.extend(fluid_entries)
    data_json["fluid_usage"] = existing_fluid_usage
    invoice.invoice_data_json = data_json
    flag_modified(invoice, "invoice_data_json")
    await db.flush()


# ---------------------------------------------------------------------------
# 11.4 — handle_quote_package_item
# Requirements: 8.5
# ---------------------------------------------------------------------------


async def handle_quote_package_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    catalogue_item_id: uuid.UUID,
) -> dict:
    """Handle a package item on a quote — cost preview without inventory deduction.

    Shows cost/profit preview on quotes but does NOT deduct inventory.
    Deduction only occurs when the quote is converted to an invoice and issued.

    Returns:
        dict with keys:
        - is_package: True if the item is a package
        - cost_price: Decimal total cost for cost/profit preview
        - components: resolved component details (for display)
        - warnings: list of any availability warnings
    """
    # Use resolve_package_line_item for cost calculation (same logic)
    resolution = await resolve_package_line_item(
        db,
        org_id=org_id,
        catalogue_item_id=catalogue_item_id,
    )

    if not resolution.get("is_package"):
        return {
            "is_package": False,
            "cost_price": None,
            "components": [],
            "warnings": [],
        }

    # Generate warnings for unavailable components
    warnings = []
    for comp in resolution.get("components", []):
        if not comp.get("is_available", True):
            comp_name = comp.get("name", "Unknown")
            warnings.append(
                f"Component '{comp_name}' is unavailable — "
                f"using snapshot cost for preview."
            )

    return {
        "is_package": True,
        "cost_price": resolution["cost_price"],
        "components": resolution["components"],
        "warnings": warnings,
    }
