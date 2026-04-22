"""Banking API router — Akahu connection, bank accounts, transactions, reconciliation.

Requirements: 15.1, 16.1, 17.1, 19.1–19.6
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.encryption import envelope_decrypt_str
from app.modules.auth.rbac import require_role
from app.modules.banking.akahu import (
    _mask_token,
    handle_callback as akahu_handle_callback,
    initiate_connection,
    sync_accounts as akahu_sync_accounts,
    sync_transactions as akahu_sync_transactions,
)
from app.modules.banking.models import AkahuConnection
from app.modules.banking.reconciliation import run_auto_matching
from app.modules.banking.schemas import (
    AkahuConnectionResponse,
    BankAccountLinkRequest,
    BankAccountListResponse,
    BankAccountResponse,
    BankTransactionListResponse,
    BankTransactionMatchRequest,
    BankTransactionResponse,
    ReconciliationSummaryResponse,
)
from app.modules.banking.service import (
    create_expense_from_transaction,
    exclude_transaction,
    get_reconciliation_summary,
    link_bank_account_to_gl,
    list_bank_accounts,
    list_transactions,
    manually_match_transaction,
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
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid auth context")
    if org_uuid is None or user_uuid is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authentication required")
    return org_uuid, user_uuid


# ---------------------------------------------------------------------------
# Akahu OAuth endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/connect",
    summary="Initiate Akahu OAuth connection",
    dependencies=[require_role("org_admin")],
)
async def connect_akahu(request: Request):
    """Redirect user to Akahu OAuth authorization page.

    Requirements: 15.1
    """
    org_id, user_id = _extract_org_context(request)
    redirect_uri = str(request.base_url).rstrip("/") + "/api/v1/banking/callback"
    state = str(org_id)
    auth_url = await initiate_connection(redirect_uri, state)
    return {"authorization_url": auth_url}


@router.get(
    "/callback",
    summary="Akahu OAuth callback",
)
async def akahu_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle Akahu OAuth callback — exchange code for tokens.

    Requirements: 15.1, 15.2
    """
    try:
        org_id = uuid.UUID(state)
    except (ValueError, TypeError):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    redirect_uri = str(request.base_url).rstrip("/") + "/api/v1/banking/callback"
    conn = await akahu_handle_callback(db, org_id, code, redirect_uri)

    # Build masked response
    from app.config import settings
    frontend_url = request.headers.get("origin") or settings.frontend_base_url
    return RedirectResponse(
        url=f"{frontend_url}/banking/accounts?connected=true",
        status_code=302,
    )


# ---------------------------------------------------------------------------
# Bank Account endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/accounts",
    response_model=BankAccountListResponse,
    summary="List connected bank accounts",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_accounts_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all connected bank accounts for the organisation.

    Requirements: 16.1, 19.1
    """
    org_id, _ = _extract_org_context(request)
    accounts, total = await list_bank_accounts(db, org_id)
    return BankAccountListResponse(
        items=[BankAccountResponse.model_validate(a) for a in accounts],
        total=total,
    )


@router.post(
    "/accounts/{account_id}/link",
    response_model=BankAccountResponse,
    summary="Link bank account to GL account",
    dependencies=[require_role("org_admin")],
)
async def link_account_endpoint(
    account_id: uuid.UUID,
    payload: BankAccountLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Link a bank account to a GL account for reconciliation posting.

    Requirements: 16.2, 19.2
    """
    org_id, _ = _extract_org_context(request)
    account = await link_bank_account_to_gl(
        db, org_id, account_id, payload.linked_gl_account_id
    )
    return BankAccountResponse.model_validate(account)


# ---------------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/sync",
    summary="Trigger manual bank sync",
    dependencies=[require_role("org_admin")],
)
async def sync_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
):
    """Trigger manual sync of bank accounts and transactions.

    Sync runs inline (not background) for immediate feedback.
    Requirements: 17.1, 17.5
    """
    org_id, _ = _extract_org_context(request)

    # Sync accounts first, then transactions
    accounts = await akahu_sync_accounts(db, org_id)
    transactions = await akahu_sync_transactions(db, org_id)

    # Run auto-matching after sync
    matched = await run_auto_matching(db, org_id)

    return {
        "accounts_synced": len(accounts),
        "transactions_synced": len(transactions),
        "auto_matched": len(matched),
    }


# ---------------------------------------------------------------------------
# Transaction endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/transactions",
    response_model=BankTransactionListResponse,
    summary="List bank transactions",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_transactions_endpoint(
    request: Request,
    bank_account_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    """List bank transactions with optional filters.

    Requirements: 19.1
    """
    org_id, _ = _extract_org_context(request)
    transactions, total = await list_transactions(
        db, org_id,
        bank_account_id=bank_account_id,
        status=status,
        from_date=from_date,
        to_date=to_date,
    )
    return BankTransactionListResponse(
        items=[BankTransactionResponse.model_validate(t) for t in transactions],
        total=total,
    )


@router.post(
    "/transactions/{transaction_id}/match",
    response_model=BankTransactionResponse,
    summary="Manually match transaction",
    dependencies=[require_role("org_admin")],
)
async def match_transaction_endpoint(
    transaction_id: uuid.UUID,
    payload: BankTransactionMatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Manually match a transaction to an invoice, expense, or journal entry.

    Requirements: 19.2
    """
    org_id, _ = _extract_org_context(request)
    txn = await manually_match_transaction(
        db, org_id, transaction_id,
        matched_invoice_id=payload.matched_invoice_id,
        matched_expense_id=payload.matched_expense_id,
        matched_journal_id=payload.matched_journal_id,
    )
    return BankTransactionResponse.model_validate(txn)


@router.post(
    "/transactions/{transaction_id}/exclude",
    response_model=BankTransactionResponse,
    summary="Exclude transaction from reconciliation",
    dependencies=[require_role("org_admin")],
)
async def exclude_transaction_endpoint(
    transaction_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Exclude a transaction from reconciliation.

    Requirements: 19.3
    """
    org_id, _ = _extract_org_context(request)
    txn = await exclude_transaction(db, org_id, transaction_id)
    return BankTransactionResponse.model_validate(txn)


@router.post(
    "/transactions/{transaction_id}/create-expense",
    response_model=BankTransactionResponse,
    summary="Create expense from transaction",
    dependencies=[require_role("org_admin")],
)
async def create_expense_endpoint(
    transaction_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create an expense from a bank transaction and link it.

    Requirements: 19.4
    """
    org_id, user_id = _extract_org_context(request)
    txn = await create_expense_from_transaction(db, org_id, user_id, transaction_id)
    return BankTransactionResponse.model_validate(txn)


# ---------------------------------------------------------------------------
# Reconciliation Summary
# ---------------------------------------------------------------------------


@router.get(
    "/reconciliation-summary",
    response_model=ReconciliationSummaryResponse,
    summary="Reconciliation summary",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def reconciliation_summary_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get match counts by status + last sync timestamp.

    Requirements: 19.5
    """
    org_id, _ = _extract_org_context(request)
    summary = await get_reconciliation_summary(db, org_id)
    return ReconciliationSummaryResponse(**summary)
