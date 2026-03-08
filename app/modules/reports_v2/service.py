"""Enhanced reporting service — dispatcher + report generators.

ReportService.generate_report() routes to specific generators based on
report_type. Each generator queries the relevant module tables and returns
a typed Pydantic report model.

**Validates: Task 54.1–54.10 — Enhanced Reporting System**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, case, distinct, extract, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports_v2.schemas import (
    AvgCompletionTimeItem,
    AvgCompletionTimeReport,
    AvgOrderValueReport,
    BASReport,
    DailySalesByMethodItem,
    DailySalesSummaryReport,
    DeadStockItem,
    DeadStockReport,
    GSTReturnReport,
    HourlySalesHeatmapReport,
    HourlySalesItem,
    JobProfitabilityItem,
    JobProfitabilityReport,
    JobStatusSummaryItem,
    JobStatusSummaryReport,
    KitchenPrepTimeItem,
    KitchenPrepTimeReport,
    LowStockItem,
    LowStockReport,
    ProgressClaimSummaryItem,
    ProgressClaimSummaryReport,
    ProjectProfitabilityItem,
    ProjectProfitabilityReport,
    ReportFilters,
    RetentionSummaryItem,
    RetentionSummaryReport,
    SessionReconciliationItem,
    SessionReconciliationReport,
    StaffUtilisationItem,
    StaffUtilisationReport,
    StockMovementSummaryItem,
    StockMovementSummaryReport,
    StockValuationItem,
    StockValuationReport,
    TableTurnoverItem,
    TableTurnoverReport,
    TipSummaryByStaffItem,
    TipSummaryReport,
    VATReturnReport,
    VariationRegisterItem,
    VariationRegisterReport,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report type registry — maps report_type strings to generator methods
# ---------------------------------------------------------------------------

REPORT_TYPES: dict[str, str] = {
    # Inventory
    "stock_valuation": "_generate_stock_valuation",
    "stock_movement_summary": "_generate_stock_movement_summary",
    "low_stock": "_generate_low_stock",
    "dead_stock": "_generate_dead_stock",
    # Jobs
    "job_profitability": "_generate_job_profitability",
    "jobs_by_status": "_generate_jobs_by_status",
    "avg_completion_time": "_generate_avg_completion_time",
    "staff_utilisation": "_generate_staff_utilisation",
    # Projects
    "project_profitability": "_generate_project_profitability",
    "progress_claim_summary": "_generate_progress_claim_summary",
    "variation_register": "_generate_variation_register",
    "retention_summary": "_generate_retention_summary",
    # POS
    "daily_sales_summary": "_generate_daily_sales_summary",
    "session_reconciliation": "_generate_session_reconciliation",
    "hourly_sales_heatmap": "_generate_hourly_sales_heatmap",
    # Hospitality
    "table_turnover": "_generate_table_turnover",
    "avg_order_value": "_generate_avg_order_value",
    "kitchen_prep_times": "_generate_kitchen_prep_times",
    "tip_summary": "_generate_tip_summary",
    # Tax
    "gst_return": "_generate_gst_return",
    "bas_return": "_generate_bas_return",
    "vat_return": "_generate_vat_return",
}


class ReportService:
    """Dispatcher that routes to specific report generators."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public dispatcher
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        org_id: uuid.UUID,
        report_type: str,
        filters: ReportFilters,
        *,
        base_currency: str = "NZD",
    ) -> object:
        """Generate a report by type. Raises ValueError for unknown types."""
        method_name = REPORT_TYPES.get(report_type)
        if method_name is None:
            raise ValueError(f"Unknown report type: {report_type}")
        method = getattr(self, method_name)
        return await method(org_id, filters, base_currency=base_currency)

    # ------------------------------------------------------------------
    # Helper: location filter
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_location_filter(stmt, model, location_id: uuid.UUID | None):
        """Apply optional location_id filter to a query."""
        if location_id is not None and hasattr(model, "location_id"):
            stmt = stmt.where(model.location_id == location_id)
        return stmt

    # ------------------------------------------------------------------
    # Helper: currency conversion
    # ------------------------------------------------------------------

    async def _get_exchange_rate(
        self, from_currency: str, to_currency: str,
    ) -> Decimal:
        """Get exchange rate, returning 1 if same currency."""
        if from_currency.upper() == to_currency.upper():
            return Decimal("1")
        try:
            from app.modules.multi_currency.models import ExchangeRate
            stmt = (
                select(ExchangeRate.rate)
                .where(
                    ExchangeRate.base_currency == to_currency.upper(),
                    ExchangeRate.target_currency == from_currency.upper(),
                )
                .order_by(ExchangeRate.effective_date.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            rate = result.scalar_one_or_none()
            if rate is not None and rate > 0:
                return Decimal("1") / Decimal(str(rate))
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to fetch exchange rate for %s->%s: %s", from_currency, to_currency, exc)
        return Decimal("1")

    def _convert_amount(
        self, amount: Decimal, rate: Decimal,
    ) -> Decimal:
        """Convert amount using exchange rate."""
        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ==================================================================
    # INVENTORY REPORTS (Task 54.2)
    # ==================================================================

    async def _generate_stock_valuation(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> StockValuationReport:
        """Stock valuation: cost_price × quantity per product."""
        from app.modules.products.models import Product

        stmt = select(Product).where(
            Product.org_id == org_id, Product.is_active.is_(True),
        )
        stmt = self._apply_location_filter(stmt, Product, filters.location_id)
        result = await self.db.execute(stmt)
        products = list(result.scalars().all())

        items = []
        total = Decimal("0")
        for p in products:
            val = (p.cost_price or Decimal("0")) * (p.stock_quantity or Decimal("0"))
            val = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total += val
            items.append(StockValuationItem(
                product_id=p.id,
                product_name=p.name,
                sku=p.sku,
                quantity=p.stock_quantity or Decimal("0"),
                cost_price=p.cost_price or Decimal("0"),
                valuation=val,
            ))
        return StockValuationReport(items=items, total_valuation=total)

    async def _generate_stock_movement_summary(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> StockMovementSummaryReport:
        """Stock movement summary grouped by movement_type for a period."""
        from app.modules.stock.models import StockMovement

        stmt = select(
            StockMovement.movement_type,
            func.sum(StockMovement.quantity_change).label("total_qty"),
            func.count().label("cnt"),
        ).where(StockMovement.org_id == org_id)

        if filters.date_from:
            stmt = stmt.where(StockMovement.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            stmt = stmt.where(StockMovement.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))
        stmt = self._apply_location_filter(stmt, StockMovement, filters.location_id)
        stmt = stmt.group_by(StockMovement.movement_type)

        result = await self.db.execute(stmt)
        items = [
            StockMovementSummaryItem(
                movement_type=row.movement_type,
                total_quantity=Decimal(str(row.total_qty or 0)),
                movement_count=row.cnt,
            )
            for row in result.all()
        ]
        return StockMovementSummaryReport(items=items)

    async def _generate_low_stock(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> LowStockReport:
        """Products where stock_quantity <= low_stock_threshold."""
        from app.modules.products.models import Product

        stmt = select(Product).where(
            Product.org_id == org_id,
            Product.is_active.is_(True),
            Product.stock_quantity <= Product.low_stock_threshold,
            Product.low_stock_threshold > 0,
        )
        stmt = self._apply_location_filter(stmt, Product, filters.location_id)
        result = await self.db.execute(stmt)
        items = [
            LowStockItem(
                product_id=p.id,
                product_name=p.name,
                sku=p.sku,
                current_quantity=p.stock_quantity or Decimal("0"),
                low_stock_threshold=p.low_stock_threshold or Decimal("0"),
            )
            for p in result.scalars().all()
        ]
        return LowStockReport(items=items)

    async def _generate_dead_stock(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> DeadStockReport:
        """Products with no stock movement in X days (default 90)."""
        from app.modules.products.models import Product
        from app.modules.stock.models import StockMovement

        days_threshold = 90
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)

        # Subquery: last movement date per product
        last_move = (
            select(
                StockMovement.product_id,
                func.max(StockMovement.created_at).label("last_move"),
            )
            .where(StockMovement.org_id == org_id)
            .group_by(StockMovement.product_id)
            .subquery()
        )

        stmt = (
            select(Product, last_move.c.last_move)
            .outerjoin(last_move, Product.id == last_move.c.product_id)
            .where(
                Product.org_id == org_id,
                Product.is_active.is_(True),
                Product.stock_quantity > 0,
            )
            .where(
                (last_move.c.last_move.is_(None)) | (last_move.c.last_move < cutoff)
            )
        )
        stmt = self._apply_location_filter(stmt, Product, filters.location_id)
        result = await self.db.execute(stmt)
        items = [
            DeadStockItem(
                product_id=row[0].id,
                product_name=row[0].name,
                sku=row[0].sku,
                quantity=row[0].stock_quantity or Decimal("0"),
                last_movement_date=row[1].date() if row[1] else None,
            )
            for row in result.all()
        ]
        return DeadStockReport(items=items, days_threshold=days_threshold)

    # ==================================================================
    # JOB REPORTS (Task 54.3)
    # ==================================================================

    async def _generate_job_profitability(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> JobProfitabilityReport:
        """Job profitability: revenue vs labour + materials + expenses."""
        from app.modules.jobs_v2.models import Job

        stmt = select(Job).where(Job.org_id == org_id)
        if filters.date_from:
            stmt = stmt.where(Job.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            stmt = stmt.where(Job.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))
        stmt = self._apply_location_filter(stmt, Job, filters.location_id)
        result = await self.db.execute(stmt)
        jobs = list(result.scalars().all())

        items = []
        total_rev = Decimal("0")
        total_cost = Decimal("0")

        for job in jobs:
            revenue = Decimal("0")
            labour = Decimal("0")
            material = Decimal("0")
            expense = Decimal("0")

            # Revenue from linked invoices
            try:
                from app.modules.invoices.models import Invoice
                inv_stmt = select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    Invoice.org_id == org_id,
                    Invoice.job_id == job.id,
                    Invoice.status.in_(["issued", "paid", "partially_paid"]),
                )
                revenue = Decimal(str((await self.db.execute(inv_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch job revenue for job %s: %s", job.id, exc)

            # Labour from time entries
            try:
                from app.modules.time_tracking_v2.models import TimeEntry
                te_stmt = select(
                    func.coalesce(func.sum(TimeEntry.duration_minutes * TimeEntry.hourly_rate / 60), 0),
                ).where(TimeEntry.org_id == org_id, TimeEntry.job_id == job.id)
                labour = Decimal(str((await self.db.execute(te_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch job labour costs for job %s: %s", job.id, exc)

            # Expenses
            try:
                from app.modules.expenses.models import Expense
                exp_stmt = select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.org_id == org_id, Expense.job_id == job.id,
                )
                expense = Decimal(str((await self.db.execute(exp_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch job expenses for job %s: %s", job.id, exc)

            cost = labour + material + expense
            profit = revenue - cost
            margin = (profit / revenue * 100).quantize(Decimal("0.01")) if revenue > 0 else Decimal("0")

            total_rev += revenue
            total_cost += cost

            items.append(JobProfitabilityItem(
                job_id=job.id,
                job_number=job.job_number,
                revenue=revenue,
                labour_cost=labour,
                material_cost=material,
                expense_cost=expense,
                profit=profit,
                margin_percent=margin,
            ))

        return JobProfitabilityReport(
            items=items,
            total_revenue=total_rev,
            total_cost=total_cost,
            total_profit=total_rev - total_cost,
        )

    async def _generate_jobs_by_status(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> JobStatusSummaryReport:
        """Jobs grouped by status."""
        from app.modules.jobs_v2.models import Job

        stmt = (
            select(Job.status, func.count().label("cnt"))
            .where(Job.org_id == org_id)
            .group_by(Job.status)
        )
        stmt = self._apply_location_filter(stmt, Job, filters.location_id)
        result = await self.db.execute(stmt)
        items = [
            JobStatusSummaryItem(status=row.status, count=row.cnt)
            for row in result.all()
        ]
        return JobStatusSummaryReport(items=items)

    async def _generate_avg_completion_time(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> AvgCompletionTimeReport:
        """Average completion time by trade category (days from created to completed)."""
        from app.modules.jobs_v2.models import Job

        stmt = (
            select(
                func.coalesce(Job.description, "General").label("trade_cat"),
                func.avg(
                    extract("epoch", Job.actual_end - Job.actual_start) / 86400
                ).label("avg_d"),
            )
            .where(
                Job.org_id == org_id,
                Job.status == "completed",
                Job.actual_start.isnot(None),
                Job.actual_end.isnot(None),
            )
            .group_by("trade_cat")
        )
        result = await self.db.execute(stmt)
        items = [
            AvgCompletionTimeItem(
                trade_category=row.trade_cat or "General",
                avg_days=Decimal(str(round(row.avg_d or 0, 1))),
            )
            for row in result.all()
        ]
        return AvgCompletionTimeReport(items=items)

    async def _generate_staff_utilisation(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> StaffUtilisationReport:
        """Staff utilisation: billable hours / total hours."""
        from app.modules.staff.models import StaffMember
        from app.modules.time_tracking_v2.models import TimeEntry

        stmt = select(StaffMember).where(
            StaffMember.org_id == org_id, StaffMember.is_active.is_(True),
        )
        result = await self.db.execute(stmt)
        staff_list = list(result.scalars().all())

        items = []
        for s in staff_list:
            te_stmt = select(
                func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("total"),
                func.coalesce(
                    func.sum(case((TimeEntry.is_billable.is_(True), TimeEntry.duration_minutes), else_=0)),
                    0,
                ).label("billable"),
            ).where(TimeEntry.org_id == org_id, TimeEntry.staff_id == s.id)

            if filters.date_from:
                te_stmt = te_stmt.where(TimeEntry.start_time >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
            if filters.date_to:
                te_stmt = te_stmt.where(TimeEntry.start_time <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))

            row = (await self.db.execute(te_stmt)).one()
            total_hrs = Decimal(str(row.total or 0)) / 60
            billable_hrs = Decimal(str(row.billable or 0)) / 60
            util = (billable_hrs / total_hrs * 100).quantize(Decimal("0.01")) if total_hrs > 0 else Decimal("0")

            items.append(StaffUtilisationItem(
                staff_id=s.id,
                staff_name=s.name,
                total_hours=total_hrs.quantize(Decimal("0.01")),
                billable_hours=billable_hrs.quantize(Decimal("0.01")),
                utilisation_percent=util,
            ))
        return StaffUtilisationReport(items=items)

    # ==================================================================
    # PROJECT REPORTS (Task 54.4)
    # ==================================================================

    async def _generate_project_profitability(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> ProjectProfitabilityReport:
        """Project profitability: contract value vs costs."""
        from app.modules.projects.models import Project

        stmt = select(Project).where(Project.org_id == org_id)
        result = await self.db.execute(stmt)
        projects = list(result.scalars().all())

        items = []
        for p in projects:
            contract = p.revised_contract_value or p.contract_value or Decimal("0")
            costs = Decimal("0")

            # Sum expenses
            try:
                from app.modules.expenses.models import Expense
                exp_stmt = select(func.coalesce(func.sum(Expense.amount), 0)).where(
                    Expense.org_id == org_id, Expense.project_id == p.id,
                )
                costs += Decimal(str((await self.db.execute(exp_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch project expenses for project %s: %s", p.id, exc)

            # Sum labour
            try:
                from app.modules.time_tracking_v2.models import TimeEntry
                te_stmt = select(
                    func.coalesce(func.sum(TimeEntry.duration_minutes * TimeEntry.hourly_rate / 60), 0),
                ).where(TimeEntry.org_id == org_id, TimeEntry.project_id == p.id)
                costs += Decimal(str((await self.db.execute(te_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch project labour costs for project %s: %s", p.id, exc)

            profit = contract - costs
            margin = (profit / contract * 100).quantize(Decimal("0.01")) if contract > 0 else Decimal("0")

            items.append(ProjectProfitabilityItem(
                project_id=p.id,
                project_name=p.name,
                contract_value=contract,
                total_costs=costs,
                profit=profit,
                margin_percent=margin,
            ))
        return ProjectProfitabilityReport(items=items)

    async def _generate_progress_claim_summary(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> ProgressClaimSummaryReport:
        """Progress claim summary per project."""
        from app.modules.projects.models import Project

        stmt = select(Project).where(Project.org_id == org_id)
        result = await self.db.execute(stmt)
        projects = list(result.scalars().all())

        items = []
        for p in projects:
            claimed = Decimal("0")
            paid = Decimal("0")
            retention = Decimal("0")

            try:
                from app.modules.progress_claims.models import ProgressClaim
                pc_stmt = select(
                    func.coalesce(func.sum(ProgressClaim.claim_amount), 0).label("claimed"),
                    func.coalesce(func.sum(ProgressClaim.paid_amount), 0).label("paid"),
                    func.coalesce(func.sum(ProgressClaim.retention_amount), 0).label("retention"),
                ).where(ProgressClaim.project_id == p.id)
                row = (await self.db.execute(pc_stmt)).one()
                claimed = Decimal(str(row.claimed or 0))
                paid = Decimal(str(row.paid or 0))
                retention = Decimal(str(row.retention or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch progress claims for project %s: %s", p.id, exc)

            items.append(ProgressClaimSummaryItem(
                project_id=p.id,
                project_name=p.name,
                total_claimed=claimed,
                total_paid=paid,
                retention_held=retention,
            ))
        return ProgressClaimSummaryReport(items=items)

    async def _generate_variation_register(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> VariationRegisterReport:
        """Variation register across all projects."""
        try:
            from app.modules.variations.models import VariationOrder
            from app.modules.projects.models import Project

            stmt = (
                select(VariationOrder, Project.name.label("proj_name"))
                .join(Project, VariationOrder.project_id == Project.id)
                .where(Project.org_id == org_id)
            )
            result = await self.db.execute(stmt)
            rows = result.all()

            items = []
            total_impact = Decimal("0")
            for row in rows:
                vo = row[0]
                impact = vo.cost_impact or Decimal("0")
                total_impact += impact
                items.append(VariationRegisterItem(
                    variation_id=vo.id,
                    project_name=row.proj_name,
                    description=vo.description or "",
                    status=vo.status or "pending",
                    cost_impact=impact,
                ))
            return VariationRegisterReport(items=items, total_impact=total_impact)
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate variation register report: %s", exc)
            return VariationRegisterReport()

    async def _generate_retention_summary(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> RetentionSummaryReport:
        """Retention summary per project."""
        from app.modules.projects.models import Project

        stmt = select(Project).where(Project.org_id == org_id)
        result = await self.db.execute(stmt)
        projects = list(result.scalars().all())

        items = []
        for p in projects:
            held = Decimal("0")
            released = Decimal("0")

            try:
                from app.modules.retentions.models import Retention
                ret_stmt = select(
                    func.coalesce(func.sum(Retention.amount), 0).label("held"),
                    func.coalesce(func.sum(
                        case((Retention.status == "released", Retention.amount), else_=0)
                    ), 0).label("released"),
                ).where(Retention.project_id == p.id)
                row = (await self.db.execute(ret_stmt)).one()
                held = Decimal(str(row.held or 0))
                released = Decimal(str(row.released or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch retention data for project %s: %s", p.id, exc)

            items.append(RetentionSummaryItem(
                project_id=p.id,
                project_name=p.name,
                retention_held=held,
                retention_released=released,
                retention_balance=held - released,
            ))
        return RetentionSummaryReport(items=items)

    # ==================================================================
    # POS REPORTS (Task 54.5)
    # ==================================================================

    async def _generate_daily_sales_summary(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> DailySalesSummaryReport:
        """Daily sales summary by payment method and product category."""
        from app.modules.pos.models import POSTransaction

        base_where = [POSTransaction.org_id == org_id]
        if filters.date_from:
            base_where.append(POSTransaction.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            base_where.append(POSTransaction.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))
        if filters.location_id:
            # Filter via session's location
            from app.modules.pos.models import POSSession
            base_where.append(POSTransaction.session_id.in_(
                select(POSSession.id).where(POSSession.location_id == filters.location_id)
            ))

        # By payment method
        pm_stmt = (
            select(
                POSTransaction.payment_method,
                func.sum(POSTransaction.total).label("total"),
                func.count().label("cnt"),
            )
            .where(*base_where)
            .group_by(POSTransaction.payment_method)
        )
        pm_result = await self.db.execute(pm_stmt)
        by_method = [
            DailySalesByMethodItem(
                payment_method=row.payment_method,
                total=Decimal(str(row.total or 0)),
                count=row.cnt,
            )
            for row in pm_result.all()
        ]

        grand_total = sum(i.total for i in by_method)

        return DailySalesSummaryReport(
            by_payment_method=by_method,
            by_category=[],  # Category breakdown requires invoice line items
            grand_total=grand_total,
        )

    async def _generate_session_reconciliation(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> SessionReconciliationReport:
        """Session reconciliation: expected vs actual cash."""
        from app.modules.pos.models import POSSession, POSTransaction

        stmt = select(POSSession).where(
            POSSession.org_id == org_id,
            POSSession.status == "closed",
        )
        if filters.date_from:
            stmt = stmt.where(POSSession.opened_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            stmt = stmt.where(POSSession.opened_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))
        if filters.location_id:
            stmt = stmt.where(POSSession.location_id == filters.location_id)

        result = await self.db.execute(stmt)
        sessions = list(result.scalars().all())

        items = []
        for s in sessions:
            # Sum cash transactions for this session
            cash_stmt = select(
                func.coalesce(func.sum(POSTransaction.total), 0),
            ).where(
                POSTransaction.session_id == s.id,
                POSTransaction.payment_method == "cash",
            )
            expected_cash_sales = Decimal(str((await self.db.execute(cash_stmt)).scalar() or 0))
            expected = s.opening_cash + expected_cash_sales
            actual = s.closing_cash if s.closing_cash is not None else expected
            variance = actual - expected

            items.append(SessionReconciliationItem(
                session_id=s.id,
                opening_cash=s.opening_cash,
                expected_cash=expected,
                actual_cash=actual,
                variance=variance,
            ))
        return SessionReconciliationReport(items=items)

    async def _generate_hourly_sales_heatmap(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> HourlySalesHeatmapReport:
        """Hourly sales heatmap."""
        from app.modules.pos.models import POSTransaction

        base_where = [POSTransaction.org_id == org_id]
        if filters.date_from:
            base_where.append(POSTransaction.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            base_where.append(POSTransaction.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))

        stmt = (
            select(
                extract("hour", POSTransaction.created_at).label("hr"),
                func.sum(POSTransaction.total).label("total"),
                func.count().label("cnt"),
            )
            .where(*base_where)
            .group_by("hr")
            .order_by("hr")
        )
        result = await self.db.execute(stmt)
        items = [
            HourlySalesItem(
                hour=int(row.hr),
                total=Decimal(str(row.total or 0)),
                count=row.cnt,
            )
            for row in result.all()
        ]
        return HourlySalesHeatmapReport(items=items)

    # ==================================================================
    # HOSPITALITY REPORTS (Task 54.6)
    # ==================================================================

    async def _generate_table_turnover(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> TableTurnoverReport:
        """Table turnover rate."""
        try:
            from app.modules.tables.models import RestaurantTable
            from app.modules.pos.models import POSTransaction

            stmt = select(RestaurantTable).where(RestaurantTable.org_id == org_id)
            if filters.location_id:
                stmt = stmt.where(RestaurantTable.location_id == filters.location_id)
            result = await self.db.execute(stmt)
            tables = list(result.scalars().all())

            items = []
            total_turnover = 0
            for t in tables:
                txn_stmt = select(func.count()).where(
                    POSTransaction.org_id == org_id,
                    POSTransaction.table_id == t.id,
                )
                if filters.date_from:
                    txn_stmt = txn_stmt.where(POSTransaction.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
                if filters.date_to:
                    txn_stmt = txn_stmt.where(POSTransaction.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))
                count = (await self.db.execute(txn_stmt)).scalar() or 0
                total_turnover += count
                items.append(TableTurnoverItem(
                    table_number=t.table_number,
                    covers=t.seat_count or 0,
                    turnover_count=count,
                ))

            avg = Decimal(str(total_turnover / len(tables))).quantize(Decimal("0.01")) if tables else Decimal("0")
            return TableTurnoverReport(items=items, avg_turnover=avg)
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate table turnover report: %s", exc)
            return TableTurnoverReport()

    async def _generate_avg_order_value(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> AvgOrderValueReport:
        """Average order value from POS transactions."""
        from app.modules.pos.models import POSTransaction

        base_where = [POSTransaction.org_id == org_id]
        if filters.date_from:
            base_where.append(POSTransaction.created_at >= datetime.combine(filters.date_from, datetime.min.time(), tzinfo=timezone.utc))
        if filters.date_to:
            base_where.append(POSTransaction.created_at <= datetime.combine(filters.date_to, datetime.max.time(), tzinfo=timezone.utc))

        stmt = select(
            func.avg(POSTransaction.total).label("avg_val"),
            func.count().label("cnt"),
            func.coalesce(func.sum(POSTransaction.total), 0).label("total_rev"),
        ).where(*base_where)
        row = (await self.db.execute(stmt)).one()

        return AvgOrderValueReport(
            avg_order_value=Decimal(str(row.avg_val or 0)).quantize(Decimal("0.01")),
            total_orders=row.cnt or 0,
            total_revenue=Decimal(str(row.total_rev or 0)),
        )

    async def _generate_kitchen_prep_times(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> KitchenPrepTimeReport:
        """Kitchen preparation times by item."""
        try:
            from app.modules.kitchen_display.models import KitchenOrder

            stmt = (
                select(
                    KitchenOrder.item_name,
                    func.avg(
                        extract("epoch", KitchenOrder.prepared_at - KitchenOrder.created_at) / 60
                    ).label("avg_mins"),
                    func.count().label("cnt"),
                )
                .where(
                    KitchenOrder.org_id == org_id,
                    KitchenOrder.status == "prepared",
                    KitchenOrder.prepared_at.isnot(None),
                )
                .group_by(KitchenOrder.item_name)
            )
            result = await self.db.execute(stmt)
            items = [
                KitchenPrepTimeItem(
                    item_name=row.item_name,
                    avg_prep_minutes=Decimal(str(round(row.avg_mins or 0, 1))),
                    order_count=row.cnt,
                )
                for row in result.all()
            ]
            return KitchenPrepTimeReport(items=items)
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate kitchen prep time report: %s", exc)
            return KitchenPrepTimeReport()

    async def _generate_tip_summary(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> TipSummaryReport:
        """Tip summary by staff."""
        try:
            from app.modules.tipping.models import TipAllocation
            from app.modules.staff.models import StaffMember

            stmt = (
                select(
                    TipAllocation.staff_id,
                    StaffMember.name.label("staff_name"),
                    func.sum(TipAllocation.amount).label("total"),
                    func.count().label("cnt"),
                )
                .join(StaffMember, TipAllocation.staff_id == StaffMember.id)
                .where(StaffMember.org_id == org_id)
                .group_by(TipAllocation.staff_id, StaffMember.name)
            )
            result = await self.db.execute(stmt)
            items = []
            grand = Decimal("0")
            for row in result.all():
                total = Decimal(str(row.total or 0))
                grand += total
                items.append(TipSummaryByStaffItem(
                    staff_id=row.staff_id,
                    staff_name=row.staff_name,
                    total_tips=total,
                    tip_count=row.cnt,
                ))
            return TipSummaryReport(items=items, grand_total=grand)
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate tip summary report: %s", exc)
            return TipSummaryReport()

    # ==================================================================
    # TAX RETURN REPORTS (Task 54.10)
    # ==================================================================

    async def _generate_gst_return(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> GSTReturnReport:
        """NZ GST return — 15% standard rate."""
        try:
            from app.modules.invoices.models import Invoice

            base_where = [
                Invoice.org_id == org_id,
                Invoice.status.in_(["issued", "paid", "partially_paid"]),
            ]
            if filters.date_from:
                base_where.append(Invoice.issue_date >= filters.date_from)
            if filters.date_to:
                base_where.append(Invoice.issue_date <= filters.date_to)

            stmt = select(
                func.coalesce(func.sum(Invoice.total_amount), 0).label("total_incl"),
                func.coalesce(func.sum(Invoice.tax_amount), 0).label("gst"),
            ).where(*base_where)
            row = (await self.db.execute(stmt)).one()

            total_incl = Decimal(str(row.total_incl or 0))
            gst_collected = Decimal(str(row.gst or 0))
            total_excl = total_incl - gst_collected

            # Purchases GST (from expenses)
            gst_on_purchases = Decimal("0")
            try:
                from app.modules.expenses.models import Expense
                exp_stmt = select(func.coalesce(func.sum(Expense.tax_amount), 0)).where(
                    Expense.org_id == org_id,
                )
                if filters.date_from:
                    exp_stmt = exp_stmt.where(Expense.date >= filters.date_from)
                if filters.date_to:
                    exp_stmt = exp_stmt.where(Expense.date <= filters.date_to)
                gst_on_purchases = Decimal(str((await self.db.execute(exp_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch GST on purchases: %s", exc)

            return GSTReturnReport(
                total_sales_incl=total_incl,
                total_sales_excl=total_excl,
                gst_collected=gst_collected,
                zero_rated_sales=Decimal("0"),
                gst_on_purchases=gst_on_purchases,
                net_gst=gst_collected - gst_on_purchases,
            )
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate GST return report: %s", exc)
            return GSTReturnReport()

    async def _generate_bas_return(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> BASReport:
        """AU BAS report — 10% GST."""
        try:
            from app.modules.invoices.models import Invoice

            base_where = [
                Invoice.org_id == org_id,
                Invoice.status.in_(["issued", "paid", "partially_paid"]),
            ]
            if filters.date_from:
                base_where.append(Invoice.issue_date >= filters.date_from)
            if filters.date_to:
                base_where.append(Invoice.issue_date <= filters.date_to)

            stmt = select(
                func.coalesce(func.sum(Invoice.total_amount), 0).label("total"),
                func.coalesce(func.sum(Invoice.tax_amount), 0).label("gst"),
            ).where(*base_where)
            row = (await self.db.execute(stmt)).one()

            total_sales = Decimal(str(row.total or 0))
            gst_on_sales = Decimal(str(row.gst or 0))

            gst_on_purchases = Decimal("0")
            try:
                from app.modules.expenses.models import Expense
                exp_stmt = select(func.coalesce(func.sum(Expense.tax_amount), 0)).where(
                    Expense.org_id == org_id,
                )
                if filters.date_from:
                    exp_stmt = exp_stmt.where(Expense.date >= filters.date_from)
                if filters.date_to:
                    exp_stmt = exp_stmt.where(Expense.date <= filters.date_to)
                gst_on_purchases = Decimal(str((await self.db.execute(exp_stmt)).scalar() or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch BAS purchases GST: %s", exc)

            return BASReport(
                total_sales=total_sales,
                gst_on_sales=gst_on_sales,
                gst_on_purchases=gst_on_purchases,
                net_gst=gst_on_sales - gst_on_purchases,
            )
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate BAS return report: %s", exc)
            return BASReport()

    async def _generate_vat_return(
        self, org_id: uuid.UUID, filters: ReportFilters, **kw,
    ) -> VATReturnReport:
        """UK VAT return with box mappings."""
        try:
            from app.modules.invoices.models import Invoice

            base_where = [
                Invoice.org_id == org_id,
                Invoice.status.in_(["issued", "paid", "partially_paid"]),
            ]
            if filters.date_from:
                base_where.append(Invoice.issue_date >= filters.date_from)
            if filters.date_to:
                base_where.append(Invoice.issue_date <= filters.date_to)

            stmt = select(
                func.coalesce(func.sum(Invoice.total_amount), 0).label("total"),
                func.coalesce(func.sum(Invoice.tax_amount), 0).label("vat"),
            ).where(*base_where)
            row = (await self.db.execute(stmt)).one()

            total = Decimal(str(row.total or 0))
            vat_due = Decimal(str(row.vat or 0))
            total_excl = total - vat_due

            # Purchases VAT
            vat_reclaimed = Decimal("0")
            total_purchases = Decimal("0")
            try:
                from app.modules.expenses.models import Expense
                exp_stmt = select(
                    func.coalesce(func.sum(Expense.amount), 0).label("total"),
                    func.coalesce(func.sum(Expense.tax_amount), 0).label("vat"),
                ).where(Expense.org_id == org_id)
                if filters.date_from:
                    exp_stmt = exp_stmt.where(Expense.date >= filters.date_from)
                if filters.date_to:
                    exp_stmt = exp_stmt.where(Expense.date <= filters.date_to)
                exp_row = (await self.db.execute(exp_stmt)).one()
                total_purchases = Decimal(str(exp_row.total or 0))
                vat_reclaimed = Decimal(str(exp_row.vat or 0))
            except (ImportError, ConnectionError, OSError) as exc:
                logger.warning("Failed to fetch VAT on purchases: %s", exc)

            return VATReturnReport(
                box1_vat_due_sales=vat_due,
                box2_vat_due_acquisitions=Decimal("0"),
                box3_total_vat_due=vat_due,
                box4_vat_reclaimed=vat_reclaimed,
                box5_net_vat=vat_due - vat_reclaimed,
                box6_total_sales_excl=total_excl,
                box7_total_purchases_excl=total_purchases - vat_reclaimed,
                box8_total_supplies_ex_vat=Decimal("0"),
                box9_total_acquisitions_ex_vat=Decimal("0"),
            )
        except (ImportError, ConnectionError, OSError) as exc:
            logger.warning("Failed to generate VAT return report: %s", exc)
            return VATReturnReport()
