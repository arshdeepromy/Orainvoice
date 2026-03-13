"""Loyalty and memberships API router.

Endpoints:
- GET    /api/v2/loyalty/config                 — get loyalty config
- PUT    /api/v2/loyalty/config                 — update loyalty config
- GET    /api/v2/loyalty/tiers                  — list tiers
- POST   /api/v2/loyalty/tiers                  — create tier
- GET    /api/v2/loyalty/customers/{id}/balance — customer loyalty balance
- POST   /api/v2/loyalty/redeem                 — redeem points

**Validates: Requirement 38 — Loyalty Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.loyalty.schemas import (
    CustomerBalanceResponse,
    LoyaltyAnalyticsResponse,
    LoyaltyConfigResponse,
    LoyaltyConfigUpdate,
    LoyaltyTierCreate,
    LoyaltyTierResponse,
    LoyaltyTransactionResponse,
    PointsAdjustmentRequest,
    RedeemPointsRequest,
)
from app.modules.loyalty.service import LoyaltyService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

@router.get("/config", response_model=LoyaltyConfigResponse, summary="Get loyalty config")
async def get_config(request: Request, db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    config = await svc.get_config(org_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Loyalty not configured")
    return LoyaltyConfigResponse.model_validate(config)


@router.put("/config", response_model=LoyaltyConfigResponse, summary="Update loyalty config")
async def update_config(
    payload: LoyaltyConfigUpdate, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    config = await svc.configure(
        org_id, earn_rate=payload.earn_rate,
        redemption_rate=payload.redemption_rate, is_active=payload.is_active,
    )
    await db.commit()
    await db.refresh(config)
    return LoyaltyConfigResponse.model_validate(config)


# ------------------------------------------------------------------
# Tiers
# ------------------------------------------------------------------

@router.get("/tiers", response_model=list[LoyaltyTierResponse], summary="List loyalty tiers")
async def list_tiers(request: Request, db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    tiers = await svc.list_tiers(org_id)
    return [LoyaltyTierResponse.model_validate(t) for t in tiers]


@router.post("/tiers", response_model=LoyaltyTierResponse, status_code=201, summary="Create tier")
async def create_tier(
    payload: LoyaltyTierCreate, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    tier = await svc.create_tier(
        org_id, name=payload.name, threshold_points=payload.threshold_points,
        discount_percent=payload.discount_percent, benefits=payload.benefits,
        display_order=payload.display_order,
    )
    await db.commit()
    await db.refresh(tier)
    return LoyaltyTierResponse.model_validate(tier)


# ------------------------------------------------------------------
# Customer balance
# ------------------------------------------------------------------

@router.get(
    "/customers/{customer_id}/balance",
    response_model=CustomerBalanceResponse,
    summary="Get customer loyalty balance",
)
async def get_customer_balance(
    customer_id: UUID, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    balance = await svc.get_customer_balance(org_id, customer_id)
    transactions = await svc.get_customer_transactions(org_id, customer_id)
    current_tier = await svc.check_tier_upgrade(org_id, customer_id)
    next_tier = await svc.get_next_tier(org_id, balance)
    points_to_next = (next_tier.threshold_points - balance) if next_tier else None

    return CustomerBalanceResponse(
        customer_id=customer_id,
        total_points=balance,
        current_tier=LoyaltyTierResponse.model_validate(current_tier) if current_tier else None,
        next_tier=LoyaltyTierResponse.model_validate(next_tier) if next_tier else None,
        points_to_next_tier=points_to_next,
        transactions=[LoyaltyTransactionResponse.model_validate(t) for t in transactions],
    )


# ------------------------------------------------------------------
# Redeem
# ------------------------------------------------------------------

@router.post("/redeem", response_model=LoyaltyTransactionResponse, summary="Redeem points")
async def redeem_points(
    payload: RedeemPointsRequest, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    try:
        txn = await svc.redeem_points(
            org_id, payload.customer_id, payload.points,
            reference_type=payload.reference_type, reference_id=payload.reference_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    await db.refresh(txn)
    return LoyaltyTransactionResponse.model_validate(txn)


# ------------------------------------------------------------------
# Analytics
# ------------------------------------------------------------------

@router.get("/analytics", response_model=LoyaltyAnalyticsResponse, summary="Get loyalty analytics")
async def get_analytics(request: Request, db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    analytics = await svc.get_analytics(org_id)
    return analytics


# ------------------------------------------------------------------
# Manual points adjustment
# ------------------------------------------------------------------

@router.post(
    "/customers/{customer_id}/adjust",
    response_model=LoyaltyTransactionResponse,
    summary="Manual points adjustment",
)
async def adjust_points(
    customer_id: UUID,
    payload: PointsAdjustmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = LoyaltyService(db)
    try:
        txn = await svc._record_transaction(
            org_id=org_id,
            customer_id=customer_id,
            transaction_type="manual_add" if payload.points > 0 else "manual_deduct",
            points=payload.points,
            reference_type="manual_adjustment",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    await db.refresh(txn)
    return LoyaltyTransactionResponse.model_validate(txn)
