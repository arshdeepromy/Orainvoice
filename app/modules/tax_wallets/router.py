"""Tax Wallets API router — wallet balances, transactions, deposit, withdraw, summary.

Requirements: 22.1, 22.2, 22.3, 22.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.tax_wallets.schemas import (
    TaxWalletListResponse,
    TaxWalletResponse,
    TaxWalletSummaryResponse,
    WalletDepositRequest,
    WalletTransactionListResponse,
    WalletTransactionResponse,
    WalletWithdrawRequest,
)
from app.modules.tax_wallets.service import (
    get_wallet_summary,
    get_wallet_transactions,
    list_wallets,
    manual_deposit,
    manual_withdrawal,
)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Extract org_id and user_id from request state."""
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid auth context")
    if org_uuid is None or user_uuid is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return org_uuid, user_uuid


@router.get(
    "",
    response_model=TaxWalletListResponse,
    summary="List all tax wallets with balances",
)
async def list_wallets_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all wallets (gst, income_tax, provisional_tax) with current balances."""
    org_id, _ = _extract_org_context(request)
    wallets = await list_wallets(db, org_id)
    return {"items": wallets, "total": len(wallets)}


@router.get(
    "/summary",
    summary="Wallet summary with traffic lights",
)
async def summary_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Balances, due dates, shortfall, and traffic light indicators."""
    org_id, _ = _extract_org_context(request)
    return await get_wallet_summary(db, org_id)


@router.get(
    "/{wallet_type}/transactions",
    response_model=WalletTransactionListResponse,
    summary="Transaction history per wallet",
)
async def transactions_endpoint(
    wallet_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get transaction history for a specific wallet type."""
    if wallet_type not in ("gst", "income_tax", "provisional_tax"):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WALLET_NOT_FOUND",
                "message": f"No {wallet_type} wallet found for this organisation",
            },
        )
    org_id, _ = _extract_org_context(request)
    txns = await get_wallet_transactions(db, org_id, wallet_type)
    return {"items": txns, "total": len(txns)}


@router.post(
    "/{wallet_type}/deposit",
    response_model=WalletTransactionResponse,
    summary="Manual deposit into wallet",
)
async def deposit_endpoint(
    wallet_type: str,
    body: WalletDepositRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Make a manual deposit into a tax wallet."""
    if wallet_type not in ("gst", "income_tax", "provisional_tax"):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WALLET_NOT_FOUND",
                "message": f"No {wallet_type} wallet found for this organisation",
            },
        )
    org_id, user_id = _extract_org_context(request)
    txn = await manual_deposit(
        db, org_id, wallet_type, body.amount, body.description, user_id
    )
    return txn


@router.post(
    "/{wallet_type}/withdraw",
    response_model=WalletTransactionResponse,
    summary="Manual withdrawal from wallet",
)
async def withdraw_endpoint(
    wallet_type: str,
    body: WalletWithdrawRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Make a manual withdrawal from a tax wallet. Rejected if amount > balance."""
    if wallet_type not in ("gst", "income_tax", "provisional_tax"):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WALLET_NOT_FOUND",
                "message": f"No {wallet_type} wallet found for this organisation",
            },
        )
    org_id, user_id = _extract_org_context(request)
    txn = await manual_withdrawal(
        db, org_id, wallet_type, body.amount, body.description, user_id
    )
    return txn
