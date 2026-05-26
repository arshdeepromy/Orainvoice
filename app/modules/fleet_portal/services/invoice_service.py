"""Invoice list/detail/PDF for fleet account admins (delegating).

Implements: B2B Fleet Portal task 13.1 — Requirements 13.1–13.7.

This service queries invoices directly by the fleet account's
customer_id and org_id, bypassing the token-based portal service.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal.dependencies import FleetSessionCtx


async def list_invoices(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    status_filter: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[S.InvoiceListItem], int]:
    """Return paginated invoices for the fleet's customer."""
    from app.modules.invoices.models import Invoice
    from app.modules.fleet_portal.models import PortalFleetAccount

    if ctx.fleet_account_id is None:
        return [], 0

    # Get the customer_id from the fleet account
    fa_res = await db.execute(
        select(PortalFleetAccount.customer_id).where(
            PortalFleetAccount.id == ctx.fleet_account_id
        )
    )
    fa_row = fa_res.first()
    if fa_row is None:
        return [], 0
    customer_id = fa_row[0]

    # Base filter
    base_filter = [
        Invoice.customer_id == customer_id,
        Invoice.org_id == ctx.org_id,
        Invoice.status.notin_(["draft", "voided"]),
    ]

    if status_filter and status_filter != "all":
        if status_filter == "unpaid":
            base_filter.append(Invoice.status.in_(["sent", "partial"]))
        elif status_filter == "paid":
            base_filter.append(Invoice.status == "paid")
        elif status_filter == "overdue":
            base_filter.append(Invoice.status == "overdue")

    # Count
    count_q = select(sa_func.count(Invoice.id)).where(*base_filter)
    total = int((await db.execute(count_q)).scalar() or 0)

    # Fetch
    stmt = (
        select(Invoice)
        .where(*base_filter)
        .order_by(Invoice.issue_date.desc().nullslast(), Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items: list[S.InvoiceListItem] = []
    for inv in rows:
        items.append(
            S.InvoiceListItem(
                invoice_id=inv.id,
                invoice_number=getattr(inv, "invoice_number", "") or str(inv.id)[:8],
                customer_vehicle_id=None,
                rego=None,
                issue_date=inv.issue_date,
                due_date=getattr(inv, "due_date", None),
                total=Decimal(str(getattr(inv, "total", 0) or 0)),
                amount_paid=Decimal(str(getattr(inv, "amount_paid", 0) or 0)),
                amount_outstanding=Decimal(str(getattr(inv, "balance_due", 0) or getattr(inv, "total", 0) or 0)),
                status=inv.status or "sent",
            )
        )

    return items, total


__all__ = ["list_invoices"]
