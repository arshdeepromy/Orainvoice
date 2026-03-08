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
from app.modules.storage.service import calculate_org_storage, determine_alert_level


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
) -> dict:
    """Revenue summary for the organisation within the date range.

    Excludes voided invoices from revenue reporting (Req 19.7).
    """
    result = await db.execute(
        select(
            func.coalesce(func.sum(Invoice.subtotal), 0).label("total_revenue"),
            func.coalesce(func.sum(Invoice.gst_amount), 0).label("total_gst"),
            func.coalesce(func.sum(Invoice.total), 0).label("total_inclusive"),
            func.count(Invoice.id).label("invoice_count"),
        )
        .where(
            Invoice.org_id == org_id,
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    row = result.one()
    count = row.invoice_count or 0
    total_rev = Decimal(str(row.total_inclusive or 0))
    avg = (total_rev / count) if count > 0 else Decimal("0")
    return {
        "total_revenue": Decimal(str(row.total_revenue or 0)),
        "total_gst": Decimal(str(row.total_gst or 0)),
        "total_inclusive": total_rev,
        "invoice_count": count,
        "average_invoice": avg.quantize(Decimal("0.01")),
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
) -> dict:
    """All invoices with an outstanding balance (issued, partially_paid, overdue)."""
    today = date.today()
    result = await db.execute(
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
        .order_by(Invoice.due_date.asc().nullslast())
    )
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
) -> dict:
    """GST return summary formatted for IRD filing.

    Separates standard-rated and zero-rated (GST-exempt) line items.
    Req 45.6
    """
    # Standard-rated items (not GST-exempt)
    std_result = await db.execute(
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
    std_sales = Decimal(str(std_result.scalar() or 0))

    # Zero-rated / GST-exempt items
    zero_result = await db.execute(
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
    zero_sales = Decimal(str(zero_result.scalar() or 0))

    # Total GST collected from invoices
    gst_result = await db.execute(
        select(
            func.coalesce(func.sum(Invoice.gst_amount), 0).label("total_gst"),
            func.coalesce(func.sum(Invoice.total), 0).label("total_sales"),
        )
        .where(
            Invoice.org_id == org_id,
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
    )
    gst_row = gst_result.one()
    total_gst = Decimal(str(gst_row.total_gst or 0))
    total_sales = Decimal(str(gst_row.total_sales or 0))

    # Standard-rated GST = total GST (zero-rated items contribute 0 GST)
    return {
        "total_sales": total_sales,
        "total_gst_collected": total_gst,
        "net_gst": total_gst,  # simplified — no input tax credits in scope
        "standard_rated_sales": std_sales,
        "standard_rated_gst": total_gst,
        "zero_rated_sales": zero_sales,
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
) -> dict:
    """Printable customer statement with invoices and payments.

    Req 45.7
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
    inv_result = await db.execute(
        select(Invoice)
        .where(
            Invoice.org_id == org_id,
            Invoice.customer_id == customer_id,
            Invoice.status != "voided",
            Invoice.status != "draft",
            Invoice.issue_date >= period_start,
            Invoice.issue_date <= period_end,
        )
        .order_by(Invoice.issue_date.asc())
    )
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
) -> dict:
    """Carjam API usage for the organisation."""
    result = await db.execute(
        select(
            Organisation.carjam_lookups_this_month,
            Organisation.carjam_lookups_reset_at,
            SubscriptionPlan.carjam_lookups_included,
        )
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    row = result.one_or_none()
    if not row:
        return {
            "lookups_this_month": 0,
            "lookups_included": 0,
            "overage_lookups": 0,
            "reset_at": None,
        }
    lookups = row.carjam_lookups_this_month or 0
    included = row.carjam_lookups_included or 0
    overage = max(0, lookups - included)
    return {
        "lookups_this_month": lookups,
        "lookups_included": included,
        "overage_lookups": overage,
        "reset_at": row.carjam_lookups_reset_at,
    }


# ---------------------------------------------------------------------------
# SMS Usage Report
# ---------------------------------------------------------------------------

async def get_sms_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """SMS usage for the organisation.

    Delegates to the admin service's get_org_sms_usage and adds reset_at.
    Requirements: 7.1
    """
    from app.modules.admin.service import get_org_sms_usage

    try:
        usage = await get_org_sms_usage(db, org_id)
    except ValueError:
        return {
            "total_sent": 0,
            "included_in_plan": 0,
            "package_credits_remaining": 0,
            "effective_quota": 0,
            "overage_count": 0,
            "overage_charge_nzd": 0.0,
            "per_sms_cost_nzd": 0.0,
            "reset_at": None,
        }

    # Fetch reset_at from the organisation record
    result = await db.execute(
        select(Organisation.sms_sent_reset_at).where(Organisation.id == org_id)
    )
    reset_at = result.scalar()

    return {
        "total_sent": usage["total_sent"],
        "included_in_plan": usage["included_in_plan"],
        "package_credits_remaining": usage["package_credits_remaining"],
        "effective_quota": usage["effective_quota"],
        "overage_count": usage["overage_count"],
        "overage_charge_nzd": usage["overage_charge_nzd"],
        "per_sms_cost_nzd": usage["per_sms_cost_nzd"],
        "reset_at": reset_at,
    }


# ---------------------------------------------------------------------------
# Storage Usage Report
# ---------------------------------------------------------------------------

async def get_storage_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> dict:
    """Storage usage for the organisation."""
    used_bytes = await calculate_org_storage(db, org_id)

    # Get quota
    result = await db.execute(
        select(Organisation.storage_quota_gb).where(Organisation.id == org_id)
    )
    quota_gb = result.scalar() or 1
    quota_bytes = quota_gb * 1_073_741_824  # 1 GB in bytes
    percentage = (used_bytes / quota_bytes * 100) if quota_bytes > 0 else 0.0
    alert = determine_alert_level(percentage)
    return {
        "storage_used_bytes": used_bytes,
        "storage_quota_bytes": quota_bytes,
        "usage_percentage": round(percentage, 2),
        "alert_level": alert,
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
