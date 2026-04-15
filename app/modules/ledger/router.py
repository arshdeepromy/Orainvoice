"""Ledger API router — COA, journal entries, and accounting periods.

Requirements: 1.1–1.7, 2.1–2.7, 3.1–3.5
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.ledger.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    AccountUpdate,
    AccountingPeriodCreate,
    AccountingPeriodListResponse,
    AccountingPeriodResponse,
    JournalEntryCreate,
    JournalEntryListResponse,
    JournalEntryResponse,
)
from app.modules.ledger.service import (
    close_period,
    create_account,
    create_journal_entry,
    create_period,
    delete_account,
    get_journal_entry,
    list_accounts,
    list_journal_entries,
    list_periods,
    post_journal_entry,
    update_account,
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
# Chart of Accounts endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/accounts",
    response_model=AccountListResponse,
    summary="List chart of accounts",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_accounts_endpoint(
    request: Request,
    account_type: str | None = Query(None, description="Filter by account type"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(get_db_session),
):
    """List COA accounts for the current organisation, filterable by type and active status."""
    org_id, _ = _extract_org_context(request)
    accounts, total = await list_accounts(
        db, org_id, account_type=account_type, is_active=is_active
    )
    return AccountListResponse(
        items=[AccountResponse.model_validate(a) for a in accounts],
        total=total,
    )


@router.post(
    "/accounts",
    response_model=AccountResponse,
    status_code=201,
    summary="Create a custom account",
    dependencies=[require_role("org_admin")],
)
async def create_account_endpoint(
    payload: AccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new custom account in the chart of accounts."""
    org_id, _ = _extract_org_context(request)
    account = await create_account(
        db,
        org_id,
        code=payload.code,
        name=payload.name,
        account_type=payload.account_type,
        sub_type=payload.sub_type,
        description=payload.description,
        parent_id=payload.parent_id,
        tax_code=payload.tax_code,
        xero_account_code=payload.xero_account_code,
    )
    return AccountResponse.model_validate(account)


@router.put(
    "/accounts/{account_id}",
    response_model=AccountResponse,
    summary="Update an account",
    dependencies=[require_role("org_admin")],
)
async def update_account_endpoint(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a COA account's mutable fields."""
    org_id, _ = _extract_org_context(request)
    account = await update_account(
        db,
        org_id,
        account_id,
        name=payload.name,
        sub_type=payload.sub_type,
        description=payload.description,
        is_active=payload.is_active,
        parent_id=payload.parent_id,
        tax_code=payload.tax_code,
        xero_account_code=payload.xero_account_code,
    )
    return AccountResponse.model_validate(account)


@router.delete(
    "/accounts/{account_id}",
    status_code=204,
    summary="Delete an account",
    dependencies=[require_role("org_admin")],
)
async def delete_account_endpoint(
    account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a COA account. Rejects system accounts and accounts with journal lines."""
    org_id, _ = _extract_org_context(request)
    await delete_account(db, org_id, account_id)


# ---------------------------------------------------------------------------
# Journal Entry endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/journal-entries",
    response_model=JournalEntryListResponse,
    summary="List journal entries",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_journal_entries_endpoint(
    request: Request,
    date_from: date | None = Query(None, description="Filter from date"),
    date_to: date | None = Query(None, description="Filter to date"),
    source_type: str | None = Query(None, description="Filter by source type"),
    db: AsyncSession = Depends(get_db_session),
):
    """List journal entries for the current organisation, filterable by date range and source type."""
    org_id, _ = _extract_org_context(request)
    entries, total = await list_journal_entries(
        db, org_id, date_from=date_from, date_to=date_to, source_type=source_type
    )
    return JournalEntryListResponse(
        items=[JournalEntryResponse.model_validate(e) for e in entries],
        total=total,
    )


@router.post(
    "/journal-entries",
    response_model=JournalEntryResponse,
    status_code=201,
    summary="Create a manual journal entry",
    dependencies=[require_role("org_admin")],
)
async def create_journal_entry_endpoint(
    payload: JournalEntryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new manual journal entry (draft, not yet posted)."""
    org_id, user_id = _extract_org_context(request)
    lines = [line.model_dump() for line in payload.lines]
    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=payload.entry_date,
        description=payload.description,
        reference=payload.reference,
        source_type=payload.source_type,
        lines=lines,
    )
    return JournalEntryResponse.model_validate(entry)


@router.get(
    "/journal-entries/{entry_id}",
    response_model=JournalEntryResponse,
    summary="Get a journal entry with lines",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_journal_entry_endpoint(
    entry_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get a single journal entry with all its lines."""
    org_id, _ = _extract_org_context(request)
    entry = await get_journal_entry(db, org_id, entry_id)
    return JournalEntryResponse.model_validate(entry)


@router.post(
    "/journal-entries/{entry_id}/post",
    response_model=JournalEntryResponse,
    summary="Post a draft journal entry",
    dependencies=[require_role("org_admin")],
)
async def post_journal_entry_endpoint(
    entry_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Post a draft journal entry. Validates balance and period status."""
    org_id, _ = _extract_org_context(request)
    entry = await post_journal_entry(db, org_id, entry_id)
    return JournalEntryResponse.model_validate(entry)


# ---------------------------------------------------------------------------
# Accounting Period endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/periods",
    response_model=AccountingPeriodListResponse,
    summary="List accounting periods",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_periods_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all accounting periods for the current organisation."""
    org_id, _ = _extract_org_context(request)
    periods, total = await list_periods(db, org_id)
    return AccountingPeriodListResponse(
        items=[AccountingPeriodResponse.model_validate(p) for p in periods],
        total=total,
    )


@router.post(
    "/periods",
    response_model=AccountingPeriodResponse,
    status_code=201,
    summary="Create an accounting period",
    dependencies=[require_role("org_admin")],
)
async def create_period_endpoint(
    payload: AccountingPeriodCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new accounting period."""
    org_id, _ = _extract_org_context(request)
    period = await create_period(
        db,
        org_id,
        period_name=payload.period_name,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return AccountingPeriodResponse.model_validate(period)


@router.post(
    "/periods/{period_id}/close",
    response_model=AccountingPeriodResponse,
    summary="Close an accounting period",
    dependencies=[require_role("org_admin")],
)
async def close_period_endpoint(
    period_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Close an accounting period. Records who closed it and when."""
    org_id, user_id = _extract_org_context(request)
    period = await close_period(db, org_id, period_id, user_id=user_id)
    return AccountingPeriodResponse.model_validate(period)
