"""Service layer for the double-entry general ledger module.

Provides COA CRUD, COA seeding, journal entry engine (create + post),
and accounting period management.

All functions are async and use flush() + refresh() before returning
ORM objects (the get_db_session dependency auto-commits via session.begin()).

Requirements: 1.1, 1.5, 1.6, 2.1–2.5, 2.7, 3.1–3.3, 3.5
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.ledger.models import (
    Account,
    AccountingPeriod,
    JournalEntry,
    JournalLine,
)


# ---------------------------------------------------------------------------
# NZ COA seed data — 30 standard accounts
# ---------------------------------------------------------------------------

_NZ_COA_SEED: list[dict] = [
    {"code": "1000", "name": "Bank/Cash", "account_type": "asset", "sub_type": "current_asset", "tax_code": "NONE", "xero_account_code": "090", "is_system": True},
    {"code": "1100", "name": "Accounts Receivable", "account_type": "asset", "sub_type": "accounts_receivable", "tax_code": "NONE", "xero_account_code": "310", "is_system": True},
    {"code": "1200", "name": "GST Receivable", "account_type": "asset", "sub_type": "current_asset", "tax_code": "NONE", "xero_account_code": "820", "is_system": True},
    {"code": "1300", "name": "Prepaid Expenses", "account_type": "asset", "sub_type": "current_asset", "tax_code": "NONE", "xero_account_code": None, "is_system": False},
    {"code": "1400", "name": "Inventory", "account_type": "asset", "sub_type": "current_asset", "tax_code": "NONE", "xero_account_code": "630", "is_system": False},
    {"code": "1500", "name": "Equipment", "account_type": "asset", "sub_type": "fixed_asset", "tax_code": "NONE", "xero_account_code": "710", "is_system": False},
    {"code": "1600", "name": "Accumulated Depreciation", "account_type": "asset", "sub_type": "fixed_asset", "tax_code": "NONE", "xero_account_code": "720", "is_system": False},
    {"code": "2000", "name": "Accounts Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": "800", "is_system": True},
    {"code": "2100", "name": "GST Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": "820", "is_system": True},
    {"code": "2200", "name": "Income Tax Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": None, "is_system": True},
    {"code": "2300", "name": "Wages Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": None, "is_system": False},
    {"code": "2400", "name": "ACC Levy Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": None, "is_system": False},
    {"code": "2500", "name": "KiwiSaver Payable", "account_type": "liability", "sub_type": "current_liability", "tax_code": "NONE", "xero_account_code": None, "is_system": False},
    {"code": "3000", "name": "Owner's Equity", "account_type": "equity", "sub_type": "owners_equity", "tax_code": "NONE", "xero_account_code": None, "is_system": True},
    {"code": "3100", "name": "Retained Earnings", "account_type": "equity", "sub_type": "retained_earnings", "tax_code": "NONE", "xero_account_code": None, "is_system": True},
    {"code": "3200", "name": "Drawings", "account_type": "equity", "sub_type": "drawings", "tax_code": "NONE", "xero_account_code": None, "is_system": False},
    {"code": "4000", "name": "Sales Revenue", "account_type": "revenue", "sub_type": "operating_revenue", "tax_code": "GST", "xero_account_code": "200", "is_system": True},
    {"code": "4100", "name": "Other Revenue", "account_type": "revenue", "sub_type": "other_revenue", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "5000", "name": "Cost of Goods Sold", "account_type": "cogs", "sub_type": "direct_costs", "tax_code": "GST", "xero_account_code": "310", "is_system": True},
    {"code": "5100", "name": "Subcontractor Costs", "account_type": "cogs", "sub_type": "direct_costs", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6000", "name": "Advertising", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6100", "name": "Bank Fees", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "EXEMPT", "xero_account_code": None, "is_system": False},
    {"code": "6200", "name": "Insurance", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "EXEMPT", "xero_account_code": None, "is_system": False},
    {"code": "6300", "name": "Office Supplies", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6400", "name": "Rent", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6500", "name": "Repairs & Maintenance", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6600", "name": "Telephone & Internet", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6700", "name": "Travel", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6800", "name": "Utilities", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
    {"code": "6990", "name": "General Expenses", "account_type": "expense", "sub_type": "operating_expense", "tax_code": "GST", "xero_account_code": None, "is_system": False},
]


# ---------------------------------------------------------------------------
# COA Seeding
# ---------------------------------------------------------------------------


async def seed_coa_for_org(db: AsyncSession, org_id: uuid.UUID) -> list[Account]:
    """Insert the 30 default NZ accounts for a new organisation.

    Requirements: 1.1
    """
    accounts: list[Account] = []
    for seed in _NZ_COA_SEED:
        account = Account(
            org_id=org_id,
            code=seed["code"],
            name=seed["name"],
            account_type=seed["account_type"],
            sub_type=seed["sub_type"],
            tax_code=seed["tax_code"],
            xero_account_code=seed["xero_account_code"],
            is_system=seed["is_system"],
        )
        db.add(account)
        accounts.append(account)
    await db.flush()
    for account in accounts:
        await db.refresh(account)
    return accounts


# ---------------------------------------------------------------------------
# COA CRUD
# ---------------------------------------------------------------------------


async def list_accounts(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    account_type: str | None = None,
    is_active: bool | None = None,
) -> tuple[list[Account], int]:
    """Return accounts for an org, optionally filtered by type and active status.

    Requirements: 1.2
    """
    stmt = select(Account).where(Account.org_id == org_id)
    if account_type is not None:
        stmt = stmt.where(Account.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(Account.is_active == is_active)
    stmt = stmt.order_by(Account.code)

    result = await db.execute(stmt)
    accounts = list(result.scalars().all())
    return accounts, len(accounts)


async def create_account(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    code: str,
    name: str,
    account_type: str,
    sub_type: str | None = None,
    description: str | None = None,
    parent_id: uuid.UUID | None = None,
    tax_code: str | None = None,
    xero_account_code: str | None = None,
) -> Account:
    """Create a custom account in the COA.

    Requirements: 1.2, 1.3
    """
    account = Account(
        org_id=org_id,
        code=code,
        name=name,
        account_type=account_type,
        sub_type=sub_type,
        description=description,
        parent_id=parent_id,
        tax_code=tax_code,
        xero_account_code=xero_account_code,
        is_system=False,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def update_account(
    db: AsyncSession,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    name: str | None = None,
    sub_type: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    parent_id: uuid.UUID | None = None,
    tax_code: str | None = None,
    xero_account_code: str | None = None,
) -> Account:
    """Update a COA account's mutable fields.

    Requirements: 1.2
    """
    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.org_id == org_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if name is not None:
        account.name = name
    if sub_type is not None:
        account.sub_type = sub_type
    if description is not None:
        account.description = description
    if is_active is not None:
        account.is_active = is_active
    if parent_id is not None:
        account.parent_id = parent_id
    if tax_code is not None:
        account.tax_code = tax_code
    if xero_account_code is not None:
        account.xero_account_code = xero_account_code

    await db.flush()
    await db.refresh(account)
    return account


async def delete_account(
    db: AsyncSession,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    """Delete a COA account. Rejects system accounts and accounts with journal lines.

    Requirements: 1.5, 1.6
    """
    result = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.org_id == org_id,
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if account.is_system:
        raise HTTPException(
            status_code=400, detail="Cannot delete system account"
        )

    # Check for associated journal lines
    line_count_result = await db.execute(
        select(func.count(JournalLine.id)).where(
            JournalLine.account_id == account_id,
        )
    )
    line_count = line_count_result.scalar() or 0
    if line_count > 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete account with journal entries",
        )

    await db.delete(account)
    await db.flush()


# ---------------------------------------------------------------------------
# Gap-free entry_number sequence
# ---------------------------------------------------------------------------


async def _get_next_entry_number(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> str:
    """Assign the next gap-free journal entry number for an org.

    Uses a row-level advisory lock via SELECT ... FOR UPDATE on the
    journal_entries table to serialise concurrent requests.

    Requirements: 2.1
    """
    result = await db.execute(
        text(
            "SELECT entry_number FROM journal_entries "
            "WHERE org_id = :org_id "
            "ORDER BY created_at DESC LIMIT 1 FOR UPDATE"
        ),
        {"org_id": str(org_id)},
    )
    row = result.first()

    if row is None:
        next_number = 1
    else:
        # entry_number format is "JE-XXXX" — extract the numeric part
        try:
            current = int(row.entry_number.replace("JE-", ""))
        except (ValueError, AttributeError):
            current = 0
        next_number = current + 1

    return f"JE-{next_number:04d}"


# ---------------------------------------------------------------------------
# Journal Entry Engine
# ---------------------------------------------------------------------------


async def list_journal_entries(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    source_type: str | None = None,
) -> tuple[list[JournalEntry], int]:
    """Return journal entries for an org, optionally filtered by date range and source_type.

    Requirements: 2.1
    """
    stmt = (
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(JournalEntry.org_id == org_id)
    )
    if date_from is not None:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    if source_type is not None:
        stmt = stmt.where(JournalEntry.source_type == source_type)
    stmt = stmt.order_by(JournalEntry.created_at.desc())

    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return entries, len(entries)


async def get_journal_entry(
    db: AsyncSession,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> JournalEntry:
    """Return a single journal entry with its lines.

    Requirements: 2.1
    """
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(
            JournalEntry.id == entry_id,
            JournalEntry.org_id == org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return entry


async def create_journal_entry(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    entry_date: date,
    description: str,
    reference: str | None = None,
    source_type: str = "manual",
    source_id: uuid.UUID | None = None,
    period_id: uuid.UUID | None = None,
    lines: list[dict] | None = None,
) -> JournalEntry:
    """Create a new journal entry with lines (draft, not yet posted).

    Each line dict must have: account_id, debit, credit, and optionally description.

    Requirements: 2.1, 2.2
    """
    entry_number = await _get_next_entry_number(db, org_id)

    entry = JournalEntry(
        org_id=org_id,
        entry_number=entry_number,
        entry_date=entry_date,
        description=description,
        reference=reference,
        source_type=source_type,
        source_id=source_id,
        period_id=period_id,
        is_posted=False,
        created_by=user_id,
    )
    db.add(entry)
    await db.flush()

    if lines:
        for line_data in lines:
            line = JournalLine(
                journal_entry_id=entry.id,
                org_id=org_id,
                account_id=line_data["account_id"],
                debit=Decimal(str(line_data.get("debit", 0))),
                credit=Decimal(str(line_data.get("credit", 0))),
                description=line_data.get("description"),
            )
            db.add(line)
        await db.flush()

    await db.refresh(entry, attribute_names=["lines"])
    return entry


async def post_journal_entry(
    db: AsyncSession,
    org_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> JournalEntry:
    """Post a draft journal entry after validating balance and period.

    Validates:
    - Sum of debits == sum of credits across all lines
    - Period (if set) is not closed

    Requirements: 2.3, 2.4, 2.5
    """
    result = await db.execute(
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .where(
            JournalEntry.id == entry_id,
            JournalEntry.org_id == org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")

    if entry.is_posted:
        raise HTTPException(
            status_code=400, detail="Journal entry is already posted"
        )

    # Validate balance: debits must equal credits
    total_debits = sum(line.debit for line in entry.lines)
    total_credits = sum(line.credit for line in entry.lines)

    if total_debits != total_credits:
        imbalance = abs(total_debits - total_credits)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Journal entry does not balance. "
                f"Debits: {total_debits}, Credits: {total_credits}, "
                f"Imbalance: {imbalance}"
            ),
        )

    # Validate period is not closed
    if entry.period_id is not None:
        period_result = await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.id == entry.period_id,
            )
        )
        period = period_result.scalar_one_or_none()
        if period is not None and period.is_closed:
            raise HTTPException(
                status_code=400,
                detail="Cannot post to a closed accounting period",
            )

    entry.is_posted = True
    await db.flush()
    await db.refresh(entry, attribute_names=["lines"])
    return entry


# ---------------------------------------------------------------------------
# Period Management
# ---------------------------------------------------------------------------


async def list_periods(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> tuple[list[AccountingPeriod], int]:
    """Return all accounting periods for an org, ordered by start_date.

    Requirements: 3.1
    """
    result = await db.execute(
        select(AccountingPeriod)
        .where(AccountingPeriod.org_id == org_id)
        .order_by(AccountingPeriod.start_date)
    )
    periods = list(result.scalars().all())
    return periods, len(periods)


async def create_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    period_name: str,
    start_date: date,
    end_date: date,
) -> AccountingPeriod:
    """Create a new accounting period.

    Requirements: 3.1, 3.5
    """
    period = AccountingPeriod(
        org_id=org_id,
        period_name=period_name,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(period)
    await db.flush()
    await db.refresh(period)
    return period


async def close_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> AccountingPeriod:
    """Close an accounting period, recording who closed it and when.

    Requirements: 3.2, 3.3
    """
    result = await db.execute(
        select(AccountingPeriod).where(
            AccountingPeriod.id == period_id,
            AccountingPeriod.org_id == org_id,
        )
    )
    period = result.scalar_one_or_none()
    if period is None:
        raise HTTPException(
            status_code=404, detail="Accounting period not found"
        )

    if period.is_closed:
        raise HTTPException(
            status_code=400, detail="Accounting period is already closed"
        )

    period.is_closed = True
    period.closed_by = user_id
    period.closed_at = datetime.utcnow()

    await db.flush()
    await db.refresh(period)
    return period


# ---------------------------------------------------------------------------
# GST Filing Periods
# ---------------------------------------------------------------------------

from app.modules.ledger.models import GstFilingPeriod


# Valid GST status transitions
_GST_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["ready"],
    "ready": ["filed"],
    "filed": ["accepted", "rejected"],
}


def _validate_gst_status_transition(current: str, target: str) -> None:
    """Raise if the status transition is not allowed."""
    allowed = _GST_STATUS_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition: {current} → {target}. "
            f"Allowed transitions from '{current}': {allowed}",
        )


async def generate_gst_periods(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_type: str,
    tax_year: int,
) -> list[GstFilingPeriod]:
    """Generate GST filing periods for a NZ tax year (Apr–Mar).

    Period types:
    - two_monthly: 6 periods (Jan-Feb, Mar-Apr, May-Jun, Jul-Aug, Sep-Oct, Nov-Dec)
    - six_monthly: 2 periods (Apr-Sep, Oct-Mar)
    - annual: 1 period (Apr-Mar)

    Due date: 28th of the month following period_end.

    Requirements: 11.1, 11.2
    """
    if period_type not in ("two_monthly", "six_monthly", "annual"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period_type: {period_type}. Must be two_monthly, six_monthly, or annual.",
        )

    # NZ tax year runs Apr of (tax_year-1) to Mar of tax_year
    year_start = tax_year - 1  # e.g. tax_year=2026 → starts Apr 2025

    periods: list[GstFilingPeriod] = []

    if period_type == "two_monthly":
        # Two-monthly periods aligned to calendar: Jan-Feb, Mar-Apr, May-Jun, Jul-Aug, Sep-Oct, Nov-Dec
        # Within a tax year (Apr–Mar), the periods are:
        # May-Jun, Jul-Aug, Sep-Oct, Nov-Dec of year_start, then Jan-Feb, Mar-Apr of tax_year
        two_month_ranges = [
            (date(year_start, 5, 1), date(year_start, 6, 30)),
            (date(year_start, 7, 1), date(year_start, 8, 31)),
            (date(year_start, 9, 1), date(year_start, 10, 31)),
            (date(year_start, 11, 1), date(year_start, 12, 31)),
            (date(tax_year, 1, 1), date(tax_year, 2, 28 if tax_year % 4 != 0 or (tax_year % 100 == 0 and tax_year % 400 != 0) else 29)),
            (date(tax_year, 3, 1), date(tax_year, 4, 30)),
        ]
        for start, end in two_month_ranges:
            # Due date: 28th of month following period_end
            due_month = end.month + 1
            due_year = end.year
            if due_month > 12:
                due_month = 1
                due_year += 1
            due = date(due_year, due_month, 28)
            period = GstFilingPeriod(
                org_id=org_id,
                period_type=period_type,
                period_start=start,
                period_end=end,
                due_date=due,
            )
            db.add(period)
            periods.append(period)

    elif period_type == "six_monthly":
        # Apr-Sep, Oct-Mar
        ranges = [
            (date(year_start, 4, 1), date(year_start, 9, 30)),
            (date(year_start, 10, 1), date(tax_year, 3, 31)),
        ]
        for start, end in ranges:
            due_month = end.month + 1
            due_year = end.year
            if due_month > 12:
                due_month = 1
                due_year += 1
            due = date(due_year, due_month, 28)
            period = GstFilingPeriod(
                org_id=org_id,
                period_type=period_type,
                period_start=start,
                period_end=end,
                due_date=due,
            )
            db.add(period)
            periods.append(period)

    elif period_type == "annual":
        start = date(year_start, 4, 1)
        end = date(tax_year, 3, 31)
        due_month = end.month + 1
        due_year = end.year
        if due_month > 12:
            due_month = 1
            due_year += 1
        due = date(due_year, due_month, 28)
        period = GstFilingPeriod(
            org_id=org_id,
            period_type=period_type,
            period_start=start,
            period_end=end,
            due_date=due,
        )
        db.add(period)
        periods.append(period)

    await db.flush()
    for p in periods:
        await db.refresh(p)
    return periods


async def list_gst_periods(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> tuple[list[GstFilingPeriod], int]:
    """Return all GST filing periods for an org, ordered by period_start.

    Requirements: 11.1
    """
    result = await db.execute(
        select(GstFilingPeriod)
        .where(GstFilingPeriod.org_id == org_id)
        .order_by(GstFilingPeriod.period_start)
    )
    periods = list(result.scalars().all())
    return periods, len(periods)


async def get_gst_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
) -> GstFilingPeriod:
    """Return a single GST filing period.

    Requirements: 11.1
    """
    result = await db.execute(
        select(GstFilingPeriod).where(
            GstFilingPeriod.id == period_id,
            GstFilingPeriod.org_id == org_id,
        )
    )
    period = result.scalar_one_or_none()
    if period is None:
        raise HTTPException(status_code=404, detail="GST filing period not found")
    return period


async def mark_period_ready(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
) -> GstFilingPeriod:
    """Transition a GST filing period from draft → ready.

    Requirements: 11.4
    """
    period = await get_gst_period(db, org_id, period_id)
    _validate_gst_status_transition(period.status, "ready")
    period.status = "ready"
    await db.flush()
    await db.refresh(period)
    return period


async def lock_gst_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
) -> GstFilingPeriod:
    """Lock invoices and expenses within a GST filing period's date range.

    Sets is_gst_locked = true on all invoices and expenses whose dates
    fall within the period's start/end range.

    Requirements: 14.1
    """
    period = await get_gst_period(db, org_id, period_id)

    # Lock invoices in the period date range
    await db.execute(
        text(
            "UPDATE invoices SET is_gst_locked = true "
            "WHERE org_id = :org_id "
            "AND issue_date >= :start AND issue_date <= :end"
        ),
        {
            "org_id": str(org_id),
            "start": period.period_start,
            "end": period.period_end,
        },
    )

    # Lock expenses in the period date range
    await db.execute(
        text(
            "UPDATE expenses SET is_gst_locked = true "
            "WHERE org_id = :org_id "
            "AND date >= :start AND date <= :end"
        ),
        {
            "org_id": str(org_id),
            "start": period.period_start,
            "end": period.period_end,
        },
    )

    await db.flush()
    await db.refresh(period)
    return period


# ---------------------------------------------------------------------------
# IRD Mod-11 Validation
# ---------------------------------------------------------------------------


def validate_ird_number(ird: str) -> bool:
    """Validate NZ IRD number using mod-11 check digit algorithm.

    Handles both 8 and 9 digit IRD numbers (strips hyphens/spaces, pads to 9).
    Weights: [3, 2, 7, 6, 5, 4, 3, 2]
    - remainder 0 → check digit must be 0
    - remainder 1 → invalid
    - remainder > 1 → check digit = 11 - remainder

    Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
    """
    digits = [int(d) for d in ird.replace("-", "").replace(" ", "").strip() if d.isdigit()]
    if len(digits) not in (8, 9):
        return False
    # Pad to 9 digits
    if len(digits) == 8:
        digits = [0] + digits

    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    weighted_sum = sum(d * w for d, w in zip(digits[:8], weights))
    remainder = weighted_sum % 11

    if remainder == 0:
        return digits[8] == 0
    if remainder == 1:
        return False
    check_digit = 11 - remainder
    return digits[8] == check_digit
