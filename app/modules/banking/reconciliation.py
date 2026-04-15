"""Auto-matching reconciliation engine for bank transactions.

Matches unmatched bank transactions against invoices and expenses
using amount proximity and date window rules.

Requirements: 18.1–18.5
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.banking.models import BankTransaction

logger = logging.getLogger(__name__)

# Matching thresholds
INVOICE_AMOUNT_TOLERANCE = Decimal("0.01")  # ±$0.01
INVOICE_DATE_WINDOW_DAYS = 7
EXPENSE_DATE_WINDOW_DAYS = 3


async def run_auto_matching(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[BankTransaction]:
    """Iterate unmatched transactions and attempt auto-matching.

    Algorithm:
    1. Positive amount → try invoice match (high confidence → auto-accept)
    2. Negative amount → try expense match (medium confidence → flag for review)
    3. Multiple matches → remain unmatched

    Requirements: 18.1, 18.2, 18.3, 18.4, 18.5
    """
    # Lazy imports to avoid circular dependencies
    from app.modules.invoices.models import Invoice
    from app.modules.expenses.models import Expense

    # Get all unmatched transactions for this org
    stmt = select(BankTransaction).where(
        BankTransaction.org_id == org_id,
        BankTransaction.reconciliation_status == "unmatched",
    )
    result = await db.execute(stmt)
    unmatched = list(result.scalars().all())

    matched_transactions: list[BankTransaction] = []

    for txn in unmatched:
        if txn.amount > 0:
            # Positive amount → try invoice match
            matched = await _try_invoice_match(db, org_id, txn, Invoice)
            if matched:
                matched_transactions.append(txn)
        elif txn.amount < 0:
            # Negative amount → try expense match
            matched = await _try_expense_match(db, org_id, txn, Expense)
            if matched:
                matched_transactions.append(txn)

    await db.flush()
    for txn in matched_transactions:
        await db.refresh(txn)

    return matched_transactions


async def _try_invoice_match(
    db: AsyncSession,
    org_id: uuid.UUID,
    txn: BankTransaction,
    Invoice: type,
) -> bool:
    """Try to match a positive transaction against invoices.

    High confidence: |amount - balance_due| ≤ $0.01 AND date within 7 days of due_date.
    If exactly one match → auto-accept. Multiple → remain unmatched.

    Requirements: 18.1, 18.3
    """
    txn_amount = abs(txn.amount)
    txn_date = txn.date
    date_lower = txn_date - timedelta(days=INVOICE_DATE_WINDOW_DAYS)
    date_upper = txn_date + timedelta(days=INVOICE_DATE_WINDOW_DAYS)

    stmt = select(Invoice).where(
        Invoice.org_id == org_id,
        Invoice.balance_due.isnot(None),
        func.abs(Invoice.balance_due - txn_amount) <= INVOICE_AMOUNT_TOLERANCE,
        Invoice.due_date >= date_lower,
        Invoice.due_date <= date_upper,
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    if len(candidates) == 1:
        # High confidence → auto-accept
        txn.matched_invoice_id = candidates[0].id
        txn.reconciliation_status = "matched"
        logger.info(
            "Auto-matched txn %s to invoice %s (high confidence)",
            txn.akahu_transaction_id, candidates[0].id,
        )
        return True

    # Multiple matches or no match → remain unmatched
    return False


async def _try_expense_match(
    db: AsyncSession,
    org_id: uuid.UUID,
    txn: BankTransaction,
    Expense: type,
) -> bool:
    """Try to match a negative transaction against expenses.

    Medium confidence: |abs(amount) - expense.amount| ≤ $0.01 AND date within 3 days.
    If exactly one match → flag for review (status='manual', NOT auto-accept).
    Multiple → remain unmatched.

    Requirements: 18.2, 18.4
    """
    txn_amount = abs(txn.amount)
    txn_date = txn.date
    date_lower = txn_date - timedelta(days=EXPENSE_DATE_WINDOW_DAYS)
    date_upper = txn_date + timedelta(days=EXPENSE_DATE_WINDOW_DAYS)

    stmt = select(Expense).where(
        Expense.org_id == org_id,
        func.abs(Expense.amount - txn_amount) <= INVOICE_AMOUNT_TOLERANCE,
        Expense.date >= date_lower,
        Expense.date <= date_upper,
    )
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    if len(candidates) == 1:
        # Medium confidence → flag for review, NOT auto-accept
        txn.matched_expense_id = candidates[0].id
        txn.reconciliation_status = "manual"
        logger.info(
            "Flagged txn %s for review — expense match %s (medium confidence)",
            txn.akahu_transaction_id, candidates[0].id,
        )
        return True

    # Multiple matches or no match → remain unmatched
    return False
