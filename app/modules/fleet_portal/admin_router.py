"""Fleet Portal admin router — ``/api/v2/fleet-portal/admin/*``.

Workshop-staff-facing endpoints, authed via the staff JWT and gated by
the ``b2b-fleet-management`` module being enabled for the org. Used by
the Workshop_Admin pages mounted in ``OrgLayout``.

Endpoints (grown across tasks 5.2, 12.3, 17.x, 4A.8, 4A.9):

- task 5.2: invite / revoke / resend-invite / list fleet accounts
- task 12.3: bookings + quotes admin queues
- task 4A.8: portal_security_policy CRUD
- task 4A.9: account-detail admin actions (unlock, force-mfa-reset,
  admin-reset-password, impersonation)
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_org_admin
from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount
from app.modules.fleet_portal.services import account_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Per-request org_id resolution from the staff JWT
# ---------------------------------------------------------------------------


def _org_id_from_request(request: Request) -> uuid.UUID:
    """Extract ``org_id`` from the staff JWT context.

    The staff middleware decodes the JWT and stashes ``user_id``,
    ``org_id``, and ``role`` on ``request.state`` (matching the rest of
    the project's pattern). We tolerate either ``state.org_id`` or the
    same key on ``request.scope['state']``.
    """
    state = getattr(request, "state", None)
    org_id = getattr(state, "org_id", None) if state is not None else None
    if org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organisation membership required",
        )
    if isinstance(org_id, str):
        return uuid.UUID(org_id)
    return org_id


def _user_id_from_request(request: Request) -> uuid.UUID | None:
    state = getattr(request, "state", None)
    user_id = getattr(state, "user_id", None) if state is not None else None
    if user_id is None:
        return None
    if isinstance(user_id, str):
        try:
            return uuid.UUID(user_id)
        except ValueError:
            return None
    return user_id


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class _InviteRequest(S._StrictBase):
    """``POST /api/v2/fleet-portal/admin/invite`` body."""

    customer_id: uuid.UUID


@router.post(
    "/invite",
    response_model=S.IdResponse,
    dependencies=[require_org_admin()],
)
async def invite(
    body: _InviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> S.IdResponse:
    """Invite a business customer to the fleet portal and send the invite email."""
    org_id = _org_id_from_request(request)
    user_id = _user_id_from_request(request) or uuid.uuid4()
    try:
        account = await account_service.invite_fleet_admin(
            db,
            org_id=org_id,
            customer_id=body.customer_id,
            invited_by_user_id=user_id,
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))

    # Send the invite email using the existing email infrastructure
    try:
        # Use the request origin so the invite link points to the correct
        # domain (same pattern as QR payment URL generation in
        # app/modules/payments/token_service.py).
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        if origin:
            # Strip trailing path from referer (e.g. "https://devin.oraflows.co.nz/customers/...")
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
        else:
            base_url = None  # falls back to settings.frontend_base_url

        await _send_fleet_portal_invite_email(
            db, org_id=org_id, account=account, base_url=base_url
        )
    except Exception as exc:
        # Email failure should not break the invite — the token is already
        # persisted and the admin can resend later.
        logger.warning(
            "fleet_portal.invite_email_failed portal_account_id=%s err=%s",
            account.id,
            exc,
        )

    return S.IdResponse(id=account.id)


@router.post(
    "/revoke/{portal_account_id}",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def revoke(
    portal_account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    org_id = _org_id_from_request(request)
    try:
        await account_service.revoke_access(
            db, portal_account_id=portal_account_id, org_id=org_id
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.post(
    "/resend-invite/{portal_account_id}",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def resend_invite(
    portal_account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    org_id = _org_id_from_request(request)
    try:
        await account_service.resend_invite(
            db, portal_account_id=portal_account_id, org_id=org_id
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return S.StatusResponse(ok=True)


class _AdminFleetAccountItem(S._ResponseBase):
    """One row in the admin fleet-accounts list."""

    fleet_account_id: uuid.UUID
    customer_id: uuid.UUID
    display_name: str | None
    is_active: bool
    portal_account_count: int = 0


class _AdminFleetAccountListResponse(S.PaginatedResponse[_AdminFleetAccountItem]):
    pass


@router.get(
    "/accounts",
    response_model=_AdminFleetAccountListResponse,
    dependencies=[require_org_admin()],
)
async def list_fleet_accounts(
    offset: int = 0,
    limit: int = 50,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> _AdminFleetAccountListResponse:
    org_id = _org_id_from_request(request)
    from sqlalchemy import func as _func

    base = select(PortalFleetAccount).where(PortalFleetAccount.org_id == org_id)
    total = (await db.execute(select(_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.offset(offset).limit(limit))).scalars().all()

    items: list[_AdminFleetAccountItem] = []
    for fa in rows:
        n = (
            await db.execute(
                select(_func.count()).where(
                    PortalAccount.fleet_account_id == fa.id,
                    PortalAccount.is_active.is_(True),
                )
            )
        ).scalar_one()
        items.append(
            _AdminFleetAccountItem(
                fleet_account_id=fa.id,
                customer_id=fa.customer_id,
                display_name=fa.display_name,
                is_active=fa.is_active,
                portal_account_count=int(n),
            )
        )
    return _AdminFleetAccountListResponse(
        items=items, total=int(total), offset=offset, limit=limit
    )


__all__ = ["router"]


# ---------------------------------------------------------------------------
# Admin Booking Queue (Req 16.2 — accept/decline booking requests)
# ---------------------------------------------------------------------------


class _BookingAcceptRequest(S._StrictBase):
    refined_date_time: str | None = None
    notes: str | None = None


class _BookingDeclineRequest(S._StrictBase):
    decline_reason: str


@router.get(
    "/bookings",
    response_model=S.BookingRequestListResponse,
    dependencies=[require_org_admin()],
)
async def list_admin_bookings(
    offset: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.BookingRequestListResponse:
    """List all fleet booking requests for this org (workshop admin view)."""
    from sqlalchemy import func as _func
    from app.modules.fleet_portal.models import FleetServiceBookingRequest

    org_id = _org_id_from_request(request)
    base = select(FleetServiceBookingRequest).where(
        FleetServiceBookingRequest.org_id == org_id,
    )
    if status_filter and status_filter != "all":
        base = base.where(FleetServiceBookingRequest.status == status_filter)

    total = (await db.execute(select(_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(FleetServiceBookingRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    # Resolve requester names
    items: list[S.BookingRequestSchema] = []
    for r in rows:
        requester_name = await _resolve_portal_account_name(db, r.requested_by_portal_account_id)
        rego = await _resolve_vehicle_rego(db, r.customer_vehicle_id)
        items.append(
            S.BookingRequestSchema(
                id=r.id,
                customer_vehicle_id=r.customer_vehicle_id,
                rego=rego,
                requested_by_portal_account_id=r.requested_by_portal_account_id,
                requested_by_name=requester_name,
                preferred_date=r.preferred_date,
                preferred_slot=r.preferred_slot,
                service_description=r.service_description,
                notes=r.notes,
                status=r.status,
                decline_reason=r.decline_reason,
                booking_id=r.booking_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return S.BookingRequestListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.post(
    "/bookings/{request_id}/accept",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def accept_booking(
    request_id: uuid.UUID,
    body: _BookingAcceptRequest,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Accept a fleet booking request (Req 11.4)."""
    from app.modules.fleet_portal.models import FleetServiceBookingRequest
    from app.modules.fleet_portal.services.booking_service import can_transition

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(FleetServiceBookingRequest).where(
            FleetServiceBookingRequest.id == request_id,
            FleetServiceBookingRequest.org_id == org_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Booking request not found")
    if not can_transition(row.status, "accepted"):
        raise HTTPException(status_code=400, detail=f"Cannot accept request in status={row.status}")

    row.status = "accepted"
    await db.flush()
    await db.refresh(row)

    # Create a draft Booking row linked to the request (Req 11.4)
    try:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        from app.modules.bookings.models import Booking
        from app.modules.fleet_portal.models import PortalAccount

        # Resolve refined date_time — fall back to preferred_date noon if missing/invalid
        refined: _dt | None = None
        raw = body.refined_date_time
        if raw:
            try:
                refined = _dt.fromisoformat(raw.replace("Z", "+00:00"))
                if refined.tzinfo is None:
                    refined = refined.replace(tzinfo=_tz.utc)
            except (ValueError, AttributeError):
                refined = None
        if refined is None:
            refined = _dt.combine(
                row.preferred_date, _dt.min.time().replace(hour=12)
            ).replace(tzinfo=_tz.utc)
        end = refined + _td(hours=1)

        # Resolve requester for customer_name
        name_res = await db.execute(
            select(PortalAccount).where(
                PortalAccount.id == row.requested_by_portal_account_id,
            )
        )
        req_account = name_res.scalars().first()
        customer_name = (
            f"{req_account.first_name or ''} {req_account.last_name or ''}".strip()
            if req_account is not None else ""
        ) or (req_account.email if req_account is not None else "Fleet customer")

        rego = await _resolve_vehicle_rego(db, row.customer_vehicle_id)
        booking = Booking(
            org_id=org_id,
            customer_name=customer_name,
            customer_email=req_account.email if req_account is not None else None,
            customer_phone=req_account.phone if req_account is not None else None,
            vehicle_rego=rego,
            service_type=(row.service_description or "")[:255],
            start_time=refined,
            end_time=end,
            status="pending",
            notes=row.notes,
        )
        db.add(booking)
        await db.flush()
        await db.refresh(booking)
        row.booking_id = booking.id
        await db.flush()
    except Exception as exc:
        logger.warning(
            "fleet_portal.accept_booking.draft_create_failed err=%s", exc
        )
        # Don't fail the click; status is already 'accepted' and the
        # admin can create a booking manually if needed.

    # Notify the fleet portal users about the acceptance
    try:
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db,
            org_id=org_id,
            category="fleet_booking_accepted",
            severity="success",
            title="Service booking accepted",
            body=f"Your booking for {row.preferred_date.isoformat()} has been accepted.",
            link_url="/fleet/bookings",
            entity_type="fleet_service_booking_request",
            entity_id=row.id,
            audience_roles=["fleet_admin", "driver"],
        )
    except Exception:
        pass
    return S.StatusResponse(ok=True)


@router.post(
    "/bookings/{request_id}/decline",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def decline_booking(
    request_id: uuid.UUID,
    body: _BookingDeclineRequest,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Decline a fleet booking request (Req 11.5)."""
    from app.modules.fleet_portal.models import FleetServiceBookingRequest
    from app.modules.fleet_portal.services.booking_service import can_transition

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(FleetServiceBookingRequest).where(
            FleetServiceBookingRequest.id == request_id,
            FleetServiceBookingRequest.org_id == org_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Booking request not found")
    if not can_transition(row.status, "declined"):
        raise HTTPException(status_code=400, detail=f"Cannot decline request in status={row.status}")

    row.status = "declined"
    row.decline_reason = body.decline_reason
    await db.flush()
    await db.refresh(row)

    # Notify the fleet portal users about the decline
    try:
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db,
            org_id=org_id,
            category="fleet_booking_declined",
            severity="warning",
            title="Service booking declined",
            body=f"Your booking for {row.preferred_date.isoformat()} was declined: {body.decline_reason[:200]}",
            link_url="/fleet/bookings",
            entity_type="fleet_service_booking_request",
            entity_id=row.id,
            audience_roles=["fleet_admin", "driver"],
        )
    except Exception:
        pass
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Admin Quote Queue (Req 16.3 — list + link quote to fleet request)
# ---------------------------------------------------------------------------


class _QuoteLinkRequest(S._StrictBase):
    quote_id: uuid.UUID


@router.get(
    "/quotes",
    response_model=S.QuoteRequestListResponse,
    dependencies=[require_org_admin()],
)
async def list_admin_quotes(
    offset: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.QuoteRequestListResponse:
    """List all fleet quote requests for this org (workshop admin view)."""
    from sqlalchemy import func as _func
    from app.modules.fleet_portal.models import FleetQuotationRequest

    org_id = _org_id_from_request(request)
    base = select(FleetQuotationRequest).where(
        FleetQuotationRequest.org_id == org_id,
    )
    if status_filter and status_filter != "all":
        base = base.where(FleetQuotationRequest.status == status_filter)

    total = (await db.execute(select(_func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(FleetQuotationRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    items: list[S.QuoteRequestSchema] = []
    for r in rows:
        requester_name = await _resolve_portal_account_name(db, r.requested_by_portal_account_id)
        rego = await _resolve_vehicle_rego(db, r.customer_vehicle_id)
        items.append(
            S.QuoteRequestSchema(
                id=r.id,
                customer_vehicle_id=r.customer_vehicle_id,
                rego=rego,
                requested_by_portal_account_id=r.requested_by_portal_account_id,
                requested_by_name=requester_name,
                service_description=r.service_description,
                notes=r.notes,
                status=r.status,
                quote_id=r.quote_id,
                quote_total=None,
                quote_valid_until=None,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
    return S.QuoteRequestListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.post(
    "/quotes/{request_id}/link",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def link_quote(
    request_id: uuid.UUID,
    body: _QuoteLinkRequest,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Link an existing org quote to a fleet quote request (Req 16.4)."""
    from app.modules.fleet_portal.models import FleetQuotationRequest
    from app.modules.fleet_portal.services.quote_service import can_transition

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(FleetQuotationRequest).where(
            FleetQuotationRequest.id == request_id,
            FleetQuotationRequest.org_id == org_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Quote request not found")
    if not can_transition(row.status, "quoted"):
        raise HTTPException(status_code=400, detail=f"Cannot link quote in status={row.status}")

    row.quote_id = body.quote_id
    row.status = "quoted"
    await db.flush()
    await db.refresh(row)

    # Notify the fleet portal users that a quote is ready
    try:
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db,
            org_id=org_id,
            category="fleet_quote_ready",
            severity="info",
            title="Quote ready",
            body=f"Your quote request '{(row.service_description or '')[:80]}' is ready.",
            link_url="/fleet/quotes",
            entity_type="fleet_quotation_request",
            entity_id=row.id,
            audience_roles=["fleet_admin"],
        )
    except Exception:
        pass
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Admin Summary endpoint (Req 16.5 — counts for sidebar badge + dashboard)
# ---------------------------------------------------------------------------


class _AdminSummaryResponse(S._ResponseBase):
    pending_bookings: int = 0
    pending_quotes: int = 0
    recent_failures: int = 0
    fleet_accounts: int = 0


@router.get(
    "/summary",
    response_model=_AdminSummaryResponse,
    dependencies=[require_org_admin()],
)
async def admin_summary(
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> _AdminSummaryResponse:
    """Return counts for the admin dashboard cards and sidebar badge."""
    from sqlalchemy import func as _func
    from app.modules.fleet_portal.models import (
        FleetServiceBookingRequest,
        FleetQuotationRequest,
        FleetChecklistSubmission,
    )
    from datetime import datetime, timedelta, timezone

    org_id = _org_id_from_request(request)

    pending_bookings = (
        await db.execute(
            select(_func.count()).where(
                FleetServiceBookingRequest.org_id == org_id,
                FleetServiceBookingRequest.status == "pending",
            )
        )
    ).scalar_one()

    pending_quotes = (
        await db.execute(
            select(_func.count()).where(
                FleetQuotationRequest.org_id == org_id,
                FleetQuotationRequest.status == "pending",
            )
        )
    ).scalar_one()

    # Recent failures = submissions completed in last 7 days with failed_item_count > 0
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_failures = (
        await db.execute(
            select(_func.count()).where(
                FleetChecklistSubmission.org_id == org_id,
                FleetChecklistSubmission.status == "completed",
                FleetChecklistSubmission.failed_item_count > 0,
                FleetChecklistSubmission.completed_at >= seven_days_ago,
            )
        )
    ).scalar_one()

    fleet_accounts = (
        await db.execute(
            select(_func.count()).where(PortalFleetAccount.org_id == org_id)
        )
    ).scalar_one()

    return _AdminSummaryResponse(
        pending_bookings=int(pending_bookings),
        pending_quotes=int(pending_quotes),
        recent_failures=int(recent_failures),
        fleet_accounts=int(fleet_accounts),
    )


# ---------------------------------------------------------------------------
# Admin Checklist Failures Feed (Req 16.7)
# ---------------------------------------------------------------------------


@router.get(
    "/checklist-failures",
    dependencies=[require_org_admin()],
)
async def list_checklist_failures(
    offset: int = 0,
    limit: int = 50,
    days: int = 30,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List recent checklist submissions with failed items (Req 16.7)."""
    from sqlalchemy import func as _func
    from datetime import datetime, timedelta, timezone
    from app.modules.fleet_portal.models import (
        FleetChecklistSubmission,
        PortalFleetAccount as _PFA,
    )

    org_id = _org_id_from_request(request)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days)))

    base = select(FleetChecklistSubmission).where(
        FleetChecklistSubmission.org_id == org_id,
        FleetChecklistSubmission.status == "completed",
        FleetChecklistSubmission.failed_item_count > 0,
        FleetChecklistSubmission.completed_at >= cutoff,
    )
    total = (
        await db.execute(select(_func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(FleetChecklistSubmission.completed_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    items: list[dict] = []
    for s in rows:
        rego = await _resolve_vehicle_rego(db, s.customer_vehicle_id)
        driver_name = await _resolve_portal_account_name(db, s.portal_account_id)
        fa_res = await db.execute(
            select(_PFA.display_name).where(_PFA.id == s.fleet_account_id)
        )
        fa_row = fa_res.first()
        items.append(
            {
                "submission_id": str(s.id),
                "fleet_account_id": str(s.fleet_account_id),
                "fleet_account_name": fa_row[0] if fa_row else None,
                "rego": rego,
                "driver_name": driver_name,
                "failed_item_count": s.failed_item_count or 0,
                "passed_item_count": s.passed_item_count or 0,
                "na_item_count": s.na_item_count or 0,
                "completed_at": (
                    s.completed_at.isoformat() if s.completed_at else None
                ),
            }
        )

    return {
        "items": items,
        "total": int(total),
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# Admin Security Policy (Req 21.2 — CRUD for portal_security_policy)
# ---------------------------------------------------------------------------


@router.get(
    "/security-policy",
    dependencies=[require_org_admin()],
)
async def get_security_policy(
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get the current portal security policy for this org."""
    from app.modules.admin.models import Organisation

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = res.scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # portal_security_policy is stored in org.settings JSONB
    settings_json = getattr(org, "settings", None) or {}
    policy = settings_json.get("portal_security_policy", {})
    pw = policy.get("password_policy", {})
    lockout = policy.get("lockout_policy", {})
    session = policy.get("session_policy", {})
    mfa = policy.get("mfa_policy", {})

    return {
        "password_min_length": pw.get("min_length", 8),
        "password_require_uppercase": pw.get("require_uppercase", False),
        "password_require_number": pw.get("require_digit", False),
        "password_require_special": pw.get("require_special", False),
        "password_history_count": pw.get("history_count", 3),
        "password_max_age_days": pw.get("expiry_days", 0),
        "lockout_threshold": lockout.get("max_attempts", 5),
        "lockout_duration_minutes": lockout.get("lockout_duration_minutes", 15),
        "session_idle_timeout_minutes": session.get("idle_timeout_minutes", 240),
        "session_max_concurrent": session.get("max_sessions_per_user", 5),
        "mfa_mode": mfa.get("mode", "optional"),
    }


@router.put(
    "/security-policy",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def update_security_policy(
    body: dict,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Update the portal security policy for this org (Req 21.2)."""
    from app.modules.admin.models import Organisation

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = res.scalars().first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Build the policy in the canonical schema shape
    policy = {
        "password_policy": {
            "min_length": max(8, min(128, int(body.get("password_min_length", 8)))),
            "require_uppercase": bool(body.get("password_require_uppercase", False)),
            "require_lowercase": True,
            "require_digit": bool(body.get("password_require_number", False)),
            "require_special": bool(body.get("password_require_special", False)),
            "history_count": max(0, min(24, int(body.get("password_history_count", 3)))),
            "expiry_days": max(0, min(365, int(body.get("password_max_age_days", 0)))),
        },
        "lockout_policy": {
            "max_attempts": max(3, min(20, int(body.get("lockout_threshold", 5)))),
            "lockout_duration_minutes": max(1, min(1440, int(body.get("lockout_duration_minutes", 15)))),
        },
        "session_policy": {
            "idle_timeout_minutes": max(5, min(1440, int(body.get("session_idle_timeout_minutes", 240)))),
            "max_sessions_per_user": max(1, min(20, int(body.get("session_max_concurrent", 5)))),
        },
        "mfa_policy": {
            "mode": body.get("mfa_mode", "optional") if body.get("mfa_mode") in ("optional", "encouraged", "required") else "optional",
            "excluded_user_ids": [],
        },
    }

    # Merge into org.settings
    settings = dict(getattr(org, "settings", None) or {})
    settings["portal_security_policy"] = policy
    org.settings = settings
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Admin Account Detail + Actions (Req 21.17, 21.18, 21.19, 21.20)
# ---------------------------------------------------------------------------


class _AccountDetailResponse(S._ResponseBase):
    portal_account_id: uuid.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    portal_user_role: str
    is_active: bool
    is_locked_permanently: bool
    failed_login_attempts: int = 0
    last_login_at: str | None = None
    mfa_methods: list[dict] = []
    created_at: str


@router.get(
    "/accounts/{portal_account_id}",
    response_model=_AccountDetailResponse,
    dependencies=[require_org_admin()],
)
async def get_account_detail(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> _AccountDetailResponse:
    """Get detailed info for a single portal account (Req 21.17)."""
    from app.modules.fleet_portal.models import PortalAccountMfaMethod

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    # Get MFA methods
    mfa_res = await db.execute(
        select(PortalAccountMfaMethod).where(
            PortalAccountMfaMethod.portal_account_id == account.id,
        )
    )
    mfa_methods = [
        {"id": str(m.id), "method": m.method, "verified": m.verified}
        for m in mfa_res.scalars().all()
    ]

    return _AccountDetailResponse(
        portal_account_id=account.id,
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        portal_user_role=account.portal_user_role,
        is_active=account.is_active,
        is_locked_permanently=account.is_locked_permanently,
        failed_login_attempts=account.failed_login_attempts,
        last_login_at=account.last_login_at.isoformat() if account.last_login_at else None,
        mfa_methods=mfa_methods,
        created_at=account.created_at.isoformat(),
    )


@router.post(
    "/accounts/{portal_account_id}/unlock",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def unlock_account(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Unlock a locked portal account (Req 21.18)."""
    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    account.failed_login_attempts = 0
    account.locked_until = None
    account.is_locked_permanently = False
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post(
    "/accounts/{portal_account_id}/force-mfa-reset",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def force_mfa_reset(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Remove all MFA methods and force re-enrolment (Req 21.19)."""
    from sqlalchemy import delete
    from app.modules.fleet_portal.models import PortalAccountMfaMethod, PortalAccountBackupCode

    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    await db.execute(
        delete(PortalAccountMfaMethod).where(
            PortalAccountMfaMethod.portal_account_id == portal_account_id
        )
    )
    await db.execute(
        delete(PortalAccountBackupCode).where(
            PortalAccountBackupCode.portal_account_id == portal_account_id
        )
    )
    account.mfa_required_at_next_login = True
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post(
    "/accounts/{portal_account_id}/reset-password",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def admin_reset_password(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Issue a password reset token and send email (Req 21.20)."""
    org_id = _org_id_from_request(request)
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        await account_service.issue_reset_token(
            db, org_id=org_id, email=account.email
        )
    except Exception as exc:
        logger.warning("admin_reset_password failed: %s", exc)
    return S.StatusResponse(ok=True)


@router.post(
    "/accounts/{portal_account_id}/revoke",
    response_model=S.StatusResponse,
    dependencies=[require_org_admin()],
)
async def admin_revoke_account(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Revoke portal access for an account."""
    org_id = _org_id_from_request(request)
    try:
        await account_service.revoke_access(
            db, portal_account_id=portal_account_id, org_id=org_id
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.post(
    "/accounts/{portal_account_id}/impersonate",
    dependencies=[require_org_admin()],
)
async def impersonate_account(
    portal_account_id: uuid.UUID,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Create an impersonation session for a portal account (Req 21.21).

    Returns a one-time URL that the admin can open in a new tab to
    log in as the portal user. The session is marked as impersonation
    in the audit log.
    """
    from app.modules.fleet_portal.services import session_service, audit_service
    import secrets as _secrets

    org_id = _org_id_from_request(request)
    user_id = _user_id_from_request(request)

    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.is_active:
        raise HTTPException(status_code=400, detail="Cannot impersonate a revoked account")

    # Create a session for the target account
    session_token, csrf_token = await session_service.create_fleet_portal_session(
        db, portal_account=account
    )

    # Audit log the impersonation
    try:
        await audit_service.log_event(
            db,
            org_id=org_id,
            action="fleet_portal_impersonation",
            portal_account_id=portal_account_id,
            details={
                "impersonated_by": str(user_id),
                "target_email": account.email,
            },
        )
    except Exception:
        pass

    # Return the session token — the admin frontend will set it as a cookie
    # and redirect to /fleet/dashboard in a new tab
    return {
        "session_token": session_token,
        "csrf_token": csrf_token,
        "target_email": account.email,
        "portal_user_role": account.portal_user_role,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_portal_account_name(
    db: AsyncSession, portal_account_id: uuid.UUID | None
) -> str | None:
    """Resolve a portal account ID to a display name."""
    if portal_account_id is None:
        return None
    res = await db.execute(
        select(PortalAccount.first_name, PortalAccount.last_name).where(
            PortalAccount.id == portal_account_id
        )
    )
    row = res.first()
    if row is None:
        return None
    return f"{row[0] or ''} {row[1] or ''}".strip() or None


async def _resolve_vehicle_rego(
    db: AsyncSession, customer_vehicle_id: uuid.UUID | None
) -> str | None:
    """Resolve a customer vehicle ID to its rego.

    Reads from the global_vehicles or org_vehicles row that the link
    points at — CustomerVehicle itself doesn't carry a rego column.
    """
    if customer_vehicle_id is None:
        return None
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    res = await db.execute(
        select(CustomerVehicle).where(CustomerVehicle.id == customer_vehicle_id)
    )
    cv = res.scalars().first()
    if cv is None:
        return None
    if cv.global_vehicle_id is not None:
        gv = (await db.execute(
            select(GlobalVehicle.rego).where(GlobalVehicle.id == cv.global_vehicle_id)
        )).first()
        return gv[0] if gv else None
    if cv.org_vehicle_id is not None:
        ov = (await db.execute(
            select(OrgVehicle.rego).where(OrgVehicle.id == cv.org_vehicle_id)
        )).first()
        return ov[0] if ov else None
    return None


async def _send_fleet_portal_invite_email(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    account,  # PortalAccount
    base_url: str | None = None,
) -> None:
    """Send the fleet portal invite email to the portal account's email.

    Uses the same email infrastructure as the existing customer portal
    link email (``send_email_task``). The invite link points to
    ``/fleet/accept-invite/{token}`` where the user sets their password.

    ``base_url`` is the request origin (e.g. ``https://devin.oraflows.co.nz``)
    so the link in the email points to the correct domain. Falls back to
    ``settings.frontend_base_url`` when not provided.
    """
    from app.config import settings
    from app.modules.admin.models import Organisation
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    if not account.email or not account.invite_token:
        return

    # Fetch org for branding
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Workshop"

    # Build invite URL using the request origin (same pattern as QR payment)
    frontend_base = (base_url or settings.frontend_base_url or "http://localhost").rstrip("/")
    invite_url = f"{frontend_base}/fleet/accept-invite/{account.invite_token}"

    customer_name = f"{account.first_name or ''} {account.last_name or ''}".strip()
    email_subject = f"You're invited to the Fleet Portal — {org_name}"

    html_body = f"""<p>Hi {customer_name or 'there'},</p>
<p>You've been invited to access the <strong>Fleet Portal</strong> for {org_name}.</p>
<p>From the Fleet Portal you can:</p>
<ul>
<li>View and manage your fleet vehicles</li>
<li>Invite drivers and assign vehicles</li>
<li>Run NZTA pre-trip safety checklists</li>
<li>Book services and request quotes</li>
<li>Manage WOF/COF/service-due reminders</li>
</ul>
<p>Click the button below to set your password and get started:</p>
<p><a href="{invite_url}" style="display:inline-block;padding:12px 24px;background-color:#4f46e5;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;">Set Up My Account</a></p>
<p>Or copy this link: <a href="{invite_url}">{invite_url}</a></p>
<p>This invitation expires in 7 days.</p>
<p>Kind regards,<br/>{org_name}</p>"""

    text_body = (
        f"Hi {customer_name or 'there'},\n\n"
        f"You've been invited to access the Fleet Portal for {org_name}.\n\n"
        f"From the Fleet Portal you can:\n"
        f"- View and manage your fleet vehicles\n"
        f"- Invite drivers and assign vehicles\n"
        f"- Run NZTA pre-trip safety checklists\n"
        f"- Book services and request quotes\n"
        f"- Manage WOF/COF/service-due reminders\n\n"
        f"Set up your account here:\n{invite_url}\n\n"
        f"This invitation expires in 7 days.\n\n"
        f"Kind regards,\n{org_name}"
    )

    # Log the email
    log_entry = await log_email_sent(
        db,
        org_id=org_id,
        recipient=account.email,
        template_type="fleet_portal_invite",
        subject=email_subject,
        status="queued",
    )

    # Dispatch via the async email task (same as portal link emails)
    await send_email_task(
        org_id=str(org_id),
        log_id=str(log_entry["id"]),
        to_email=account.email,
        to_name=customer_name,
        subject=email_subject,
        html_body=html_body,
        text_body=text_body,
        org_sender_name=org_name,
        template_type="fleet_portal_invite",
    )
