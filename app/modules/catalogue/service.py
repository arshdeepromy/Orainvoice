"""Business logic for Items Catalogue, Parts Catalogue, and Labour Rates CRUD.

Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6,
              5.1, 5.6, 9.1, 9.3, 9.4, 10.1, 10.3, 11.4,
              27.1, 27.2, 27.3, 28.1, 28.2, 28.3
"""

from __future__ import annotations

import copy
import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.catalogue.models import ItemsCatalogue, LabourRate, PartsCatalogue
from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.inventory.models import StockItem

logger = logging.getLogger(__name__)


def _item_to_dict(item: ItemsCatalogue, *, include_costs: bool = False, package_cost: float | None = None, package_profit: float | None = None, has_unavailable_components: bool = False) -> dict:
    """Convert an ItemsCatalogue ORM instance to a serialisable dict.

    Args:
        include_costs: If True, include package_cost and package_profit fields.
        package_cost: Pre-computed package cost (admin only).
        package_profit: Pre-computed package profit (admin only).
        has_unavailable_components: Whether any component is deactivated.
    """
    result = {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "default_price": str(item.default_price),
        "is_gst_exempt": item.is_gst_exempt,
        "gst_inclusive": getattr(item, 'gst_inclusive', False),
        "category": item.category,
        "is_active": item.is_active,
        "is_package": getattr(item, 'is_package', False),
        "package_components": getattr(item, 'package_components', None),
        "has_unavailable_components": has_unavailable_components,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
    if include_costs:
        result["package_cost"] = package_cost
        result["package_profit"] = package_profit
    else:
        result["package_cost"] = None
        result["package_profit"] = None
    return result


# Backward-compatible alias
_service_to_dict = _item_to_dict


# ---------------------------------------------------------------------------
# Package component helpers — Requirements: 7.1, 7.2, 7.3
# ---------------------------------------------------------------------------


async def _validate_and_snapshot_components(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    components: list[dict],
) -> list[dict]:
    """Validate each component exists and capture cost_per_unit_snapshot.

    For each component:
    - Validate catalogue_item_id exists in parts_catalogue or fluid_oil_products
    - Capture cost_per_unit_snapshot from stock_items (preferred) or catalogue fallback

    Returns the components list with cost_per_unit_snapshot populated.
    Raises ValueError if any component references a non-existent catalogue item.

    Requirements: 7.2, 7.3
    """
    validated = []
    for comp in components:
        catalogue_item_id = comp.get("catalogue_item_id")
        catalogue_type = comp.get("catalogue_type")

        if isinstance(catalogue_item_id, str):
            catalogue_item_id = uuid.UUID(catalogue_item_id)

        # Validate the catalogue item exists
        if catalogue_type in ("part", "tyre"):
            result = await db.execute(
                select(PartsCatalogue.id, PartsCatalogue.cost_per_unit).where(
                    PartsCatalogue.id == catalogue_item_id,
                    PartsCatalogue.org_id == org_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                raise ValueError(f"Component not found: {catalogue_item_id}")
            catalogue_cost = float(row.cost_per_unit) if row.cost_per_unit else None
        elif catalogue_type == "fluid":
            result = await db.execute(
                select(FluidOilProduct.id, FluidOilProduct.cost_per_unit).where(
                    FluidOilProduct.id == catalogue_item_id,
                    FluidOilProduct.org_id == org_id,
                )
            )
            row = result.one_or_none()
            if row is None:
                raise ValueError(f"Component not found: {catalogue_item_id}")
            catalogue_cost = float(row.cost_per_unit) if row.cost_per_unit else None
        else:
            raise ValueError(f"Invalid catalogue_type: {catalogue_type}")

        # Try to get cost from stock_items first (more accurate, branch-specific)
        stock_result = await db.execute(
            select(StockItem.purchase_price, StockItem.cost_per_unit).where(
                StockItem.catalogue_item_id == catalogue_item_id,
                StockItem.org_id == org_id,
            ).limit(1)
        )
        stock_row = stock_result.one_or_none()
        if stock_row is not None:
            # Prefer purchase_price, fall back to cost_per_unit
            cost = stock_row.purchase_price or stock_row.cost_per_unit
            snapshot_cost = float(cost) if cost else catalogue_cost
        else:
            snapshot_cost = catalogue_cost

        # Build the validated component dict
        validated_comp = {
            "catalogue_item_id": str(catalogue_item_id),
            "catalogue_type": catalogue_type,
            "cost_per_unit_snapshot": snapshot_cost,
        }
        # Copy quantity/volume and optional fluid metadata
        if catalogue_type in ("part", "tyre"):
            validated_comp["quantity"] = comp.get("quantity")
        elif catalogue_type == "fluid":
            validated_comp["volume"] = comp.get("volume")
            validated_comp["fluid_type"] = comp.get("fluid_type")
            validated_comp["oil_type"] = comp.get("oil_type")
            validated_comp["grade"] = comp.get("grade")

        validated.append(validated_comp)

    return validated


async def list_items(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
    category: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user_role: str | None = None,
) -> dict:
    """List items catalogue entries for an organisation.

    When ``active_only`` is True, only active items are returned.
    When ``search`` is provided, filters items whose name contains the
    search term (case-insensitive).

    Includes package metadata:
    - is_package, has_unavailable_components for all roles
    - package_cost, package_profit for admin roles only (org_admin, global_admin)

    Requirements: 2.1, 2.5, 9.1, 9.3, 10.3, 11.4
    """
    is_admin = user_role in ("org_admin", "global_admin")

    filters = [ItemsCatalogue.org_id == org_id]

    if active_only:
        filters.append(ItemsCatalogue.is_active.is_(True))

    if category:
        filters.append(ItemsCatalogue.category == category)

    if search:
        filters.append(ItemsCatalogue.name.ilike(f"%{search}%"))

    count_stmt = select(func.count(ItemsCatalogue.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(ItemsCatalogue)
        .where(*filters)
        .order_by(ItemsCatalogue.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    items_list = []
    for item in items:
        has_unavailable = False
        package_cost = None
        package_profit = None

        if getattr(item, 'is_package', False) and item.package_components:
            # Check component availability
            has_unavailable = await _check_unavailable_components(
                db, org_id=org_id, components=item.package_components
            )

            # Calculate cost/profit for admin roles
            if is_admin:
                package_cost = await _calculate_package_cost(
                    db, org_id=org_id, components=item.package_components
                )
                if package_cost is not None:
                    package_profit = float(item.default_price) - package_cost

        items_list.append(
            _item_to_dict(
                item,
                include_costs=is_admin,
                package_cost=package_cost,
                package_profit=package_profit,
                has_unavailable_components=has_unavailable,
            )
        )

    return {
        "items": items_list,
        "total": total,
    }


async def create_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    default_price: str,
    category: str | None = None,
    description: str | None = None,
    is_gst_exempt: bool = False,
    gst_inclusive: bool = False,
    is_active: bool = True,
    is_package: bool = False,
    package_components: list[dict] | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new items catalogue entry.

    Accepts any string or None for category (free-text, no constraint).
    When is_package=True and package_components is provided, validates each
    component exists and captures cost_per_unit_snapshot from current prices.

    Requirements: 1.4, 1.5, 2.2, 7.1, 7.2, 7.3
    """
    try:
        price = Decimal(default_price)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid price format")

    if price < 0:
        raise ValueError("Price cannot be negative")

    # Validate and snapshot package components if provided
    persisted_components = None
    if is_package and package_components:
        persisted_components = await _validate_and_snapshot_components(
            db, org_id=org_id, components=package_components
        )
    elif package_components and not is_package:
        raise ValueError("is_package must be true when package_components is provided")

    item = ItemsCatalogue(
        org_id=org_id,
        name=name,
        description=description,
        default_price=price,
        is_gst_exempt=is_gst_exempt,
        gst_inclusive=gst_inclusive,
        category=category or "general",
        is_active=is_active,
        is_package=is_package,
        package_components=persisted_components,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.item.created",
        entity_type="items_catalogue",
        entity_id=item.id,
        before_value=None,
        after_value={
            "name": name,
            "default_price": str(price),
            "category": category,
            "is_gst_exempt": is_gst_exempt,
            "gst_inclusive": gst_inclusive,
            "is_active": is_active,
            "is_package": is_package,
            "package_components": persisted_components,
        },
        ip_address=ip_address,
    )

    return _item_to_dict(item)


async def update_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    ip_address: str | None = None,
    **kwargs,
) -> dict:
    """Update an items catalogue entry. Only non-None kwargs are applied.

    Accepts any string or None for category (free-text, no constraint).
    Handles package data:
    - Replaces existing package_components with the new set (not merge)
    - If is_package set to false, clears package_components to null
    - Re-snapshots cost_per_unit_snapshot from current prices on update

    Requirements: 2.3, 7.4, 7.5, 7.6
    """
    result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == item_id,
            ItemsCatalogue.org_id == org_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Item not found")

    allowed_fields = {"name", "description", "default_price", "is_gst_exempt", "gst_inclusive", "category", "is_active"}
    before_value = {}
    updated_fields = []

    for field in allowed_fields:
        value = kwargs.get(field)
        if value is not None:
            if field == "default_price":
                try:
                    value = Decimal(value)
                except (InvalidOperation, ValueError):
                    raise ValueError("Invalid price format")
                if value < 0:
                    raise ValueError("Price cannot be negative")

            before_value[field] = str(getattr(item, field)) if field == "default_price" else getattr(item, field)
            setattr(item, field, value)
            updated_fields.append(field)

    # Handle package fields — Requirements: 7.4, 7.5, 7.6
    is_package_value = kwargs.get("is_package")
    package_components_value = kwargs.get("package_components")

    # If is_package explicitly set to False, clear package_components
    if is_package_value is False:
        before_value["is_package"] = item.is_package
        before_value["package_components"] = item.package_components
        item.is_package = False
        item.package_components = None
        updated_fields.extend(["is_package", "package_components"])
    elif is_package_value is True:
        before_value["is_package"] = item.is_package
        item.is_package = True
        updated_fields.append("is_package")

        # If package_components provided, validate and re-snapshot
        if package_components_value is not None:
            before_value["package_components"] = item.package_components
            persisted_components = await _validate_and_snapshot_components(
                db, org_id=org_id, components=package_components_value
            )
            item.package_components = persisted_components
            updated_fields.append("package_components")
    elif package_components_value is not None:
        # package_components provided without explicit is_package change
        # Only valid if item is already a package or is_package is being set
        if not item.is_package:
            raise ValueError("is_package must be true when package_components is provided")
        before_value["package_components"] = item.package_components
        persisted_components = await _validate_and_snapshot_components(
            db, org_id=org_id, components=package_components_value
        )
        item.package_components = persisted_components
        updated_fields.append("package_components")

    if not updated_fields:
        return _item_to_dict(item)

    await db.flush()
    await db.refresh(item)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.item.updated",
        entity_type="items_catalogue",
        entity_id=item.id,
        before_value=before_value,
        after_value={f: (str(kwargs[f]) if f == "default_price" else kwargs.get(f, getattr(item, f, None))) for f in updated_fields},
        ip_address=ip_address,
    )

    return _item_to_dict(item)


async def get_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
) -> dict:
    """Retrieve a single item by ID within the organisation."""
    result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == item_id,
            ItemsCatalogue.org_id == org_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Item not found")

    return _item_to_dict(item)


# ---------------------------------------------------------------------------
# Package availability & cost helpers — Requirements: 9.1, 9.3, 10.3, 11.4
# ---------------------------------------------------------------------------


async def _check_unavailable_components(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    components: list[dict],
) -> bool:
    """Check if any component in the package is deactivated/unavailable.

    Returns True if at least one component is unavailable.

    Requirements: 11.4
    """
    for comp in components:
        catalogue_item_id = comp.get("catalogue_item_id")
        catalogue_type = comp.get("catalogue_type")

        if isinstance(catalogue_item_id, str):
            catalogue_item_id = uuid.UUID(catalogue_item_id)

        if catalogue_type in ("part", "tyre"):
            result = await db.execute(
                select(PartsCatalogue.is_active).where(
                    PartsCatalogue.id == catalogue_item_id,
                    PartsCatalogue.org_id == org_id,
                )
            )
            row = result.one_or_none()
            if row is None or not row.is_active:
                return True
        elif catalogue_type == "fluid":
            result = await db.execute(
                select(FluidOilProduct.is_active).where(
                    FluidOilProduct.id == catalogue_item_id,
                    FluidOilProduct.org_id == org_id,
                )
            )
            row = result.one_or_none()
            if row is None or not row.is_active:
                return True

    return False


async def _calculate_package_cost(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    components: list[dict],
) -> float | None:
    """Calculate total package cost from live stock/catalogue prices.

    For each component:
    - Query stock_items for live price (purchase_price or cost_per_unit)
    - Fall back to catalogue cost_per_unit if no stock item
    - Multiply by quantity (parts/tyres) or volume (fluids)

    Returns total cost as float, or None if no components.

    Requirements: 5.1
    """
    if not components:
        return None

    total_cost = 0.0
    for comp in components:
        catalogue_item_id = comp.get("catalogue_item_id")
        catalogue_type = comp.get("catalogue_type")

        if isinstance(catalogue_item_id, str):
            catalogue_item_id = uuid.UUID(catalogue_item_id)

        # Try stock_items first
        stock_result = await db.execute(
            select(StockItem.purchase_price, StockItem.cost_per_unit).where(
                StockItem.catalogue_item_id == catalogue_item_id,
                StockItem.org_id == org_id,
            ).limit(1)
        )
        stock_row = stock_result.one_or_none()

        if stock_row is not None:
            cost = stock_row.purchase_price or stock_row.cost_per_unit
            unit_cost = float(cost) if cost else 0.0
        else:
            # Fall back to catalogue
            if catalogue_type in ("part", "tyre"):
                cat_result = await db.execute(
                    select(PartsCatalogue.cost_per_unit).where(
                        PartsCatalogue.id == catalogue_item_id,
                    )
                )
                cat_row = cat_result.one_or_none()
                unit_cost = float(cat_row.cost_per_unit) if cat_row and cat_row.cost_per_unit else 0.0
            elif catalogue_type == "fluid":
                cat_result = await db.execute(
                    select(FluidOilProduct.cost_per_unit).where(
                        FluidOilProduct.id == catalogue_item_id,
                    )
                )
                cat_row = cat_result.one_or_none()
                unit_cost = float(cat_row.cost_per_unit) if cat_row and cat_row.cost_per_unit else 0.0
            else:
                unit_cost = 0.0

        # Calculate line total
        if catalogue_type in ("part", "tyre"):
            quantity = comp.get("quantity", 1)
            total_cost += unit_cost * (quantity or 1)
        elif catalogue_type == "fluid":
            volume = comp.get("volume", 0)
            total_cost += unit_cost * (volume or 0)

    return round(total_cost, 2)


# ---------------------------------------------------------------------------
# resolve_package_costs — Requirements: 5.1, 5.6, 10.1, 10.3
# ---------------------------------------------------------------------------


async def resolve_package_costs(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    item_id: uuid.UUID,
    user_role: str | None = None,
) -> dict:
    """Resolve live costs for all components of a package item.

    For each component:
    - Query stock_items by catalogue_item_id and org_id
    - Single stock item → use its purchase_price or cost_per_unit
    - Multiple stock items → return all options (branch, cost, available qty)
    - No stock item → fall back to catalogue cost_per_unit

    Calculate line_total per component and total_cost sum.
    Omit cost fields for non-admin roles.

    Requirements: 5.1, 5.6, 10.1, 10.3
    """
    is_admin = user_role in ("org_admin", "global_admin")

    # Fetch the item
    result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == item_id,
            ItemsCatalogue.org_id == org_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Item not found")

    if not item.is_package or not item.package_components:
        raise ValueError("Item is not a package or has no components")

    components_response = []
    total_cost = 0.0

    for comp in item.package_components:
        catalogue_item_id = comp.get("catalogue_item_id")
        catalogue_type = comp.get("catalogue_type")

        if isinstance(catalogue_item_id, str):
            catalogue_item_id = uuid.UUID(catalogue_item_id)

        # Get component name from catalogue
        name = "Unknown"
        catalogue_cost = 0.0
        is_available = True

        if catalogue_type in ("part", "tyre"):
            cat_result = await db.execute(
                select(
                    PartsCatalogue.name,
                    PartsCatalogue.cost_per_unit,
                    PartsCatalogue.is_active,
                ).where(
                    PartsCatalogue.id == catalogue_item_id,
                    PartsCatalogue.org_id == org_id,
                )
            )
            cat_row = cat_result.one_or_none()
            if cat_row:
                name = cat_row.name
                catalogue_cost = float(cat_row.cost_per_unit) if cat_row.cost_per_unit else 0.0
                is_available = cat_row.is_active
            else:
                is_available = False
        elif catalogue_type == "fluid":
            cat_result = await db.execute(
                select(
                    FluidOilProduct.product_name,
                    FluidOilProduct.cost_per_unit,
                    FluidOilProduct.is_active,
                ).where(
                    FluidOilProduct.id == catalogue_item_id,
                    FluidOilProduct.org_id == org_id,
                )
            )
            cat_row = cat_result.one_or_none()
            if cat_row:
                name = cat_row.product_name or "Unknown Fluid"
                catalogue_cost = float(cat_row.cost_per_unit) if cat_row.cost_per_unit else 0.0
                is_available = cat_row.is_active
            else:
                is_available = False

        # Query stock_items for this component
        stock_result = await db.execute(
            select(StockItem).where(
                StockItem.catalogue_item_id == catalogue_item_id,
                StockItem.org_id == org_id,
            )
        )
        stock_items = stock_result.scalars().all()

        # Determine cost and stock availability
        cost_per_unit = catalogue_cost
        stock_available = 0.0
        stock_options = None

        if len(stock_items) == 1:
            si = stock_items[0]
            cost_per_unit = float(si.purchase_price or si.cost_per_unit or 0)
            stock_available = float(si.current_quantity)
        elif len(stock_items) > 1:
            # Multiple stock items — return all options
            stock_options = []
            for si in stock_items:
                option = {
                    "stock_item_id": str(si.id),
                    "branch_id": str(si.branch_id) if si.branch_id else None,
                    "location": si.location,
                    "available_qty": float(si.current_quantity),
                }
                if is_admin:
                    option["cost_per_unit"] = float(si.purchase_price or si.cost_per_unit or 0)
                stock_options.append(option)
            # Use first stock item's cost as default
            si = stock_items[0]
            cost_per_unit = float(si.purchase_price or si.cost_per_unit or 0)
            stock_available = sum(float(s.current_quantity) for s in stock_items)
        # else: no stock items, use catalogue_cost (already set)

        # Calculate line total
        if catalogue_type in ("part", "tyre"):
            quantity = comp.get("quantity", 1)
            line_total = cost_per_unit * (quantity or 1)
        elif catalogue_type == "fluid":
            volume = comp.get("volume", 0)
            line_total = cost_per_unit * (volume or 0)
        else:
            line_total = 0.0

        total_cost += line_total

        # Build component response
        comp_response: dict = {
            "catalogue_item_id": str(catalogue_item_id),
            "catalogue_type": catalogue_type,
            "name": name,
            "is_available": is_available,
            "stock_available": stock_available,
        }

        if catalogue_type in ("part", "tyre"):
            comp_response["quantity"] = comp.get("quantity")
        elif catalogue_type == "fluid":
            comp_response["volume"] = comp.get("volume")

        if is_admin:
            comp_response["cost_per_unit"] = cost_per_unit
            comp_response["line_total"] = round(line_total, 2)

        if stock_options:
            comp_response["stock_options"] = stock_options

        components_response.append(comp_response)

    # Build final response
    response: dict = {
        "components": components_response,
    }

    if is_admin:
        sell_price = float(item.default_price)
        response["total_cost"] = round(total_cost, 2)
        response["sell_price"] = sell_price
        response["profit"] = round(sell_price - total_cost, 2)

    return response


# ---------------------------------------------------------------------------
# duplicate_item — Requirements: 9.4
# ---------------------------------------------------------------------------


async def duplicate_item(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Deep-copy a package item with all package_components data.

    Appends " (Copy)" to the name and generates a new UUID.
    Only allows duplication of package items (is_package=true).

    Requirements: 9.4
    """
    # Fetch the original item
    result = await db.execute(
        select(ItemsCatalogue).where(
            ItemsCatalogue.id == item_id,
            ItemsCatalogue.org_id == org_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Item not found")

    if not item.is_package:
        raise ValueError("Only package items can be duplicated")

    # Deep-copy the package_components
    components_copy = copy.deepcopy(item.package_components) if item.package_components else None

    # Create the duplicate
    duplicate = ItemsCatalogue(
        org_id=org_id,
        name=f"{item.name} (Copy)",
        description=item.description,
        default_price=item.default_price,
        is_gst_exempt=item.is_gst_exempt,
        gst_inclusive=item.gst_inclusive,
        category=item.category,
        is_active=item.is_active,
        is_package=True,
        package_components=components_copy,
    )
    db.add(duplicate)
    await db.flush()
    await db.refresh(duplicate)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.item.duplicated",
        entity_type="items_catalogue",
        entity_id=duplicate.id,
        before_value=None,
        after_value={
            "source_item_id": str(item_id),
            "name": duplicate.name,
            "is_package": True,
            "package_components": components_copy,
        },
        ip_address=ip_address,
    )

    return _item_to_dict(duplicate)


# ---------------------------------------------------------------------------
# Backward-compatible aliases — other modules (router, bookings, tests) still
# import the old names until they are updated in later tasks.
# ---------------------------------------------------------------------------
list_services = list_items
create_service = create_item
update_service = update_item
get_service = get_item


# ===========================================================================
# Parts Catalogue CRUD — Requirements: 28.1, 28.2
# ===========================================================================


def _compute_pricing(
    purchase_price: Decimal | None,
    qty_per_pack: int | None,
    total_packs: int | None,
    sell_price_per_unit: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Derive cost_per_unit, margin, and margin_pct from pricing inputs.

    Returns (cost_per_unit, margin, margin_pct).  Any field that cannot be
    computed (missing or invalid inputs) is returned as ``None``.

    Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4
    """
    cost_per_unit: Decimal | None = None
    margin: Decimal | None = None
    margin_pct: Decimal | None = None

    if (
        purchase_price is not None
        and qty_per_pack is not None
        and total_packs is not None
        and purchase_price > 0
        and qty_per_pack > 0
        and total_packs > 0
    ):
        total_units = qty_per_pack * total_packs
        cost_per_unit = Decimal(str(purchase_price)) / Decimal(str(total_units))

    if sell_price_per_unit is not None and cost_per_unit is not None:
        margin = Decimal(str(sell_price_per_unit)) - cost_per_unit
        if sell_price_per_unit > 0:
            margin_pct = (margin / Decimal(str(sell_price_per_unit))) * Decimal("100")
        else:
            margin_pct = Decimal("0.00")

    return cost_per_unit, margin, margin_pct

def _map_gst_legacy(is_gst_exempt: bool, gst_inclusive: bool) -> str:
    """Map legacy GST boolean fields to the unified gst_mode string.

    Requirements: 4.3, 4.4, 4.5, 4.6
    """
    if is_gst_exempt:
        return "exempt"
    if gst_inclusive:
        return "inclusive"
    return "exclusive"



def _part_to_dict(part: PartsCatalogue) -> dict:
    """Convert a PartsCatalogue ORM instance to a serialisable dict."""
    # Use getattr with None default to avoid lazy-load greenlet errors
    cat_name = None
    sup_name = None
    sup_id = part.supplier_id
    cat_id = part.category_id
    try:
        cat = getattr(part, "category", None)
        if cat is not None:
            cat_name = cat.name
    except Exception:
        pass
    try:
        sup = getattr(part, "supplier", None)
        if sup is not None:
            sup_name = sup.name
    except Exception:
        pass
    return {
        "id": str(part.id),
        "name": part.name,
        "part_number": part.part_number,
        "description": getattr(part, "description", None),
        "part_type": getattr(part, "part_type", None) or "part",
        "category_id": str(cat_id) if cat_id else None,
        "category_name": cat_name,
        "brand": getattr(part, "brand", None),
        "supplier_id": str(sup_id) if sup_id else None,
        "supplier_name": sup_name or getattr(part, "_supplier_name", None),
        "default_price": str(part.default_price),
        "is_gst_exempt": getattr(part, 'is_gst_exempt', False),
        "gst_inclusive": getattr(part, 'gst_inclusive', False),
        "supplier": getattr(part, "_supplier_name", None) or sup_name,
        "is_active": part.is_active,
        # Packaging & pricing fields
        "purchase_price": str(part.purchase_price) if part.purchase_price is not None else None,
        "packaging_type": part.packaging_type,
        "qty_per_pack": part.qty_per_pack,
        "total_packs": part.total_packs,
        "cost_per_unit": str(part.cost_per_unit) if part.cost_per_unit is not None else None,
        "sell_price_per_unit": str(part.sell_price_per_unit) if part.sell_price_per_unit is not None else None,
        "margin": str(part.margin) if part.margin is not None else None,
        "margin_pct": str(part.margin_pct) if part.margin_pct is not None else None,
        "gst_mode": part.gst_mode if part.gst_mode is not None else _map_gst_legacy(
            getattr(part, 'is_gst_exempt', False),
            getattr(part, 'gst_inclusive', False),
        ),
        "tyre_width": getattr(part, "tyre_width", None),
        "tyre_profile": getattr(part, "tyre_profile", None),
        "tyre_rim_dia": getattr(part, "tyre_rim_dia", None),
        "tyre_load_index": getattr(part, "tyre_load_index", None),
        "tyre_speed_index": getattr(part, "tyre_speed_index", None),
        "created_at": part.created_at.isoformat() if part.created_at else None,
        "updated_at": part.updated_at.isoformat() if part.updated_at else None,
    }


async def list_parts(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List parts catalogue entries for an organisation.

    Requirements: 28.1
    """
    filters = [PartsCatalogue.org_id == org_id]

    if active_only:
        filters.append(PartsCatalogue.is_active.is_(True))

    count_stmt = select(func.count(PartsCatalogue.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(PartsCatalogue)
        .where(*filters)
        .order_by(PartsCatalogue.name)
        .limit(limit)
        .offset(offset)
    )
    from sqlalchemy.orm import selectinload
    stmt = stmt.options(
        selectinload(PartsCatalogue.category),
        selectinload(PartsCatalogue.supplier),
    )
    result = await db.execute(stmt)
    parts = result.scalars().all()

    return {
        "parts": [_part_to_dict(p) for p in parts],
        "total": total,
    }


async def create_part(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    default_price: str,
    part_number: str | None = None,
    description: str | None = None,
    part_type: str = "part",
    category_id: str | None = None,
    brand: str | None = None,
    supplier_id: str | None = None,
    supplier: str | None = None,
    is_gst_exempt: bool = False,
    gst_inclusive: bool = False,
    is_active: bool = True,
    min_stock_threshold: int = 0,
    reorder_quantity: int = 0,
    # Packaging & pricing fields
    purchase_price: str | None = None,
    packaging_type: str | None = None,
    qty_per_pack: int | None = None,
    total_packs: int | None = None,
    sell_price_per_unit: str | None = None,
    gst_mode: str | None = None,
    tyre_width: str | None = None,
    tyre_profile: str | None = None,
    tyre_rim_dia: str | None = None,
    tyre_load_index: str | None = None,
    tyre_speed_index: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new parts catalogue entry.

    Requirements: 28.1, 7.1, 7.4
    """
    try:
        price = Decimal(default_price)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid price format")

    if price < 0:
        raise ValueError("Price cannot be negative")

    # Parse optional Decimal pricing fields
    pp: Decimal | None = None
    if purchase_price is not None:
        try:
            pp = Decimal(purchase_price)
        except (InvalidOperation, ValueError):
            raise ValueError("Invalid purchase_price format")

    spu: Decimal | None = None
    if sell_price_per_unit is not None:
        try:
            spu = Decimal(sell_price_per_unit)
        except (InvalidOperation, ValueError):
            raise ValueError("Invalid sell_price_per_unit format")

    # Compute derived pricing fields
    cost_per_unit, margin, margin_pct = _compute_pricing(
        pp, qty_per_pack, total_packs, spu,
    )

    part = PartsCatalogue(
        org_id=org_id,
        name=name,
        part_number=part_number,
        description=description,
        part_type=part_type or "part",
        category_id=uuid.UUID(category_id) if category_id else None,
        brand=brand,
        supplier_id=uuid.UUID(supplier_id) if supplier_id else None,
        default_price=price,
        is_gst_exempt=is_gst_exempt,
        gst_inclusive=gst_inclusive,
        min_stock_threshold=min_stock_threshold,
        reorder_quantity=reorder_quantity,
        is_active=is_active,
        # Packaging & pricing
        purchase_price=pp,
        packaging_type=packaging_type,
        qty_per_pack=qty_per_pack,
        total_packs=total_packs,
        cost_per_unit=cost_per_unit,
        sell_price_per_unit=spu,
        margin=margin,
        margin_pct=margin_pct,
        gst_mode=gst_mode,
        tyre_width=tyre_width,
        tyre_profile=tyre_profile,
        tyre_rim_dia=tyre_rim_dia,
        tyre_load_index=tyre_load_index,
        tyre_speed_index=tyre_speed_index,
    )
    part._supplier_name = supplier  # type: ignore[attr-defined]
    db.add(part)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.part.created",
        entity_type="parts_catalogue",
        entity_id=part.id,
        before_value=None,
        after_value={
            "name": name,
            "part_number": part_number,
            "default_price": str(price),
            "supplier": supplier,
            "is_active": is_active,
        },
        ip_address=ip_address,
    )

    # Re-fetch with eager loading for the response
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(PartsCatalogue)
        .where(PartsCatalogue.id == part.id)
        .options(selectinload(PartsCatalogue.category), selectinload(PartsCatalogue.supplier))
    )
    loaded_part = result.scalar_one()
    return _part_to_dict(loaded_part)


# ===========================================================================
# Labour Rates CRUD — Requirements: 28.3
# ===========================================================================


def _labour_rate_to_dict(rate: LabourRate) -> dict:
    """Convert a LabourRate ORM instance to a serialisable dict."""
    return {
        "id": str(rate.id),
        "name": rate.name,
        "hourly_rate": str(rate.hourly_rate),
        "is_active": rate.is_active,
        "created_at": rate.created_at.isoformat() if rate.created_at else None,
        "updated_at": rate.updated_at.isoformat() if rate.updated_at else None,
    }


async def list_labour_rates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List labour rates for an organisation.

    Requirements: 28.3
    """
    filters = [LabourRate.org_id == org_id]

    if active_only:
        filters.append(LabourRate.is_active.is_(True))

    count_stmt = select(func.count(LabourRate.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(LabourRate)
        .where(*filters)
        .order_by(LabourRate.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    rates = result.scalars().all()

    return {
        "labour_rates": [_labour_rate_to_dict(r) for r in rates],
        "total": total,
    }


async def create_labour_rate(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    hourly_rate: str,
    is_active: bool = True,
    ip_address: str | None = None,
) -> dict:
    """Create a new labour rate.

    Requirements: 28.3
    """
    try:
        rate = Decimal(hourly_rate)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid hourly rate format")

    if rate < 0:
        raise ValueError("Hourly rate cannot be negative")

    labour_rate = LabourRate(
        org_id=org_id,
        name=name,
        hourly_rate=rate,
        is_active=is_active,
    )
    db.add(labour_rate)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.labour_rate.created",
        entity_type="labour_rates",
        entity_id=labour_rate.id,
        before_value=None,
        after_value={
            "name": name,
            "hourly_rate": str(rate),
            "is_active": is_active,
        },
        ip_address=ip_address,
    )

    return _labour_rate_to_dict(labour_rate)


async def update_labour_rate(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    name: str | None = None,
    hourly_rate: str | None = None,
    is_active: bool | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update an existing labour rate.

    Only provided fields are updated. Returns the updated rate dict.
    """
    result = await db.execute(
        select(LabourRate).where(
            LabourRate.id == rate_id,
            LabourRate.org_id == org_id,
        )
    )
    labour_rate = result.scalar_one_or_none()
    if labour_rate is None:
        raise ValueError("Labour rate not found")

    before = _labour_rate_to_dict(labour_rate)

    if name is not None:
        labour_rate.name = name
    if hourly_rate is not None:
        try:
            rate = Decimal(hourly_rate)
        except (InvalidOperation, ValueError):
            raise ValueError("Invalid hourly rate format")
        if rate < 0:
            raise ValueError("Hourly rate cannot be negative")
        labour_rate.hourly_rate = rate
    if is_active is not None:
        labour_rate.is_active = is_active

    await db.flush()
    await db.refresh(labour_rate)

    after = _labour_rate_to_dict(labour_rate)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.labour_rate.updated",
        entity_type="labour_rates",
        entity_id=labour_rate.id,
        before_value=before,
        after_value=after,
        ip_address=ip_address,
    )

    return after


async def delete_labour_rate(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    rate_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Permanently delete a labour rate.

    Hard delete — the record is removed from the database.
    """
    result = await db.execute(
        select(LabourRate).where(
            LabourRate.id == rate_id,
            LabourRate.org_id == org_id,
        )
    )
    labour_rate = result.scalar_one_or_none()
    if labour_rate is None:
        raise ValueError("Labour rate not found")

    before = _labour_rate_to_dict(labour_rate)

    await db.delete(labour_rate)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="catalogue.labour_rate.deleted",
        entity_type="labour_rates",
        entity_id=rate_id,
        before_value=before,
        after_value=None,
        ip_address=ip_address,
    )
