"""Booking API routers — internal and public endpoints.

Internal endpoints (authenticated):
- GET    /api/v2/bookings              — list bookings
- POST   /api/v2/bookings              — create booking
- GET    /api/v2/bookings/{id}         — get booking
- PUT    /api/v2/bookings/{id}         — update booking
- PUT    /api/v2/bookings/{id}/cancel  — cancel booking
- POST   /api/v2/bookings/{id}/convert-to-job    — convert to job
- POST   /api/v2/bookings/{id}/convert-to-invoice — convert to invoice
- GET    /api/v2/booking-rules         — get booking rules
- PUT    /api/v2/booking-rules         — update booking rules

Public endpoints (no auth):
- GET    /api/v2/public/bookings/{org_slug}       — page data
- POST   /api/v2/public/bookings/{org_slug}       — submit booking
- GET    /api/v2/public/bookings/{org_slug}/slots  — available slots

**Validates: Requirement 19 — Booking Module**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.bookings_v2.schemas import (
    AvailableSlotsResponse,
    BookingCreate,
    BookingListResponse,
    BookingResponse,
    BookingRuleResponse,
    BookingRuleUpdate,
    BookingUpdate,
    PublicBookingPageData,
    PublicBookingSubmit,
)
from app.modules.bookings_v2.service import BookingService

# --- Internal router (authenticated) ---
router = APIRouter()

# --- Public router (no auth) ---
public_router = APIRouter()

# --- Booking rules router ---
rules_router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ======================================================================
# Internal booking endpoints
# ======================================================================


@router.get("", response_model=BookingListResponse, summary="List bookings")
async def list_bookings(
    request: Request,
    status: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    bookings, total = await svc.list_bookings(
        org_id, status=status, start_date=start_date, end_date=end_date,
        skip=skip, limit=limit,
    )
    return BookingListResponse(
        bookings=[BookingResponse.model_validate(b) for b in bookings],
        total=total,
    )


@router.post("", response_model=BookingResponse, status_code=201, summary="Create booking")
async def create_booking(
    payload: BookingCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    try:
        booking = await svc.create_booking(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return BookingResponse.model_validate(booking)


@router.get("/{booking_id}", response_model=BookingResponse, summary="Get booking")
async def get_booking(
    booking_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    booking = await svc.get_booking(org_id, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)


@router.put("/{booking_id}", response_model=BookingResponse, summary="Update booking")
async def update_booking(
    booking_id: UUID,
    payload: BookingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    try:
        booking = await svc.update_booking(org_id, booking_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)


@router.put("/{booking_id}/cancel", response_model=BookingResponse, summary="Cancel booking")
async def cancel_booking(
    booking_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    try:
        booking = await svc.cancel_booking(org_id, booking_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)


@router.post(
    "/{booking_id}/convert-to-job",
    response_model=BookingResponse,
    summary="Convert booking to job",
)
async def convert_to_job(
    booking_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    try:
        booking = await svc.convert_to_job(org_id, booking_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)


@router.post(
    "/{booking_id}/convert-to-invoice",
    response_model=BookingResponse,
    summary="Convert booking to invoice",
)
async def convert_to_invoice(
    booking_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    try:
        booking = await svc.convert_to_invoice(org_id, booking_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return BookingResponse.model_validate(booking)


# ======================================================================
# Booking rules endpoints
# ======================================================================


@rules_router.get("", response_model=list[BookingRuleResponse], summary="Get booking rules")
async def get_booking_rules(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    rules = await svc.get_booking_rules(org_id)
    return [BookingRuleResponse.model_validate(r) for r in rules]


@rules_router.put("", response_model=BookingRuleResponse, summary="Update booking rules")
async def update_booking_rules(
    payload: BookingRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = BookingService(db)
    rule = await svc.update_booking_rules(org_id, payload.model_dump(exclude_unset=True))
    return BookingRuleResponse.model_validate(rule)


# ======================================================================
# Public booking endpoints (no auth required)
# ======================================================================


async def _resolve_org(db: AsyncSession, org_slug: str):
    """Resolve an organisation by slug-like name lookup."""
    from app.modules.admin.models import Organisation
    from sqlalchemy import func as sa_func

    # Try exact name match (case-insensitive) or treat slug as lowered name
    stmt = select(Organisation).where(
        sa_func.lower(Organisation.name) == org_slug.lower().replace("-", " "),
    )
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()
    if org is None:
        # Try matching the slug directly as an ID (UUID)
        try:
            org_uuid = UUID(org_slug)
            stmt = select(Organisation).where(Organisation.id == org_uuid)
            result = await db.execute(stmt)
            org = result.scalar_one_or_none()
        except (ValueError, AttributeError):
            pass
    return org


@public_router.get(
    "/{org_slug}",
    response_model=PublicBookingPageData,
    summary="Public booking page data",
)
async def public_booking_page(
    org_slug: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return org branding and booking rules for the public booking page."""
    org = await _resolve_org(db, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    svc = BookingService(db)
    rules = await svc.get_booking_rules(org.id)
    default_rule = rules[0] if rules else None

    # Extract branding from org settings JSONB
    settings = getattr(org, "settings", {}) or {}

    return PublicBookingPageData(
        org_name=org.name,
        org_slug=org_slug,
        logo_url=settings.get("logo_url"),
        primary_colour=settings.get("primary_colour"),
        services=[],
        booking_rules=BookingRuleResponse.model_validate(default_rule) if default_rule else None,
    )


@public_router.post(
    "/{org_slug}",
    response_model=BookingResponse,
    status_code=201,
    summary="Submit public booking",
)
async def submit_public_booking(
    org_slug: str,
    payload: PublicBookingSubmit,
    db: AsyncSession = Depends(get_db_session),
):
    org = await _resolve_org(db, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    svc = BookingService(db)
    try:
        booking = await svc.create_public_booking(org.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return BookingResponse.model_validate(booking)


@public_router.get(
    "/{org_slug}/slots",
    response_model=AvailableSlotsResponse,
    summary="Get available time slots",
)
async def get_available_slots(
    org_slug: str,
    target_date: date = Query(..., alias="date"),
    service_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org = await _resolve_org(db, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    svc = BookingService(db)
    slots = await svc.get_available_slots(org.id, target_date, service_type)
    return AvailableSlotsResponse(date=target_date, slots=slots)
