"""Project service: CRUD, profitability calculation, progress tracking,
and activity feed.

**Validates: Requirement 14.1 (Project Module)**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, and_, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project, PROJECT_STATUSES
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectUpdate,
)


class ProjectService:
    """Service layer for project management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_projects(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        customer_id: uuid.UUID | None = None,
        search: str | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[list[Project], int]:
        """List projects with pagination and filtering."""
        stmt = select(Project).where(Project.org_id == org_id)

        if branch_id is not None:
            stmt = stmt.where(Project.branch_id == branch_id)
        if status is not None:
            stmt = stmt.where(Project.status == status)
        if customer_id is not None:
            stmt = stmt.where(Project.customer_id == customer_id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                Project.name.ilike(pattern)
                | Project.description.ilike(pattern)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(Project.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_project(
        self,
        org_id: uuid.UUID,
        payload: ProjectCreate,
        *,
        created_by: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> Project:
        """Create a new project."""
        if payload.status and payload.status not in PROJECT_STATUSES:
            raise ValueError(f"Invalid status: {payload.status}")

        # Validate branch is active if provided (Req 2.2)
        if branch_id is not None:
            from app.core.branch_validation import validate_branch_active
            await validate_branch_active(self.db, branch_id)

        project = Project(
            org_id=org_id,
            name=payload.name,
            customer_id=payload.customer_id,
            description=payload.description,
            budget_amount=payload.budget_amount,
            contract_value=payload.contract_value,
            revised_contract_value=payload.revised_contract_value,
            retention_percentage=payload.retention_percentage,
            start_date=payload.start_date,
            target_end_date=payload.target_end_date,
            status=payload.status,
            created_by=created_by,
            branch_id=branch_id,
        )
        self.db.add(project)
        await self.db.flush()
        return project

    async def get_project(
        self, org_id: uuid.UUID, project_id: uuid.UUID,
    ) -> Project | None:
        """Get a single project by ID."""
        stmt = select(Project).where(
            and_(Project.org_id == org_id, Project.id == project_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_project(
        self, org_id: uuid.UUID, project_id: uuid.UUID, payload: ProjectUpdate,
    ) -> Project | None:
        """Update an existing project."""
        project = await self.get_project(org_id, project_id)
        if project is None:
            return None

        update_data = payload.model_dump(exclude_unset=True)
        if "status" in update_data and update_data["status"] not in PROJECT_STATUSES:
            raise ValueError(f"Invalid status: {update_data['status']}")

        for field, value in update_data.items():
            setattr(project, field, value)
        await self.db.flush()
        return project

    # ------------------------------------------------------------------
    # Profitability: revenue (paid invoices) vs costs (expenses + labour)
    # ------------------------------------------------------------------

    async def calculate_profitability(
        self, org_id: uuid.UUID, project_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Calculate project profitability.

        Revenue = sum of amount_paid on invoices linked to the project
                  (via jobs.project_id → jobs.converted_invoice_id).
        Costs   = sum of expenses.amount for project
                + sum of (time_entries.duration_minutes / 60 * hourly_rate)
                  for project.
        """
        from app.modules.jobs_v2.models import Job
        from app.modules.invoices.models import Invoice
        from app.modules.time_tracking_v2.models import TimeEntry

        # Revenue: sum of amount_paid from invoices linked via jobs
        revenue_stmt = (
            select(func.coalesce(func.sum(Invoice.amount_paid), 0))
            .select_from(Job)
            .join(Invoice, Job.converted_invoice_id == Invoice.id)
            .where(
                and_(
                    Job.org_id == org_id,
                    Job.project_id == project_id,
                    Job.converted_invoice_id.isnot(None),
                )
            )
        )
        revenue = Decimal(str((await self.db.execute(revenue_stmt)).scalar() or 0))

        # Labour costs: sum of (duration_minutes / 60) * hourly_rate
        labour_stmt = (
            select(
                func.coalesce(
                    func.sum(
                        TimeEntry.duration_minutes / 60.0 * TimeEntry.hourly_rate
                    ),
                    0,
                )
            )
            .where(
                and_(
                    TimeEntry.org_id == org_id,
                    TimeEntry.project_id == project_id,
                    TimeEntry.duration_minutes.isnot(None),
                    TimeEntry.hourly_rate.isnot(None),
                )
            )
        )
        labour_costs = Decimal(str((await self.db.execute(labour_stmt)).scalar() or 0))

        # Expense costs: query expenses table if it exists
        expense_costs = Decimal("0")
        try:
            from app.modules.expenses.models import Expense
            expense_stmt = (
                select(func.coalesce(func.sum(Expense.amount), 0))
                .where(
                    and_(
                        Expense.org_id == org_id,
                        Expense.project_id == project_id,
                    )
                )
            )
            expense_costs = Decimal(str((await self.db.execute(expense_stmt)).scalar() or 0))
        except (ImportError, Exception):
            # Expenses module not yet implemented
            pass

        total_costs = labour_costs + expense_costs
        profit = revenue - total_costs
        margin = (
            (profit / revenue * 100) if revenue > 0 else None
        )

        return {
            "project_id": project_id,
            "revenue": revenue,
            "expense_costs": expense_costs,
            "labour_costs": labour_costs,
            "total_costs": total_costs,
            "profit": profit,
            "margin_percentage": margin,
        }

    # ------------------------------------------------------------------
    # Progress: invoiced amount vs contract value
    # ------------------------------------------------------------------

    async def get_progress(
        self, org_id: uuid.UUID, project_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Calculate project progress as invoiced amount vs contract value."""
        from app.modules.jobs_v2.models import Job
        from app.modules.invoices.models import Invoice

        project = await self.get_project(org_id, project_id)
        if project is None:
            return {
                "project_id": project_id,
                "contract_value": None,
                "invoiced_amount": Decimal("0"),
                "progress_percentage": Decimal("0"),
            }

        # Sum of invoice totals linked via jobs
        invoiced_stmt = (
            select(func.coalesce(func.sum(Invoice.total), 0))
            .select_from(Job)
            .join(Invoice, Job.converted_invoice_id == Invoice.id)
            .where(
                and_(
                    Job.org_id == org_id,
                    Job.project_id == project_id,
                    Job.converted_invoice_id.isnot(None),
                )
            )
        )
        invoiced_amount = Decimal(str((await self.db.execute(invoiced_stmt)).scalar() or 0))

        contract_value = project.revised_contract_value or project.contract_value
        progress = Decimal("0")
        if contract_value and contract_value > 0:
            progress = (invoiced_amount / contract_value * 100).quantize(Decimal("0.01"))
            progress = min(progress, Decimal("100"))

        return {
            "project_id": project_id,
            "contract_value": contract_value,
            "invoiced_amount": invoiced_amount,
            "progress_percentage": progress,
        }

    # ------------------------------------------------------------------
    # Activity feed: recent jobs, quotes, invoices, time entries
    # ------------------------------------------------------------------

    async def get_activity_feed(
        self,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get recent activity for a project across linked entities."""
        from app.modules.jobs_v2.models import Job
        from app.modules.quotes_v2.models import Quote
        from app.modules.time_tracking_v2.models import TimeEntry

        items: list[dict[str, Any]] = []

        # Jobs linked to project
        jobs_stmt = (
            select(Job)
            .where(and_(Job.org_id == org_id, Job.project_id == project_id))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        jobs_result = await self.db.execute(jobs_stmt)
        for job in jobs_result.scalars().all():
            items.append({
                "entity_type": "job",
                "entity_id": job.id,
                "title": f"{job.job_number}: {job.title}",
                "status": job.status,
                "created_at": job.created_at,
            })

        # Quotes linked to project
        quotes_stmt = (
            select(Quote)
            .where(and_(Quote.org_id == org_id, Quote.project_id == project_id))
            .order_by(Quote.created_at.desc())
            .limit(limit)
        )
        quotes_result = await self.db.execute(quotes_stmt)
        for quote in quotes_result.scalars().all():
            items.append({
                "entity_type": "quote",
                "entity_id": quote.id,
                "title": f"Quote {quote.quote_number}",
                "status": quote.status,
                "created_at": quote.created_at,
            })

        # Time entries linked to project
        te_stmt = (
            select(TimeEntry)
            .where(and_(TimeEntry.org_id == org_id, TimeEntry.project_id == project_id))
            .order_by(TimeEntry.created_at.desc())
            .limit(limit)
        )
        te_result = await self.db.execute(te_stmt)
        for te in te_result.scalars().all():
            desc = te.description or "Time entry"
            hours = f"{(te.duration_minutes or 0) / 60:.1f}h"
            items.append({
                "entity_type": "time_entry",
                "entity_id": te.id,
                "title": f"{desc} ({hours})",
                "status": "invoiced" if te.is_invoiced else "recorded",
                "created_at": te.created_at,
            })

        # Sort all items by created_at descending and limit
        items.sort(key=lambda x: x["created_at"], reverse=True)
        items = items[:limit]

        return {
            "project_id": project_id,
            "items": items,
            "total": len(items),
        }
