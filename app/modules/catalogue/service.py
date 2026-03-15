"""Business logic for Items Catalogue, Parts Catalogue, and Labour Rates CRUD.

Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.5, 27.1, 27.2, 27.3, 28.1, 28.2, 28.3
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.catalogue.models import ItemsCatalogue, LabourRate, PartsCatalogue

logger = logging.getLogger(__name__)


def _item_to_dict(item: ItemsCatalogue) -> dict:
    """Convert an ItemsCatalogue ORM instance to a serialisable dict."""
    return {
        "id": str(item.id),
        "name": item.name,
        "description": item.description,
        "default_price": str(item.default_price),
        "is_gst_exempt": item.is_gst_exempt,
        "category": item.category,
        "is_active": item.is_active,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


# Backward-compatible alias
_service_to_dict = _item_to_dict


async def list_items(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    active_only: bool = False,
    category: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List items catalogue entries for an organisation.

    When ``active_only`` is True, only active items are returned.
    When ``search`` is provided, filters items whose name contains the
    search term (case-insensitive).

    Requirements: 2.1, 2.5
    """
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

    return {
        "items": [_item_to_dict(i) for i in items],
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
    is_active: bool = True,
    ip_address: str | None = None,
) -> dict:
    """Create a new items catalogue entry.

    Accepts any string or None for category (free-text, no constraint).

    Requirements: 1.4, 1.5, 2.2
    """
    try:
        price = Decimal(default_price)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid price format")

    if price < 0:
        raise ValueError("Price cannot be negative")

    item = ItemsCatalogue(
        org_id=org_id,
        name=name,
        description=description,
        default_price=price,
        is_gst_exempt=is_gst_exempt,
        category=category or "general",
        is_active=is_active,
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
            "is_active": is_active,
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

    Requirements: 2.3
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

    allowed_fields = {"name", "description", "default_price", "is_gst_exempt", "category", "is_active"}
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
        after_value={f: str(kwargs[f]) if f == "default_price" else kwargs[f] for f in updated_fields},
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


def _part_to_dict(part: PartsCatalogue) -> dict:
    """Convert a PartsCatalogue ORM instance to a serialisable dict."""
    return {
        "id": str(part.id),
        "name": part.name,
        "part_number": part.part_number,
        "default_price": str(part.default_price),
        "supplier": getattr(part, "_supplier_name", None),
        "is_active": part.is_active,
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
    supplier: str | None = None,
    is_active: bool = True,
    ip_address: str | None = None,
) -> dict:
    """Create a new parts catalogue entry.

    The ``supplier`` field is stored as a simple text reference on the
    part record (not a foreign key to the suppliers table) to keep
    pre-loading lightweight.  Ad-hoc parts per invoice (Req 28.2) are
    handled at the invoice line-item level and do not require a
    catalogue entry.

    Requirements: 28.1
    """
    try:
        price = Decimal(default_price)
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid price format")

    if price < 0:
        raise ValueError("Price cannot be negative")

    part = PartsCatalogue(
        org_id=org_id,
        name=name,
        part_number=part_number,
        default_price=price,
        is_active=is_active,
    )
    # Store supplier name as a transient attribute for the response.
    # The PartsCatalogue model doesn't have a direct supplier text column,
    # so we keep it lightweight — supplier linkage is via part_suppliers table.
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

    return _part_to_dict(part)


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
