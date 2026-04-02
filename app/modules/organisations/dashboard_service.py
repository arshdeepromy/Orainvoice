"""Branch dashboard service — metrics and comparison views.

Provides aggregated and per-branch metrics for the organisation dashboard,
including revenue, invoice count/value, customer count, staff count, and
expense breakdown.

Requirements: 15.1, 15.2, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoices.models import Invoice
from app.modules.customers.models import Customer
from app.modules.organisations.models import Branch


async def get_branch_metrics(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Return dashboard metrics scoped to a branch or aggregated org-wide.

    Metrics returned:
    - revenue: total invoice revenue (non-voided, non-draft)
    - invoice_count: number of invoices
    - invoice_value: total invoice value
    - customer_count: number of customers
    - staff_count: number of users assigned to the branch
    - expenses: total expense amount

    When branch_id is None, returns org-wide aggregated metrics.
    Requirements: 15.1, 15.2, 15.3, 15.4
    """
    # --- Revenue & invoice metrics ---
    inv_query = select(
        func.count(Invoice.id).label("invoice_count"),
        func.coalesce(func.sum(Invoice.total), 0).label("invoice_value"),
        func.coalesce(func.sum(Invoice.subtotal), 0).label("revenue"),
    ).where(
        Invoice.org_id == org_id,
        Invoice.status != "voided",
        Invoice.status != "draft",
    )
    if branch_id is not None:
        inv_query = inv_query.where(Invoice.branch_id == branch_id)

    inv_result = await db.execute(inv_query)
    inv_row = inv_result.one()

    revenue = Decimal(str(inv_row.revenue or 0))
    invoice_count = inv_row.invoice_count or 0
    invoice_value = Decimal(str(inv_row.invoice_value or 0))

    # --- Customer count ---
    cust_query = select(func.count(Customer.id)).where(
        Customer.org_id == org_id,
    )
    if branch_id is not None:
        cust_query = cust_query.where(
            (Customer.branch_id == branch_id) | (Customer.branch_id.is_(None))
        )

    cust_result = await db.execute(cust_query)
    customer_count = cust_result.scalar() or 0

    # --- Staff count ---
    from app.modules.auth.models import User

    staff_query = select(func.count(User.id)).where(
        User.org_id == org_id,
        User.is_active == True,  # noqa: E712
    )
    if branch_id is not None:
        # Users whose branch_ids JSON array contains the branch_id
        staff_query = staff_query.where(
            User.branch_ids.op("@>")(func.cast(f'["{branch_id}"]', type_=User.branch_ids.type))
        )

    staff_result = await db.execute(staff_query)
    staff_count = staff_result.scalar() or 0

    # --- Expense breakdown ---
    try:
        from app.modules.expenses.models import Expense

        exp_query = select(
            func.coalesce(func.sum(Expense.amount), 0).label("total_expenses"),
        ).where(
            Expense.org_id == org_id,
        )
        if branch_id is not None:
            exp_query = exp_query.where(Expense.branch_id == branch_id)

        exp_result = await db.execute(exp_query)
        total_expenses = Decimal(str(exp_result.scalar() or 0))
    except Exception:
        total_expenses = Decimal("0")

    return {
        "branch_id": str(branch_id) if branch_id else None,
        "revenue": revenue,
        "invoice_count": invoice_count,
        "invoice_value": invoice_value,
        "customer_count": customer_count,
        "staff_count": staff_count,
        "total_expenses": total_expenses,
    }


async def get_branch_comparison(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_ids: list[uuid.UUID],
) -> dict:
    """Return side-by-side metrics for selected branches.

    Fetches metrics for each branch individually and returns them
    in a list for comparison. Also computes highlights (best/worst
    per metric).

    Requirements: 16.1, 16.2, 16.3, 16.4
    """
    if not branch_ids:
        return {"branches": [], "highlights": {}}

    # Validate branches belong to org
    branch_query = select(Branch).where(
        Branch.org_id == org_id,
        Branch.id.in_(branch_ids),
    )
    branch_result = await db.execute(branch_query)
    valid_branches = {b.id: b.name for b in branch_result.scalars().all()}

    branch_metrics = []
    for bid in branch_ids:
        if bid not in valid_branches:
            continue
        metrics = await get_branch_metrics(db, org_id, branch_id=bid)
        metrics["branch_name"] = valid_branches[bid]
        branch_metrics.append(metrics)

    # Compute highlights — best and worst per metric
    highlights = {}
    for metric_key in ("revenue", "invoice_count", "customer_count", "total_expenses"):
        if not branch_metrics:
            break
        values = [(m["branch_name"], m[metric_key]) for m in branch_metrics]
        best = max(values, key=lambda x: x[1])
        worst = min(values, key=lambda x: x[1])
        highlights[metric_key] = {
            "highest": {"branch": best[0], "value": best[1]},
            "lowest": {"branch": worst[0], "value": worst[1]},
        }

    return {
        "branches": branch_metrics,
        "highlights": highlights,
    }
