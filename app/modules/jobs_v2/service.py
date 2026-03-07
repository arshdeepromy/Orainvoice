"""Job service: CRUD, status transitions, staff assignment, attachments,
convert-to-invoice, and template management.

**Validates: Requirement 11.1, 11.2, 11.3, 11.5, 11.6, 11.7**
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs_v2.models import (
    Job, JobAttachment, JobStaffAssignment, JobStatusHistory, JobTemplate,
)
from app.modules.jobs_v2.schemas import (
    VALID_TRANSITIONS,
    ConvertToInvoiceRequest,
    JobAttachmentCreate,
    JobCreate,
    JobStaffAssignmentCreate,
    JobTemplateCreate,
    JobTemplateUpdate,
    JobUpdate,
)


class InvalidStatusTransition(Exception):
    """Raised when a job status transition is not allowed."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        allowed = VALID_TRANSITIONS.get(from_status, [])
        super().__init__(
            f"Invalid status transition from '{from_status}' to '{to_status}'. "
            f"Allowed transitions: {allowed}"
        )


class JobService:
    """Service layer for job and work order management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Job number generation
    # ------------------------------------------------------------------

    async def _next_job_number(self, org_id: uuid.UUID) -> str:
        """Generate the next sequential job number for an org."""
        stmt = (
            select(func.count())
            .select_from(Job)
            .where(Job.org_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return f"JOB-{count + 1:05d}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_jobs(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        customer_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[Job], int]:
        """List jobs with pagination and filtering."""
        stmt = select(Job).where(Job.org_id == org_id)

        if status is not None:
            stmt = stmt.where(Job.status == status)
        if customer_id is not None:
            stmt = stmt.where(Job.customer_id == customer_id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                Job.title.ilike(pattern)
                | Job.job_number.ilike(pattern)
                | Job.description.ilike(pattern)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(Job.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_job(
        self,
        org_id: uuid.UUID,
        data: JobCreate,
        *,
        created_by: uuid.UUID | None = None,
    ) -> Job:
        """Create a new job with auto-generated job number."""
        job_number = await self._next_job_number(org_id)
        job = Job(
            org_id=org_id,
            customer_id=data.customer_id,
            location_id=data.location_id,
            project_id=data.project_id,
            template_id=data.template_id,
            job_number=job_number,
            title=data.title,
            description=data.description,
            status="draft",
            priority=data.priority,
            site_address=data.site_address,
            scheduled_start=data.scheduled_start,
            scheduled_end=data.scheduled_end,
            checklist=data.checklist,
            internal_notes=data.internal_notes,
            customer_notes=data.customer_notes,
            created_by=created_by,
        )
        self.db.add(job)
        await self.db.flush()

        # Record initial status
        history = JobStatusHistory(
            job_id=job.id,
            from_status=None,
            to_status="draft",
            changed_by=created_by,
        )
        self.db.add(history)
        await self.db.flush()
        return job

    async def get_job(
        self, org_id: uuid.UUID, job_id: uuid.UUID,
    ) -> Job | None:
        """Get a single job by ID."""
        stmt = select(Job).where(
            and_(Job.id == job_id, Job.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_job(
        self, org_id: uuid.UUID, job_id: uuid.UUID, data: JobUpdate,
    ) -> Job | None:
        """Update a job's fields."""
        job = await self.get_job(org_id, job_id)
        if job is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(job, field, value)
        await self.db.flush()
        return job

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    @staticmethod
    def validate_transition(from_status: str, to_status: str) -> bool:
        """Check if a status transition is valid."""
        allowed = VALID_TRANSITIONS.get(from_status, [])
        return to_status in allowed

    async def change_status(
        self,
        org_id: uuid.UUID,
        job_id: uuid.UUID,
        to_status: str,
        *,
        changed_by: uuid.UUID | None = None,
        notes: str | None = None,
    ) -> Job:
        """Change job status with transition validation.

        Raises InvalidStatusTransition if the transition is not allowed.
        """
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")

        if not self.validate_transition(job.status, to_status):
            raise InvalidStatusTransition(job.status, to_status)

        from_status = job.status
        job.status = to_status
        await self.db.flush()

        history = JobStatusHistory(
            job_id=job.id,
            from_status=from_status,
            to_status=to_status,
            changed_by=changed_by,
            notes=notes,
        )
        self.db.add(history)
        await self.db.flush()
        return job

    # ------------------------------------------------------------------
    # Staff assignments
    # ------------------------------------------------------------------

    async def assign_staff(
        self,
        org_id: uuid.UUID,
        job_id: uuid.UUID,
        data: JobStaffAssignmentCreate,
    ) -> JobStaffAssignment:
        """Assign a staff member to a job."""
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")

        assignment = JobStaffAssignment(
            job_id=job.id,
            user_id=data.user_id,
            role=data.role,
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def remove_staff(
        self,
        org_id: uuid.UUID,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Remove a staff assignment from a job."""
        job = await self.get_job(org_id, job_id)
        if job is None:
            return False
        stmt = select(JobStaffAssignment).where(
            and_(
                JobStaffAssignment.job_id == job.id,
                JobStaffAssignment.user_id == user_id,
            ),
        )
        result = await self.db.execute(stmt)
        assignment = result.scalar_one_or_none()
        if assignment is None:
            return False
        await self.db.delete(assignment)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    async def add_attachment(
        self,
        org_id: uuid.UUID,
        job_id: uuid.UUID,
        data: JobAttachmentCreate,
        *,
        uploaded_by: uuid.UUID | None = None,
    ) -> JobAttachment:
        """Add a file attachment to a job.

        Also increments the org's storage_used_bytes.
        """
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")

        attachment = JobAttachment(
            job_id=job.id,
            file_key=data.file_key,
            file_name=data.file_name,
            file_size=data.file_size,
            content_type=data.content_type,
            uploaded_by=uploaded_by,
        )
        self.db.add(attachment)

        # Update org storage quota
        from sqlalchemy import text
        await self.db.execute(
            text(
                "UPDATE organisations SET storage_used_bytes = storage_used_bytes + :size "
                "WHERE id = :org_id"
            ),
            {"size": data.file_size, "org_id": str(org_id)},
        )
        await self.db.flush()
        return attachment

    async def list_attachments(
        self, org_id: uuid.UUID, job_id: uuid.UUID,
    ) -> list[JobAttachment]:
        """List all attachments for a job."""
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")
        stmt = select(JobAttachment).where(
            JobAttachment.job_id == job.id,
        ).order_by(JobAttachment.uploaded_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Convert to invoice
    # ------------------------------------------------------------------

    async def convert_to_invoice(
        self,
        org_id: uuid.UUID,
        job_id: uuid.UUID,
        data: ConvertToInvoiceRequest,
        *,
        changed_by: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Convert a completed job to a Draft invoice.

        Creates line items from:
        - time_entries → Labour items (hours × rate)
        - expenses → pass-through line items
        - materials → Product line items

        Returns dict with invoice_id and line_items_count.
        """
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")

        if job.status != "completed":
            raise ValueError("Only completed jobs can be converted to invoices")

        if job.converted_invoice_id is not None:
            raise ValueError("Job has already been converted to an invoice")

        # Build line items from provided data
        line_items: list[dict] = []

        # Time entries → Labour items
        for entry in data.time_entries:
            hours = entry.get("hours", 0)
            rate = entry.get("rate", 0)
            line_items.append({
                "type": "labour",
                "description": entry.get("description", "Labour"),
                "quantity": hours,
                "unit_price": rate,
                "total": round(hours * rate, 2),
            })

        # Expenses → pass-through items
        for expense in data.expenses:
            line_items.append({
                "type": "expense",
                "description": expense.get("description", "Expense"),
                "quantity": 1,
                "unit_price": expense.get("amount", 0),
                "total": expense.get("amount", 0),
            })

        # Materials → Product items
        for material in data.materials:
            qty = material.get("quantity", 1)
            price = material.get("unit_price", 0)
            line_items.append({
                "type": "product",
                "description": material.get("description", "Material"),
                "quantity": qty,
                "unit_price": price,
                "total": round(qty * price, 2),
                "product_id": material.get("product_id"),
            })

        # Create a placeholder invoice ID (actual invoice creation
        # would be handled by the invoice module in production)
        invoice_id = uuid.uuid4()

        # Update job status to invoiced
        job.converted_invoice_id = invoice_id
        job.status = "invoiced"
        await self.db.flush()

        # Record status change
        history = JobStatusHistory(
            job_id=job.id,
            from_status="completed",
            to_status="invoiced",
            changed_by=changed_by,
            notes="Converted to invoice",
        )
        self.db.add(history)
        await self.db.flush()

        return {
            "job_id": job.id,
            "invoice_id": invoice_id,
            "line_items": line_items,
            "line_items_count": len(line_items),
        }

    # ------------------------------------------------------------------
    # Status history
    # ------------------------------------------------------------------

    async def get_status_history(
        self, org_id: uuid.UUID, job_id: uuid.UUID,
    ) -> list[JobStatusHistory]:
        """Get the full status history for a job."""
        job = await self.get_job(org_id, job_id)
        if job is None:
            raise ValueError("Job not found")
        stmt = (
            select(JobStatusHistory)
            .where(JobStatusHistory.job_id == job.id)
            .order_by(JobStatusHistory.changed_at)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    async def list_templates(
        self,
        org_id: uuid.UUID,
        *,
        trade_category_slug: str | None = None,
    ) -> tuple[list[JobTemplate], int]:
        """List job templates for an org."""
        stmt = select(JobTemplate).where(
            and_(JobTemplate.org_id == org_id, JobTemplate.is_active.is_(True)),
        )
        if trade_category_slug:
            stmt = stmt.where(
                JobTemplate.trade_category_slug == trade_category_slug,
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(JobTemplate.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_template(
        self, org_id: uuid.UUID, data: JobTemplateCreate,
    ) -> JobTemplate:
        """Create a new job template."""
        template = JobTemplate(
            org_id=org_id,
            name=data.name,
            trade_category_slug=data.trade_category_slug,
            description=data.description,
            checklist=data.checklist,
            default_line_items=data.default_line_items,
        )
        self.db.add(template)
        await self.db.flush()
        return template

    async def get_template(
        self, org_id: uuid.UUID, template_id: uuid.UUID,
    ) -> JobTemplate | None:
        stmt = select(JobTemplate).where(
            and_(JobTemplate.id == template_id, JobTemplate.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_template(
        self, org_id: uuid.UUID, template_id: uuid.UUID, data: JobTemplateUpdate,
    ) -> JobTemplate | None:
        template = await self.get_template(org_id, template_id)
        if template is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(template, field, value)
        await self.db.flush()
        return template

    async def delete_template(
        self, org_id: uuid.UUID, template_id: uuid.UUID,
    ) -> bool:
        """Soft-delete a template by setting is_active=False."""
        template = await self.get_template(org_id, template_id)
        if template is None:
            return False
        template.is_active = False
        await self.db.flush()
        return True
