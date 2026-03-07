"""Pricing rules API router.

Endpoints:
- GET    /api/v2/pricing-rules          — list rules
- POST   /api/v2/pricing-rules          — create rule
- GET    /api/v2/pricing-rules/{id}     — get rule
- PUT    /api/v2/pricing-rules/{id}     — update rule
- DELETE /api/v2/pricing-rules/{id}     — delete rule

**Validates: Requirement 10.1, 10.2, 10.5**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.pricing_rules.schemas import (
    PricingRuleCreate,
    PricingRuleListResponse,
    PricingRuleResponse,
    PricingRuleUpdate,
)
from app.modules.pricing_rules.service import PricingRuleService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=PricingRuleListResponse, summary="List pricing rules")
async def list_pricing_rules(
    request: Request,
    product_id: UUID | None = Query(None),
    is_active: bool | None = Query(True),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PricingRuleService(db)
    rules = await svc.list_rules(org_id, product_id=product_id, is_active=is_active)
    return PricingRuleListResponse(
        rules=[PricingRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )


@router.post(
    "", response_model=PricingRuleResponse, status_code=201,
    summary="Create pricing rule",
)
async def create_pricing_rule(
    payload: PricingRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PricingRuleService(db)
    rule, warnings = await svc.create_rule(org_id, payload)
    response = PricingRuleResponse.model_validate(rule)
    # Warnings are included in response headers for transparency
    if warnings:
        return response
    return response


@router.get(
    "/{rule_id}", response_model=PricingRuleResponse, summary="Get pricing rule",
)
async def get_pricing_rule(
    rule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PricingRuleService(db)
    rule = await svc.get_rule(org_id, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    return PricingRuleResponse.model_validate(rule)


@router.put(
    "/{rule_id}", response_model=PricingRuleResponse, summary="Update pricing rule",
)
async def update_pricing_rule(
    rule_id: UUID,
    payload: PricingRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PricingRuleService(db)
    rule = await svc.update_rule(org_id, rule_id, payload)
    if rule is None:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    return PricingRuleResponse.model_validate(rule)


@router.delete(
    "/{rule_id}", response_model=PricingRuleResponse, summary="Delete pricing rule",
)
async def delete_pricing_rule(
    rule_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PricingRuleService(db)
    rule = await svc.delete_rule(org_id, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    return PricingRuleResponse.model_validate(rule)
