"""Multi-currency API router.

Endpoints:
- GET    /api/v2/currencies              — list enabled currencies
- POST   /api/v2/currencies/enable       — enable currency
- GET    /api/v2/exchange-rates          — get exchange rates
- POST   /api/v2/exchange-rates          — set manual rate
- POST   /api/v2/exchange-rates/refresh  — fetch latest rates from provider

**Validates: Requirement — MultiCurrency Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.multi_currency.schemas import (
    EnableCurrencyRequest,
    ExchangeRateCreate,
    ExchangeRateResponse,
    OrgCurrencyResponse,
)
from app.modules.multi_currency.service import CurrencyService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ------------------------------------------------------------------
# Currency management
# ------------------------------------------------------------------

@router.get(
    "",
    response_model=list[OrgCurrencyResponse],
    summary="List enabled currencies",
)
async def list_currencies(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = CurrencyService(db)
    currencies = await svc.list_enabled_currencies(org_id)
    return [OrgCurrencyResponse.model_validate(c) for c in currencies]


@router.post(
    "/enable",
    response_model=OrgCurrencyResponse,
    status_code=201,
    summary="Enable a currency for the organisation",
)
async def enable_currency(
    payload: EnableCurrencyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = CurrencyService(db)
    currency = await svc.enable_currency(org_id, payload)
    return OrgCurrencyResponse.model_validate(currency)


# ------------------------------------------------------------------
# Exchange rates
# ------------------------------------------------------------------

@router.get(
    "/rates",
    response_model=list[ExchangeRateResponse],
    summary="List exchange rates",
)
async def list_exchange_rates(
    request: Request,
    base_currency: str | None = Query(default=None),
    target_currency: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)  # auth check
    svc = CurrencyService(db)
    rates = await svc.list_exchange_rates(base_currency, target_currency)
    return [ExchangeRateResponse.model_validate(r) for r in rates]


@router.post(
    "/rates",
    response_model=ExchangeRateResponse,
    status_code=201,
    summary="Set a manual exchange rate",
)
async def set_manual_rate(
    payload: ExchangeRateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)  # auth check
    svc = CurrencyService(db)
    rate = await svc.set_exchange_rate(payload, source="manual")
    return ExchangeRateResponse.model_validate(rate)


@router.post(
    "/rates/refresh",
    response_model=list[ExchangeRateResponse],
    summary="Refresh exchange rates from provider",
)
async def refresh_rates(
    request: Request,
    base_currency: str = Query(..., min_length=3, max_length=3),
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)  # auth check
    svc = CurrencyService(db)
    try:
        rates = await svc.refresh_rates_from_provider(base_currency)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return [ExchangeRateResponse.model_validate(r) for r in rates]
