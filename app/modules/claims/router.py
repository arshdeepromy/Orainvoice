"""Claims router — CRUD and workflow endpoints.

Requirements: 1.1-1.8, 2.1-2.7, 3.1-3.8, 6.1-6.5, 7.1-7.5, 8.1-8.4, 9.1-9.3, 11.2, 11.3, 12.1-12.5
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.claims.schemas import (
    ClaimCreateRequest,
    ClaimListResponse,
    ClaimNoteRequest,
    ClaimResolveRequest,
    ClaimResponse,
    ClaimStatusUpdateRequest,
    ClaimsByPeriodResponse,
    CostOverheadResponse,
    CustomerClaimsSummaryResponse,
    ServiceQualityResponse,
    SupplierQualityResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = request.client.host if request.client else None
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


# ---------------------------------------------------------------------------
# 8.1  POST /api/claims — Create new claim
# Requirements: 1.1-1.8, 8.1-8.4
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ClaimResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new claim",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_claim_endpoint(
    payload: ClaimCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new claim linked to a customer and original transaction.

    Requirements: 1.1-1.8, 8.1-8.4
    """
    from app.modules.claims.service import create_claim

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_claim(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            claim_type=payload.claim_type,
            description=payload.description,
            invoice_id=payload.invoice_id,
            job_card_id=payload.job_card_id,
            line_item_ids=payload.line_item_ids,
            branch_id=payload.branch_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 8.2  GET /api/claims — List claims with filters
# Requirements: 6.1-6.5, 11.2, 11.3
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ClaimListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List claims with filters",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_claims_endpoint(
    request: Request,
    status: str | None = Query(default=None, description="Filter by claim status"),
    claim_type: str | None = Query(default=None, description="Filter by claim type"),
    customer_id: uuid.UUID | None = Query(default=None, description="Filter by customer"),
    branch_id: uuid.UUID | None = Query(default=None, description="Filter by branch"),
    date_from: date | None = Query(default=None, description="Filter from date"),
    date_to: date | None = Query(default=None, description="Filter to date"),
    search: str | None = Query(default=None, description="Search by customer name, invoice number, or description"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """List claims with pagination and filtering.

    Non-admin users are scoped to their branch context (Req 11.2).
    Org admins can view claims across all branches (Req 11.3).

    Requirements: 6.1-6.5, 11.2, 11.3
    """
    from app.modules.claims.service import list_claims

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Apply branch context for non-admin users (Req 11.2)
    role = getattr(request.state, "role", None)
    if branch_id is None and role != "org_admin":
        ctx_branch = getattr(request.state, "branch_id", None)
        if ctx_branch:
            try:
                branch_id = uuid.UUID(str(ctx_branch))
            except (ValueError, TypeError):
                pass

    result = await list_claims(
        db,
        org_id=org_uuid,
        status=status,
        claim_type=claim_type,
        customer_id=customer_id,
        branch_id=branch_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    return result


# ---------------------------------------------------------------------------
# 9.1  GET /api/claims/reports/by-period — Claims by period report
# Requirements: 10.1, 10.5, 10.6
# ---------------------------------------------------------------------------


@router.get(
    "/reports/by-period",
    response_model=ClaimsByPeriodResponse,
    summary="Claims by period report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def claims_by_period_report_endpoint(
    request: Request,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Return claim_count, total_cost, average_resolution_time grouped by period.

    Requirements: 10.1, 10.5, 10.6
    """
    from app.modules.claims.reports_service import get_claims_by_period_report

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    return await get_claims_by_period_report(
        db, org_id=org_uuid, date_from=date_from, date_to=date_to, branch_id=branch_id,
    )


# ---------------------------------------------------------------------------
# 9.2  GET /api/claims/reports/cost-overhead — Cost overhead report
# Requirements: 10.2, 10.5, 10.6
# ---------------------------------------------------------------------------


@router.get(
    "/reports/cost-overhead",
    response_model=CostOverheadResponse,
    summary="Cost overhead report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def cost_overhead_report_endpoint(
    request: Request,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Return total_refunds, total_credit_notes, total_write_offs, total_labour_cost.

    Requirements: 10.2, 10.5, 10.6
    """
    from app.modules.claims.reports_service import get_cost_overhead_report

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    return await get_cost_overhead_report(
        db, org_id=org_uuid, date_from=date_from, date_to=date_to, branch_id=branch_id,
    )


# ---------------------------------------------------------------------------
# 9.3  GET /api/claims/reports/supplier-quality — Supplier quality report
# Requirements: 10.3, 10.5, 10.6
# ---------------------------------------------------------------------------


@router.get(
    "/reports/supplier-quality",
    response_model=SupplierQualityResponse,
    summary="Supplier quality report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def supplier_quality_report_endpoint(
    request: Request,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Return parts with highest return rates.

    Requirements: 10.3, 10.5, 10.6
    """
    from app.modules.claims.reports_service import get_supplier_quality_report

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    return await get_supplier_quality_report(
        db, org_id=org_uuid, date_from=date_from, date_to=date_to, branch_id=branch_id,
    )


# ---------------------------------------------------------------------------
# 9.4  GET /api/claims/reports/service-quality — Service quality report
# Requirements: 10.4, 10.5, 10.6
# ---------------------------------------------------------------------------


@router.get(
    "/reports/service-quality",
    response_model=ServiceQualityResponse,
    summary="Service quality report",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def service_quality_report_endpoint(
    request: Request,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    branch_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Return technicians with most redo claims.

    Requirements: 10.4, 10.5, 10.6
    """
    from app.modules.claims.reports_service import get_service_quality_report

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    return await get_service_quality_report(
        db, org_id=org_uuid, date_from=date_from, date_to=date_to, branch_id=branch_id,
    )


# ---------------------------------------------------------------------------
# 8.3  GET /api/claims/{id} — Get claim details
# Requirements: 7.1-7.5
# ---------------------------------------------------------------------------


@router.get(
    "/{claim_id}",
    response_model=ClaimResponse,
    responses={
        400: {"description": "Claim not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get claim details",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_claim_endpoint(
    claim_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return full claim details with timeline and related entities.

    Requirements: 7.1-7.5
    """
    from app.modules.claims.service import get_claim

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_claim(db, org_id=org_uuid, claim_id=claim_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 8.4  PATCH /api/claims/{id}/status — Update claim status
# Requirements: 2.1-2.7
# ---------------------------------------------------------------------------


@router.patch(
    "/{claim_id}/status",
    response_model=ClaimResponse,
    responses={
        400: {"description": "Invalid status transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Update claim status",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_claim_status_endpoint(
    claim_id: uuid.UUID,
    payload: ClaimStatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Transition claim to a new status with workflow validation.

    Requirements: 2.1-2.7
    """
    from app.modules.claims.service import update_claim_status

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await update_claim_status(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            claim_id=claim_id,
            new_status=payload.new_status,
            notes=payload.notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 8.5  POST /api/claims/{id}/resolve — Apply resolution
# Requirements: 2.4, 2.5, 3.1-3.8
# ---------------------------------------------------------------------------


@router.post(
    "/{claim_id}/resolve",
    response_model=ClaimResponse,
    responses={
        400: {"description": "Resolution error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Apply resolution to a claim",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def resolve_claim_endpoint(
    claim_id: uuid.UUID,
    payload: ClaimResolveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Apply resolution and trigger downstream actions.

    Requirements: 2.4, 2.5, 3.1-3.8
    """
    from app.modules.claims.service import resolve_claim

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await resolve_claim(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            claim_id=claim_id,
            resolution_type=payload.resolution_type,
            resolution_amount=payload.resolution_amount,
            resolution_notes=payload.resolution_notes,
            return_stock_item_ids=payload.return_stock_item_ids,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 8.6  POST /api/claims/{id}/notes — Add internal note
# Requirements: 7.5
# ---------------------------------------------------------------------------


@router.post(
    "/{claim_id}/notes",
    response_model=ClaimResponse,
    status_code=201,
    responses={
        400: {"description": "Claim not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Add internal note to a claim",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def add_claim_note_endpoint(
    claim_id: uuid.UUID,
    payload: ClaimNoteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Add an internal note to a claim's timeline.

    Requirements: 7.5
    """
    from app.modules.claims.service import add_claim_note

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await add_claim_note(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            claim_id=claim_id,
            notes=payload.notes,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# 8.7  GET /api/customers/{id}/claims — Customer claims with summary
# Requirements: 9.1-9.3
# ---------------------------------------------------------------------------

customer_claims_router = APIRouter()


@customer_claims_router.get(
    "/{customer_id}/claims",
    response_model=CustomerClaimsSummaryResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get customer claims with summary",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_customer_claims_endpoint(
    customer_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all claims for a customer with summary statistics.

    Requirements: 9.1-9.3
    """
    from app.modules.claims.service import get_customer_claims_summary

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await get_customer_claims_summary(
        db,
        org_id=org_uuid,
        customer_id=customer_id,
    )
    return result
