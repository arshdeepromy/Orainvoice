"""Business logic for Inventory Stock Tracking.

Requirements: 62.1, 62.2, 62.3, 62.4, 62.5
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.catalogue.models import PartsCatalogue
from app.modules.stock.models import StockMovement

logger = logging.getLogger(__name__)


def _part_to_stock_level(part: PartsCatalogue) -> dict:
    """Convert a PartsCatalogue ORM instance to a stock level dict."""
    return {
        "part_id": str(part.id),
        "part_name": part.name,
        "part_number": part.part_number,
        "current_stock": part.current_stock,
        "min_threshold": part.min_stock_threshold,
        "reorder_quantity": part.reorder_quantity,
        "is_below_threshold": part.current_stock <= part.min_stock_threshold,
    }


def _movement_to_dict(movement: StockMovement) -> dict:
    """Convert a StockMovement ORM instance to a serialisable dict."""
    return {
        "id": str(movement.id),
        "part_id": str(movement.product_id),
        "quantity_change": int(movement.quantity_change),
        "reason": movement.notes or movement.movement_type,
        "reference_id": str(movement.reference_id) if movement.reference_id else None,
        "recorded_by": str(movement.performed_by) if movement.performed_by else None,
        "created_at": movement.created_at.isoformat() if movement.created_at else None,
    }


async def get_stock_levels(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    below_threshold_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List stock levels for all active parts in the organisation.

    Requirements: 62.1, 62.4
    """
    filters = [
        PartsCatalogue.org_id == org_id,
        PartsCatalogue.is_active.is_(True),
    ]

    if below_threshold_only:
        filters.append(
            PartsCatalogue.current_stock <= PartsCatalogue.min_stock_threshold
        )

    count_stmt = select(func.count(PartsCatalogue.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(PartsCatalogue)
        .where(*filters)
        .order_by(PartsCatalogue.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    parts = result.scalars().all()

    return {
        "stock_levels": [_part_to_stock_level(p) for p in parts],
        "total": total,
    }


async def adjust_stock(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity_change: int,
    reason: str,
    ip_address: str | None = None,
) -> dict:
    """Manually adjust stock level for a part with audit logging.

    Uses raw SQL to avoid ORM lazy-loading issues.
    Requirements: 62.5
    """
    from sqlalchemy import text

    # Get current stock
    result = await db.execute(
        text("SELECT current_stock, name, part_number, min_stock_threshold, reorder_quantity FROM parts_catalogue WHERE id = :pid AND org_id = :oid"),
        {"pid": str(part_id), "oid": str(org_id)},
    )
    row = result.fetchone()
    if not row:
        raise ValueError("Part not found")

    old_stock = row[0]
    new_stock = old_stock + quantity_change
    if new_stock < 0:
        raise ValueError("Stock cannot go below zero")

    await db.execute(
        text("UPDATE parts_catalogue SET current_stock = :ns WHERE id = :pid"),
        {"ns": new_stock, "pid": str(part_id)},
    )
    await db.flush()

    await write_audit_log(
        db,
        org_id=org_id,
        user_id=user_id,
        action="inventory.stock_adjusted",
        entity_type="parts_catalogue",
        entity_id=part_id,
        before_value={"current_stock": old_stock},
        after_value={
            "current_stock": new_stock,
            "quantity_change": quantity_change,
            "reason": reason,
        },
        ip_address=ip_address,
    )

    return {
        "stock_level": {
            "part_id": str(part_id),
            "part_name": row[1],
            "part_number": row[2],
            "current_stock": new_stock,
            "min_threshold": row[3],
            "reorder_quantity": row[4],
            "is_below_threshold": new_stock <= row[3],
        },
    }


async def decrement_stock_for_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    part_id: uuid.UUID,
    quantity: int,
    invoice_id: uuid.UUID,
) -> dict | None:
    """Auto-decrement stock when a part is added to an invoice.

    Returns None if the part is not found (ad-hoc parts without catalogue entry).
    Uses raw SQL to avoid ORM lazy-loading issues.

    Requirements: 62.2
    """
    from sqlalchemy import text
    result = await db.execute(
        text("UPDATE parts_catalogue SET current_stock = GREATEST(0, current_stock - :qty) WHERE id = :pid AND org_id = :oid RETURNING current_stock"),
        {"qty": quantity, "pid": str(part_id), "oid": str(org_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    await db.flush()
    return {"new_stock": row[0]}


async def get_reorder_alerts(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict:
    """Get parts where current stock is at or below the minimum threshold.

    Requirements: 62.3
    """
    filters = [
        PartsCatalogue.org_id == org_id,
        PartsCatalogue.is_active.is_(True),
        PartsCatalogue.current_stock <= PartsCatalogue.min_stock_threshold,
        PartsCatalogue.min_stock_threshold > 0,
    ]

    stmt = (
        select(PartsCatalogue)
        .where(*filters)
        .order_by(PartsCatalogue.current_stock)
    )
    result = await db.execute(stmt)
    parts = result.scalars().all()

    alerts = [
        {
            "part_id": str(p.id),
            "part_name": p.name,
            "part_number": p.part_number,
            "current_stock": p.current_stock,
            "min_threshold": p.min_stock_threshold,
            "reorder_quantity": p.reorder_quantity,
        }
        for p in parts
    ]

    return {"alerts": alerts, "total": len(alerts)}


async def get_stock_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    movement_limit: int = 50,
) -> dict:
    """Generate a stock report with current levels, below-threshold parts, and movement history.

    Requirements: 62.4
    """
    # All active parts
    all_parts_stmt = (
        select(PartsCatalogue)
        .where(
            PartsCatalogue.org_id == org_id,
            PartsCatalogue.is_active.is_(True),
        )
        .order_by(PartsCatalogue.name)
    )
    all_result = await db.execute(all_parts_stmt)
    all_parts = all_result.scalars().all()

    current_levels = [_part_to_stock_level(p) for p in all_parts]
    below_threshold = [sl for sl in current_levels if sl["is_below_threshold"] and sl["min_threshold"] > 0]

    # Recent movement history
    movements_stmt = (
        select(StockMovement)
        .where(StockMovement.org_id == org_id)
        .order_by(StockMovement.created_at.desc())
        .limit(movement_limit)
    )
    movements_result = await db.execute(movements_stmt)
    movements = movements_result.scalars().all()

    return {
        "current_levels": current_levels,
        "below_threshold": below_threshold,
        "movement_history": [_movement_to_dict(m) for m in movements],
    }

# ---------------------------------------------------------------------------
# Fluid / Oil stock management — Requirements: 4.1, 4.2, 4.3, 4.5
# ---------------------------------------------------------------------------

from decimal import Decimal
from app.modules.catalogue.fluid_oil_models import FluidOilProduct


def _fluid_display_name(product: FluidOilProduct) -> str:
    """Build display name: oil_type + grade if oil, else product_name."""
    if product.oil_type:
        grade = product.grade or ""
        return f"{product.oil_type} {grade}".strip()
    return product.product_name or ""


def _fluid_to_stock_level(product: FluidOilProduct) -> dict:
    """Convert a FluidOilProduct ORM instance to a stock level dict."""
    min_vol = float(product.min_stock_volume or 0)
    cur_vol = float(product.current_stock_volume or 0)
    return {
        "product_id": str(product.id),
        "display_name": _fluid_display_name(product),
        "brand_name": product.brand_name,
        "fluid_type": product.fluid_type,
        "oil_type": product.oil_type,
        "grade": product.grade,
        "unit_type": product.unit_type,
        "current_stock_volume": cur_vol,
        "min_stock_volume": min_vol,
        "reorder_volume": float(product.reorder_volume or 0),
        "is_below_threshold": cur_vol <= min_vol and min_vol > 0,
    }


async def get_fluid_stock_levels(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List stock levels for all active fluid/oil products in the organisation.

    Requirements: 4.1, 4.5
    """
    filters = [
        FluidOilProduct.org_id == org_id,
        FluidOilProduct.is_active.is_(True),
    ]

    count_stmt = select(func.count(FluidOilProduct.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(FluidOilProduct)
        .where(*filters)
        .order_by(FluidOilProduct.product_name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    return {
        "fluid_stock_levels": [_fluid_to_stock_level(p) for p in products],
        "total": total,
    }


async def adjust_fluid_stock(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    volume_change: float,
    reason: str,
    ip_address: str | None = None,
) -> dict:
    """Manually adjust stock volume for a fluid/oil product with audit logging.

    Uses raw SQL to avoid ORM lazy-loading issues.
    Requirements: 4.2, 4.5
    """
    from sqlalchemy import text

    # Get current product
    result = await db.execute(
        text(
            "SELECT current_stock_volume, product_name, oil_type, grade, brand_name, "
            "fluid_type, unit_type, min_stock_volume, reorder_volume "
            "FROM fluid_oil_products "
            "WHERE id = :pid AND org_id = :oid AND is_active = true"
        ),
        {"pid": str(product_id), "oid": str(org_id)},
    )
    row = result.fetchone()
    if not row:
        raise ValueError("Fluid/oil product not found")

    old_volume = float(row[0] or 0)
    new_volume = old_volume + volume_change
    if new_volume < 0:
        raise ValueError("Stock volume cannot go below zero")

    await db.execute(
        text(
            "UPDATE fluid_oil_products SET current_stock_volume = :nv, "
            "updated_at = NOW() WHERE id = :pid"
        ),
        {"nv": new_volume, "pid": str(product_id)},
    )
    await db.flush()

    # Build display name from raw row
    oil_type = row[2]
    grade = row[3]
    product_name = row[1]
    display_name = f"{oil_type} {grade}".strip() if oil_type else (product_name or "")

    min_vol = float(row[7] or 0)

    await write_audit_log(
        db,
        org_id=org_id,
        user_id=user_id,
        action="inventory.fluid_stock_adjusted",
        entity_type="fluid_oil_products",
        entity_id=product_id,
        before_value={"current_stock_volume": old_volume},
        after_value={
            "current_stock_volume": new_volume,
            "volume_change": volume_change,
            "reason": reason,
        },
        ip_address=ip_address,
    )

    return {
        "stock_level": {
            "product_id": str(product_id),
            "display_name": display_name,
            "brand_name": row[4],
            "fluid_type": row[5],
            "oil_type": oil_type,
            "grade": grade,
            "unit_type": row[6],
            "current_stock_volume": new_volume,
            "min_stock_volume": min_vol,
            "reorder_volume": float(row[8] or 0),
            "is_below_threshold": new_volume <= min_vol and min_vol > 0,
        },
    }


async def get_fluid_reorder_alerts(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict:
    """Get fluid/oil products where stock is at or below the minimum threshold.

    Requirements: 4.3, 4.5
    """
    filters = [
        FluidOilProduct.org_id == org_id,
        FluidOilProduct.is_active.is_(True),
        FluidOilProduct.current_stock_volume <= FluidOilProduct.min_stock_volume,
        FluidOilProduct.min_stock_volume > 0,
    ]

    stmt = (
        select(FluidOilProduct)
        .where(*filters)
        .order_by(FluidOilProduct.current_stock_volume)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    alerts = [
        {
            "product_id": str(p.id),
            "display_name": _fluid_display_name(p),
            "brand_name": p.brand_name,
            "unit_type": p.unit_type,
            "current_stock_volume": float(p.current_stock_volume or 0),
            "min_stock_volume": float(p.min_stock_volume or 0),
            "reorder_volume": float(p.reorder_volume or 0),
        }
        for p in products
    ]

    return {"alerts": alerts, "total": len(alerts)}



# ---------------------------------------------------------------------------
# Supplier management — Requirements: 63.1, 63.2, 63.3
# ---------------------------------------------------------------------------

from app.modules.suppliers.models import Supplier
from app.modules.inventory.models import PartSupplier


def _supplier_to_dict(supplier: Supplier) -> dict:
    """Convert a Supplier ORM instance to a serialisable dict."""
    return {
        "id": str(supplier.id),
        "name": supplier.name,
        "contact_name": supplier.contact_name,
        "email": supplier.email,
        "phone": supplier.phone,
        "address": supplier.address,
        "account_number": supplier.account_number,
        "created_at": supplier.created_at.isoformat() if supplier.created_at else None,
    }


def _part_supplier_to_dict(ps: PartSupplier) -> dict:
    """Convert a PartSupplier ORM instance to a serialisable dict."""
    return {
        "id": str(ps.id),
        "part_id": str(ps.part_id),
        "supplier_id": str(ps.supplier_id),
        "supplier_part_number": ps.supplier_part_number,
        "supplier_cost": float(ps.supplier_cost) if ps.supplier_cost is not None else None,
        "is_preferred": ps.is_preferred,
    }


async def create_supplier(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    account_number: str | None = None,
) -> dict:
    """Create a new supplier record for the organisation.

    Requirements: 63.1
    """
    supplier = Supplier(
        org_id=org_id,
        name=name,
        contact_name=contact_name,
        email=email,
        phone=phone,
        address=address,
        account_number=account_number,
    )
    db.add(supplier)
    await db.flush()
    return _supplier_to_dict(supplier)


async def list_suppliers(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List all suppliers for the organisation.

    Requirements: 63.1
    """
    count_stmt = select(func.count(Supplier.id)).where(Supplier.org_id == org_id)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Supplier)
        .where(Supplier.org_id == org_id)
        .order_by(Supplier.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    suppliers = result.scalars().all()

    return {
        "suppliers": [_supplier_to_dict(s) for s in suppliers],
        "total": total,
    }


async def link_part_to_supplier(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    supplier_id: uuid.UUID,
    part_id: uuid.UUID,
    supplier_part_number: str | None = None,
    supplier_cost: float | None = None,
    is_preferred: bool = False,
) -> dict:
    """Link a part to a supplier with supplier-specific part number and cost.

    Requirements: 63.2
    """
    # Verify supplier belongs to org
    supplier_stmt = select(Supplier).where(
        Supplier.id == supplier_id, Supplier.org_id == org_id
    )
    supplier_result = await db.execute(supplier_stmt)
    if not supplier_result.scalar_one_or_none():
        raise ValueError("Supplier not found")

    # Verify part belongs to org
    part_stmt = select(PartsCatalogue).where(
        PartsCatalogue.id == part_id, PartsCatalogue.org_id == org_id
    )
    part_result = await db.execute(part_stmt)
    if not part_result.scalar_one_or_none():
        raise ValueError("Part not found")

    from decimal import Decimal

    link = PartSupplier(
        part_id=part_id,
        supplier_id=supplier_id,
        supplier_part_number=supplier_part_number,
        supplier_cost=Decimal(str(supplier_cost)) if supplier_cost is not None else None,
        is_preferred=is_preferred,
    )
    db.add(link)
    await db.flush()
    return _part_supplier_to_dict(link)


async def generate_purchase_order_pdf(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    supplier_id: uuid.UUID,
    items: list[dict],
    notes: str | None = None,
) -> bytes:
    """Generate a purchase order PDF for a supplier.

    Requirements: 63.3
    """
    import jinja2
    from weasyprint import HTML

    # Fetch supplier
    supplier_stmt = select(Supplier).where(
        Supplier.id == supplier_id, Supplier.org_id == org_id
    )
    supplier_result = await db.execute(supplier_stmt)
    supplier = supplier_result.scalar_one_or_none()
    if not supplier:
        raise ValueError("Supplier not found")

    # Fetch organisation settings
    from app.modules.admin.models import Organisation

    org_stmt = select(Organisation).where(Organisation.id == org_id)
    org_result = await db.execute(org_stmt)
    org = org_result.scalar_one_or_none()

    # Resolve parts and build line items
    po_items = []
    total = 0.0
    for item in items:
        part_id = uuid.UUID(item["part_id"])
        quantity = item["quantity"]

        part_stmt = select(PartsCatalogue).where(
            PartsCatalogue.id == part_id, PartsCatalogue.org_id == org_id
        )
        part_result = await db.execute(part_stmt)
        part = part_result.scalar_one_or_none()
        if not part:
            continue

        # Try to find supplier-specific part number and cost
        ps_stmt = select(PartSupplier).where(
            PartSupplier.part_id == part_id,
            PartSupplier.supplier_id == supplier_id,
        )
        ps_result = await db.execute(ps_stmt)
        ps = ps_result.scalar_one_or_none()

        supplier_pn = ps.supplier_part_number if ps else part.part_number
        unit_cost = float(ps.supplier_cost) if ps and ps.supplier_cost else float(part.default_price)
        line_total = unit_cost * quantity
        total += line_total

        po_items.append({
            "part_name": part.name,
            "part_number": supplier_pn or "",
            "quantity": quantity,
            "unit_cost": unit_cost,
            "line_total": line_total,
        })

    # Build org context for template
    settings = org.settings if org else {}
    org_ctx = {
        "name": org.name if org else "",
        "address": settings.get("address", ""),
        "phone": settings.get("phone", ""),
        "email": settings.get("email", ""),
        "gst_number": settings.get("gst_number", ""),
        "logo_url": settings.get("logo_url", ""),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
    }

    from datetime import datetime, timezone

    po_number = f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    template_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("app/templates/pdf"),
        autoescape=True,
    )
    template = template_env.get_template("purchase_order.html")
    html_content = template.render(
        org=org_ctx,
        supplier=_supplier_to_dict(supplier),
        po_number=po_number,
        items=po_items,
        total=total,
        notes=notes,
        generated_at=datetime.now(timezone.utc),
    )

    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes
