"""Expense service: CRUD, summary reports, and invoice inclusion.

**Validates: Requirement — Expense Module**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.expenses.models import Expense, MileagePreference, MileageRate
from app.modules.expenses.schemas import ExpenseCreate, ExpenseUpdate, MileagePreferenceUpdate

logger = logging.getLogger(__name__)


class ExpenseService:
    """Service layer for expense management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_expenses(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        job_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        category: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[list[Expense], int]:
        """List expenses with pagination and filtering."""
        stmt = select(Expense).where(Expense.org_id == org_id)

        # Branch filter
        if branch_id is not None:
            stmt = stmt.where(Expense.branch_id == branch_id)

        if job_id is not None:
            stmt = stmt.where(Expense.job_id == job_id)
        if project_id is not None:
            stmt = stmt.where(Expense.project_id == project_id)
        if category is not None:
            stmt = stmt.where(Expense.category == category)
        if date_from is not None:
            stmt = stmt.where(Expense.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Expense.date <= date_to)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(Expense.date.desc(), Expense.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_expense(
        self,
        org_id: uuid.UUID,
        payload: ExpenseCreate,
        *,
        created_by: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> Expense:
        """Create a new expense."""
        # Validate branch is active if provided (Req 2.2)
        if branch_id is not None:
            from app.core.branch_validation import validate_branch_active
            await validate_branch_active(self.db, branch_id)

        expense = Expense(
            org_id=org_id,
            job_id=payload.job_id,
            project_id=payload.project_id,
            customer_id=payload.customer_id,
            date=payload.date,
            description=payload.description,
            amount=payload.amount,
            tax_amount=payload.tax_amount,
            category=payload.category,
            reference_number=payload.reference_number,
            notes=payload.notes,
            receipt_file_key=payload.receipt_file_key,
            is_pass_through=payload.is_pass_through,
            is_billable=payload.is_billable,
            tax_inclusive=payload.tax_inclusive,
            expense_type=payload.expense_type,
            created_by=created_by,
            branch_id=branch_id,
        )
        self.db.add(expense)
        await self.db.flush()

        # Auto-post journal entry for the expense (Req 4.3, 4.6, 4.7)
        try:
            from app.modules.ledger.auto_poster import auto_post_expense
            await auto_post_expense(self.db, expense, created_by or uuid.UUID(int=0))
        except Exception as exc:
            logger.warning(
                "Auto-post failed for expense %s: %s", expense.id, exc
            )

        return expense

    async def get_expense(
        self, org_id: uuid.UUID, expense_id: uuid.UUID,
    ) -> Expense | None:
        """Get a single expense by ID."""
        stmt = select(Expense).where(
            and_(Expense.org_id == org_id, Expense.id == expense_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_expense(
        self, org_id: uuid.UUID, expense_id: uuid.UUID, payload: ExpenseUpdate,
    ) -> Expense | None:
        """Update an existing expense."""
        expense = await self.get_expense(org_id, expense_id)
        if expense is None:
            return None
        if expense.is_invoiced:
            raise ValueError("Cannot update an invoiced expense")

        # GST lock check — reject edits on locked expenses (Req 14.3)
        try:
            if getattr(expense, "is_gst_locked", False):
                raise ValueError(
                    "GST_LOCKED: This expense is locked because its GST filing period has been filed. "
                    "Edits are not permitted on GST-locked expenses."
                )
        except Exception as exc:
            if "GST_LOCKED" in str(exc):
                raise
            pass  # Column may not exist yet — ignore

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(expense, field, value)
        await self.db.flush()
        return expense

    async def delete_expense(
        self, org_id: uuid.UUID, expense_id: uuid.UUID,
    ) -> bool:
        """Delete an expense. Returns True if deleted."""
        expense = await self.get_expense(org_id, expense_id)
        if expense is None:
            return False
        if expense.is_invoiced:
            raise ValueError("Cannot delete an invoiced expense")
        await self.db.delete(expense)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Summary report
    # ------------------------------------------------------------------

    async def get_summary_report(
        self,
        org_id: uuid.UUID,
        *,
        job_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Get expense summary with totals by category, project, and job."""
        base = select(Expense).where(Expense.org_id == org_id)
        if job_id is not None:
            base = base.where(Expense.job_id == job_id)
        if project_id is not None:
            base = base.where(Expense.project_id == project_id)
        if date_from is not None:
            base = base.where(Expense.date >= date_from)
        if date_to is not None:
            base = base.where(Expense.date <= date_to)

        sub = base.subquery()

        # Totals
        totals_stmt = select(
            func.coalesce(func.sum(sub.c.amount), 0),
            func.coalesce(func.sum(sub.c.tax_amount), 0),
            func.count(sub.c.id),
        )
        row = (await self.db.execute(totals_stmt)).one()
        total_amount = Decimal(str(row[0]))
        total_tax = Decimal(str(row[1]))
        total_count = int(row[2])

        # By category
        cat_stmt = (
            select(
                sub.c.category,
                func.sum(sub.c.amount).label("total_amount"),
                func.count(sub.c.id).label("count"),
            )
            .group_by(sub.c.category)
            .order_by(func.sum(sub.c.amount).desc())
        )
        cat_rows = (await self.db.execute(cat_stmt)).all()
        by_category = [
            {"category": r[0], "total_amount": Decimal(str(r[1])), "count": int(r[2])}
            for r in cat_rows
        ]

        # By project
        proj_stmt = (
            select(
                sub.c.project_id,
                func.sum(sub.c.amount).label("total_amount"),
                func.count(sub.c.id).label("count"),
            )
            .where(sub.c.project_id.isnot(None))
            .group_by(sub.c.project_id)
            .order_by(func.sum(sub.c.amount).desc())
        )
        proj_rows = (await self.db.execute(proj_stmt)).all()
        by_project = [
            {"project_id": r[0], "total_amount": Decimal(str(r[1])), "count": int(r[2])}
            for r in proj_rows
        ]

        # By job
        job_stmt = (
            select(
                sub.c.job_id,
                func.sum(sub.c.amount).label("total_amount"),
                func.count(sub.c.id).label("count"),
            )
            .where(sub.c.job_id.isnot(None))
            .group_by(sub.c.job_id)
            .order_by(func.sum(sub.c.amount).desc())
        )
        job_rows = (await self.db.execute(job_stmt)).all()
        by_job = [
            {"job_id": r[0], "total_amount": Decimal(str(r[1])), "count": int(r[2])}
            for r in job_rows
        ]

        return {
            "total_amount": total_amount,
            "total_tax": total_tax,
            "total_count": total_count,
            "by_category": by_category,
            "by_project": by_project,
            "by_job": by_job,
        }

    # ------------------------------------------------------------------
    # Include in invoice
    # ------------------------------------------------------------------

    async def include_in_invoice(
        self,
        org_id: uuid.UUID,
        expense_ids: list[uuid.UUID],
        invoice_id: uuid.UUID,
    ) -> list[Expense]:
        """Mark expenses as invoiced and link to an invoice."""
        updated: list[Expense] = []
        for eid in expense_ids:
            expense = await self.get_expense(org_id, eid)
            if expense is None:
                raise ValueError(f"Expense {eid} not found")
            if expense.is_invoiced:
                raise ValueError(f"Expense {eid} is already invoiced")
            expense.is_invoiced = True
            expense.invoice_id = invoice_id
            updated.append(expense)
        await self.db.flush()
        return updated

    # ------------------------------------------------------------------
    # Pass-through expenses for job-to-invoice conversion
    # ------------------------------------------------------------------

    async def get_pass_through_expenses(
        self, org_id: uuid.UUID, job_id: uuid.UUID,
    ) -> list[Expense]:
        """Get all pass-through expenses for a job (not yet invoiced)."""
        stmt = (
            select(Expense)
            .where(
                and_(
                    Expense.org_id == org_id,
                    Expense.job_id == job_id,
                    Expense.is_pass_through.is_(True),
                    Expense.is_invoiced.is_(False),
                )
            )
            .order_by(Expense.date)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mileage preferences & rates
    # ------------------------------------------------------------------

    async def get_mileage_preferences(self, org_id: uuid.UUID) -> dict:
        """Get mileage preferences and rates for an org."""
        pref_stmt = select(MileagePreference).where(MileagePreference.org_id == org_id)
        pref = (await self.db.execute(pref_stmt)).scalar_one_or_none()

        rates_stmt = select(MileageRate).where(MileageRate.org_id == org_id).order_by(MileageRate.start_date.asc().nullsfirst())
        rates = list((await self.db.execute(rates_stmt)).scalars().all())

        return {
            "default_unit": pref.default_unit if pref else "km",
            "default_account": pref.default_account if pref else None,
            "rates": rates,
        }

    async def save_mileage_preferences(self, org_id: uuid.UUID, payload: MileagePreferenceUpdate) -> dict:
        """Upsert mileage preferences and replace rates."""
        pref_stmt = select(MileagePreference).where(MileagePreference.org_id == org_id)
        pref = (await self.db.execute(pref_stmt)).scalar_one_or_none()

        if pref is None:
            pref = MileagePreference(org_id=org_id)
            self.db.add(pref)

        if payload.default_unit is not None:
            pref.default_unit = payload.default_unit
        if payload.default_account is not None:
            pref.default_account = payload.default_account

        # Replace all rates
        del_stmt = select(MileageRate).where(MileageRate.org_id == org_id)
        existing = list((await self.db.execute(del_stmt)).scalars().all())
        for r in existing:
            await self.db.delete(r)

        new_rates = []
        for rate_data in payload.rates:
            rate = MileageRate(
                org_id=org_id,
                start_date=rate_data.start_date,
                rate_per_unit=rate_data.rate_per_unit,
                currency=rate_data.currency,
            )
            self.db.add(rate)
            new_rates.append(rate)

        await self.db.flush()
        return {
            "default_unit": pref.default_unit,
            "default_account": pref.default_account,
            "rates": new_rates,
        }

    async def bulk_create_expenses(
        self,
        org_id: uuid.UUID,
        expenses_data: list[ExpenseCreate],
        *,
        created_by: uuid.UUID | None = None,
    ) -> list[Expense]:
        """Bulk create multiple expenses."""
        created = []
        for payload in expenses_data:
            expense = await self.create_expense(org_id, payload, created_by=created_by)
            created.append(expense)
        return created
