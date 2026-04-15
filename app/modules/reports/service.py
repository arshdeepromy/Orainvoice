"""Service layer for org-level reports.

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.customers.models import Customer, FleetAccount
from app.modules.expenses.models import Expense
from app.modules.invoices.models import CreditNote, Invoice, LineItem
from app.modules.ledger.models import Account, JournalEntry, JournalLine

logger = logging.getLogger(__name__)
from app.modules.payments.models import Payment


# ---------------------------------------------------------------------------
# Date-range helpers
# ---------------------------------------------------------------------------

def resolve_date_range(
    preset: str | None,
    start: date | None,
    end: date | None,
) -> tuple[date, date]:
    """Return (start_date, end_date) from a preset or custom range."""
    today = date.today()
    if preset == "day":
        return today, today
    if preset == "week":
        return today - timedelta(days=today.weekday()), today
    if preset == "month":
        return today.replace(day=1), today
    if preset == "quarter":
        q_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_month, day=1), today
    if preset == "year":
        return today.replace(month=1, day=1), today
    # custom or fallback
    if start and end:
        return start, end
    # default to current month
    return today.replace(day=1), today


# ---------------------------------------------------------------------------
# Revenue Summary
# ---------------------------------------------------------------------------

async def get_revenue_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_start: date,
    period_end: date,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Revenue summary for the organisation within the date range.

    All amounts are converted to NZD using each invoice's exchange_rate_to_nzd
    so that multi-currency invoices produce correct NZD totals.

    Excludes voided invoices from revenue reporting (Req 19.7).
    Accounts for refunds (credit notes + refund payments) in the period.
    When branch_id is provided, scopes data to that branch only.
    Requirements: 20.1
    """
    inv_query = select(
        func.coalesce(
            func.sum(Invoice.subtotal * Invoice.exchange_rate_to_nzd), 0
        ).label("total_revenue_nzd"),
        func.coalesce(
            func.sum(Invoice.gst_amount * Invoice.exchange_rate_to_nzd), 0
        ).label("total_gst_nzd"),
        func.coalesce(
            func.sum(Invoice.total * Invoice.exchange_rate_to_nzd), 0
        ).label("total_inclusive_nzd"),
        func.count(Invoice.id).label("invoice_count"),
    ).where(
        Invoice.org_id == org_id,
        Invoice.status != "voided",
        Invoice.status != "draft",
        Invoice.issue_date >= period_start,
        Invoice.issue_date <= period_end,
    )
    if branch_id is not None:
        inv_query = inv_query.where(Invoice.branch_id == branch_id)
    result = await db.execute(inv_query)
    row = result.one()
    count = row.invoice_count or 0
    total_rev = Decimal(str(row.total_inclusive_nzd or 0)).quantize(Decimal("0.01"))
    total_revenue_ex = Decimal(str(row.total_revenue_nzd or 0)).quantize(Decimal("0.01"))
    total_gst = Decimal(str(row.total_gst_nzd or 0)).quantize(Decimal("0.01"))
    avg = (total_rev / count).quantize(Decimal("0.01")) if count > 0 else Decimal("0")

    # Refunds: credit notes + refund payments — converted to NZD via parent invoice rate
    cn_result = await db.execute(
        select(
            func.coalesce(
                func.sum(CreditNote.amount * Invoice.exchange_rate_to_nzd), 0
            ).label("cn_refunds_nzd"),
        )
        .join(Invoice, CreditNote.invoice_id == Invoice.id)
        .where(
            CreditNote.org_id == org_id,
            func.date(CreditNote.created_at) >= period_start,
            func.date(CreditNote.created_at) <= period_end,
        )
    )
    cn_refunds = Decimal(str(cn_result.scalar() or 0)).quantize(Decimal("0.01"))

    pay_refund_result = await db.execute(
        select(
            func.coalesce(
                func.sum(Payment.amount * Invoice.exchange_rate_to_nzd), 0
            ).label("pay_refunds_nzd"),
        )
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(
            Payment.org_id == org_id,
            Payment.is_refund == True,  # noqa: E712
            func.date(Payment.created_at) >= period_start,
            func.date(Payment.created_at) <= period_end,
        )
    )
    pay_refunds = Decimal(str(pay_refund_result.scalar() or 0)).quantize(Decimal("0.01"))

    total_refunds = cn_refunds + pay_refunds
    gst_rate = Decimal("3") / Decimal("23")
    refund_gst = (total_refunds * gst_rate).quantize(Decimal("0.01"))
    refund_ex_gst = total_refunds - refund_gst

    net_revenue = total_revenue_ex - refund_ex_gst
    net_gst = total_gst - refund_gst

    return {
        "currency": "NZD",
        "total_revenue": total_revenue_ex,
        "total_gst": total_gst,
        "total_inclusive": total_rev,
        "invoice_count": count,
        "average_invoice": avg,
        "total_refunds": total_refunds,
        "refund_gst": refund_gst,
        "net_revenue": net_revenue,
        "net_gst": net_gst,
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# Invoice Status Report
# ---------------------------------------------------------------------------

async def get_invoice_status_report(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> dict:
    """Breakdown of invoices by status within the date range."""
    result = await db.execute(
        select(
            Invoice.status,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.total), 0).label("total"),
        )
        .where(
            Invoice.org_id == org_id,
            Invoice.created_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            Invoice.created_at <= datetime.combine(period_end, datetime.max.time(), tzinfo=timezone.utc),
        )
        .group_by(Invoice.status)
    )
    rows = result.all()
    breakdown = [
        {"status": r.status, "count": r.count, "total": Decimal(str(r.total))}
        for r in rows
    ]
    return {
        "breakdown": breakdown,
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# Outstanding Invoices
# ---------------------------------------------------------------------------

async def get_outstanding_invoices(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """All invoices with an outstanding balance (issued, partially_paid, overdue).

    When branch_id is provided, scopes data to that branch only.
    Requirements: 20.3
    """
    today = date.today()
    outstanding_query = (
        select(
            Invoice.id,
            Invoice.invoice_number,
            Invoice.customer_id,
            Invoice.vehicle_rego,
            Invoice.issue_date,
            Invoice.due_date,
            Invoice.total,
            Invoice.balance_due,
            Customer.first_name,
            Customer.last_name,
        )
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.org_id == org_id,
            Invoice.status.in_(["issued", "partially_paid", "overdue"]),
            Invoice.balance_due > 0,
        )
    )
    if branch_id is not None:
        outstanding_query = outstanding_query.where(Invoice.branch_id == branch_id)
    outstanding_query = outstanding_query.order_by(Invoice.due_date.asc().nullslast())
    result = await db.execute(outstanding_query)
    rows = result.all()
    invoices = []
    total_outstanding = Decimal("0")
    for r in rows:
        days_overdue = (today - r.due_date).days if r.due_date and r.due_date < today else 0
        invoices.append({
            "invoice_id": r.id,
            "invoice_number": r.invoice_number,
            "customer_name": f"{r.first_name} {r.last_name}",
            "customer_id": r.customer_id,
            "vehicle_rego": r.vehicle_rego,
            "issue_date": r.issue_date,
            "due_date": r.due_date,
            "total": Decimal(str(r.total)),
            "balance_due": Decimal(str(r.balance_due)),
            "days_overdue": days_overdue,
        })
        total_outstanding += Decimal(str(r.balance_due))
    return {
        "invoices": invoices,
        "total_outstanding": total_outstanding,
        "count": len(invoices),
    }


# ---------------------------------------------------------------------------
# Top Services by Revenue
# ---------------------------------------------------------------------------

async def get_top_services(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_start: date,
    period_end: date,
    limit: int = 20,
) -> dict:
    """Top services by revenue within the date range."""
    result = await db.execute(
        select(
            LineItem.description,
            LineItem.catalogue_item_id,
            func.count(LineItem.id).label("count"),
            func.coalesce(func.sum(LineItem.line_total), 0).label("total_revenue"),
        )
        .join(Invoice, LineItem.invoice_id == Invoice.id)
        .where(
            LineItem.org_id == org_id,
            LineItem.item_type == "service",
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
        .group_by(LineItem.description, LineItem.catalogue_item_id)
        .order_by(func.sum(LineItem.line_total).desc())
        .limit(limit)
    )
    rows = result.all()
    services = [
        {
            "description": r.description,
            "catalogue_item_id": r.catalogue_item_id,
            "count": r.count,
            "total_revenue": Decimal(str(r.total_revenue)),
        }
        for r in rows
    ]
    return {
        "services": services,
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# GST Return Summary
# ---------------------------------------------------------------------------

async def get_gst_return(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_start: date,
    period_end: date,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """GST return summary formatted for IRD filing.

    All amounts are converted to NZD using each invoice's exchange_rate_to_nzd
    so that multi-currency invoices produce correct NZD totals for IRD.

    Separates standard-rated and zero-rated (GST-exempt) line items.
    Accounts for refunds/credit notes processed within the period,
    using the credit note's created_at date (not the original invoice date).
    When branch_id is provided, scopes data to that branch only.
    Req 45.6, 20.2
    """
    # Standard-rated items (not GST-exempt) — converted to NZD
    std_query = (
        select(
            func.coalesce(
                func.sum(LineItem.line_total * Invoice.exchange_rate_to_nzd), 0
            ).label("std_sales_nzd"),
        )
        .join(Invoice, LineItem.invoice_id == Invoice.id)
        .where(
            LineItem.org_id == org_id,
            LineItem.is_gst_exempt == False,  # noqa: E712
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    if branch_id is not None:
        std_query = std_query.where(Invoice.branch_id == branch_id)
    std_result = await db.execute(std_query)
    std_sales = Decimal(str(std_result.scalar() or 0)).quantize(Decimal("0.01"))

    # Zero-rated / GST-exempt items — converted to NZD
    zero_query = (
        select(
            func.coalesce(
                func.sum(LineItem.line_total * Invoice.exchange_rate_to_nzd), 0
            ).label("zero_sales_nzd"),
        )
        .join(Invoice, LineItem.invoice_id == Invoice.id)
        .where(
            LineItem.org_id == org_id,
            LineItem.is_gst_exempt == True,  # noqa: E712
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    if branch_id is not None:
        zero_query = zero_query.where(Invoice.branch_id == branch_id)
    zero_result = await db.execute(zero_query)
    zero_sales = Decimal(str(zero_result.scalar() or 0)).quantize(Decimal("0.01"))

    # Total GST collected from invoices — converted to NZD
    gst_query = select(
        func.coalesce(
            func.sum(Invoice.gst_amount * Invoice.exchange_rate_to_nzd), 0
        ).label("total_gst_nzd"),
        func.coalesce(
            func.sum(Invoice.total * Invoice.exchange_rate_to_nzd), 0
        ).label("total_sales_nzd"),
    ).where(
        Invoice.org_id == org_id,
        Invoice.status != "voided",
        Invoice.status != "draft",
        Invoice.issue_date >= period_start,
        Invoice.issue_date <= period_end,
    )
    if branch_id is not None:
        gst_query = gst_query.where(Invoice.branch_id == branch_id)
    gst_result = await db.execute(gst_query)
    gst_row = gst_result.one()
    total_gst = Decimal(str(gst_row.total_gst_nzd or 0)).quantize(Decimal("0.01"))
    total_sales = Decimal(str(gst_row.total_sales_nzd or 0)).quantize(Decimal("0.01"))

    # Refunds processed within the period — converted to NZD via parent invoice rate.
    # 1. Credit notes — join to invoice for exchange_rate_to_nzd
    cn_result = await db.execute(
        select(
            func.coalesce(
                func.sum(CreditNote.amount * Invoice.exchange_rate_to_nzd), 0
            ).label("cn_refunds_nzd"),
        )
        .join(Invoice, CreditNote.invoice_id == Invoice.id)
        .where(
            CreditNote.org_id == org_id,
            func.date(CreditNote.created_at) >= period_start,
            func.date(CreditNote.created_at) <= period_end,
        )
    )
    cn_refunds = Decimal(str(cn_result.scalar() or 0)).quantize(Decimal("0.01"))

    # 2. Refund payments — join to invoice for exchange_rate_to_nzd
    pay_refund_result = await db.execute(
        select(
            func.coalesce(
                func.sum(Payment.amount * Invoice.exchange_rate_to_nzd), 0
            ).label("pay_refunds_nzd"),
        )
        .join(Invoice, Payment.invoice_id == Invoice.id)
        .where(
            Payment.org_id == org_id,
            Payment.is_refund == True,  # noqa: E712
            func.date(Payment.created_at) >= period_start,
            func.date(Payment.created_at) <= period_end,
        )
    )
    pay_refunds = Decimal(str(pay_refund_result.scalar() or 0)).quantize(Decimal("0.01"))

    total_refunds = cn_refunds + pay_refunds

    # GST component of refunds: refund amounts are GST-inclusive at 15%
    # GST portion = refund_amount * 3/23 (i.e. 15/115)
    gst_rate = Decimal("3") / Decimal("23")
    refund_gst = (total_refunds * gst_rate).quantize(Decimal("0.01"))

    # --- Input tax from expenses (purchases) ---
    # Expenses are always in NZD (no currency field on expenses table).
    # tax_amount is the GST component the business paid on purchases.
    # We sum all expenses in the period that have a non-zero tax_amount.
    # Both tax_inclusive and non-tax-inclusive expenses can have tax_amount
    # set — it's the explicit GST component regardless of how amount is entered.
    expense_query = select(
        func.coalesce(func.sum(Expense.amount), 0).label("total_purchases"),
        func.coalesce(func.sum(Expense.tax_amount), 0).label("total_input_tax"),
    ).where(
        Expense.org_id == org_id,
        Expense.date >= period_start,
        Expense.date <= period_end,
    )
    if branch_id is not None:
        expense_query = expense_query.where(Expense.branch_id == branch_id)
    expense_result = await db.execute(expense_query)
    expense_row = expense_result.one()
    total_purchases = Decimal(str(expense_row.total_purchases or 0)).quantize(Decimal("0.01"))
    total_input_tax = Decimal(str(expense_row.total_input_tax or 0)).quantize(Decimal("0.01"))

    # Adjusted figures (all in NZD)
    adjusted_total_sales = total_sales - total_refunds
    adjusted_output_gst = total_gst - refund_gst

    # Net GST payable = output tax (what you collected) - input tax (what you paid)
    # Positive = you owe IRD. Negative = IRD owes you a refund.
    net_gst_payable = adjusted_output_gst - total_input_tax

    return {
        "currency": "NZD",
        # --- Sales (output) side — IRD Box 5, 6 ---
        "total_sales": total_sales,
        "total_gst_collected": total_gst,
        "standard_rated_sales": std_sales,
        "standard_rated_gst": adjusted_output_gst,
        "zero_rated_sales": zero_sales,
        "total_refunds": total_refunds,
        "refund_gst": refund_gst,
        "adjusted_total_sales": adjusted_total_sales,
        "adjusted_output_gst": adjusted_output_gst,
        # --- Purchases (input) side — IRD Box 11, 13 ---
        "total_purchases": total_purchases,
        "total_input_tax": total_input_tax,
        # --- Net position — IRD Box 14 ---
        "net_gst_payable": net_gst_payable,
        # Legacy alias (kept for backward compat with frontend)
        "net_gst": net_gst_payable,
        "adjusted_gst_collected": adjusted_output_gst,
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# Customer Statement
# ---------------------------------------------------------------------------

async def get_customer_statement(
    db: AsyncSession,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    period_start: date,
    period_end: date,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Printable customer statement with invoices and payments.

    When branch_id is provided, includes only transactions associated with that branch.
    Req 45.7, 20.4
    """
    # Fetch customer
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if not customer:
        return None

    customer_name = f"{customer.first_name} {customer.last_name}"

    # Fetch invoices in the period (non-voided, non-draft)
    inv_stmt = (
        select(Invoice)
        .where(
            Invoice.org_id == org_id,
            Invoice.customer_id == customer_id,
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    if branch_id is not None:
        inv_stmt = inv_stmt.where(Invoice.branch_id == branch_id)
    inv_stmt = inv_stmt.order_by(Invoice.issue_date.asc())
    inv_result = await db.execute(inv_stmt)
    invoices = inv_result.scalars().all()

    # Fetch payments in the period
    invoice_ids = [inv.id for inv in invoices]
    payments = []
    if invoice_ids:
        pay_result = await db.execute(
            select(Payment)
            .where(
                Payment.org_id == org_id,
                Payment.invoice_id.in_(invoice_ids),
            )
            .order_by(Payment.created_at.asc())
        )
        payments = pay_result.scalars().all()

    # Build statement lines
    items = []
    running_balance = Decimal("0")

    for inv in invoices:
        running_balance += inv.total
        items.append({
            "date": inv.issue_date,
            "description": f"Invoice {inv.invoice_number or 'Draft'}",
            "reference": inv.invoice_number,
            "debit": inv.total,
            "credit": Decimal("0"),
            "balance": running_balance,
        })

    for pay in payments:
        amount = pay.amount
        if pay.is_refund:
            running_balance += amount
            items.append({
                "date": pay.created_at.date() if pay.created_at else None,
                "description": f"Refund ({pay.method})",
                "reference": None,
                "debit": amount,
                "credit": Decimal("0"),
                "balance": running_balance,
            })
        else:
            running_balance -= amount
            items.append({
                "date": pay.created_at.date() if pay.created_at else None,
                "description": f"Payment ({pay.method})",
                "reference": None,
                "debit": Decimal("0"),
                "credit": amount,
                "balance": running_balance,
            })

    # Sort by date
    items.sort(key=lambda x: x["date"] or date.min)

    # Recalculate running balance in sorted order
    balance = Decimal("0")
    for item in items:
        balance += item["debit"] - item["credit"]
        item["balance"] = balance

    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "items": items,
        "opening_balance": Decimal("0"),
        "closing_balance": balance,
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# Carjam Usage Report
# ---------------------------------------------------------------------------

async def get_carjam_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """Carjam API usage for the organisation with daily breakdown."""
    from app.modules.admin.models import AuditLog
    from app.modules.admin.service import get_carjam_per_lookup_cost

    # Get org plan info
    result = await db.execute(
        select(
            SubscriptionPlan.carjam_lookups_included,
        )
        .select_from(Organisation)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    row = result.one_or_none()
    included = (row.carjam_lookups_included or 0) if row else 0

    # Default date range
    if not date_from:
        now = datetime.now(timezone.utc)
        date_from = date(now.year, now.month, 1)
    if not date_to:
        date_to = datetime.now(timezone.utc).date()

    carjam_actions = [
        "vehicle.refresh",
        "vehicle.carjam_abcd_lookup",
        "vehicle.carjam_basic_lookup",
        "vehicle.carjam_lookup",
    ]

    date_filter = [
        AuditLog.org_id == org_id,
        AuditLog.action.in_(carjam_actions),
        AuditLog.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc),
        AuditLog.created_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc),
    ]

    # Total lookups within the date range (from audit log)
    total_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(*date_filter)
    )
    lookups = total_result.scalar() or 0

    overage = max(0, lookups - included)
    try:
        per_lookup_cost = await get_carjam_per_lookup_cost(db)
    except Exception:
        per_lookup_cost = 0.0
    overage_charge = round(overage * per_lookup_cost, 2)

    # Daily breakdown
    daily_result = await db.execute(
        select(
            func.date(AuditLog.created_at).label("day"),
            func.count().label("count"),
        )
        .where(*date_filter)
        .group_by(func.date(AuditLog.created_at))
        .order_by(func.date(AuditLog.created_at))
    )
    daily_rows = daily_result.all()
    daily_breakdown = [
        {"date": str(r.day), "lookups": r.count}
        for r in daily_rows
    ]

    return {
        "total_lookups": lookups,
        "included_in_plan": included,
        "overage_lookups": overage,
        "overage_charge": overage_charge,
        "daily_breakdown": daily_breakdown,
    }


# ---------------------------------------------------------------------------
# SMS Usage Report
# ---------------------------------------------------------------------------

async def get_sms_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    """SMS usage for the organisation within the date range.

    Counts outbound messages from sms_messages table filtered by date.
    Requirements: 7.1
    """
    from app.modules.sms_chat.models import SmsMessage
    from app.modules.admin.service import get_sms_per_message_cost
    from sqlalchemy import text as _text

    # Default date range: current month
    if not date_from:
        now = datetime.now(timezone.utc)
        date_from = date(now.year, now.month, 1)
    if not date_to:
        date_to = datetime.now(timezone.utc).date()

    # Count outbound messages in the date range using raw SQL to bypass RLS.
    # Two sources: sms_messages (chat sends) + notification_log (notification/reminder SMS)
    start_dt = datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)

    msg_result = await db.execute(
        _text(
            "SELECT "
            "  (SELECT COUNT(*) FROM sms_messages "
            "   WHERE org_id = :oid AND direction = 'outbound' "
            "   AND created_at >= :start AND created_at <= :end_dt) "
            "+ (SELECT COUNT(*) FROM notification_log "
            "   WHERE org_id = :oid AND channel = 'sms' "
            "   AND status != 'failed' "
            "   AND created_at >= :start AND created_at <= :end_dt) "
            "AS total"
        ),
        {"oid": str(org_id), "start": start_dt, "end_dt": end_dt},
    )
    total_sent = int(msg_result.scalar() or 0)

    # Get plan included quota
    result = await db.execute(
        select(
            SubscriptionPlan.sms_included,
            SubscriptionPlan.sms_included_quota,
        )
        .select_from(Organisation)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    row = result.one_or_none()
    sms_enabled = bool(row.sms_included) if row else False
    included = (row.sms_included_quota or 0) if row and sms_enabled else 0

    # Sum package credits from SmsPackagePurchase
    from app.modules.admin.models import SmsPackagePurchase
    pkg_result = await db.execute(
        select(
            func.coalesce(func.sum(SmsPackagePurchase.credits_remaining), 0)
        ).where(SmsPackagePurchase.org_id == org_id)
    )
    package_credits = int(pkg_result.scalar() or 0)
    effective_quota = (included + package_credits) if sms_enabled else 0

    overage = max(0, total_sent - effective_quota)
    try:
        per_sms_cost = await get_sms_per_message_cost(db)
    except Exception:
        per_sms_cost = 0.0
    overage_charge = round(overage * per_sms_cost, 2)

    # Fetch reset_at from the organisation record
    reset_result = await db.execute(
        select(Organisation.sms_sent_reset_at).where(Organisation.id == org_id)
    )
    reset_at = reset_result.scalar()

    return {
        "total_sent": total_sent,
        "included_in_plan": included,
        "package_credits_remaining": package_credits,
        "effective_quota": effective_quota,
        "overage_count": overage,
        "overage_charge_nzd": overage_charge,
        "per_sms_cost_nzd": per_sms_cost,
        "reset_at": reset_at,
    }


# ---------------------------------------------------------------------------
# Storage Usage Report
# ---------------------------------------------------------------------------

async def get_storage_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Storage usage for the organisation.

    Uses storage_used_bytes (actual file uploads tracked by StorageManager)
    and storage_quota_gb (plan quota) from the organisations table.
    This reflects real file storage (receipts, attachments, logos) rather
    than raw DB text field sizes.
    """
    result = await db.execute(
        select(
            Organisation.storage_used_bytes,
            Organisation.storage_quota_gb,
        ).where(Organisation.id == org_id)
    )
    row = result.one_or_none()
    if row is None:
        return {"used_bytes": 0, "used_gb": 0.0, "quota_gb": 100, "usage_percent": 0.0, "breakdown": []}

    used_bytes = row.storage_used_bytes or 0
    quota_gb = row.storage_quota_gb or 100
    quota_bytes = quota_gb * 1_073_741_824
    percentage = (used_bytes / quota_bytes * 100) if quota_bytes > 0 else 0.0
    used_gb = round(used_bytes / 1_073_741_824, 4)

    return {
        "used_bytes": used_bytes,
        "used_gb": used_gb,
        "quota_gb": quota_gb,
        "usage_percent": round(percentage, 2),
        "breakdown": [],
    }


# ---------------------------------------------------------------------------
# Fleet Account Report
# ---------------------------------------------------------------------------

async def get_fleet_report(
    db: AsyncSession,
    org_id: uuid.UUID,
    fleet_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> dict | None:
    """Fleet account report: total spend, vehicles serviced, outstanding balance.

    Req 66.4
    """
    # Fetch fleet account
    fleet_result = await db.execute(
        select(FleetAccount).where(
            FleetAccount.id == fleet_id,
            FleetAccount.org_id == org_id,
        )
    )
    fleet = fleet_result.scalar_one_or_none()
    if not fleet:
        return None

    # Get customer IDs belonging to this fleet
    cust_result = await db.execute(
        select(Customer.id).where(
            Customer.org_id == org_id,
            Customer.fleet_account_id == fleet_id,
        )
    )
    customer_ids = [r[0] for r in cust_result.all()]

    if not customer_ids:
        return {
            "fleet_account_id": fleet_id,
            "fleet_name": fleet.name,
            "total_spend": Decimal("0"),
            "vehicles_serviced": 0,
            "outstanding_balance": Decimal("0"),
            "period_start": period_start,
            "period_end": period_end,
        }

    # Total spend (paid invoices)
    spend_result = await db.execute(
        select(
            func.coalesce(func.sum(Invoice.total), 0).label("total_spend"),
            func.coalesce(func.sum(Invoice.balance_due), 0).label("outstanding"),
        )
        .where(
            Invoice.org_id == org_id,
            Invoice.customer_id.in_(customer_ids),
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    spend_row = spend_result.one()

    # Distinct vehicles serviced
    vehicle_result = await db.execute(
        select(func.count(func.distinct(Invoice.vehicle_rego)))
        .where(
            Invoice.org_id == org_id,
            Invoice.customer_id.in_(customer_ids),
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.vehicle_rego.isnot(None),
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    vehicles_serviced = vehicle_result.scalar() or 0

    return {
        "fleet_account_id": fleet_id,
        "fleet_name": fleet.name,
        "total_spend": Decimal(str(spend_row.total_spend or 0)),
        "vehicles_serviced": vehicles_serviced,
        "outstanding_balance": Decimal(str(spend_row.outstanding or 0)),
        "period_start": period_start,
        "period_end": period_end,
    }


# ---------------------------------------------------------------------------
# Profit & Loss Report (Sprint 2)
# Requirements: 6.1–6.7
# ---------------------------------------------------------------------------

async def get_profit_loss(
    db: AsyncSession,
    org_id: uuid.UUID,
    period_start: date,
    period_end: date,
    basis: str = "accrual",
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Profit & Loss report aggregating journal lines by account type.

    basis="accrual": all posted entries by entry_date in range.
    basis="cash": only entries where source_type='payment'.
    Optional branch_id filter joins through source invoice/expense.
    Requirements: 6.1–6.7
    """
    # Base query: journal_lines joined with accounts and journal_entries
    base_q = (
        select(
            Account.id.label("account_id"),
            Account.code.label("account_code"),
            Account.name.label("account_name"),
            Account.account_type,
            func.coalesce(func.sum(JournalLine.debit), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("total_credit"),
        )
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(
            JournalLine.org_id == org_id,
            JournalEntry.is_posted == True,  # noqa: E712
            JournalEntry.entry_date >= period_start,
            JournalEntry.entry_date <= period_end,
        )
    )

    # Cash basis: only payment-sourced entries
    if basis == "cash":
        base_q = base_q.where(JournalEntry.source_type == "payment")

    # Branch filter: join through source invoice or expense
    if branch_id is not None:
        base_q = base_q.where(
            JournalEntry.source_id.in_(
                select(Invoice.id).where(Invoice.branch_id == branch_id)
            )
            | JournalEntry.source_id.in_(
                select(Expense.id).where(Expense.branch_id == branch_id)
            )
        )

    # Filter to revenue, cogs, expense account types
    base_q = base_q.where(
        Account.account_type.in_(["revenue", "cogs", "expense"])
    )
    base_q = base_q.group_by(
        Account.id, Account.code, Account.name, Account.account_type
    )

    result = await db.execute(base_q)
    rows = result.all()

    revenue_items = []
    cogs_items = []
    expense_items = []
    total_revenue = Decimal("0")
    total_cogs = Decimal("0")
    total_expenses = Decimal("0")

    for r in rows:
        debit = Decimal(str(r.total_debit))
        credit = Decimal(str(r.total_credit))

        if r.account_type == "revenue":
            # Revenue accounts: credits increase revenue
            amount = (credit - debit).quantize(Decimal("0.01"))
            total_revenue += amount
            revenue_items.append({
                "account_id": r.account_id,
                "account_code": r.account_code,
                "account_name": r.account_name,
                "amount": amount,
            })
        elif r.account_type == "cogs":
            # COGS accounts: debits increase cost
            amount = (debit - credit).quantize(Decimal("0.01"))
            total_cogs += amount
            cogs_items.append({
                "account_id": r.account_id,
                "account_code": r.account_code,
                "account_name": r.account_name,
                "amount": amount,
            })
        elif r.account_type == "expense":
            # Expense accounts: debits increase expense
            amount = (debit - credit).quantize(Decimal("0.01"))
            total_expenses += amount
            expense_items.append({
                "account_id": r.account_id,
                "account_code": r.account_code,
                "account_name": r.account_name,
                "amount": amount,
            })

    gross_profit = total_revenue - total_cogs
    gross_margin_pct = (
        (gross_profit / total_revenue * 100).quantize(Decimal("0.01"))
        if total_revenue != 0
        else Decimal("0")
    )
    net_profit = gross_profit - total_expenses
    net_margin_pct = (
        (net_profit / total_revenue * 100).quantize(Decimal("0.01"))
        if total_revenue != 0
        else Decimal("0")
    )

    return {
        "currency": "NZD",
        "revenue_items": revenue_items,
        "total_revenue": total_revenue.quantize(Decimal("0.01")),
        "cogs_items": cogs_items,
        "total_cogs": total_cogs.quantize(Decimal("0.01")),
        "gross_profit": gross_profit.quantize(Decimal("0.01")),
        "gross_margin_pct": gross_margin_pct,
        "expense_items": expense_items,
        "total_expenses": total_expenses.quantize(Decimal("0.01")),
        "net_profit": net_profit.quantize(Decimal("0.01")),
        "net_margin_pct": net_margin_pct,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
    }


# ---------------------------------------------------------------------------
# Balance Sheet Report (Sprint 2)
# Requirements: 7.1–7.5
# ---------------------------------------------------------------------------

async def get_balance_sheet(
    db: AsyncSession,
    org_id: uuid.UUID,
    as_at_date: date,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Balance Sheet as at a specific date.

    Aggregates all posted journal lines up to as_at_date for asset,
    liability, and equity account types. Groups into current/non_current.
    Requirements: 7.1–7.5
    """
    base_q = (
        select(
            Account.id.label("account_id"),
            Account.code.label("account_code"),
            Account.name.label("account_name"),
            Account.account_type,
            Account.sub_type,
            func.coalesce(func.sum(JournalLine.debit), 0).label("total_debit"),
            func.coalesce(func.sum(JournalLine.credit), 0).label("total_credit"),
        )
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(
            JournalLine.org_id == org_id,
            JournalEntry.is_posted == True,  # noqa: E712
            JournalEntry.entry_date <= as_at_date,
        )
    )

    if branch_id is not None:
        base_q = base_q.where(
            JournalEntry.source_id.in_(
                select(Invoice.id).where(Invoice.branch_id == branch_id)
            )
            | JournalEntry.source_id.in_(
                select(Expense.id).where(Expense.branch_id == branch_id)
            )
        )

    base_q = base_q.where(
        Account.account_type.in_(["asset", "liability", "equity"])
    )
    base_q = base_q.group_by(
        Account.id, Account.code, Account.name, Account.account_type, Account.sub_type
    )

    result = await db.execute(base_q)
    rows = result.all()

    assets_current = []
    assets_non_current = []
    liabilities_current = []
    liabilities_non_current = []
    equity_items = []

    total_assets = Decimal("0")
    total_liabilities = Decimal("0")
    total_equity = Decimal("0")

    for r in rows:
        debit = Decimal(str(r.total_debit))
        credit = Decimal(str(r.total_credit))

        item = {
            "account_id": r.account_id,
            "account_code": r.account_code,
            "account_name": r.account_name,
            "sub_type": r.sub_type,
        }

        if r.account_type == "asset":
            # Assets: debit-normal (debits increase, credits decrease)
            balance = (debit - credit).quantize(Decimal("0.01"))
            item["balance"] = balance
            total_assets += balance
            if r.sub_type and "non_current" in r.sub_type:
                assets_non_current.append(item)
            else:
                assets_current.append(item)

        elif r.account_type == "liability":
            # Liabilities: credit-normal (credits increase, debits decrease)
            balance = (credit - debit).quantize(Decimal("0.01"))
            item["balance"] = balance
            total_liabilities += balance
            if r.sub_type and "non_current" in r.sub_type:
                liabilities_non_current.append(item)
            else:
                liabilities_current.append(item)

        elif r.account_type == "equity":
            # Equity: credit-normal
            balance = (credit - debit).quantize(Decimal("0.01"))
            item["balance"] = balance
            total_equity += balance
            equity_items.append(item)

    total_assets = total_assets.quantize(Decimal("0.01"))
    total_liabilities = total_liabilities.quantize(Decimal("0.01"))
    total_equity = total_equity.quantize(Decimal("0.01"))
    balanced = total_assets == total_liabilities + total_equity

    return {
        "currency": "NZD",
        "as_at_date": as_at_date,
        "assets": {
            "current": assets_current,
            "non_current": assets_non_current,
            "total": total_assets,
        },
        "liabilities": {
            "current": liabilities_current,
            "non_current": liabilities_non_current,
            "total": total_liabilities,
        },
        "equity": {
            "items": equity_items,
            "total": total_equity,
        },
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "balanced": balanced,
    }


# ---------------------------------------------------------------------------
# Aged Receivables Report (Sprint 2)
# Requirements: 8.1–8.3
# ---------------------------------------------------------------------------

async def get_aged_receivables(
    db: AsyncSession,
    org_id: uuid.UUID,
    report_date: date | None = None,
) -> dict:
    """Aged receivables grouping outstanding invoices into ageing buckets.

    Buckets: 0–30 days, 31–60 days, 61–90 days, 90+ days overdue.
    Per-customer and overall totals.
    Requirements: 8.1–8.3
    """
    if report_date is None:
        report_date = date.today()

    q = (
        select(
            Invoice.id.label("invoice_id"),
            Invoice.invoice_number,
            Invoice.customer_id,
            Invoice.due_date,
            Invoice.balance_due,
            Customer.first_name,
            Customer.last_name,
        )
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.org_id == org_id,
            Invoice.status != "paid",
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.balance_due > 0,
        )
    )

    result = await db.execute(q)
    rows = result.all()

    # Per-customer buckets
    customers: dict[uuid.UUID, dict] = {}
    overall = {"current": Decimal("0"), "31_60": Decimal("0"), "61_90": Decimal("0"), "90_plus": Decimal("0")}

    for r in rows:
        balance = Decimal(str(r.balance_due))
        days_overdue = (report_date - r.due_date).days if r.due_date else 0

        if days_overdue <= 30:
            bucket = "current"
        elif days_overdue <= 60:
            bucket = "31_60"
        elif days_overdue <= 90:
            bucket = "61_90"
        else:
            bucket = "90_plus"

        overall[bucket] += balance

        cust_id = r.customer_id
        if cust_id not in customers:
            customers[cust_id] = {
                "customer_id": cust_id,
                "customer_name": f"{r.first_name} {r.last_name}",
                "current": Decimal("0"),
                "31_60": Decimal("0"),
                "61_90": Decimal("0"),
                "90_plus": Decimal("0"),
                "total": Decimal("0"),
                "invoices": [],
            }

        customers[cust_id][bucket] += balance
        customers[cust_id]["total"] += balance
        customers[cust_id]["invoices"].append({
            "invoice_id": r.invoice_id,
            "invoice_number": r.invoice_number,
            "due_date": r.due_date,
            "balance_due": balance,
            "days_overdue": days_overdue,
            "bucket": bucket,
        })

    overall_total = overall["current"] + overall["31_60"] + overall["61_90"] + overall["90_plus"]

    return {
        "report_date": report_date,
        "customers": list(customers.values()),
        "overall": {
            "current": overall["current"].quantize(Decimal("0.01")),
            "31_60": overall["31_60"].quantize(Decimal("0.01")),
            "61_90": overall["61_90"].quantize(Decimal("0.01")),
            "90_plus": overall["90_plus"].quantize(Decimal("0.01")),
            "total": overall_total.quantize(Decimal("0.01")),
        },
    }


# ---------------------------------------------------------------------------
# NZ Tax Bracket Helpers (Sprint 2)
# ---------------------------------------------------------------------------

def _calculate_sole_trader_tax(taxable_income: Decimal) -> Decimal:
    """Apply NZ progressive tax brackets for sole traders.

    Brackets:
      10.5% on $0–$14,000
      17.5% on $14,001–$48,000
      30%   on $48,001–$70,000
      33%   on $70,001–$180,000
      39%   on $180,001+
    """
    income = max(taxable_income, Decimal("0"))
    brackets = [
        (Decimal("14000"), Decimal("0.105")),
        (Decimal("34000"), Decimal("0.175")),
        (Decimal("22000"), Decimal("0.30")),
        (Decimal("110000"), Decimal("0.33")),
        (None, Decimal("0.39")),  # unlimited
    ]
    tax = Decimal("0")
    remaining = income
    for width, rate in brackets:
        if remaining <= 0:
            break
        if width is None:
            taxable = remaining
        else:
            taxable = min(remaining, width)
        tax += (taxable * rate).quantize(Decimal("0.01"))
        remaining -= taxable
    return tax


def _calculate_company_tax(taxable_income: Decimal) -> Decimal:
    """Flat 28% company tax rate."""
    income = max(taxable_income, Decimal("0"))
    return (income * Decimal("0.28")).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Income Tax Estimator (Sprint 2)
# Requirements: 9.1–9.6
# ---------------------------------------------------------------------------

async def get_tax_estimate(
    db: AsyncSession,
    org_id: uuid.UUID,
    tax_year_start: date,
    tax_year_end: date,
) -> dict:
    """Income tax estimate for a tax year.

    Derives taxable_income from P&L net_profit, applies NZ brackets
    based on business_type (sole_trader progressive / company 28% flat).
    Computes provisional_tax = prior year tax × 1.05.
    Requirements: 9.1–9.6
    """
    # Get business_type from organisations table (Sprint 7 column)
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org_row = org_result.scalar_one_or_none()
    business_type = (getattr(org_row, "business_type", None) or "sole_trader") if org_row else "sole_trader"

    # Get P&L for the tax year
    pnl = await get_profit_loss(db, org_id, tax_year_start, tax_year_end, basis="accrual")
    taxable_income = pnl["net_profit"]

    # Calculate estimated tax
    if business_type == "company":
        estimated_tax = _calculate_company_tax(taxable_income)
    else:
        estimated_tax = _calculate_sole_trader_tax(taxable_income)

    effective_rate = (
        (estimated_tax / taxable_income * 100).quantize(Decimal("0.01"))
        if taxable_income > 0
        else Decimal("0")
    )

    # Provisional tax: prior year tax × 1.05
    # Get prior year P&L
    prior_year_start = tax_year_start.replace(year=tax_year_start.year - 1)
    prior_year_end = tax_year_end.replace(year=tax_year_end.year - 1)
    prior_pnl = await get_profit_loss(db, org_id, prior_year_start, prior_year_end, basis="accrual")
    prior_income = prior_pnl["net_profit"]

    if business_type == "company":
        prior_tax = _calculate_company_tax(prior_income)
    else:
        prior_tax = _calculate_sole_trader_tax(prior_income)

    provisional_tax_amount = (prior_tax * Decimal("1.05")).quantize(Decimal("0.01"))

    # Next provisional due date: NZ provisional tax dates are 28 Aug, 15 Jan, 7 May
    # for standard method. Use the next upcoming date.
    today = date.today()
    prov_dates = [
        date(today.year, 8, 28),
        date(today.year + 1, 1, 15),
        date(today.year + 1, 5, 7),
    ]
    next_provisional_due = None
    for d in sorted(prov_dates):
        if d >= today:
            next_provisional_due = d
            break
    if next_provisional_due is None:
        next_provisional_due = date(today.year + 1, 8, 28)

    return {
        "currency": "NZD",
        "business_type": business_type,
        "taxable_income": taxable_income.quantize(Decimal("0.01")),
        "estimated_tax": estimated_tax,
        "effective_rate": effective_rate,
        "provisional_tax_amount": provisional_tax_amount,
        "next_provisional_due_date": next_provisional_due,
        "already_paid": Decimal("0.00"),
        "balance_owing": estimated_tax,
        "tax_year_start": tax_year_start,
        "tax_year_end": tax_year_end,
    }


# ---------------------------------------------------------------------------
# Tax Position Dashboard (Sprint 2)
# Requirements: 10.1, 10.2
# ---------------------------------------------------------------------------

async def get_tax_position(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Combined GST + income tax position with next due dates.

    Combines GST owing (from get_gst_return), income tax estimate
    (from get_tax_estimate), and next due dates.
    Must return within 2 seconds for dashboard polling.
    Requirements: 10.1, 10.2
    """
    today = date.today()

    # Current GST period: use current 2-month period
    # NZ GST periods are typically 2-monthly aligned to odd months
    gst_period_start_month = today.month if today.month % 2 == 1 else today.month - 1
    gst_period_start = today.replace(month=gst_period_start_month, day=1)
    if gst_period_start_month + 1 <= 12:
        gst_period_end_month = gst_period_start_month + 1
        gst_period_end_year = today.year
    else:
        gst_period_end_month = 1
        gst_period_end_year = today.year + 1
    # End of the 2-month period
    last_day = calendar.monthrange(gst_period_end_year, gst_period_end_month)[1]
    gst_period_end = date(gst_period_end_year, gst_period_end_month, last_day)

    gst_return = await get_gst_return(db, org_id, gst_period_start, gst_period_end)
    gst_owing = gst_return.get("net_gst_payable", Decimal("0"))

    # Next GST due date: 28th of month after period end
    if gst_period_end_month + 1 <= 12:
        next_gst_due = date(gst_period_end_year, gst_period_end_month + 1, 28)
    else:
        next_gst_due = date(gst_period_end_year + 1, 1, 28)

    # Income tax estimate for current tax year (NZ: 1 Apr – 31 Mar)
    if today.month >= 4:
        tax_year_start = date(today.year, 4, 1)
        tax_year_end = date(today.year + 1, 3, 31)
    else:
        tax_year_start = date(today.year - 1, 4, 1)
        tax_year_end = date(today.year, 3, 31)

    tax_estimate = await get_tax_estimate(db, org_id, tax_year_start, tax_year_end)
    income_tax_estimate = tax_estimate.get("estimated_tax", Decimal("0"))
    next_income_tax_due = tax_estimate.get("next_provisional_due_date")

    # ── Wallet balances + traffic lights (Sprint 5, Req 23.1, 23.2) ──
    gst_wallet_balance = Decimal("0")
    income_tax_wallet_balance = Decimal("0")
    gst_shortfall = gst_owing
    income_tax_shortfall = income_tax_estimate
    gst_traffic_light = "red" if gst_owing > 0 else "green"
    income_tax_traffic_light = "red" if income_tax_estimate > 0 else "green"

    try:
        from app.modules.tax_wallets.service import (
            list_wallets as tw_list_wallets,
            compute_traffic_light,
        )

        wallets = await tw_list_wallets(db, org_id)
        wallet_map = {w.wallet_type: w for w in wallets}

        gst_w = wallet_map.get("gst")
        if gst_w:
            gst_wallet_balance = gst_w.balance
        it_w = wallet_map.get("income_tax")
        if it_w:
            income_tax_wallet_balance = it_w.balance

        gst_shortfall = max(Decimal("0"), gst_owing - gst_wallet_balance)
        income_tax_shortfall = max(Decimal("0"), income_tax_estimate - income_tax_wallet_balance)
        gst_traffic_light = compute_traffic_light(gst_wallet_balance, gst_owing)
        income_tax_traffic_light = compute_traffic_light(income_tax_wallet_balance, income_tax_estimate)
    except Exception as exc:
        logger.warning("Could not load wallet data for tax position: %s", exc)

    return {
        "currency": "NZD",
        "gst_owing": gst_owing,
        "next_gst_due": next_gst_due,
        "income_tax_estimate": income_tax_estimate,
        "next_income_tax_due": next_income_tax_due,
        "provisional_tax_amount": tax_estimate.get("provisional_tax_amount", Decimal("0")),
        "tax_year_start": tax_year_start,
        "tax_year_end": tax_year_end,
        # Sprint 5 wallet extensions
        "gst_wallet_balance": gst_wallet_balance,
        "gst_shortfall": gst_shortfall,
        "gst_traffic_light": gst_traffic_light,
        "income_tax_wallet_balance": income_tax_wallet_balance,
        "income_tax_shortfall": income_tax_shortfall,
        "income_tax_traffic_light": income_tax_traffic_light,
    }
