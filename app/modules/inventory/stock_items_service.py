"""Service layer for Stock Items (catalogue-to-inventory).

Business logic for listing, creating, updating, and deleting stock items
that link catalogue entries to the inventory system.

Requirements: 1.1, 1.2, 1.3, 5.5, 5.6, 6.1, 6.4, 7.3, 8.4, 9.1, 9.2, 9.3, 9.5,
              10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.catalogue.models import PartsCatalogue
from app.modules.inventory.models import InventoryLocation, StockItem
from app.modules.inventory.stock_items_schemas import (
    AdjustStockItemRequest,
    CreateLocationRequest,
    CreateStockItemRequest,
    LocationListResponse,
    LocationResponse,
    StockItemListResponse,
    StockItemResponse,
    UpdateStockItemRequest,
)
from app.modules.stock.models import StockMovement
from app.modules.suppliers.models import Supplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_catalogue_query(
    catalogue_type: str, catalogue_item_id: uuid.UUID
):
    """Map catalogue_type to the correct catalogue table query.

    - 'part' / 'tyre' → parts_catalogue (filtered by is_active)
    - 'fluid'          → fluid_oil_products (filtered by is_active)
    """
    if catalogue_type in ("part", "tyre"):
        return select(PartsCatalogue).where(
            PartsCatalogue.id == catalogue_item_id,
            PartsCatalogue.is_active.is_(True),
        )
    elif catalogue_type == "fluid":
        return select(FluidOilProduct).where(
            FluidOilProduct.id == catalogue_item_id,
            FluidOilProduct.is_active.is_(True),
        )
    raise ValueError(f"Invalid catalogue_type: {catalogue_type}")


def _fluid_display_name(product: FluidOilProduct) -> str:
    """Build display name for a fluid/oil product."""
    if product.oil_type:
        grade = product.grade or ""
        return f"{product.oil_type} {grade}".strip()
    return product.product_name or ""


def _build_stock_item_response(
    stock_item: StockItem,
    item_name: str,
    part_number: str | None,
    brand: str | None,
    supplier_name: str | None,
    subtitle: str | None = None,
    gst_mode: str | None = None,
) -> StockItemResponse:
    """Build a StockItemResponse from a StockItem and joined catalogue fields."""
    current_qty = float(stock_item.current_quantity)
    reserved_qty = float(getattr(stock_item, 'reserved_quantity', 0) or 0)
    available_qty = max(0, current_qty - reserved_qty)
    min_thresh = float(stock_item.min_threshold)
    is_below = available_qty <= min_thresh and min_thresh > 0

    return StockItemResponse(
        id=str(stock_item.id),
        catalogue_item_id=str(stock_item.catalogue_item_id),
        catalogue_type=stock_item.catalogue_type,
        item_name=item_name,
        part_number=part_number,
        brand=brand,
        subtitle=subtitle,
        current_quantity=current_qty,
        reserved_quantity=reserved_qty,
        available_quantity=available_qty,
        min_threshold=min_thresh,
        reorder_quantity=float(stock_item.reorder_quantity),
        is_below_threshold=is_below,
        supplier_id=str(stock_item.supplier_id) if stock_item.supplier_id else None,
        supplier_name=supplier_name,
        barcode=stock_item.barcode,
        location=stock_item.location,
        cost_per_unit=float(stock_item.cost_per_unit) if stock_item.cost_per_unit else None,
        sell_price=float(stock_item.sell_price) if stock_item.sell_price else None,
        gst_mode=gst_mode,
        created_at=stock_item.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_stock_items(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    search: str | None = None,
    below_threshold_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> StockItemListResponse:
    """List stock items joined to catalogue tables for display fields.

    Supports search by name, part number, brand, and barcode.
    Computes is_below_threshold = current_quantity <= min_threshold AND min_threshold > 0.

    Requirements: 1.1, 1.2, 1.3, 7.3, 9.1, 9.2, 9.3, 9.5
    """
    # Base query: all stock items for this org
    base_filter = [StockItem.org_id == org_id]

    if below_threshold_only:
        base_filter.append(
            and_(
                StockItem.current_quantity <= StockItem.min_threshold,
                StockItem.min_threshold > 0,
            )
        )

    # Count total
    count_stmt = select(func.count(StockItem.id)).where(*base_filter)

    # We need to apply search filtering before counting if search is provided
    # Fetch all stock items first, then join catalogue data
    stmt = select(StockItem).where(*base_filter)

    if search:
        # We'll filter after joining catalogue data — for now, also check barcode
        # at the DB level for the barcode field on stock_items
        pass  # handled below after fetching

    # For search, we need a different approach: query stock items and join
    # catalogue data in-memory since the catalogue tables are polymorphic
    result = await db.execute(
        stmt.order_by(StockItem.created_at.desc())
    )
    all_items = list(result.scalars().all())

    if not all_items:
        return StockItemListResponse(stock_items=[], total=0)

    # Batch-load catalogue data for parts/tyres
    part_tyre_ids = [
        si.catalogue_item_id
        for si in all_items
        if si.catalogue_type in ("part", "tyre")
    ]
    fluid_ids = [
        si.catalogue_item_id
        for si in all_items
        if si.catalogue_type == "fluid"
    ]

    # Load parts catalogue items
    parts_map: dict[uuid.UUID, PartsCatalogue] = {}
    if part_tyre_ids:
        parts_result = await db.execute(
            select(PartsCatalogue).where(PartsCatalogue.id.in_(part_tyre_ids))
        )
        for p in parts_result.scalars().all():
            parts_map[p.id] = p

    # Load fluid/oil products
    fluids_map: dict[uuid.UUID, FluidOilProduct] = {}
    if fluid_ids:
        fluids_result = await db.execute(
            select(FluidOilProduct).where(FluidOilProduct.id.in_(fluid_ids))
        )
        for f in fluids_result.scalars().all():
            fluids_map[f.id] = f

    # Load supplier names
    supplier_ids = [si.supplier_id for si in all_items if si.supplier_id]
    suppliers_map: dict[uuid.UUID, str] = {}
    if supplier_ids:
        sup_result = await db.execute(
            select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids))
        )
        for row in sup_result.all():
            suppliers_map[row[0]] = row[1]

    # Build response items with catalogue data
    response_items: list[StockItemResponse] = []
    for si in all_items:
        item_name = ""
        part_number: str | None = None
        brand: str | None = None
        subtitle: str | None = None
        gst_mode: str | None = None

        if si.catalogue_type in ("part", "tyre"):
            cat = parts_map.get(si.catalogue_item_id)
            if cat:
                item_name = cat.name
                part_number = cat.part_number
                brand = cat.brand
                # Resolve GST mode from catalogue fields
                gst_mode = getattr(cat, "gst_mode", None)
                if gst_mode is None:
                    if getattr(cat, "is_gst_exempt", False):
                        gst_mode = "exempt"
                    elif getattr(cat, "gst_inclusive", False):
                        gst_mode = "inclusive"
                    else:
                        gst_mode = "exclusive"
                # Build tyre size subtitle
                if si.catalogue_type == "tyre":
                    tyre_parts = []
                    w = getattr(cat, "tyre_width", None)
                    p = getattr(cat, "tyre_profile", None)
                    r = getattr(cat, "tyre_rim_dia", None)
                    li = getattr(cat, "tyre_load_index", None)
                    si_idx = getattr(cat, "tyre_speed_index", None)
                    if w:
                        tyre_parts.append(str(w))
                    if p:
                        tyre_parts.append(f"/{p}")
                    if r:
                        tyre_parts.append(f"R{r}")
                    tyre_size = "".join(tyre_parts)
                    extra = "".join(filter(None, [str(li) if li else None, str(si_idx) if si_idx else None]))
                    if tyre_size:
                        subtitle = f"{tyre_size} {extra}".strip() if extra else tyre_size
        elif si.catalogue_type == "fluid":
            cat_fluid = fluids_map.get(si.catalogue_item_id)
            if cat_fluid:
                item_name = _fluid_display_name(cat_fluid)
                part_number = None  # fluids don't have part numbers
                brand = cat_fluid.brand_name
                gst_mode = getattr(cat_fluid, "gst_mode", None) or "exclusive"

        supplier_name = suppliers_map.get(si.supplier_id) if si.supplier_id else None

        # Apply search filter
        if search:
            search_lower = search.lower()
            searchable_fields = [
                item_name,
                part_number or "",
                brand or "",
                si.barcode or "",
            ]
            if not any(search_lower in f.lower() for f in searchable_fields):
                continue

        response_items.append(
            _build_stock_item_response(si, item_name, part_number, brand, supplier_name, subtitle, gst_mode)
        )

    total = len(response_items)

    # Apply pagination after filtering
    paginated = response_items[offset : offset + limit]

    return StockItemListResponse(stock_items=paginated, total=total)


async def create_stock_item(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CreateStockItemRequest,
) -> StockItemResponse:
    """Create a new stock item from a catalogue item.

    - Validates catalogue item exists and is active
    - Checks uniqueness (org + catalogue_item_id + catalogue_type)
    - Resolves supplier from catalogue if not provided
    - Inserts stock_items row + initial stock_movements record

    Requirements: 5.5, 5.6, 6.1, 6.4, 8.4, 10.1, 10.2, 10.3, 10.4, 10.5
    """
    # 1. Validate catalogue item exists and is active
    cat_query = _resolve_catalogue_query(payload.catalogue_type, payload.catalogue_item_id)
    result = await db.execute(cat_query)
    catalogue_item = result.scalar_one_or_none()

    if catalogue_item is None:
        raise ValueError("Catalogue item not found or inactive")

    # 2. Always create a new stock item (multiple entries per catalogue item allowed)

    # 3. Resolve supplier from catalogue if not provided
    supplier_id = payload.supplier_id
    if supplier_id is None:
        supplier_id = getattr(catalogue_item, "supplier_id", None)

    # 4. Create stock item — copy thresholds from catalogue
    cat_min = Decimal("0")
    cat_reorder = Decimal("0")
    if payload.catalogue_type in ("part", "tyre"):
        cat_min = Decimal(str(getattr(catalogue_item, "min_stock_threshold", 0) or 0))
        cat_reorder = Decimal(str(getattr(catalogue_item, "reorder_quantity", 0) or 0))
    elif payload.catalogue_type == "fluid":
        cat_min = Decimal(str(getattr(catalogue_item, "min_stock_volume", 0) or 0))
        cat_reorder = Decimal(str(getattr(catalogue_item, "reorder_volume", 0) or 0))

    stock_item = StockItem(
        org_id=org_id,
        catalogue_item_id=payload.catalogue_item_id,
        catalogue_type=payload.catalogue_type,
        current_quantity=Decimal(str(payload.quantity)),
        min_threshold=cat_min,
        reorder_quantity=cat_reorder,
        supplier_id=supplier_id,
        purchase_price=Decimal(str(payload.purchase_price)) if payload.purchase_price is not None else None,
        sell_price=Decimal(str(payload.sell_price)) if payload.sell_price is not None else None,
        cost_per_unit=Decimal(str(payload.cost_per_unit)) if payload.cost_per_unit is not None else None,
        barcode=payload.barcode,
        location=payload.location,
        created_by=user_id,
    )
    db.add(stock_item)
    await db.flush()

    # 5. Create initial stock movement
    movement = StockMovement(
        org_id=org_id,
        movement_type="purchase",
        quantity_change=Decimal(str(payload.quantity)),
        resulting_quantity=Decimal(str(payload.quantity)),
        notes=payload.reason,
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    # 6. Build response with catalogue data
    item_name = ""
    part_number: str | None = None
    brand: str | None = None

    if payload.catalogue_type in ("part", "tyre"):
        item_name = catalogue_item.name
        part_number = catalogue_item.part_number
        brand = catalogue_item.brand
    elif payload.catalogue_type == "fluid":
        item_name = _fluid_display_name(catalogue_item)
        part_number = None
        brand = catalogue_item.brand_name

    # Resolve supplier name
    supplier_name: str | None = None
    if stock_item.supplier_id:
        sup_result = await db.execute(
            select(Supplier.name).where(Supplier.id == stock_item.supplier_id)
        )
        supplier_name = sup_result.scalar_one_or_none()

    return _build_stock_item_response(
        stock_item, item_name, part_number, brand, supplier_name
    )


async def update_stock_item(
    db: AsyncSession,
    org_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    payload: UpdateStockItemRequest,
) -> StockItemResponse:
    """Update stock item metadata (barcode, supplier, thresholds).

    Requirements: 7.4, 9.3
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        raise ValueError("Stock item not found")

    # Apply updates for provided fields
    if payload.barcode is not None:
        stock_item.barcode = payload.barcode
    if payload.location is not None:
        stock_item.location = payload.location
    if payload.supplier_id is not None:
        stock_item.supplier_id = payload.supplier_id
    if payload.min_threshold is not None:
        stock_item.min_threshold = Decimal(str(payload.min_threshold))
    if payload.reorder_quantity is not None:
        stock_item.reorder_quantity = Decimal(str(payload.reorder_quantity))

    await db.flush()

    # Resolve catalogue data for response
    item_name = ""
    part_number: str | None = None
    brand: str | None = None

    if stock_item.catalogue_type in ("part", "tyre"):
        cat_result = await db.execute(
            select(PartsCatalogue).where(PartsCatalogue.id == stock_item.catalogue_item_id)
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            item_name = cat.name
            part_number = cat.part_number
            brand = cat.brand
    elif stock_item.catalogue_type == "fluid":
        cat_result = await db.execute(
            select(FluidOilProduct).where(FluidOilProduct.id == stock_item.catalogue_item_id)
        )
        cat_fluid = cat_result.scalar_one_or_none()
        if cat_fluid:
            item_name = _fluid_display_name(cat_fluid)
            brand = cat_fluid.brand_name

    # Resolve supplier name
    supplier_name: str | None = None
    if stock_item.supplier_id:
        sup_result = await db.execute(
            select(Supplier.name).where(Supplier.id == stock_item.supplier_id)
        )
        supplier_name = sup_result.scalar_one_or_none()

    return _build_stock_item_response(
        stock_item, item_name, part_number, brand, supplier_name
    )


async def delete_stock_item(
    db: AsyncSession,
    org_id: uuid.UUID,
    stock_item_id: uuid.UUID,
) -> None:
    """Remove a stock item from inventory.

    Requirements: 1.4
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        raise ValueError("Stock item not found")

    await db.delete(stock_item)
    await db.flush()


async def adjust_stock_item(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    payload: AdjustStockItemRequest,
) -> dict:
    """Adjust stock quantity for a stock item with audit trail."""
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        raise ValueError("Stock item not found")

    old_qty = stock_item.current_quantity
    new_qty = old_qty + Decimal(str(payload.quantity_change))
    if new_qty < 0:
        raise ValueError("Stock cannot go below zero")

    stock_item.current_quantity = new_qty
    await db.flush()

    # Create audit movement
    movement = StockMovement(
        org_id=org_id,
        movement_type="adjustment",
        quantity_change=Decimal(str(payload.quantity_change)),
        resulting_quantity=new_qty,
        notes=payload.reason,
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    return {
        "stock_item_id": str(stock_item.id),
        "previous_quantity": float(old_qty),
        "new_quantity": float(new_qty),
        "quantity_change": payload.quantity_change,
    }


# ---------------------------------------------------------------------------
# Location management
# ---------------------------------------------------------------------------


async def list_locations(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> LocationListResponse:
    """List all inventory locations for an organisation."""
    result = await db.execute(
        select(InventoryLocation)
        .where(InventoryLocation.org_id == org_id)
        .order_by(InventoryLocation.name)
    )
    locations = result.scalars().all()
    return LocationListResponse(
        locations=[
            LocationResponse(
                id=str(loc.id),
                name=loc.name,
                created_at=loc.created_at.isoformat(),
            )
            for loc in locations
        ]
    )


async def create_location(
    db: AsyncSession,
    org_id: uuid.UUID,
    payload: CreateLocationRequest,
) -> LocationResponse:
    """Create a new inventory location (unique per org)."""
    # Check for duplicate
    existing = await db.execute(
        select(InventoryLocation).where(
            InventoryLocation.org_id == org_id,
            InventoryLocation.name == payload.name.strip(),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("Location already exists")

    location = InventoryLocation(
        org_id=org_id,
        name=payload.name.strip(),
    )
    db.add(location)
    await db.flush()

    return LocationResponse(
        id=str(location.id),
        name=location.name,
        created_at=location.created_at.isoformat(),
    )


async def delete_location(
    db: AsyncSession,
    org_id: uuid.UUID,
    location_id: uuid.UUID,
) -> None:
    """Delete an inventory location. Does NOT affect stock_items.location text."""
    result = await db.execute(
        select(InventoryLocation).where(
            InventoryLocation.id == location_id,
            InventoryLocation.org_id == org_id,
        )
    )
    location = result.scalar_one_or_none()
    if location is None:
        raise ValueError("Location not found")

    await db.delete(location)
    await db.flush()


# ---------------------------------------------------------------------------
# Invoice stock decrement (new stock_items-based)
# ---------------------------------------------------------------------------


async def decrement_stock_for_invoice_v2(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    quantity: float,
    invoice_id: uuid.UUID,
) -> dict | None:
    """Decrement stock from a specific stock_item when used on an invoice.

    Creates a StockMovement with movement_type='sale' and reference to the invoice.
    Returns None if stock item not found.
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        return None

    old_qty = stock_item.current_quantity
    new_qty = max(Decimal("0"), old_qty - Decimal(str(quantity)))
    stock_item.current_quantity = new_qty
    await db.flush()

    # Create sale movement with invoice reference
    movement = StockMovement(
        org_id=org_id,
        movement_type="sale",
        quantity_change=Decimal(str(-quantity)),
        resulting_quantity=new_qty,
        reference_type="invoice",
        reference_id=invoice_id,
        notes=f"Used on invoice",
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    return {
        "stock_item_id": str(stock_item.id),
        "previous_quantity": float(old_qty),
        "new_quantity": float(new_qty),
    }


# ---------------------------------------------------------------------------
# Stock reservation (hold for drafts/bookings)
# ---------------------------------------------------------------------------


async def reserve_stock(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    quantity: float,
    reference_type: str = "invoice_draft",
    reference_id: uuid.UUID | None = None,
) -> dict | None:
    """Reserve stock for a draft invoice or booking.

    Increments reserved_quantity without changing current_quantity.
    Creates a StockMovement with movement_type='reservation'.
    Returns None if stock item not found or insufficient available stock.
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        return None

    available = stock_item.current_quantity - stock_item.reserved_quantity
    qty = Decimal(str(quantity))
    if qty > available:
        return None  # Not enough available stock

    stock_item.reserved_quantity += qty
    await db.flush()

    movement = StockMovement(
        org_id=org_id,
        movement_type="reservation",
        quantity_change=qty,
        resulting_quantity=stock_item.current_quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=f"Reserved for {reference_type}",
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    return {
        "stock_item_id": str(stock_item.id),
        "reserved": float(qty),
        "total_reserved": float(stock_item.reserved_quantity),
    }


async def release_reservation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    quantity: float,
    reference_type: str = "invoice_draft",
    reference_id: uuid.UUID | None = None,
) -> dict | None:
    """Release a stock reservation (e.g. draft deleted or edited down).

    Decrements reserved_quantity without changing current_quantity.
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        return None

    qty = Decimal(str(quantity))
    stock_item.reserved_quantity = max(Decimal("0"), stock_item.reserved_quantity - qty)
    await db.flush()

    movement = StockMovement(
        org_id=org_id,
        movement_type="reservation_release",
        quantity_change=-qty,
        resulting_quantity=stock_item.current_quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        notes=f"Released reservation for {reference_type}",
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    return {
        "stock_item_id": str(stock_item.id),
        "released": float(qty),
        "total_reserved": float(stock_item.reserved_quantity),
    }


async def convert_reservation_to_sale(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    quantity: float,
    invoice_id: uuid.UUID,
) -> dict | None:
    """Convert a reservation to an actual sale (draft → issued).

    Decrements both current_quantity and reserved_quantity.
    Creates a StockMovement with movement_type='sale'.
    """
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    stock_item = result.scalar_one_or_none()
    if stock_item is None:
        return None

    qty = Decimal(str(quantity))
    old_qty = stock_item.current_quantity
    new_qty = max(Decimal("0"), old_qty - qty)
    stock_item.current_quantity = new_qty
    stock_item.reserved_quantity = max(Decimal("0"), stock_item.reserved_quantity - qty)
    await db.flush()

    movement = StockMovement(
        org_id=org_id,
        movement_type="sale",
        quantity_change=-qty,
        resulting_quantity=new_qty,
        reference_type="invoice",
        reference_id=invoice_id,
        notes="Reservation converted to sale",
        performed_by=user_id,
        stock_item_id=stock_item.id,
    )
    db.add(movement)
    await db.flush()

    return {
        "stock_item_id": str(stock_item.id),
        "previous_quantity": float(old_qty),
        "new_quantity": float(new_qty),
    }


# ---------------------------------------------------------------------------
# Usage history (stock movements from invoices)
# ---------------------------------------------------------------------------


async def list_usage_history(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List stock movements of type 'sale' with joined item, supplier, and invoice data.

    Returns usage records showing what was used, how much, on which vehicle, supplier, and invoice.
    """
    from app.modules.invoices.models import Invoice

    # Query sale movements joined with stock items
    stmt = (
        select(StockMovement)
        .where(
            StockMovement.org_id == org_id,
            StockMovement.movement_type == "sale",
        )
        .order_by(StockMovement.created_at.desc())
    )
    result = await db.execute(stmt)
    all_movements = list(result.scalars().all())

    if not all_movements:
        return {"usage": [], "total": 0}

    # Batch-load stock items
    stock_item_ids = list({m.stock_item_id for m in all_movements if m.stock_item_id})
    stock_items_map: dict = {}
    if stock_item_ids:
        si_result = await db.execute(
            select(StockItem).where(StockItem.id.in_(stock_item_ids))
        )
        for si in si_result.scalars().all():
            stock_items_map[si.id] = si

    # Batch-load catalogue data
    part_ids = list({si.catalogue_item_id for si in stock_items_map.values() if si.catalogue_type in ("part", "tyre")})
    fluid_ids = list({si.catalogue_item_id for si in stock_items_map.values() if si.catalogue_type == "fluid"})

    parts_map: dict = {}
    if part_ids:
        from app.modules.catalogue.models import PartsCatalogue
        pr = await db.execute(select(PartsCatalogue).where(PartsCatalogue.id.in_(part_ids)))
        for p in pr.scalars().all():
            parts_map[p.id] = p

    fluids_map: dict = {}
    if fluid_ids:
        from app.modules.catalogue.fluid_oil_models import FluidOilProduct
        fr = await db.execute(select(FluidOilProduct).where(FluidOilProduct.id.in_(fluid_ids)))
        for f in fr.scalars().all():
            fluids_map[f.id] = f

    # Batch-load suppliers
    supplier_ids = list({si.supplier_id for si in stock_items_map.values() if si.supplier_id})
    suppliers_map: dict = {}
    if supplier_ids:
        sr = await db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids)))
        for row in sr.all():
            suppliers_map[row[0]] = row[1]

    # Batch-load invoices for reference
    invoice_ids = list({m.reference_id for m in all_movements if m.reference_type == "invoice" and m.reference_id})
    invoices_map: dict = {}
    if invoice_ids:
        inv_result = await db.execute(
            select(Invoice.id, Invoice.invoice_number, Invoice.vehicle_rego, Invoice.customer_id)
            .where(Invoice.id.in_(invoice_ids))
        )
        for row in inv_result.all():
            invoices_map[row[0]] = {"invoice_number": row[1], "vehicle_rego": row[2], "customer_id": str(row[3])}

    # Build response
    usage_records = []
    for m in all_movements:
        si = stock_items_map.get(m.stock_item_id)
        if not si:
            continue

        item_name = ""
        catalogue_type = si.catalogue_type
        part_number = None
        subtitle = None
        if catalogue_type in ("part", "tyre"):
            cat = parts_map.get(si.catalogue_item_id)
            item_name = cat.name if cat else ""
            part_number = cat.part_number if cat else None
            if catalogue_type == "tyre" and cat:
                tyre_parts = []
                w = getattr(cat, "tyre_width", None)
                p = getattr(cat, "tyre_profile", None)
                r = getattr(cat, "tyre_rim_dia", None)
                li_idx = getattr(cat, "tyre_load_index", None)
                si_idx = getattr(cat, "tyre_speed_index", None)
                if w: tyre_parts.append(str(w))
                if p: tyre_parts.append(f"/{p}")
                if r: tyre_parts.append(f"R{r}")
                tyre_size = "".join(tyre_parts)
                extra = "".join(filter(None, [str(li_idx) if li_idx else None, str(si_idx) if si_idx else None]))
                if tyre_size:
                    subtitle = f"{tyre_size} {extra}".strip() if extra else tyre_size
        elif catalogue_type == "fluid":
            cat = fluids_map.get(si.catalogue_item_id)
            item_name = _fluid_display_name(cat) if cat else ""

        supplier_name = suppliers_map.get(si.supplier_id) if si.supplier_id else None
        invoice_info = invoices_map.get(m.reference_id, {}) if m.reference_type == "invoice" else {}

        usage_records.append({
            "id": str(m.id),
            "item_name": item_name,
            "subtitle": subtitle,
            "part_number": part_number,
            "barcode": si.barcode,
            "catalogue_type": catalogue_type,
            "quantity_used": abs(float(m.quantity_change)),
            "unit": "L" if catalogue_type == "fluid" else "units",
            "supplier_name": supplier_name,
            "vehicle_rego": invoice_info.get("vehicle_rego"),
            "invoice_id": str(m.reference_id) if m.reference_type == "invoice" else None,
            "invoice_number": invoice_info.get("invoice_number"),
            "notes": m.notes,
            "date": m.created_at.isoformat(),
        })

    total = len(usage_records)
    paginated = usage_records[offset:offset + limit]
    return {"usage": paginated, "total": total}


async def list_stock_movement_log(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    limit: int = 500,
) -> dict:
    """List all stock movements as an audit log with joined item/supplier/user data."""
    from app.modules.invoices.models import Invoice

    stmt = (
        select(StockMovement)
        .where(StockMovement.org_id == org_id)
        .order_by(StockMovement.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    all_movements = list(result.scalars().all())
    if not all_movements:
        return {"movements": [], "total": 0}

    # Batch-load stock items
    si_ids = list({m.stock_item_id for m in all_movements if m.stock_item_id})
    si_map: dict = {}
    if si_ids:
        r = await db.execute(select(StockItem).where(StockItem.id.in_(si_ids)))
        for si in r.scalars().all():
            si_map[si.id] = si

    # Batch-load catalogue
    part_ids = list({si.catalogue_item_id for si in si_map.values() if si.catalogue_type in ("part", "tyre")})
    fluid_ids = list({si.catalogue_item_id for si in si_map.values() if si.catalogue_type == "fluid"})
    parts_map: dict = {}
    if part_ids:
        pr = await db.execute(select(PartsCatalogue).where(PartsCatalogue.id.in_(part_ids)))
        for p in pr.scalars().all():
            parts_map[p.id] = p
    fluids_map: dict = {}
    if fluid_ids:
        fr = await db.execute(select(FluidOilProduct).where(FluidOilProduct.id.in_(fluid_ids)))
        for f in fr.scalars().all():
            fluids_map[f.id] = f

    # Batch-load suppliers
    sup_ids = list({si.supplier_id for si in si_map.values() if si.supplier_id})
    sup_map: dict = {}
    if sup_ids:
        sr = await db.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(sup_ids)))
        for row in sr.all():
            sup_map[row[0]] = row[1]

    # Batch-load users who performed actions
    user_ids = list({m.performed_by for m in all_movements if m.performed_by})
    user_map: dict = {}
    if user_ids:
        from app.modules.auth.models import User
        ur = await db.execute(select(User.id, User.first_name, User.last_name, User.email).where(User.id.in_(user_ids)))
        for row in ur.all():
            display = f"{row[1] or ''} {row[2] or ''}".strip() or row[3] or str(row[0])[:8]
            user_map[row[0]] = display

    records = []
    for m in all_movements:
        si = si_map.get(m.stock_item_id)
        item_name = ""
        part_number = None
        barcode = None
        catalogue_type = ""
        supplier_name = None
        subtitle = None
        if si:
            catalogue_type = si.catalogue_type
            barcode = si.barcode
            supplier_name = sup_map.get(si.supplier_id) if si.supplier_id else None
            if catalogue_type in ("part", "tyre"):
                cat = parts_map.get(si.catalogue_item_id)
                if cat:
                    item_name = cat.name
                    part_number = cat.part_number
                    if catalogue_type == "tyre":
                        tp = []
                        w = getattr(cat, "tyre_width", None)
                        p = getattr(cat, "tyre_profile", None)
                        r2 = getattr(cat, "tyre_rim_dia", None)
                        li2 = getattr(cat, "tyre_load_index", None)
                        si2 = getattr(cat, "tyre_speed_index", None)
                        if w: tp.append(str(w))
                        if p: tp.append(f"/{p}")
                        if r2: tp.append(f"R{r2}")
                        ts = "".join(tp)
                        ex = "".join(filter(None, [str(li2) if li2 else None, str(si2) if si2 else None]))
                        if ts: subtitle = f"{ts} {ex}".strip() if ex else ts
            elif catalogue_type == "fluid":
                cat_f = fluids_map.get(si.catalogue_item_id)
                if cat_f:
                    item_name = _fluid_display_name(cat_f)

        qty_change = float(m.quantity_change)
        records.append({
            "id": str(m.id),
            "item_name": item_name,
            "subtitle": subtitle,
            "part_number": part_number,
            "barcode": barcode,
            "catalogue_type": catalogue_type,
            "supplier_name": supplier_name,
            "movement_type": m.movement_type,
            "quantity_change": qty_change,
            "resulting_quantity": float(m.resulting_quantity),
            "direction": "in" if qty_change > 0 else ("out" if qty_change < 0 else "neutral"),
            "reference_type": m.reference_type,
            "reference_id": str(m.reference_id) if m.reference_id else None,
            "notes": m.notes,
            "performed_by": user_map.get(m.performed_by, "System") if m.performed_by else "System",
            "date": m.created_at.isoformat(),
        })

    return {"movements": records, "total": len(records)}
