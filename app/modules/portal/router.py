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
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from starlette.responses import Response as StarletteResponse
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
    PortalJobsResponse,
    PortalClaimsResponse,
    PortalProjectsResponse,
    PortalProgressClaimsResponse,
    PortalRecurringResponse,
    PortalLoyaltyResponse,
    PortalDocumentsResponse,
    PortalProfileUpdateRequest,
    PortalProfileUpdateResponse,
    PortalDSARRequest,
    PortalDSARResponse,
    PortalRecoverRequest,
    PortalRecoverResponse,
    PortalMessagesResponse,
)
from app.modules.portal.service import (
    CSRFValidationError,
    PortalDisabledError,
    create_portal_payment,
    create_portal_session,
    destroy_portal_session,
    get_portal_access,
    get_portal_invoices,
    get_portal_vehicles,
    get_portal_quotes,
    accept_portal_quote,
    get_portal_assets,
    get_portal_bookings,
    create_portal_booking,
    get_portal_available_slots,
    get_portal_jobs,
    get_portal_claims,
    get_portal_projects,
    get_portal_progress_claims,
    get_portal_recurring,
    get_portal_loyalty,
    get_portal_documents,
    update_portal_profile,
    cancel_portal_booking,
    create_portal_dsar,
    recover_portal_link,
    validate_portal_csrf,
    validate_portal_session,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom route class — adds Cache-Control headers to all portal responses
# (Req 43.3: prevent caching of token-bearing URLs)
# ---------------------------------------------------------------------------


class PortalCacheRoute(APIRoute):
    """Custom APIRoute that injects ``Cache-Control: no-store`` and
    ``Pragma: no-cache`` headers on every portal response."""

    def get_route_handler(self) -> Callable:
        original_handler = super().get_route_handler()

        async def _wrapped(request: Request) -> StarletteResponse:
            response: StarletteResponse = await original_handler(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            return response

        return _wrapped


router = APIRouter(route_class=PortalCacheRoute)


# ---------------------------------------------------------------------------
# Stripe Connect webhook  (Req 11.1–11.5)
# ---------------------------------------------------------------------------


@router.post(
    "/stripe-webhook",
    status_code=200,
    responses={
        400: {"description": "Invalid signature or payload"},
    },
    summary="Stripe Connect webhook for portal payments",
)
async def portal_stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Receive Stripe Connect webhook events for portal payments.

    Validates the event signature using the Connect webhook signing
    secret (separate from the platform webhook secret) and delegates
    processing to the shared ``handle_stripe_webhook`` handler.

    Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
    """
    from app.integrations.stripe_connect import verify_webhook_signature
    from app.modules.payments.service import handle_stripe_webhook
    from app.config import settings as app_settings

    # Read raw body for signature verification
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not sig_header:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing Stripe-Signature header"},
        )

    webhook_secret = app_settings.stripe_connect_webhook_secret
    if not webhook_secret:
        logger.error("Stripe Connect webhook secret not configured")
        return JSONResponse(
            status_code=500,
            content={"detail": "Webhook verification not configured"},
        )

    try:
        event = verify_webhook_signature(
            payload=payload,
            sig_header=sig_header,
            webhook_secret=webhook_secret,
        )
    except ValueError as exc:
        logger.warning("Stripe Connect webhook signature verification failed: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    event_type = event.get("type", "")
    event_data = event.get("data", {}).get("object", {})

    try:
        result = await handle_stripe_webhook(
            db,
            event_type=event_type,
            event_data=event_data,
        )
        return result
    except Exception as exc:
        logger.exception("Error processing Stripe Connect webhook: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": f"Webhook processing error: {exc}"},
        )


# ---------------------------------------------------------------------------
# Portal logout  (Req 40.1, 40.2)
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=200,
    summary="Log out of the customer portal",
)
async def portal_logout(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Clear the portal session and cookie.

    Requirements: 40.1, 40.2
    """
    session_token = request.cookies.get("portal_session")
    if session_token:
        await destroy_portal_session(db, session_token)

    response = JSONResponse(content={"detail": "Signed out successfully"})
    response.delete_cookie(
        key="portal_session",
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie(
        key="portal_csrf",
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# Self-service token recovery  (Req 52.1, 52.2, 52.3, 52.4)
# ---------------------------------------------------------------------------


@router.post(
    "/recover",
    response_model=PortalRecoverResponse,
    status_code=200,
    summary="Recover portal access link via email",
)
async def portal_recover(
    payload: PortalRecoverRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Look up portal-enabled customers by email and send portal links.

    Always returns 200 with a generic message regardless of whether any
    matching customers were found — this prevents email enumeration.

    Requirements: 52.1, 52.2, 52.3, 52.4
    """
    result = await recover_portal_link(db, payload.email)
    return PortalRecoverResponse(message=result["message"])


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
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate the portal token and return customer + org branding.

    No account creation required — the unique link is the credential.
    On success, creates a portal session and sets an HttpOnly cookie
    for subsequent request authentication.

    Requirements: 61.1, 61.5, 40.3, 40.4
    """
    try:
        result = await get_portal_access(db, token)

        # Create a portal session and set HttpOnly cookie (Req 40.3, 40.4)
        session_token, csrf_token = await create_portal_session(db, result.customer.customer_id)

        response = JSONResponse(content=result.model_dump(mode="json"))
        response.set_cookie(
            key="portal_session",
            value=session_token,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=4 * 60 * 60,  # 4 hours
            path="/",
        )
        # CSRF double-submit cookie — non-HttpOnly so JS can read it (Req 41.1, 41.2)
        response.set_cookie(
            key="portal_csrf",
            value=csrf_token,
            httponly=False,
            secure=True,
            samesite="lax",
            max_age=4 * 60 * 60,  # 4 hours
            path="/",
        )
        return response
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's invoice history with outstanding balances
    and payment history.

    Requirements: 61.2
    """
    try:
        return await get_portal_invoices(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/invoices/{invoice_id}/pdf",
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token or invoice not found"},
    },
    summary="Download invoice PDF from customer portal",
)
async def portal_invoice_pdf(
    token: str,
    invoice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate and return a PDF for a specific invoice.

    Validates that the invoice belongs to the customer associated with
    the portal token, then reuses the existing PDF generation logic.

    Requirements: 18.1, 18.2, 18.3, 18.4
    """
    from app.modules.portal.service import get_portal_invoice_pdf

    try:
        pdf_bytes, invoice_number = await get_portal_invoice_pdf(db, token, invoice_id)
        filename = f"invoice-{invoice_number}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's vehicles with dates and services performed.

    Requirements: 61.4
    """
    try:
        return await get_portal_vehicles(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/jobs",
    response_model=PortalJobsResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer job cards with status and staff info",
)
async def portal_jobs(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's job cards with status, assigned staff,
    and linked invoice references.

    Requirements: 16.1, 16.2, 16.3, 16.4
    """
    try:
        return await get_portal_jobs(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/claims",
    response_model=PortalClaimsResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer claims with status and action timeline",
)
async def portal_claims(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's claims with type, status, resolution details,
    and action timeline.

    Requirements: 17.1, 17.2, 17.3
    """
    try:
        return await get_portal_claims(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/projects",
    response_model=PortalProjectsResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer projects with status and details",
)
async def portal_projects(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's projects with status, description,
    and budget/contract details.

    Requirements: 49.1, 49.2, 49.3
    """
    try:
        return await get_portal_projects(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/progress-claims",
    response_model=PortalProgressClaimsResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Progress claims linked to customer's projects",
)
async def portal_progress_claims(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return progress claims linked to the customer's projects
    with claim number, status, amount, and completion percentage.

    Requirements: 51.1, 51.2, 51.3
    """
    try:
        return await get_portal_progress_claims(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


@router.get(
    "/{token}/recurring",
    response_model=PortalRecurringResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer recurring invoice schedules",
)
async def portal_recurring(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's recurring invoice schedules with frequency,
    next run date, amount, and status.

    Requirements: 50.1, 50.2, 50.3
    """
    try:
        return await get_portal_recurring(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    invoice_id: uuid.UUID,
    request: Request,
    payload: PortalPayRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a Stripe Checkout link for the customer to pay an
    outstanding invoice.

    Requirements: 61.3
    """
    from app.middleware.auth import get_client_ip

    amount = payload.amount if payload else None
    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await create_portal_payment(db, token, invoice_id, amount, ip_address=ip_address)
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's quotes. Sent quotes can be accepted.

    Requirements: 49.2
    """
    try:
        return await get_portal_quotes(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a quote, triggering status update to 'accepted'.

    Requirements: 49.2
    """
    from app.middleware.auth import get_client_ip

    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await accept_portal_quote(db, token, quote_id, ip_address=ip_address)
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's assets with linked invoices, jobs, and quotes.

    Requirements: 49.2
    """
    try:
        return await get_portal_assets(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's bookings.

    Requirements: 49.4
    """
    try:
        return await get_portal_bookings(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    payload: PortalBookingCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Book an appointment using the same availability rules as the public page.

    Requirements: 49.4
    """
    from app.middleware.auth import get_client_ip

    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await create_portal_booking(
            db, token, payload.service_type, payload.start_time, payload.notes,
            ip_address=ip_address,
        )
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    target_date: date = Query(..., alias="date", description="Date to check slots for"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return available booking time slots for a given date.

    Requirements: 49.4
    """
    try:
        return await get_portal_available_slots(db, token, target_date)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Booking cancellation  (Req 22)
# ---------------------------------------------------------------------------


@router.patch(
    "/{token}/bookings/{booking_id}/cancel",
    status_code=200,
    responses={400: {"description": "Validation error or booking not cancellable"}},
    summary="Cancel a booking from the customer portal",
)
async def portal_cancel_booking(
    token: str,
    booking_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel a booking that is in a cancellable status (pending or confirmed).

    Requirements: 22.1, 22.2, 22.3
    """
    from app.middleware.auth import get_client_ip

    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await cancel_portal_booking(db, token, booking_id, ip_address=ip_address)
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# SMS conversation history  (Req 63.1, 63.2, 63.3, 63.4)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/messages",
    response_model=PortalMessagesResponse,
    status_code=200,
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Customer SMS conversation history",
)
async def portal_messages(
    token: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's SMS conversation history with the organisation.

    Messages are ordered chronologically with the most recent at the bottom.

    Requirements: 63.1, 63.2, 63.3, 63.4
    """
    from app.modules.portal.service import get_portal_messages

    try:
        return await get_portal_messages(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
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
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the customer's loyalty points, tier, and transaction history.

    Requirements: 49.2, 38.6
    """
    try:
        return await get_portal_loyalty(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Compliance documents  (Req 19)
# ---------------------------------------------------------------------------


@router.get(
    "/{token}/documents",
    response_model=PortalDocumentsResponse,
    status_code=200,
    responses={400: {"description": "Invalid or expired token"}},
    summary="Customer compliance documents linked to invoices",
)
async def portal_documents(
    token: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Return compliance documents linked to the customer's invoices.

    Requirements: 19.1, 19.2, 19.3
    """
    try:
        return await get_portal_documents(db, token, limit=limit, offset=offset)
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Profile update  (Req 21)
# ---------------------------------------------------------------------------


@router.patch(
    "/{token}/profile",
    response_model=PortalProfileUpdateResponse,
    status_code=200,
    responses={400: {"description": "Validation error or invalid token"}},
    summary="Update customer contact details from the portal",
)
async def portal_update_profile(
    token: str,
    payload: PortalProfileUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Allow the customer to update their email and/or phone number.

    Requirements: 21.1, 21.2, 21.3, 21.4
    """
    from app.middleware.auth import get_client_ip

    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await update_portal_profile(db, token, payload, ip_address=ip_address)
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# DSAR — Data Subject Access Request  (Req 45)
# ---------------------------------------------------------------------------


@router.post(
    "/{token}/dsar",
    response_model=PortalDSARResponse,
    status_code=201,
    responses={
        400: {"description": "Invalid token or invalid request type"},
        403: {"description": "CSRF validation failed"},
    },
    summary="Submit a Data Subject Access Request (DSAR) from the portal",
)
async def portal_dsar(
    token: str,
    payload: PortalDSARRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Submit a privacy request (data export or account deletion).

    Creates a DSAR record and notifies the org admin via email.

    Requirements: 45.1, 45.2, 45.3, 45.4, 45.5
    """
    from app.middleware.auth import get_client_ip

    ip_address = get_client_ip(request)
    try:
        validate_portal_csrf(request)
        return await create_portal_dsar(
            db, token, payload.request_type, ip_address=ip_address,
        )
    except CSRFValidationError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except PortalDisabledError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
