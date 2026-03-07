"""Customer Portal router — token-based access, no login required.

All endpoints are public (no JWT auth). Access is controlled by a
unique per-customer portal token stored on the customer record.

Requirements: 61.1, 61.2, 61.3, 61.4, 61.5
Enhanced: Requirement 49 — Customer Portal Enhancements
"""

from __future__ import annotations

import uuid
import logging
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.portal.schemas import (
    PortalAccessResponse,
    PortalInvoicesResponse,
    PortalPayRequest,
    PortalPayResponse,
    PortalVehiclesResponse,
    PortalQuotesResponse,
    PortalAcceptQuoteResponse,
    PortalAssetsResponse,
    PortalBookingsResponse,
    PortalBookingCreateRequest,
    PortalBookingCreateResponse,
    PortalAvailableSlotsResponse,
    PortalLoyaltyResponse,
)
from app.modules.portal.service import (
    create_portal_payment,
    get_portal_access,
    get_portal_invoices,
    get_portal_vehicles,
    get_portal_quotes,
    accept_portal_quote,
    get_portal_assets,
    get_portal_bookings,
    create_portal_booking,
    get_portal_available_slots,
    get_portal_loyalty,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{token}",
    response_model=PortalAccessResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Access customer portal via secure link",
)
async def portal_access(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate the portal token and return customer + org branding.

    No account creation required — the unique link is the credential.

    Requirements: 61.1, 61.5
    """
    try:
        return await get_portal_access(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/invoices",
    response_model=PortalInvoicesResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer invoice history, balances, and payments",
)
async def portal_invoices(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's invoice history with outstanding balances
    and payment history.

    Requirements: 61.2
    """
    try:
        return await get_portal_invoices(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/vehicles",
    response_model=PortalVehiclesResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer vehicle service history",
)
async def portal_vehicles(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's vehicles with dates and services performed.

    Requirements: 61.4
    """
    try:
        return await get_portal_vehicles(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post(
    "/{token}/pay/{invoice_id}",
    response_model=PortalPayResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error or payment not possible"},
    },
    summary="Pay an outstanding invoice via Stripe",
)
async def portal_pay(
    token: uuid.UUID,
    invoice_id: uuid.UUID,
    payload: PortalPayRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a Stripe Checkout link for the customer to pay an
    outstanding invoice.

    Requirements: 61.3
    """
    amount = payload.amount if payload else None
    try:
        return await create_portal_payment(db, token, invoice_id, amount)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})



# ---------------------------------------------------------------------------
# Quote acceptance  (Req 49.2)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/quotes",
    response_model=PortalQuotesResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Customer quotes with acceptance capability",
)
async def portal_quotes(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's quotes. Sent quotes can be accepted.

    Requirements: 49.2
    """
    try:
        return await get_portal_quotes(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post(
    "/{token}/quotes/{quote_id}/accept",
    response_model=PortalAcceptQuoteResponse,
    status_code=200,
    responses={400: {"description": "Validation error or quote not acceptable"}},
    summary="Accept a quote from the customer portal",
)
async def portal_accept_quote(
    token: uuid.UUID,
    quote_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a quote, triggering status update to 'accepted'.

    Requirements: 49.2
    """
    try:
        return await accept_portal_quote(db, token, quote_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Asset / service history  (Req 49.2)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/assets",
    response_model=PortalAssetsResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Customer assets with service history",
)
async def portal_assets(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's assets with linked invoices, jobs, and quotes.

    Requirements: 49.2
    """
    try:
        return await get_portal_assets(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Booking management  (Req 49.4)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/bookings",
    response_model=PortalBookingsResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Customer bookings",
)
async def portal_bookings(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's bookings.

    Requirements: 49.4
    """
    try:
        return await get_portal_bookings(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.post(
    "/{token}/bookings",
    response_model=PortalBookingCreateResponse,
    status_code=201,
    responses={400: {"description": "Validation error or slot unavailable"}},
    summary="Create a booking from the customer portal",
)
async def portal_create_booking(
    token: uuid.UUID,
    payload: PortalBookingCreateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Book an appointment using the same availability rules as the public page.

    Requirements: 49.4
    """
    try:
        return await create_portal_booking(
            db, token, payload.service_type, payload.start_time, payload.notes,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/bookings/slots",
    response_model=PortalAvailableSlotsResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Available booking slots for a date",
)
async def portal_booking_slots(
    token: uuid.UUID,
    target_date: date = Query(..., alias="date", description="Date to check slots for"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return available booking time slots for a given date.

    Requirements: 49.4
    """
    try:
        return await get_portal_available_slots(db, token, target_date)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Loyalty balance  (Req 49.2, Req 38.6)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/loyalty",
    response_model=PortalLoyaltyResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Customer loyalty balance and tier info",
)
async def portal_loyalty(
    token: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's loyalty points, tier, and transaction history.

    Requirements: 49.2, 38.6
    """
    try:
        return await get_portal_loyalty(db, token)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
