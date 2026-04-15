"""Banking service — CRUD operations for bank accounts, transactions, and reconciliation.

Requirements: 19.1–19.6, 37.1
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.banking.models import AkahuConnection, BankAccount, BankTransaction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bank Accounts
# ---------------------------------------------------------------------------


async def list_bank_accounts(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> tuple[list[BankAccount], int]:
    """List all bank accounts for the organisation.

    Requirements: 16.1, 19.1
    """
    stmt = select(BankAccount).where(BankAccount.org_id == org_id)
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    count_stmt = select(func.count()).select_from(BankAccount).where(
        BankAccount.org_id == org_id
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return accounts, total


async def link_bank_account_to_gl(
    db: AsyncSession,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID,
    linked_gl_account_id: uuid.UUID,
) -> BankAccount:
    """Link a bank account to a GL account for reconciliation posting.

    Requirements: 16.2, 19.2
    """
    stmt = select(BankAccount).where(
        BankAccount.id == bank_account_id,
        BankAccount.org_id == org_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Bank account not found")

    # Verify GL account exists
    from app.modules.ledger.models import Account
    gl_stmt = select(Account).where(
        Account.id == linked_gl_account_id,
        Account.org_id == org_id,
    )
    gl_result = await db.execute(gl_stmt)
    gl_account = gl_result.scalar_one_or_none()
    if not gl_account:
        raise HTTPException(status_code=404, detail="GL account not found")

    account.linked_gl_account_id = linked_gl_account_id
    await db.flush()
    await db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Bank Transactions
# ---------------------------------------------------------------------------


async def list_transactions(
    db: AsyncSession,
    org_id: uuid.UUID,
    bank_account_id: uuid.UUID | None = None,
    status: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[BankTransaction], int]:
    """List bank transactions with optional filters.

    Requirements: 19.1
    """
    stmt = select(BankTransaction).where(BankTransaction.org_id == org_id)

    if bank_account_id:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if status:
        stmt = stmt.where(BankTransaction.reconciliation_status == status)
    if from_date:
        stmt = stmt.where(BankTransaction.date >= from_date)
    if to_date:
        stmt = stmt.where(BankTransaction.date <= to_date)

    stmt = stmt.order_by(BankTransaction.date.desc())
    result = await db.execute(stmt)
    transactions = list(result.scalars().all())

    # Count query
    count_stmt = select(func.count()).select_from(BankTransaction).where(
        BankTransaction.org_id == org_id
    )
    if bank_account_id:
        count_stmt = count_stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if status:
        count_stmt = count_stmt.where(BankTransaction.reconciliation_status == status)
    if from_date:
        count_stmt = count_stmt.where(BankTransaction.date >= from_date)
    if to_date:
        count_stmt = count_stmt.where(BankTransaction.date <= to_date)

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    return transactions, total


async def manually_match_transaction(
    db: AsyncSession,
    org_id: uuid.UUID,
    transaction_id: uuid.UUID,
    matched_invoice_id: uuid.UUID | None = None,
    matched_expense_id: uuid.UUID | None = None,
    matched_journal_id: uuid.UUID | None = None,
) -> BankTransaction:
    """Manually match a transaction to an invoice, expense, or journal entry.

    Requirements: 19.2, 18.5
    """
    stmt = select(BankTransaction).where(
        BankTransaction.id == transaction_id,
        BankTransaction.org_id == org_id,
    )
    result = await db.execute(stmt)
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.reconciliation_status == "matched":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ALREADY_MATCHED",
                "message": f"Transaction already matched",
            },
        )

    # Enforce single FK constraint
    fk_count = sum(
        1 for fk in [matched_invoice_id, matched_expense_id, matched_journal_id]
        if fk is not None
    )
    if fk_count != 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MULTIPLE_MATCHES",
                "message": "Transaction can only be matched to one entity",
            },
        )

    txn.matched_invoice_id = matched_invoice_id
    txn.matched_expense_id = matched_expense_id
    txn.matched_journal_id = matched_journal_id
    txn.reconciliation_status = "matched"

    await db.flush()
    await db.refresh(txn)
    return txn


async def exclude_transaction(
    db: AsyncSession,
    org_id: uuid.UUID,
    transaction_id: uuid.UUID,
) -> BankTransaction:
    """Exclude a transaction from reconciliation.

    Requirements: 19.3
    """
    stmt = select(BankTransaction).where(
        BankTransaction.id == transaction_id,
        BankTransaction.org_id == org_id,
    )
    result = await db.execute(stmt)
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn.reconciliation_status = "excluded"
    txn.matched_invoice_id = None
    txn.matched_expense_id = None
    txn.matched_journal_id = None

    await db.flush()
    await db.refresh(txn)
    return txn


async def create_expense_from_transaction(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    transaction_id: uuid.UUID,
) -> BankTransaction:
    """Create an expense from a bank transaction and link it.

    Requirements: 19.4
    """
    from app.modules.expenses.models import Expense

    stmt = select(BankTransaction).where(
        BankTransaction.id == transaction_id,
        BankTransaction.org_id == org_id,
    )
    result = await db.execute(stmt)
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Create expense from transaction data
    expense = Expense(
        org_id=org_id,
        date=txn.date,
        description=txn.description,
        amount=abs(txn.amount),
        tax_amount=Decimal("0"),
        category=txn.category or "other",
        reference_number=txn.akahu_transaction_id,
        created_by=user_id,
    )
    db.add(expense)
    await db.flush()
    await db.refresh(expense)

    # Link transaction to expense
    txn.matched_expense_id = expense.id
    txn.reconciliation_status = "matched"

    await db.flush()
    await db.refresh(txn)
    return txn


# ---------------------------------------------------------------------------
# Reconciliation Summary
# ---------------------------------------------------------------------------


async def get_reconciliation_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Get match counts by status + last sync timestamp.

    Requirements: 19.5
    """
    # Count by status
    stmt = (
        select(
            BankTransaction.reconciliation_status,
            func.count().label("count"),
        )
        .where(BankTransaction.org_id == org_id)
        .group_by(BankTransaction.reconciliation_status)
    )
    result = await db.execute(stmt)
    counts = {row[0]: row[1] for row in result.all()}

    # Get last sync timestamp
    conn_stmt = select(AkahuConnection.last_sync_at).where(
        AkahuConnection.org_id == org_id
    )
    conn_result = await db.execute(conn_stmt)
    last_sync_at = conn_result.scalar_one_or_none()

    total = sum(counts.values())

    return {
        "unmatched": counts.get("unmatched", 0),
        "matched": counts.get("matched", 0),
        "excluded": counts.get("excluded", 0),
        "manual": counts.get("manual", 0),
        "total": total,
        "last_sync_at": last_sync_at,
    }
