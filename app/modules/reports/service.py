"""Service layer for org-level reports.

Requirements: 45.1, 45.2, 45.3, 45.4, 45.5, 45.6, 45.7, 66.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.customers.models import Customer, FleetAccount
from app.modules.invoices.models import CreditNote, Invoice, LineItem
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

    Excludes voided invoices from revenue reporting (Req 19.7).
    Accounts for refunds (credit notes + refund payments) in the period.
    When branch_id is provided, scopes data to that branch only.
    Requirements: 20.1
    """
    inv_query = select(
        func.coalesce(func.sum(Invoice.subtotal), 0).label("total_revenue"),
        func.coalesce(func.sum(Invoice.gst_amount), 0).label("total_gst"),
        func.coalesce(func.sum(Invoice.total), 0).label("total_inclusive"),
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
    total_rev = Decimal(str(row.total_inclusive or 0))
    total_revenue_ex = Decimal(str(row.total_revenue or 0))
    total_gst = Decimal(str(row.total_gst or 0))
    avg = (total_rev / count) if count > 0 else Decimal("0")

    # Refunds: credit notes + refund payments in the period
    cn_result = await db.execute(
        select(
            func.coalesce(func.sum(CreditNote.amount), 0).label("cn_refunds"),
        )
        .where(
            CreditNote.org_id == org_id,
            func.date(CreditNote.created_at) >= period_start,
            func.date(CreditNote.created_at) <= period_end,
        )
    )
    cn_refunds = Decimal(str(cn_result.scalar() or 0))

    pay_refund_result = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount), 0).label("pay_refunds"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.is_refund == True,  # noqa: E712
            func.date(Payment.created_at) >= period_start,
            func.date(Payment.created_at) <= period_end,
        )
    )
    pay_refunds = Decimal(str(pay_refund_result.scalar() or 0))

    total_refunds = cn_refunds + pay_refunds
    gst_rate = Decimal("3") / Decimal("23")
    refund_gst = (total_refunds * gst_rate).quantize(Decimal("0.01"))
    refund_ex_gst = total_refunds - refund_gst

    net_revenue = total_revenue_ex - refund_ex_gst
    net_gst = total_gst - refund_gst

    return {
        "total_revenue": total_revenue_ex,
        "total_gst": total_gst,
        "total_inclusive": total_rev,
        "invoice_count": count,
        "average_invoice": avg.quantize(Decimal("0.01")),
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

    Separates standard-rated and zero-rated (GST-exempt) line items.
    Accounts for refunds/credit notes processed within the period,
    using the credit note's created_at date (not the original invoice date).
    When branch_id is provided, scopes data to that branch only.
    Req 45.6, 20.2
    """
    # Standard-rated items (not GST-exempt)
    std_query = (
        select(
            func.coalesce(func.sum(LineItem.line_total), 0).label("std_sales"),
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
    std_sales = Decimal(str(std_result.scalar() or 0))

    # Zero-rated / GST-exempt items
    zero_query = (
        select(
            func.coalesce(func.sum(LineItem.line_total), 0).label("zero_sales"),
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
    zero_sales = Decimal(str(zero_result.scalar() or 0))

    # Total GST collected from invoices
    gst_query = select(
        func.coalesce(func.sum(Invoice.gst_amount), 0).label("total_gst"),
        func.coalesce(func.sum(Invoice.total), 0).label("total_sales"),
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
    total_gst = Decimal(str(gst_row.total_gst or 0))
    total_sales = Decimal(str(gst_row.total_sales or 0))

    # Refunds processed within the period — from both sources:
    # 1. Credit notes (created via credit note flow)
    # 2. Refund payments (created via process_refund with is_refund=True)
    cn_result = await db.execute(
        select(
            func.coalesce(func.sum(CreditNote.amount), 0).label("cn_refunds"),
        )
        .where(
            CreditNote.org_id == org_id,
            func.date(CreditNote.created_at) >= period_start,
            func.date(CreditNote.created_at) <= period_end,
        )
    )
    cn_refunds = Decimal(str(cn_result.scalar() or 0))

    pay_refund_result = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount), 0).label("pay_refunds"),
        )
        .where(
            Payment.org_id == org_id,
            Payment.is_refund == True,  # noqa: E712
            func.date(Payment.created_at) >= period_start,
            func.date(Payment.created_at) <= period_end,
        )
    )
    pay_refunds = Decimal(str(pay_refund_result.scalar() or 0))

    total_refunds = cn_refunds + pay_refunds

    # GST component of refunds: refund amounts are GST-inclusive at 15%
    # GST portion = refund_amount * 3/23 (i.e. 15/115)
    gst_rate = Decimal("3") / Decimal("23")
    refund_gst = (total_refunds * gst_rate).quantize(Decimal("0.01"))

    # Adjusted figures
    adjusted_total_sales = total_sales - total_refunds
    adjusted_gst = total_gst - refund_gst
    adjusted_std_gst = total_gst - refund_gst

    return {
        "total_sales": total_sales,
        "total_gst_collected": total_gst,
        "net_gst": adjusted_gst,
        "standard_rated_sales": std_sales,
        "standard_rated_gst": adjusted_std_gst,
        "zero_rated_sales": zero_sales,
        "total_refunds": total_refunds,
        "refund_gst": refund_gst,
        "adjusted_total_sales": adjusted_total_sales,
        "adjusted_gst_collected": adjusted_gst,
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
