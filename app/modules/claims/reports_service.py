"""Service layer for Claims Reports.

Provides aggregated reporting queries for claims data.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.claims.models import CustomerClaim
from app.modules.job_cards.models import JobCard
from app.modules.products.models import Product
from app.modules.staff.models import StaffMember
from app.modules.stock.models import StockMovement


def _apply_date_and_branch_filters(query, *, date_from: date | None, date_to: date | None, branch_id: uuid.UUID | None):
    """Apply common date range and branch filters to a query on CustomerClaim."""
    if date_from is not None:
        query = query.where(
            CustomerClaim.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc)
        )
    if date_to is not None:
        query = query.where(
            CustomerClaim.created_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc)
        )
    if branch_id is not None:
        query = query.where(CustomerClaim.branch_id == branch_id)
    return query


# ---------------------------------------------------------------------------
# 9.1  Claims by Period Report
# Requirements: 10.1, 10.5, 10.6
# ---------------------------------------------------------------------------


async def get_claims_by_period_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Return claim_count, total_cost, average_resolution_time grouped by month.

    Requirements: 10.1, 10.5, 10.6
    """
    period_expr = func.date_trunc("month", CustomerClaim.created_at)

    # Average resolution time in hours (resolved_at - created_at)
    avg_resolution = func.avg(
        func.extract(
            "epoch",
            CustomerClaim.resolved_at - CustomerClaim.created_at,
        )
    ) / 3600  # convert seconds to hours

    query = (
        select(
            period_expr.label("period"),
            func.count(CustomerClaim.id).label("claim_count"),
            func.coalesce(func.sum(CustomerClaim.cost_to_business), 0).label("total_cost"),
            avg_resolution.label("average_resolution_hours"),
        )
        .where(CustomerClaim.org_id == org_id)
        .group_by(period_expr)
        .order_by(period_expr)
    )

    query = _apply_date_and_branch_filters(query, date_from=date_from, date_to=date_to, branch_id=branch_id)

    result = await db.execute(query)
    rows = result.all()

    periods = []
    for row in rows:
        periods.append({
            "period": row.period.isoformat() if row.period else None,
            "claim_count": row.claim_count,
            "total_cost": Decimal(str(row.total_cost)),
            "average_resolution_hours": round(float(row.average_resolution_hours or 0), 2),
        })

    return {"periods": periods}


# ---------------------------------------------------------------------------
# 9.2  Cost Overhead Report
# Requirements: 10.2, 10.5, 10.6
# ---------------------------------------------------------------------------


async def get_cost_overhead_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Return total_refunds, total_credit_notes, total_write_offs, total_labour_cost.

    Requirements: 10.2, 10.5, 10.6
    """
    # Count by resolution type and sum costs from cost_breakdown JSON
    total_refunds = func.coalesce(
        func.sum(
            case(
                (CustomerClaim.resolution_type.in_(["full_refund", "partial_refund"]),
                 CustomerClaim.resolution_amount),
                else_=Decimal("0"),
            )
        ),
        0,
    )

    total_credit_notes = func.coalesce(
        func.sum(
            case(
                (CustomerClaim.resolution_type == "credit_note",
                 CustomerClaim.resolution_amount),
                else_=Decimal("0"),
            )
        ),
        0,
    )

    # Extract write_off_cost and labour_cost from JSONB cost_breakdown
    total_write_offs = func.coalesce(
        func.sum(
            (CustomerClaim.cost_breakdown["write_off_cost"].as_float())
        ),
        0,
    )

    total_labour_cost = func.coalesce(
        func.sum(
            (CustomerClaim.cost_breakdown["labour_cost"].as_float())
        ),
        0,
    )

    query = (
        select(
            total_refunds.label("total_refunds"),
            total_credit_notes.label("total_credit_notes"),
            total_write_offs.label("total_write_offs"),
            total_labour_cost.label("total_labour_cost"),
        )
        .where(CustomerClaim.org_id == org_id)
    )

    query = _apply_date_and_branch_filters(query, date_from=date_from, date_to=date_to, branch_id=branch_id)

    result = await db.execute(query)
    row = result.one()

    return {
        "total_refunds": Decimal(str(row.total_refunds)),
        "total_credit_notes": Decimal(str(row.total_credit_notes)),
        "total_write_offs": Decimal(str(round(float(row.total_write_offs), 2))),
        "total_labour_cost": Decimal(str(round(float(row.total_labour_cost), 2))),
    }


# ---------------------------------------------------------------------------
# 9.3  Supplier Quality Report
# Requirements: 10.3, 10.5, 10.6
# ---------------------------------------------------------------------------


async def get_supplier_quality_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = 20,
) -> dict:
    """Return parts with highest return rates.

    Joins claims → stock_movements (reference_type='claim') → products
    to find which products have the most returns via claims.

    Requirements: 10.3, 10.5, 10.6
    """
    query = (
        select(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Product.sku.label("sku"),
            func.count(StockMovement.id).label("return_count"),
        )
        .select_from(CustomerClaim)
        .join(
            StockMovement,
            (StockMovement.reference_type == "claim")
            & (StockMovement.reference_id == CustomerClaim.id),
        )
        .join(Product, Product.id == StockMovement.product_id)
        .where(CustomerClaim.org_id == org_id)
        .where(StockMovement.movement_type == "return")
        .group_by(Product.id, Product.name, Product.sku)
        .order_by(func.count(StockMovement.id).desc())
        .limit(limit)
    )

    query = _apply_date_and_branch_filters(query, date_from=date_from, date_to=date_to, branch_id=branch_id)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for row in rows:
        items.append({
            "product_id": row.product_id,
            "product_name": row.product_name,
            "sku": row.sku,
            "return_count": row.return_count,
        })

    return {"items": items}


# ---------------------------------------------------------------------------
# 9.4  Service Quality Report
# Requirements: 10.4, 10.5, 10.6
# ---------------------------------------------------------------------------


async def get_service_quality_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = 20,
) -> dict:
    """Return technicians with most redo claims.

    Joins claims (claim_type='service_redo') → job_cards (original) → staff_members
    to find which technicians have the most redo claims against their work.

    Requirements: 10.4, 10.5, 10.6
    """
    query = (
        select(
            StaffMember.id.label("staff_id"),
            StaffMember.name.label("staff_name"),
            func.count(CustomerClaim.id).label("redo_count"),
        )
        .select_from(CustomerClaim)
        .join(JobCard, JobCard.id == CustomerClaim.job_card_id)
        .join(StaffMember, StaffMember.id == JobCard.assigned_to)
        .where(CustomerClaim.org_id == org_id)
        .where(CustomerClaim.claim_type == "service_redo")
        .group_by(StaffMember.id, StaffMember.name)
        .order_by(func.count(CustomerClaim.id).desc())
        .limit(limit)
    )

    query = _apply_date_and_branch_filters(query, date_from=date_from, date_to=date_to, branch_id=branch_id)

    result = await db.execute(query)
    rows = result.all()

    items = []
    for row in rows:
        items.append({
            "staff_id": row.staff_id,
            "staff_name": row.staff_name,
            "redo_count": row.redo_count,
        })

    return {"items": items}
