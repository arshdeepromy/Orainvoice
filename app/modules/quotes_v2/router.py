"""Quote API router.

Endpoints:
- GET    /api/v2/quotes                         — list (paginated/filterable)
- POST   /api/v2/quotes                         — create
- GET    /api/v2/quotes/{id}                    — get
- PUT    /api/v2/quotes/{id}                    — update
- PUT    /api/v2/quotes/{id}/send               — send to customer
- POST   /api/v2/quotes/{id}/convert-to-invoice — convert to invoice
- POST   /api/v2/quotes/{id}/revise             — create new version

Public endpoint (separate router):
- GET    /api/v2/public/quotes/accept/{token}   — customer acceptance

**Validates: Requirement 12**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.quotes_v2.schemas import (
    AcceptQuoteResponse,
    ConvertToInvoiceResponse,
    QuoteCreate,
    QuoteListResponse,
    QuoteResponse,
    QuoteUpdate,
)
from app.modules.quotes_v2.service import QuoteService

router = APIRouter()
public_router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    """Extract org_id from request state (set by auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    """Extract user_id from request state if available."""
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# Quote CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=QuoteListResponse)
async def list_quotes(
    request: Request,
    status: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = QuoteService(db)
    return await svc.list_quotes(org_id, status=status, customer_id=customer_id, page=page, page_size=page_size)


@router.post("", response_model=QuoteResponse, status_code=201)
async def create_quote(
    request: Request,
    data: QuoteCreate,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = QuoteService(db)
    return await svc.create_quote(org_id, data, created_by=user_id)


@router.get("/{quote_id}", response_model=QuoteResponse)
async def get_quote(
    request: Request,
    quote_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = QuoteService(db)
    quote = await svc.get_quote(org_id, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


@router.put("/{quote_id}", response_model=QuoteResponse)
async def update_quote(
    request: Request,
    quote_id: UUID,
    data: QuoteUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = QuoteService(db)
    try:
        quote = await svc.update_quote(org_id, quote_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if quote is None:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.put("/{quote_id}/send", response_model=QuoteResponse)
async def send_quote(
    request: Request,
    quote_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = QuoteService(db)
    try:
        return await svc.send_to_customer(org_id, quote_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{quote_id}/convert-to-invoice", response_model=ConvertToInvoiceResponse)
async def convert_to_invoice(
    request: Request,
    quote_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = QuoteService(db)
    try:
        result = await svc.convert_to_invoice(org_id, quote_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ConvertToInvoiceResponse(
        quote_id=result["quote_id"],
        invoice_id=result["invoice_id"],
        line_items_count=result["line_items_count"],
        message="Quote converted to invoice successfully",
    )


@router.post("/{quote_id}/revise", response_model=QuoteResponse, status_code=201)
async def revise_quote(
    request: Request,
    quote_id: UUID,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = QuoteService(db)
    try:
        return await svc.create_revision(org_id, quote_id, created_by=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Public acceptance endpoint
# ---------------------------------------------------------------------------

@public_router.get("/accept/{token}", response_model=AcceptQuoteResponse)
async def accept_quote(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint for customers to accept a quote via token link."""
    svc = QuoteService(db)
    try:
        quote = await svc.accept_quote(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AcceptQuoteResponse(
        quote_id=quote.id,
        status=quote.status,
        accepted_at=quote.accepted_at,
        message="Quote accepted successfully",
    )
