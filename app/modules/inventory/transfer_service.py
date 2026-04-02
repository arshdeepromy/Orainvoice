"""Business logic for inter-branch stock transfers.

Manages the full transfer lifecycle: create → approve → ship → receive,
with cancellation allowed from pending/approved/shipped states.

All stock mutations happen in a single transaction for consistency.

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import StockItem
from app.modules.inventory.transfer_models import StockTransfer
from app.modules.organisations.models import Branch

logger = logging.getLogger(__name__)

# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "cancelled"},
    "approved": {"shipped", "cancelled"},
    "shipped": {"received", "cancelled"},
}


async def create_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    from_branch_id: uuid.UUID,
    to_branch_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    quantity: float,
    requested_by: uuid.UUID,
    notes: str | None = None,
) -> dict:
    """Create a new stock transfer with status 'pending'.

    Validates that source and destination branches differ.

    Requirements: 17.1
    """
    if from_branch_id == to_branch_id:
        raise ValueError("Source and destination branches must be different")

    if quantity <= 0:
        raise ValueError("Transfer quantity must be positive")

    # Verify both branches exist and belong to org
    for bid, label in [(from_branch_id, "Source"), (to_branch_id, "Destination")]:
        result = await db.execute(
            select(Branch).where(Branch.id == bid, Branch.org_id == org_id)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"{label} branch not found")

    # Verify stock item exists and belongs to org
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise ValueError("Stock item not found")

    transfer = StockTransfer(
        org_id=org_id,
        from_branch_id=from_branch_id,
        to_branch_id=to_branch_id,
        stock_item_id=stock_item_id,
        quantity=quantity,
        status="pending",
        requested_by=requested_by,
        notes=notes,
    )
    db.add(transfer)
    await db.flush()

    return _transfer_to_dict(transfer)


async def approve_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> dict:
    """Move a transfer from pending → approved.

    Requirements: 17.2
    """
    transfer = await _get_transfer(db, org_id=org_id, transfer_id=transfer_id)

    _validate_transition(transfer.status, "approved")

    transfer.status = "approved"
    transfer.approved_by = approved_by
    await db.flush()

    return _transfer_to_dict(transfer)


async def ship_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
) -> dict:
    """Move a transfer from approved → shipped and deduct stock from source.

    Requirements: 17.3
    """
    transfer = await _get_transfer(db, org_id=org_id, transfer_id=transfer_id)

    _validate_transition(transfer.status, "shipped")

    # Deduct quantity from source branch stock
    stock_item = await _get_stock_item_for_branch(
        db,
        org_id=org_id,
        stock_item_id=transfer.stock_item_id,
        branch_id=transfer.from_branch_id,
    )

    available = float(stock_item.current_quantity) - float(stock_item.reserved_quantity)
    if available < float(transfer.quantity):
        raise ValueError(
            f"Insufficient stock: available {available}, requested {float(transfer.quantity)}"
        )

    stock_item.current_quantity = stock_item.current_quantity - transfer.quantity
    transfer.status = "shipped"
    transfer.shipped_at = datetime.now(timezone.utc)
    await db.flush()

    return _transfer_to_dict(transfer)


async def receive_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
) -> dict:
    """Move a transfer from shipped → received and add stock to destination.

    Requirements: 17.4
    """
    transfer = await _get_transfer(db, org_id=org_id, transfer_id=transfer_id)

    _validate_transition(transfer.status, "received")

    # Add quantity to destination branch stock
    stock_item = await _get_stock_item_for_branch(
        db,
        org_id=org_id,
        stock_item_id=transfer.stock_item_id,
        branch_id=transfer.to_branch_id,
    )

    stock_item.current_quantity = stock_item.current_quantity + transfer.quantity
    transfer.status = "received"
    transfer.received_at = datetime.now(timezone.utc)
    await db.flush()

    return _transfer_to_dict(transfer)


async def cancel_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
) -> dict:
    """Cancel a transfer from pending/approved/shipped.

    If the transfer was shipped, restore stock to source branch.

    Requirements: 17.5
    """
    transfer = await _get_transfer(db, org_id=org_id, transfer_id=transfer_id)

    _validate_transition(transfer.status, "cancelled")

    was_shipped = transfer.status == "shipped"

    # Restore stock if it was already deducted (shipped state)
    if was_shipped:
        stock_item = await _get_stock_item_for_branch(
            db,
            org_id=org_id,
            stock_item_id=transfer.stock_item_id,
            branch_id=transfer.from_branch_id,
        )
        stock_item.current_quantity = stock_item.current_quantity + transfer.quantity

    transfer.status = "cancelled"
    transfer.cancelled_at = datetime.now(timezone.utc)
    await db.flush()

    return _transfer_to_dict(transfer)


async def list_transfers(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    from_branch_id: uuid.UUID | None = None,
    to_branch_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[dict]:
    """List transfers for an org with optional branch/status filtering.

    Requirements: 17.6
    """
    query = (
        select(StockTransfer)
        .where(StockTransfer.org_id == org_id)
        .order_by(StockTransfer.created_at.desc())
    )

    if from_branch_id is not None:
        query = query.where(StockTransfer.from_branch_id == from_branch_id)
    if to_branch_id is not None:
        query = query.where(StockTransfer.to_branch_id == to_branch_id)
    if status is not None:
        query = query.where(StockTransfer.status == status)

    result = await db.execute(query)
    transfers = result.scalars().all()

    return [_transfer_to_dict(t) for t in transfers]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_transfer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    transfer_id: uuid.UUID,
) -> StockTransfer:
    """Fetch a transfer by ID, scoped to org. Raises ValueError if not found."""
    result = await db.execute(
        select(StockTransfer).where(
            StockTransfer.id == transfer_id,
            StockTransfer.org_id == org_id,
        )
    )
    transfer = result.scalar_one_or_none()
    if transfer is None:
        raise ValueError("Transfer not found")
    return transfer


async def _get_stock_item_for_branch(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    stock_item_id: uuid.UUID,
    branch_id: uuid.UUID,
) -> StockItem:
    """Fetch a stock item scoped to org and branch. Raises ValueError if not found."""
    result = await db.execute(
        select(StockItem).where(
            StockItem.id == stock_item_id,
            StockItem.org_id == org_id,
            StockItem.branch_id == branch_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise ValueError("Stock item not found for this branch")
    return item


def _validate_transition(current_status: str, target_status: str) -> None:
    """Validate that a status transition is allowed."""
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ValueError(
            f"Cannot transition from {current_status} to {target_status}"
        )


def _transfer_to_dict(transfer: StockTransfer) -> dict:
    """Convert a StockTransfer ORM instance to a response dict."""
    return {
        "id": str(transfer.id),
        "org_id": str(transfer.org_id),
        "from_branch_id": str(transfer.from_branch_id),
        "to_branch_id": str(transfer.to_branch_id),
        "stock_item_id": str(transfer.stock_item_id),
        "quantity": float(transfer.quantity),
        "status": transfer.status,
        "requested_by": str(transfer.requested_by),
        "approved_by": str(transfer.approved_by) if transfer.approved_by else None,
        "shipped_at": transfer.shipped_at.isoformat() if transfer.shipped_at else None,
        "received_at": transfer.received_at.isoformat() if transfer.received_at else None,
        "cancelled_at": transfer.cancelled_at.isoformat() if transfer.cancelled_at else None,
        "notes": transfer.notes,
        "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
        "updated_at": transfer.updated_at.isoformat() if transfer.updated_at else None,
    }
