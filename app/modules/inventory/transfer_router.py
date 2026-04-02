"""Stock Transfer router — endpoints for inter-branch inventory transfers.

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.inventory.transfer_service import (
    approve_transfer,
    cancel_transfer,
    create_transfer,
    list_transfers,
    receive_transfer,
    ship_transfer,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CreateTransferRequest(BaseModel):
    """POST /inventory/transfers — create a new stock transfer."""

    from_branch_id: uuid.UUID = Field(..., description="Source branch UUID")
    to_branch_id: uuid.UUID = Field(..., description="Destination branch UUID")
    stock_item_id: uuid.UUID = Field(..., description="Stock item UUID")
    quantity: float = Field(..., gt=0, description="Quantity to transfer")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional notes")


class ApproveTransferRequest(BaseModel):
    """POST /inventory/transfers/{id}/approve — optional body."""
    pass


class TransferResponse(BaseModel):
    """Single transfer response."""

    id: str
    org_id: str
    from_branch_id: str
    to_branch_id: str
    stock_item_id: str
    quantity: float
    status: str
    requested_by: str
    approved_by: Optional[str] = None
    shipped_at: Optional[str] = None
    received_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TransferListResponse(BaseModel):
    """List of transfers."""

    transfers: list[TransferResponse]


class TransferActionResponse(BaseModel):
    """Response for transfer lifecycle actions."""

    message: str
    transfer: TransferResponse


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Extract org_id and user_id from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None
    return org_uuid, user_uuid


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TransferActionResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
    },
    summary="Create a stock transfer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_transfer_endpoint(
    payload: CreateTransferRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new inter-branch stock transfer with status 'pending'.

    Requirements: 17.1
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_transfer(
            db,
            org_id=org_uuid,
            from_branch_id=payload.from_branch_id,
            to_branch_id=payload.to_branch_id,
            stock_item_id=payload.stock_item_id,
            quantity=payload.quantity,
            requested_by=user_uuid or uuid.uuid4(),
            notes=payload.notes,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return TransferActionResponse(
        message="Transfer created",
        transfer=TransferResponse(**result),
    )


@router.get(
    "",
    response_model=TransferListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
    },
    summary="List stock transfers",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_transfers_endpoint(
    request: Request,
    from_branch_id: uuid.UUID | None = Query(None, description="Filter by source branch"),
    to_branch_id: uuid.UUID | None = Query(None, description="Filter by destination branch"),
    status: str | None = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(get_db_session),
):
    """List stock transfers with optional branch/status filtering.

    Requirements: 17.6
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    results = await list_transfers(
        db,
        org_id=org_uuid,
        from_branch_id=from_branch_id,
        to_branch_id=to_branch_id,
        status=status,
    )

    return TransferListResponse(
        transfers=[TransferResponse(**t) for t in results],
    )


@router.post(
    "/{transfer_id}/approve",
    response_model=TransferActionResponse,
    responses={
        400: {"description": "Invalid state transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Transfer not found"},
    },
    summary="Approve a pending transfer",
    dependencies=[require_role("org_admin")],
)
async def approve_transfer_endpoint(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Approve a pending stock transfer.

    Requirements: 17.2
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        transfer_uuid = uuid.UUID(transfer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid transfer ID"})

    try:
        result = await approve_transfer(
            db,
            org_id=org_uuid,
            transfer_id=transfer_uuid,
            approved_by=user_uuid or uuid.uuid4(),
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return TransferActionResponse(
        message="Transfer approved",
        transfer=TransferResponse(**result),
    )


@router.post(
    "/{transfer_id}/ship",
    response_model=TransferActionResponse,
    responses={
        400: {"description": "Invalid state transition or insufficient stock"},
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
        404: {"description": "Transfer not found"},
    },
    summary="Mark transfer as shipped",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def ship_transfer_endpoint(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Mark an approved transfer as shipped. Deducts stock from source branch.

    Requirements: 17.3
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        transfer_uuid = uuid.UUID(transfer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid transfer ID"})

    try:
        result = await ship_transfer(
            db,
            org_id=org_uuid,
            transfer_id=transfer_uuid,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return TransferActionResponse(
        message="Transfer shipped",
        transfer=TransferResponse(**result),
    )


@router.post(
    "/{transfer_id}/receive",
    response_model=TransferActionResponse,
    responses={
        400: {"description": "Invalid state transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Role required"},
        404: {"description": "Transfer not found"},
    },
    summary="Mark transfer as received",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def receive_transfer_endpoint(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Mark a shipped transfer as received. Adds stock to destination branch.

    Requirements: 17.4
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        transfer_uuid = uuid.UUID(transfer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid transfer ID"})

    try:
        result = await receive_transfer(
            db,
            org_id=org_uuid,
            transfer_id=transfer_uuid,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return TransferActionResponse(
        message="Transfer received",
        transfer=TransferResponse(**result),
    )


@router.post(
    "/{transfer_id}/cancel",
    response_model=TransferActionResponse,
    responses={
        400: {"description": "Invalid state transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Transfer not found"},
    },
    summary="Cancel a transfer",
    dependencies=[require_role("org_admin")],
)
async def cancel_transfer_endpoint(
    transfer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel a transfer. Restores stock if it was already shipped.

    Requirements: 17.5
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        transfer_uuid = uuid.UUID(transfer_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid transfer ID"})

    try:
        result = await cancel_transfer(
            db,
            org_id=org_uuid,
            transfer_id=transfer_uuid,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": detail})

    return TransferActionResponse(
        message="Transfer cancelled",
        transfer=TransferResponse(**result),
    )
