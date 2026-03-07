"""Integration test: job-to-invoice conversion flow.

Flow: create job → assign staff → log time → add expenses → add materials
      → convert to invoice → verify all items present → issue → pay.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.jobs_v2.models import Job, JobStaffAssignment, JobStatusHistory
from app.modules.jobs_v2.service import JobService, InvalidStatusTransition
from app.modules.jobs_v2.schemas import (
    ConvertToInvoiceRequest,
    JobCreate,
    JobStaffAssignmentCreate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(org_id, *, status="draft", job_number="JOB-00001"):
    job = Job()
    job.id = uuid.uuid4()
    job.org_id = org_id
    job.job_number = job_number
    job.title = "Fix plumbing"
    job.status = status
    job.customer_id = uuid.uuid4()
    job.location_id = None
    job.project_id = None
    job.converted_invoice_id = None
    job.created_at = datetime.now(timezone.utc)
    job.updated_at = datetime.now(timezone.utc)
    return job


def _make_db_for_job(job):
    """Create a mock DB that returns the given job on queries."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()

    job_result = MagicMock()
    job_result.scalar_one_or_none.return_value = job
    count_result = MagicMock()
    count_result.scalar.return_value = 1

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        sql_str = str(stmt) if not isinstance(stmt, MagicMock) else ""
        if "count" in sql_str.lower():
            return count_result
        return job_result

    db.execute = mock_execute
    return db


class TestJobToInvoiceFlow:
    """End-to-end job lifecycle: create → staff → time → expenses → invoice."""

    @pytest.mark.asyncio
    async def test_create_job_generates_number(self):
        """Creating a job auto-generates a sequential job number."""
        org_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 5
        db.execute = AsyncMock(return_value=count_result)

        svc = JobService(db)
        job_data = JobCreate(
            title="Fix plumbing",
            customer_id=uuid.uuid4(),
        )
        job = await svc.create_job(org_id, job_data, created_by=uuid.uuid4())

        assert job.job_number == "JOB-00006"
        assert job.status == "draft"
        assert db.add.called

    @pytest.mark.asyncio
    async def test_assign_staff_to_job(self):
        """Staff can be assigned to a job."""
        org_id = uuid.uuid4()
        job = _make_job(org_id)
        db = _make_db_for_job(job)

        svc = JobService(db)
        assignment_data = JobStaffAssignmentCreate(
            user_id=uuid.uuid4(),
            role="lead",
        )
        assignment = await svc.assign_staff(org_id, job.id, assignment_data)

        assert assignment.job_id == job.id
        assert db.add.called

    @pytest.mark.asyncio
    async def test_valid_status_transitions(self):
        """Job follows valid status transition path."""
        org_id = uuid.uuid4()
        job = _make_job(org_id, status="draft")
        db = _make_db_for_job(job)
        svc = JobService(db)

        # draft → scheduled
        result = await svc.change_status(org_id, job.id, "scheduled")
        assert result.status == "scheduled"

        # scheduled → in_progress
        result = await svc.change_status(org_id, job.id, "in_progress")
        assert result.status == "in_progress"

        # in_progress → completed
        result = await svc.change_status(org_id, job.id, "completed")
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_invalid_status_transition_rejected(self):
        """Invalid status transitions are rejected."""
        org_id = uuid.uuid4()
        job = _make_job(org_id, status="draft")
        db = _make_db_for_job(job)
        svc = JobService(db)

        with pytest.raises(InvalidStatusTransition):
            await svc.change_status(org_id, job.id, "completed")

    @pytest.mark.asyncio
    async def test_convert_completed_job_to_invoice(self):
        """Converting a completed job creates an invoice with all line items."""
        org_id = uuid.uuid4()
        job = _make_job(org_id, status="completed")
        db = _make_db_for_job(job)
        svc = JobService(db)

        convert_data = ConvertToInvoiceRequest(
            time_entries=[
                {"description": "Plumbing work", "hours": 3.0, "rate": 85.0},
                {"description": "Travel time", "hours": 0.5, "rate": 65.0},
            ],
            expenses=[
                {"description": "Pipe fittings", "amount": 45.50},
            ],
            materials=[
                {"description": "Copper pipe 2m", "quantity": 2, "unit_price": 28.00, "product_id": str(uuid.uuid4())},
            ],
        )

        result = await svc.convert_to_invoice(
            org_id, job.id, convert_data, changed_by=uuid.uuid4()
        )

        assert result["line_items_count"] == 4  # 2 time + 1 expense + 1 material
        assert result["invoice_id"] is not None

        # Verify line item types
        types = [item["type"] for item in result["line_items"]]
        assert types.count("labour") == 2
        assert types.count("expense") == 1
        assert types.count("product") == 1

        # Verify labour calculations
        labour_items = [i for i in result["line_items"] if i["type"] == "labour"]
        assert labour_items[0]["total"] == 255.0  # 3 * 85
        assert labour_items[1]["total"] == 32.5   # 0.5 * 65

        # Job status should be updated to invoiced
        assert job.status == "invoiced"
        assert job.converted_invoice_id is not None

    @pytest.mark.asyncio
    async def test_cannot_convert_non_completed_job(self):
        """Only completed jobs can be converted to invoices."""
        org_id = uuid.uuid4()
        job = _make_job(org_id, status="in_progress")
        db = _make_db_for_job(job)
        svc = JobService(db)

        with pytest.raises(ValueError, match="Only completed jobs"):
            await svc.convert_to_invoice(
                org_id, job.id,
                ConvertToInvoiceRequest(time_entries=[], expenses=[], materials=[]),
            )

    @pytest.mark.asyncio
    async def test_cannot_convert_already_invoiced_job(self):
        """A job that's already been converted cannot be converted again."""
        org_id = uuid.uuid4()
        job = _make_job(org_id, status="completed")
        job.converted_invoice_id = uuid.uuid4()  # Already converted
        db = _make_db_for_job(job)
        svc = JobService(db)

        with pytest.raises(ValueError, match="already been converted"):
            await svc.convert_to_invoice(
                org_id, job.id,
                ConvertToInvoiceRequest(time_entries=[], expenses=[], materials=[]),
            )
