"""Auto-posting engine for the double-entry general ledger.

Automatically creates and posts journal entries when invoices, payments,
expenses, credit notes, or refunds are recorded. Called synchronously
within the same database transaction as the originating event.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ledger.models import Account
from app.modules.ledger.service import create_journal_entry, post_journal_entry


# ---------------------------------------------------------------------------
# Category → account code mapping for expenses
# ---------------------------------------------------------------------------

_EXPENSE_CATEGORY_MAP: dict[str, str] = {
    "materials": "5000",
    "subcontractor": "5100",
    "advertising": "6000",
    "fuel": "6700",
    "travel": "6700",
    "accommodation": "6700",
    "meals": "6700",
    "office": "6300",
    "equipment": "6500",
    "other": "6990",
}

_DEFAULT_EXPENSE_CODE = "6990"


# ---------------------------------------------------------------------------
# Helper: look up account by code for an org
# ---------------------------------------------------------------------------


async def _get_account_by_code(
    db: AsyncSession,
    org_id: uuid.UUID,
    code: str,
) -> Account:
    """Look up an active account by code within an organisation.

    Raises ValueError if the account is not found.
    """
    result = await db.execute(
        select(Account).where(
            Account.org_id == org_id,
            Account.code == code,
            Account.is_active == True,  # noqa: E712
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise ValueError(
            f"Account with code '{code}' not found for org {org_id}"
        )
    return account


# ---------------------------------------------------------------------------
# Auto-post: Invoice issued
# ---------------------------------------------------------------------------


async def auto_post_invoice(
    db: AsyncSession,
    invoice: object,
    user_id: uuid.UUID,
) -> None:
    """Create and post a journal entry for an issued invoice.

    DR 1100 Accounts Receivable  — net amount + GST (NZD)
    CR 4000 Sales Revenue        — net amount (NZD)
    CR 2100 GST Payable          — GST amount (NZD)

    FX invoices are converted to NZD using invoice.exchange_rate_to_nzd.

    Requirements: 4.1, 4.6, 4.7, 4.8
    """
    org_id: uuid.UUID = invoice.org_id
    rate: Decimal = Decimal(str(invoice.exchange_rate_to_nzd))

    net_amount = (invoice.total - invoice.gst_amount) * rate
    gst_amount = invoice.gst_amount * rate
    total_nzd = net_amount + gst_amount

    # Look up accounts
    ar = await _get_account_by_code(db, org_id, "1100")
    revenue = await _get_account_by_code(db, org_id, "4000")
    gst_payable = await _get_account_by_code(db, org_id, "2100")

    lines: list[dict] = [
        {
            "account_id": ar.id,
            "debit": total_nzd,
            "credit": Decimal("0"),
            "description": "Accounts Receivable",
        },
        {
            "account_id": revenue.id,
            "debit": Decimal("0"),
            "credit": net_amount,
            "description": "Sales Revenue",
        },
    ]

    if gst_amount > 0:
        lines.append(
            {
                "account_id": gst_payable.id,
                "debit": Decimal("0"),
                "credit": gst_amount,
                "description": "GST Payable",
            }
        )

    entry_date: date = invoice.issue_date or date.today()

    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=entry_date,
        description=f"Invoice {invoice.invoice_number or invoice.id} issued",
        source_type="invoice",
        source_id=invoice.id,
        lines=lines,
    )

    await post_journal_entry(db, org_id, entry.id)


# ---------------------------------------------------------------------------
# Auto-post: Payment received
# ---------------------------------------------------------------------------


async def auto_post_payment(
    db: AsyncSession,
    payment: object,
    invoice: object,
    user_id: uuid.UUID,
) -> None:
    """Create and post a journal entry for a received payment.

    DR 1000 Bank/Cash             — payment amount
    CR 1100 Accounts Receivable   — payment amount

    Requirements: 4.2, 4.6, 4.7
    """
    org_id: uuid.UUID = payment.org_id
    amount: Decimal = payment.amount

    bank = await _get_account_by_code(db, org_id, "1000")
    ar = await _get_account_by_code(db, org_id, "1100")

    lines: list[dict] = [
        {
            "account_id": bank.id,
            "debit": amount,
            "credit": Decimal("0"),
            "description": "Bank/Cash",
        },
        {
            "account_id": ar.id,
            "debit": Decimal("0"),
            "credit": amount,
            "description": "Accounts Receivable",
        },
    ]

    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=date.today(),
        description=f"Payment received for invoice {invoice.invoice_number or invoice.id}",
        source_type="payment",
        source_id=payment.id,
        lines=lines,
    )

    await post_journal_entry(db, org_id, entry.id)


# ---------------------------------------------------------------------------
# Auto-post: Expense recorded
# ---------------------------------------------------------------------------


async def auto_post_expense(
    db: AsyncSession,
    expense: object,
    user_id: uuid.UUID,
) -> None:
    """Create and post a journal entry for a recorded expense.

    DR 6xxx Expense Account   — expense amount minus tax_amount
    DR 1200 GST Receivable    — tax_amount (if > 0)
    CR 2000 Accounts Payable  — expense amount

    The expense account code is derived from the expense category.
    If no category or unmapped, defaults to 6990 (General Expenses).

    Requirements: 4.3, 4.6, 4.7
    """
    org_id: uuid.UUID = expense.org_id
    total: Decimal = expense.amount
    tax: Decimal = expense.tax_amount or Decimal("0")
    net: Decimal = total - tax

    # Determine expense account code from category
    account_code = _EXPENSE_CATEGORY_MAP.get(
        (expense.category or "").lower(),
        _DEFAULT_EXPENSE_CODE,
    )

    expense_acct = await _get_account_by_code(db, org_id, account_code)
    ap = await _get_account_by_code(db, org_id, "2000")

    lines: list[dict] = [
        {
            "account_id": expense_acct.id,
            "debit": net,
            "credit": Decimal("0"),
            "description": f"Expense: {expense.description or account_code}",
        },
    ]

    if tax > 0:
        gst_recv = await _get_account_by_code(db, org_id, "1200")
        lines.append(
            {
                "account_id": gst_recv.id,
                "debit": tax,
                "credit": Decimal("0"),
                "description": "GST Receivable",
            }
        )

    lines.append(
        {
            "account_id": ap.id,
            "debit": Decimal("0"),
            "credit": total,
            "description": "Accounts Payable",
        }
    )

    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=expense.date or date.today(),
        description=f"Expense: {expense.description or 'Expense recorded'}",
        source_type="expense",
        source_id=expense.id,
        lines=lines,
    )

    await post_journal_entry(db, org_id, entry.id)


# ---------------------------------------------------------------------------
# Auto-post: Credit note issued (reverse of invoice)
# ---------------------------------------------------------------------------


async def auto_post_credit_note(
    db: AsyncSession,
    credit_note: object,
    invoice: object,
    user_id: uuid.UUID,
) -> None:
    """Create and post a journal entry reversing the invoice entry.

    DR 4000 Sales Revenue        — net portion of credit note (NZD)
    DR 2100 GST Payable          — GST portion of credit note (NZD)
    CR 1100 Accounts Receivable  — total credit note amount (NZD)

    The GST proportion is derived from the original invoice's GST ratio.
    FX conversion uses the invoice's exchange_rate_to_nzd.

    Requirements: 4.4, 4.6, 4.7
    """
    org_id: uuid.UUID = credit_note.org_id
    rate: Decimal = Decimal(str(invoice.exchange_rate_to_nzd))
    cn_total: Decimal = credit_note.amount

    # Derive GST proportion from the original invoice
    if invoice.total and invoice.total > 0:
        gst_ratio = invoice.gst_amount / invoice.total
    else:
        gst_ratio = Decimal("0")

    gst_portion = (cn_total * gst_ratio * rate).quantize(Decimal("0.01"))
    net_portion = (cn_total * rate) - gst_portion
    total_nzd = net_portion + gst_portion

    revenue = await _get_account_by_code(db, org_id, "4000")
    gst_payable = await _get_account_by_code(db, org_id, "2100")
    ar = await _get_account_by_code(db, org_id, "1100")

    lines: list[dict] = [
        {
            "account_id": revenue.id,
            "debit": net_portion,
            "credit": Decimal("0"),
            "description": "Sales Revenue reversal",
        },
    ]

    if gst_portion > 0:
        lines.append(
            {
                "account_id": gst_payable.id,
                "debit": gst_portion,
                "credit": Decimal("0"),
                "description": "GST Payable reversal",
            }
        )

    lines.append(
        {
            "account_id": ar.id,
            "debit": Decimal("0"),
            "credit": total_nzd,
            "description": "Accounts Receivable reversal",
        }
    )

    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=date.today(),
        description=f"Credit note {credit_note.credit_note_number} for invoice {invoice.invoice_number or invoice.id}",
        source_type="credit_note",
        source_id=credit_note.id,
        lines=lines,
    )

    await post_journal_entry(db, org_id, entry.id)


# ---------------------------------------------------------------------------
# Auto-post: Refund paid
# ---------------------------------------------------------------------------


async def auto_post_refund(
    db: AsyncSession,
    payment: object,
    invoice: object,
    user_id: uuid.UUID,
) -> None:
    """Create and post a journal entry for a refund payment.

    DR 1100 Accounts Receivable  — refund amount
    CR 1000 Bank/Cash            — refund amount

    Requirements: 4.5, 4.6, 4.7
    """
    org_id: uuid.UUID = payment.org_id
    amount: Decimal = payment.amount

    ar = await _get_account_by_code(db, org_id, "1100")
    bank = await _get_account_by_code(db, org_id, "1000")

    lines: list[dict] = [
        {
            "account_id": ar.id,
            "debit": amount,
            "credit": Decimal("0"),
            "description": "Accounts Receivable",
        },
        {
            "account_id": bank.id,
            "debit": Decimal("0"),
            "credit": amount,
            "description": "Bank/Cash",
        },
    ]

    entry = await create_journal_entry(
        db,
        org_id,
        user_id=user_id,
        entry_date=date.today(),
        description=f"Refund for invoice {invoice.invoice_number or invoice.id}",
        source_type="payment",
        source_id=payment.id,
        lines=lines,
    )

    await post_journal_entry(db, org_id, entry.id)
