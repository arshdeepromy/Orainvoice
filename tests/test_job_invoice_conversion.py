"""Test: job-to-invoice conversion creates correct line items.

**Validates: Requirement 11.6** — Property 5

Verifies that converting a completed job to an invoice creates the
correct line items from time entries (Labour), expenses (pass-through),
and materials (Product).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.jobs_v2.models import Job
from app.modules.jobs_v2.schemas import ConvertToInvoiceRequest
from app.modules.jobs_v2.service import JobService


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    added_objects: list = []

    async def fake_flush():
        pass

    def fake_add(obj):
        added_objects.append(obj)

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    mock_db._added = added_objects
    return mock_db


def _make_completed_job() -> Job:
    """Create a completed Job instance."""
    return Job(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        job_number="JOB-00001",
        title="Test Job",
        status="completed",
        customer_id=uuid.uuid4(),
    )


class TestJobToInvoiceConversion:
    """Validates: Requirement 11.6"""

    @pytest.mark.asyncio
    async def test_time_entries_become_labour_items(self):
        """Time entries are converted to Labour line items (hours × rate)."""
        job = _make_completed_job()
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = ConvertToInvoiceRequest(
            time_entries=[
                {"description": "Plumbing work", "hours": 3.5, "rate": 85.0},
                {"description": "Electrical work", "hours": 2.0, "rate": 95.0},
            ],
        )
        result = await svc.convert_to_invoice(job.org_id, job.id, data)

        assert result["line_items_count"] == 2
        items = result["line_items"]
        assert items[0]["type"] == "labour"
        assert items[0]["description"] == "Plumbing work"
        assert items[0]["quantity"] == 3.5
        assert items[0]["unit_price"] == 85.0
        assert items[0]["total"] == 297.5
        assert items[1]["type"] == "labour"
        assert items[1]["total"] == 190.0

    @pytest.mark.asyncio
    async def test_expenses_become_pass_through_items(self):
        """Expenses are converted to expense line items."""
        job = _make_completed_job()
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = ConvertToInvoiceRequest(
            expenses=[
                {"description": "Pipe fittings", "amount": 45.50},
                {"description": "Travel", "amount": 30.00},
            ],
        )
        result = await svc.convert_to_invoice(job.org_id, job.id, data)

        assert result["line_items_count"] == 2
        items = result["line_items"]
        assert items[0]["type"] == "expense"
        assert items[0]["total"] == 45.50
        assert items[1]["type"] == "expense"
        assert items[1]["total"] == 30.00

    @pytest.mark.asyncio
    async def test_materials_become_product_items(self):
        """Materials are converted to Product line items."""
        job = _make_completed_job()
        mock_db = _make_mock_db()
        product_id = uuid.uuid4()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = ConvertToInvoiceRequest(
            materials=[
                {"description": "Copper pipe 15mm", "quantity": 5, "unit_price": 12.00, "product_id": str(product_id)},
            ],
        )
        result = await svc.convert_to_invoice(job.org_id, job.id, data)

        assert result["line_items_count"] == 1
        item = result["line_items"][0]
        assert item["type"] == "product"
        assert item["quantity"] == 5
        assert item["unit_price"] == 12.00
        assert item["total"] == 60.00
        assert item["product_id"] == str(product_id)

    @pytest.mark.asyncio
    async def test_combined_conversion_all_types(self):
        """All three types combined produce correct total line items."""
        job = _make_completed_job()
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = ConvertToInvoiceRequest(
            time_entries=[{"description": "Labour", "hours": 2, "rate": 80}],
            expenses=[{"description": "Parts", "amount": 50}],
            materials=[{"description": "Widget", "quantity": 3, "unit_price": 10}],
        )
        result = await svc.convert_to_invoice(job.org_id, job.id, data)

        assert result["line_items_count"] == 3
        types = [item["type"] for item in result["line_items"]]
        assert types == ["labour", "expense", "product"]

    @pytest.mark.asyncio
    async def test_job_status_changes_to_invoiced(self):
        """After conversion, job status is 'invoiced'."""
        job = _make_completed_job()
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = ConvertToInvoiceRequest()
        await svc.convert_to_invoice(job.org_id, job.id, data)

        assert job.status == "invoiced"
        assert job.converted_invoice_id is not None

    @pytest.mark.asyncio
    async def test_non_completed_job_cannot_convert(self):
        """Only completed jobs can be converted."""
        job = _make_completed_job()
        job.status = "in_progress"
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        with pytest.raises(ValueError, match="Only completed jobs"):
            await svc.convert_to_invoice(
                job.org_id, job.id, ConvertToInvoiceRequest(),
            )

    @pytest.mark.asyncio
    async def test_already_converted_job_cannot_convert_again(self):
        """A job that's already been converted cannot be converted again."""
        job = _make_completed_job()
        job.converted_invoice_id = uuid.uuid4()
        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        with pytest.raises(ValueError, match="already been converted"):
            await svc.convert_to_invoice(
                job.org_id, job.id, ConvertToInvoiceRequest(),
            )
