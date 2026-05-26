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


# ---------------------------------------------------------------------------
# Dashboard Widget Service Functions (automotive-dashboard-widgets spec)
# ---------------------------------------------------------------------------

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, func, and_, or_, case, Date, cast

logger = logging.getLogger(__name__)


def _empty_section() -> dict:
    return {"items": [], "total": 0}


async def get_recent_customers(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Last 10 customers who had invoices created, newest first."""
    from app.modules.customers.models import Customer
    from sqlalchemy import text as sa_text

    params: dict = {"org_id": str(org_id)}
    sql = sa_text("""
        SELECT c.id AS customer_id,
               COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS customer_name,
               i.created_at AS invoice_date,
               i.vehicle_rego
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        WHERE i.org_id = :org_id AND i.status != 'voided'
        ORDER BY i.created_at DESC
        LIMIT 10
    """)
    if branch_id is not None:
        sql = sa_text("""
            SELECT c.id AS customer_id,
                   COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS customer_name,
                   i.created_at AS invoice_date,
                   i.vehicle_rego
            FROM invoices i
            JOIN customers c ON i.customer_id = c.id
            WHERE i.org_id = :org_id AND i.status != 'voided' AND i.branch_id = :branch_id
            ORDER BY i.created_at DESC
            LIMIT 10
        """)
        params["branch_id"] = str(branch_id)

    result = await db.execute(sql, params)
    rows = result.all()
    items = [
        {
            "customer_id": str(r.customer_id),
            "customer_name": r.customer_name or "Unknown",
            "invoice_date": r.invoice_date.isoformat() if r.invoice_date else "",
            "vehicle_rego": r.vehicle_rego,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


async def get_todays_bookings(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Bookings scheduled for today, sorted by start time ascending."""
    from sqlalchemy import text as sa_text
    params: dict = {"org_id": str(org_id), "today": date.today()}
    sql = sa_text("""
        SELECT b.id AS booking_id, b.start_time AS scheduled_time,
               COALESCE(b.customer_name, 'Walk-in') AS customer_name,
               b.vehicle_rego
        FROM bookings b
        WHERE b.org_id = :org_id AND b.start_time::date = :today
        ORDER BY b.start_time ASC
    """)
    if branch_id is not None:
        sql = sa_text("""
            SELECT b.id AS booking_id, b.start_time AS scheduled_time,
                   COALESCE(b.customer_name, 'Walk-in') AS customer_name,
                   b.vehicle_rego
            FROM bookings b
            WHERE b.org_id = :org_id AND b.start_time::date = :today AND b.branch_id = :branch_id
            ORDER BY b.start_time ASC
        """)
        params["branch_id"] = str(branch_id)
    result = await db.execute(sql, params)
    rows = result.all()
    return {"items": [
        {"booking_id": str(r.booking_id), "scheduled_time": r.scheduled_time.isoformat() if r.scheduled_time else "",
         "customer_name": r.customer_name or "Walk-in", "vehicle_rego": r.vehicle_rego}
        for r in rows
    ], "total": len(rows)}


async def get_public_holidays(
    db: AsyncSession, org_id: uuid.UUID
) -> dict:
    """Next 5 upcoming public holidays for the org's country."""
    try:
        # Public holidays may not have a dedicated table yet — return empty
        # until the table is created. This is safe per the per-widget error handling.
        return _empty_section()
    except Exception:
        logger.exception("get_public_holidays failed")
        return _empty_section()


async def get_inventory_overview(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Inventory grouped by catalogue_type with low-stock counts."""
    from sqlalchemy import text as sa_text
    params: dict = {"org_id": str(org_id)}
    sql = sa_text("""
        SELECT COALESCE(catalogue_type, 'other') AS category,
               COUNT(*) AS total_count,
               COUNT(*) FILTER (WHERE current_quantity <= min_threshold) AS low_stock_count
        FROM stock_items
        WHERE org_id = :org_id
        GROUP BY COALESCE(catalogue_type, 'other')
    """)
    if branch_id is not None:
        sql = sa_text("""
            SELECT COALESCE(catalogue_type, 'other') AS category,
                   COUNT(*) AS total_count,
                   COUNT(*) FILTER (WHERE current_quantity <= min_threshold) AS low_stock_count
            FROM stock_items
            WHERE org_id = :org_id AND branch_id = :branch_id
            GROUP BY COALESCE(catalogue_type, 'other')
        """)
        params["branch_id"] = str(branch_id)

    result = await db.execute(sql, params)
    rows = result.all()
    return {"items": [
        {"category": r.category or "other", "total_count": r.total_count or 0, "low_stock_count": r.low_stock_count or 0}
        for r in rows
    ], "total": len(rows)}


async def get_cash_flow(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Monthly revenue and expenses for the last 6 months."""
    from sqlalchemy import text as sa_text
    six_months_ago = date.today().replace(day=1) - timedelta(days=180)

    params: dict = {"org_id": str(org_id), "cutoff": six_months_ago}
    rev_sql = sa_text("""
        SELECT to_char(created_at, 'YYYY-MM') AS month,
               to_char(created_at, 'Mon YYYY') AS month_label,
               COALESCE(SUM(subtotal), 0) AS revenue
        FROM invoices
        WHERE org_id = :org_id AND status NOT IN ('voided', 'draft') AND created_at >= :cutoff
        GROUP BY to_char(created_at, 'YYYY-MM'), to_char(created_at, 'Mon YYYY')
        ORDER BY to_char(created_at, 'YYYY-MM')
    """)
    if branch_id is not None:
        rev_sql = sa_text("""
            SELECT to_char(created_at, 'YYYY-MM') AS month,
                   to_char(created_at, 'Mon YYYY') AS month_label,
                   COALESCE(SUM(subtotal), 0) AS revenue
            FROM invoices
            WHERE org_id = :org_id AND status NOT IN ('voided', 'draft') AND created_at >= :cutoff AND branch_id = :branch_id
            GROUP BY to_char(created_at, 'YYYY-MM'), to_char(created_at, 'Mon YYYY')
            ORDER BY to_char(created_at, 'YYYY-MM')
        """)
        params["branch_id"] = str(branch_id)

    rev_result = await db.execute(rev_sql, params)
    rev_rows = {r.month: r for r in rev_result.all()}

    # Expenses — column is "date" not "expense_date" (ISSUE-107)
    # Wrapped in savepoint so failure doesn't poison the parent transaction
    exp_map: dict[str, float] = {}
    try:
        exp_savepoint = await db.begin_nested()
        try:
            exp_params: dict = {"org_id": str(org_id), "cutoff": six_months_ago}
            exp_sql = sa_text("SELECT to_char(date, 'YYYY-MM') AS month, COALESCE(SUM(amount), 0) AS expenses FROM expenses WHERE org_id = :org_id AND date >= :cutoff GROUP BY to_char(date, 'YYYY-MM')")
            if branch_id is not None:
                exp_sql = sa_text("SELECT to_char(date, 'YYYY-MM') AS month, COALESCE(SUM(amount), 0) AS expenses FROM expenses WHERE org_id = :org_id AND date >= :cutoff AND branch_id = :branch_id GROUP BY to_char(date, 'YYYY-MM')")
                exp_params["branch_id"] = str(branch_id)
            exp_result = await db.execute(exp_sql, exp_params)
            exp_map = {r.month: float(r.expenses) for r in exp_result.all()}
        except Exception:
            await exp_savepoint.rollback()
            logger.debug("Expenses query failed in cash_flow widget — using empty data")
    except Exception:
        pass  # savepoint creation failed — skip expenses

    all_months = sorted(set(list(rev_rows.keys()) + list(exp_map.keys())))
    items = []
    for m in all_months:
        rev_row = rev_rows.get(m)
        items.append({
            "month": m,
            "month_label": rev_row.month_label if rev_row else m,
            "revenue": float(rev_row.revenue) if rev_row else 0.0,
            "expenses": exp_map.get(m, 0.0),
        })
    return {"items": items, "total": len(items)}


async def get_cash_flow_by_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    period: str = "monthly",
    days: int = 180,
) -> dict:
    """Revenue and expenses grouped by the specified period.

    period: 'daily' | 'weekly' | 'monthly'
    days: lookback window in days
    """
    from sqlalchemy import text as sa_text

    cutoff = date.today() - timedelta(days=days)

    # SQL format strings for each period type
    if period == "daily":
        date_format = "YYYY-MM-DD"
        label_format = "DD Mon"
        date_col_rev = "created_at::date"
        date_col_exp = "date"
    elif period == "weekly":
        date_format = "IYYY-IW"  # ISO year-week
        label_format = "IYYY-IW"  # Just use the key as label (W20 2026 style handled in Python)
        date_col_rev = "created_at"
        date_col_exp = "date"
    else:  # monthly (default)
        date_format = "YYYY-MM"
        label_format = "Mon YYYY"
        date_col_rev = "created_at"
        date_col_exp = "date"

    params: dict = {"org_id": str(org_id), "cutoff": cutoff}
    branch_filter = ""
    if branch_id is not None:
        branch_filter = "AND branch_id = :branch_id"
        params["branch_id"] = str(branch_id)

    rev_sql = sa_text(f"""
        SELECT to_char({date_col_rev}, '{date_format}') AS period_key,
               to_char({date_col_rev}, '{label_format}') AS period_label,
               COALESCE(SUM(subtotal), 0) AS revenue
        FROM invoices
        WHERE org_id = :org_id AND status NOT IN ('voided', 'draft')
          AND created_at >= :cutoff {branch_filter}
        GROUP BY to_char({date_col_rev}, '{date_format}'), to_char({date_col_rev}, '{label_format}')
        ORDER BY to_char({date_col_rev}, '{date_format}')
    """)

    rev_result = await db.execute(rev_sql, params)
    rev_rows = {r.period_key: r for r in rev_result.all()}

    # Expenses
    exp_map: dict[str, float] = {}
    try:
        exp_savepoint = await db.begin_nested()
        try:
            exp_params: dict = {"org_id": str(org_id), "cutoff": cutoff}
            exp_branch = ""
            if branch_id is not None:
                exp_branch = "AND branch_id = :branch_id"
                exp_params["branch_id"] = str(branch_id)

            exp_sql = sa_text(f"""
                SELECT to_char({date_col_exp}, '{date_format}') AS period_key,
                       COALESCE(SUM(amount), 0) AS expenses
                FROM expenses
                WHERE org_id = :org_id AND date >= :cutoff {exp_branch}
                GROUP BY to_char({date_col_exp}, '{date_format}')
            """)
            exp_result = await db.execute(exp_sql, exp_params)
            exp_map = {r.period_key: float(r.expenses) for r in exp_result.all()}
        except Exception:
            await exp_savepoint.rollback()
    except Exception:
        pass

    all_keys = sorted(set(list(rev_rows.keys()) + list(exp_map.keys())))
    items = []
    for k in all_keys:
        rev_row = rev_rows.get(k)
        # Build a human-readable label
        if rev_row and rev_row.period_label != k:
            label = rev_row.period_label
        elif period == "weekly" and "-" in k:
            # Convert "2026-20" to "W20"
            parts = k.split("-")
            label = f"W{parts[1]}" if len(parts) == 2 else k
        else:
            label = rev_row.period_label if rev_row else k
        items.append({
            "month": k,  # keep "month" key for frontend compat
            "month_label": label,
            "revenue": float(rev_row.revenue) if rev_row else 0.0,
            "expenses": exp_map.get(k, 0.0),
        })

    return {"items": items, "total": len(items)}


async def get_recent_invoices_by_period(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    period: str = "monthly",
    offset: int = 0,
    limit: int = 5,
) -> dict:
    """Recent invoices with profit margin data for the specified period.

    period: 'daily' (last 1 day) | 'weekly' (last 7 days) | 'monthly' (last 30 days)
    """
    from sqlalchemy import text as sa_text

    days_map = {"daily": 1, "weekly": 7, "monthly": 30}
    lookback_days = days_map.get(period, 30)
    cutoff = date.today() - timedelta(days=lookback_days)

    params: dict = {"org_id": str(org_id), "cutoff": cutoff, "lim": limit, "off": offset}
    branch_filter = ""
    if branch_id is not None:
        branch_filter = "AND i.branch_id = :branch_id"
        params["branch_id"] = str(branch_id)

    # Count total matching invoices
    count_sql = sa_text(f"""
        SELECT COUNT(*) FROM invoices i
        WHERE i.org_id = :org_id AND i.status NOT IN ('voided', 'draft')
          AND i.created_at >= :cutoff {branch_filter}
    """)
    count_result = await db.execute(count_sql, params)
    total = count_result.scalar() or 0

    # Fetch invoices with line item cost data for margin calculation
    sql = sa_text(f"""
        SELECT i.id, i.invoice_number, i.status, i.created_at,
               i.subtotal, i.total,
               COALESCE(c.display_name, c.first_name || ' ' || COALESCE(c.last_name, '')) AS customer_name,
               (SELECT COALESCE(SUM(li.cost_price * li.quantity), 0)
                FROM line_items li WHERE li.invoice_id = i.id AND li.cost_price IS NOT NULL) AS total_cost,
               COALESCE(
                   (SELECT SUM((elem->>'total_cost')::numeric)
                    FROM jsonb_array_elements(i.invoice_data_json->'fluid_usage') AS elem
                    WHERE elem->>'total_cost' IS NOT NULL), 0
               ) AS fluid_cost
        FROM invoices i
        LEFT JOIN customers c ON i.customer_id = c.id
        WHERE i.org_id = :org_id AND i.status NOT IN ('voided', 'draft')
          AND i.created_at >= :cutoff {branch_filter}
        ORDER BY i.created_at DESC
        LIMIT :lim OFFSET :off
    """)

    result = await db.execute(sql, params)
    rows = result.all()

    items = []
    for r in rows:
        revenue = float(r.subtotal or 0)
        cost = float(r.total_cost or 0) + float(r.fluid_cost or 0)
        profit = revenue - cost
        margin_pct = (profit / revenue * 100) if revenue > 0 else None
        items.append({
            "id": str(r.id),
            "invoice_number": r.invoice_number or "DRAFT",
            "customer_name": (r.customer_name or "").strip() or "Unknown",
            "status": r.status,
            "date": r.created_at.strftime("%d %b %Y") if r.created_at else "",
            "total": float(r.total or 0),
            "revenue": revenue,
            "cost": cost,
            "profit": profit,
            "margin_pct": round(margin_pct, 1) if margin_pct is not None else None,
        })

    return {"items": items, "total": int(total)}


async def get_recent_claims(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Last 10 customer claims, newest first."""
    from sqlalchemy import text as sa_text
    params: dict = {"org_id": str(org_id)}
    sql = sa_text("""
        SELECT cc.id AS claim_id, COALESCE(cc.reference, 'CLM-' || LEFT(cc.id::text, 8)) AS reference,
               COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS customer_name,
               cc.created_at AS claim_date, cc.status
        FROM customer_claims cc
        LEFT JOIN customers c ON cc.customer_id = c.id
        WHERE cc.org_id = :org_id
        ORDER BY cc.created_at DESC LIMIT 10
    """)
    if branch_id is not None:
        sql = sa_text("""
            SELECT cc.id AS claim_id, COALESCE(cc.reference, 'CLM-' || LEFT(cc.id::text, 8)) AS reference,
                   COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS customer_name,
                   cc.created_at AS claim_date, cc.status
            FROM customer_claims cc
            LEFT JOIN customers c ON cc.customer_id = c.id
            WHERE cc.org_id = :org_id AND cc.branch_id = :branch_id
            ORDER BY cc.created_at DESC LIMIT 10
        """)
        params["branch_id"] = str(branch_id)
    result = await db.execute(sql, params)
    rows = result.all()
    return {"items": [
        {"claim_id": str(r.claim_id), "reference": r.reference or "", "customer_name": r.customer_name or "Unknown",
         "claim_date": r.claim_date.isoformat() if r.claim_date else "", "status": r.status or "open"}
        for r in rows
    ], "total": len(rows)}


async def get_active_staff(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Staff currently clocked in (time entries with no end_time today)."""
    from sqlalchemy import text as sa_text
    # time_entries does NOT have branch_id — skip branch filtering for this widget
    params: dict = {"org_id": str(org_id), "today": date.today()}
    sql = sa_text("""
        SELECT u.id AS staff_id, u.email AS name, te.start_time AS clock_in_time
        FROM time_entries te
        JOIN users u ON te.user_id = u.id
        WHERE te.org_id = :org_id AND te.end_time IS NULL AND te.start_time::date = :today
    """)
    result = await db.execute(sql, params)
    rows = result.all()
    return {"items": [
        {"staff_id": str(r.staff_id), "name": r.name or "Unknown",
         "clock_in_time": r.clock_in_time.isoformat() if r.clock_in_time else ""}
        for r in rows
    ], "total": len(rows)}


async def get_expiry_reminders(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Vehicles with upcoming WOF/COF/service expiry, excluding dismissed."""
    from sqlalchemy import text as sa_text

    # Get config thresholds
    cfg_result = await db.execute(sa_text("SELECT wof_days, service_days FROM dashboard_reminder_config WHERE org_id = :org_id"), {"org_id": str(org_id)})
    cfg_row = cfg_result.first()
    wof_days = cfg_row.wof_days if cfg_row else 30
    service_days = cfg_row.service_days if cfg_row else 30

    today = date.today()
    wof_cutoff = today + timedelta(days=wof_days)
    cof_cutoff = today + timedelta(days=wof_days)  # COF uses same threshold as WOF
    service_cutoff = today + timedelta(days=service_days)

    # Get dismissed combos
    dis_result = await db.execute(sa_text("SELECT vehicle_id, reminder_type, expiry_date::text FROM dashboard_reminder_dismissals WHERE org_id = :org_id"), {"org_id": str(org_id)})
    dismissed_set = {(str(r.vehicle_id), r.reminder_type, r.expiry_date[:10]) for r in dis_result.all()}

    # Get vehicles with upcoming expiry — Task 11.3 (vehicle-data-isolation).
    #
    # The widget reads from TWO sources:
    #   1. org_vehicles directly for the calling org — every promoted
    #      vehicle (and every is_manual_entry=True row) lives here, with
    #      its customer-driven dates (wof_expiry, cof_expiry,
    #      service_due_date) stored on the OrgVehicle row.
    #   2. global_vehicles via customer_vehicles for un-promoted regos —
    #      i.e. customer_vehicles rows whose link still points at
    #      global_vehicle_id (org_vehicle_id IS NULL).
    #
    # Pre-Task-11.3 the widget joined ``org_vehicles ov ON
    # ov.global_vehicle_id = gv.id``, but ``org_vehicles.global_vehicle_id``
    # is not a column on the model — the query would error on any non-empty
    # result. The new query has no such reference.
    bind = {
        "org_id": str(org_id),
        "today": today,
        "wof_cutoff": wof_cutoff,
        "cof_cutoff": cof_cutoff,
        "service_cutoff": service_cutoff,
    }

    # Source 1: org_vehicles rows for this org (covers promoted +
    # manually-entered vehicles).
    ov_result = await db.execute(sa_text("""
        SELECT ov.id AS vehicle_id, ov.rego AS vehicle_rego, ov.make AS vehicle_make,
               ov.model AS vehicle_model, ov.wof_expiry, ov.cof_expiry,
               ov.inspection_type, ov.service_due_date
        FROM org_vehicles ov
        WHERE ov.org_id = :org_id
          AND ((ov.wof_expiry IS NOT NULL AND ov.wof_expiry >= :today AND ov.wof_expiry <= :wof_cutoff)
            OR (ov.cof_expiry IS NOT NULL AND ov.cof_expiry >= :today AND ov.cof_expiry <= :cof_cutoff)
            OR (ov.service_due_date IS NOT NULL AND ov.service_due_date >= :today AND ov.service_due_date <= :service_cutoff))
    """), bind)

    # Source 2: global_vehicles via un-promoted customer_vehicles links.
    gv_result = await db.execute(sa_text("""
        SELECT gv.id AS vehicle_id, gv.rego AS vehicle_rego, gv.make AS vehicle_make,
               gv.model AS vehicle_model, gv.wof_expiry, gv.cof_expiry,
               gv.inspection_type, gv.service_due_date
        FROM global_vehicles gv
        JOIN customer_vehicles cv ON cv.global_vehicle_id = gv.id
        WHERE cv.org_id = :org_id
          AND cv.org_vehicle_id IS NULL
          AND ((gv.wof_expiry IS NOT NULL AND gv.wof_expiry >= :today AND gv.wof_expiry <= :wof_cutoff)
            OR (gv.cof_expiry IS NOT NULL AND gv.cof_expiry >= :today AND gv.cof_expiry <= :cof_cutoff)
            OR (gv.service_due_date IS NOT NULL AND gv.service_due_date >= :today AND gv.service_due_date <= :service_cutoff))
    """), bind)

    # Concatenate; deduplicate by vehicle_id in case the same row is
    # surfaced by both sources (defensive — shouldn't normally happen).
    seen_ids: set[str] = set()
    vehicles = []
    for row in list(ov_result.all()) + list(gv_result.all()):
        rid = str(row.vehicle_id)
        if rid in seen_ids:
            continue
        seen_ids.add(rid)
        vehicles.append(row)

    items = []
    for v in vehicles:
        vid = str(v.vehicle_id)
        # Get linked customer — accept either link type since the
        # vehicle id may be an org_vehicle_id (Source 1) or a
        # global_vehicle_id (Source 2). Always scope by org_id.
        cv_result = await db.execute(sa_text("""
            SELECT c.id, COALESCE(c.display_name, c.first_name || ' ' || c.last_name) AS name
            FROM customers c JOIN customer_vehicles cv ON cv.customer_id = c.id
            WHERE (cv.org_vehicle_id = :vid OR cv.global_vehicle_id = :vid)
              AND cv.org_id = :org_id
            LIMIT 1
        """), {"vid": vid, "org_id": str(org_id)})
        cv_row = cv_result.first()
        cust_name = cv_row.name if cv_row else "Unlinked"
        cust_id = str(cv_row.id) if cv_row else ""

        # Determine which inspection expiry to show when vehicle has both
        # If vehicle has both wof_expiry and cof_expiry, display the one matching inspection_type
        has_wof = v.wof_expiry and v.wof_expiry >= today and v.wof_expiry <= wof_cutoff
        has_cof = v.cof_expiry and v.cof_expiry >= today and v.cof_expiry <= cof_cutoff

        if has_wof and has_cof:
            # Both present — show only the one matching inspection_type
            if v.inspection_type == "cof":
                has_wof = False
            else:
                has_cof = False

        if has_wof:
            exp_str = str(v.wof_expiry)[:10]
            if (vid, "wof", exp_str) not in dismissed_set:
                items.append({"vehicle_id": vid, "vehicle_rego": v.vehicle_rego or "", "vehicle_make": v.vehicle_make,
                              "vehicle_model": v.vehicle_model, "expiry_type": "wof", "expiry_date": exp_str,
                              "customer_name": cust_name, "customer_id": cust_id})

        if has_cof:
            exp_str = str(v.cof_expiry)[:10]
            if (vid, "cof", exp_str) not in dismissed_set:
                items.append({"vehicle_id": vid, "vehicle_rego": v.vehicle_rego or "", "vehicle_make": v.vehicle_make,
                              "vehicle_model": v.vehicle_model, "expiry_type": "cof", "expiry_date": exp_str,
                              "customer_name": cust_name, "customer_id": cust_id})

        if v.service_due_date and v.service_due_date >= today and v.service_due_date <= service_cutoff:
            exp_str = str(v.service_due_date)[:10]
            if (vid, "service", exp_str) not in dismissed_set:
                items.append({"vehicle_id": vid, "vehicle_rego": v.vehicle_rego or "", "vehicle_make": v.vehicle_make,
                              "vehicle_model": v.vehicle_model, "expiry_type": "service", "expiry_date": exp_str,
                              "customer_name": cust_name, "customer_id": cust_id})

    items.sort(key=lambda x: x.get("expiry_date", ""))
    return {"items": items, "total": len(items)}


async def get_reminder_config(
    db: AsyncSession, org_id: uuid.UUID
) -> dict:
    """Get the org's reminder threshold config, or defaults."""
    from sqlalchemy import text as sa_text
    result = await db.execute(sa_text("SELECT wof_days, service_days FROM dashboard_reminder_config WHERE org_id = :org_id"), {"org_id": str(org_id)})
    row = result.first()
    if row:
        return {"wof_days": row.wof_days, "service_days": row.service_days}
    return {"wof_days": 30, "service_days": 30}


async def update_reminder_config(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID,
    wof_days: int, service_days: int
) -> dict:
    """Upsert the org's reminder threshold config."""
    from app.modules.organisations.models import DashboardReminderConfig

    result = await db.execute(
        select(DashboardReminderConfig).where(DashboardReminderConfig.org_id == org_id)
    )
    config = result.scalar_one_or_none()
    if config:
        config.wof_days = wof_days
        config.service_days = service_days
        config.updated_by = user_id
        config.updated_at = datetime.now(timezone.utc)
    else:
        config = DashboardReminderConfig(
            org_id=org_id,
            wof_days=wof_days,
            service_days=service_days,
            updated_by=user_id,
        )
        db.add(config)
    await db.flush()
    await db.refresh(config)
    return {"wof_days": config.wof_days, "service_days": config.service_days}


async def dismiss_reminder(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID,
    vehicle_id: str, reminder_type: str, expiry_date: str, action: str
) -> dict:
    """Create a dismissal record (idempotent)."""
    from app.modules.organisations.models import DashboardReminderDismissal

    vid = uuid.UUID(vehicle_id)
    exp_date = datetime.strptime(expiry_date[:10], "%Y-%m-%d").date()

    # Check if already dismissed
    existing = await db.execute(
        select(DashboardReminderDismissal).where(
            DashboardReminderDismissal.org_id == org_id,
            DashboardReminderDismissal.vehicle_id == vid,
            DashboardReminderDismissal.reminder_type == reminder_type,
            cast(DashboardReminderDismissal.expiry_date, Date) == exp_date,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        return {"id": str(row.id), "action": row.action, "status": "already_exists"}

    dismissal = DashboardReminderDismissal(
        org_id=org_id,
        vehicle_id=vid,
        reminder_type=reminder_type,
        action=action,
        expiry_date=exp_date,
        dismissed_by=user_id,
    )
    db.add(dismissal)
    await db.flush()
    await db.refresh(dismissal)
    return {"id": str(dismissal.id), "action": dismissal.action, "status": "created"}


async def get_all_widget_data(
    db: AsyncSession, org_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> dict:
    """Aggregate all widget data in one call.

    Each widget query runs inside a SAVEPOINT so that if one fails
    (e.g. missing table, bad column), the transaction isn't poisoned
    for subsequent widgets. See ISSUE-044 / performance-and-resilience
    steering doc for the pattern.
    """
    async def _safe_call(name: str, coro):
        try:
            savepoint = await db.begin_nested()
            try:
                result = await coro
                return result
            except Exception:
                await savepoint.rollback()
                logger.exception("Widget: %s failed", name)
                return _empty_section()
        except Exception:
            logger.exception("Widget: %s savepoint failed", name)
            return _empty_section()

    recent_customers = await _safe_call("recent_customers", get_recent_customers(db, org_id, branch_id))
    todays_bookings = await _safe_call("todays_bookings", get_todays_bookings(db, org_id, branch_id))
    public_holidays = await _safe_call("public_holidays", get_public_holidays(db, org_id))
    inventory_overview = await _safe_call("inventory_overview", get_inventory_overview(db, org_id, branch_id))
    cash_flow = await _safe_call("cash_flow", get_cash_flow(db, org_id, branch_id))
    recent_claims = await _safe_call("recent_claims", get_recent_claims(db, org_id, branch_id))
    active_staff = await _safe_call("active_staff", get_active_staff(db, org_id, branch_id))
    expiry_reminders = await _safe_call("expiry_reminders", get_expiry_reminders(db, org_id, branch_id))

    # Reminder config returns a dict, not a section
    try:
        savepoint = await db.begin_nested()
        try:
            reminder_config = await get_reminder_config(db, org_id)
        except Exception:
            await savepoint.rollback()
            logger.exception("Widget: reminder_config failed")
            reminder_config = {"wof_days": 30, "service_days": 30}
    except Exception:
        reminder_config = {"wof_days": 30, "service_days": 30}

    return {
        "recent_customers": recent_customers,
        "todays_bookings": todays_bookings,
        "public_holidays": public_holidays,
        "inventory_overview": inventory_overview,
        "cash_flow": cash_flow,
        "recent_claims": recent_claims,
        "active_staff": active_staff,
        "expiry_reminders": expiry_reminders,
        "reminder_config": reminder_config,
    }
