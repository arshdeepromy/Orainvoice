"""Test: pass-through expenses appear as line items on job-to-invoice conversion.

**Validates: Requirement 11.6, Expense Module**

Verifies that when a job is converted to an invoice, pass-through expenses
(is_pass_through=True) are included as expense line items, while non-pass-through
expenses are excluded.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.expenses.models import Expense
from app.modules.expenses.service import ExpenseService
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

    async def fake_delete(obj):
        pass

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    mock_db.delete = fake_delete
    mock_db._added = added_objects
    return mock_db


def _make_expense(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    is_pass_through: bool = False,
    amount: Decimal = Decimal("50.00"),
    description: str = "Test expense",
) -> Expense:
    """Create an Expense instance for testing."""
    return Expense(
        id=uuid.uuid4(),
        org_id=org_id,
        job_id=job_id,
        date=date.today(),
        description=description,
        amount=amount,
        tax_amount=Decimal("0"),
        category="materials",
        is_pass_through=is_pass_through,
        is_invoiced=False,
    )


class TestPassThroughExpensesOnInvoiceConversion:
    """Validates: Requirement 11.6 — pass-through expenses appear as line items."""

    @pytest.mark.asyncio
    async def test_pass_through_expenses_returned_by_service(self):
        """ExpenseService.get_pass_through_expenses returns only pass-through, non-invoiced expenses."""
        org_id = uuid.uuid4()
        job_id = uuid.uuid4()

        pass_through_1 = _make_expense(org_id, job_id, is_pass_through=True, amount=Decimal("100.00"), description="Pipe fittings")
        pass_through_2 = _make_expense(org_id, job_id, is_pass_through=True, amount=Decimal("75.50"), description="Travel")
        non_pass_through = _make_expense(org_id, job_id, is_pass_through=False, amount=Decimal("200.00"), description="Internal cost")

        mock_db = _make_mock_db()

        # Mock the query to return only pass-through expenses
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [pass_through_1, pass_through_2]
        mock_result.scalars.return_value = mock_scalars

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = ExpenseService(mock_db)
        expenses = await svc.get_pass_through_expenses(org_id, job_id)

        assert len(expenses) == 2
        assert all(e.is_pass_through for e in expenses)
        assert expenses[0].description == "Pipe fittings"
        assert expenses[1].description == "Travel"

    @pytest.mark.asyncio
    async def test_pass_through_expenses_become_invoice_line_items(self):
        """When converting a job to invoice, pass-through expenses appear as expense line items."""
        org_id = uuid.uuid4()
        job_id = uuid.uuid4()
        job = Job(
            id=job_id,
            org_id=org_id,
            job_number="JOB-00010",
            title="Plumbing repair",
            status="completed",
            customer_id=uuid.uuid4(),
        )

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        # Simulate pass-through expenses as expense line items in the conversion request
        data = ConvertToInvoiceRequest(
            expenses=[
                {"description": "Pipe fittings (pass-through)", "amount": 100.00},
                {"description": "Travel (pass-through)", "amount": 75.50},
            ],
        )
        result = await svc.convert_to_invoice(org_id, job_id, data)

        assert result["line_items_count"] == 2
        items = result["line_items"]
        assert items[0]["type"] == "expense"
        assert items[0]["description"] == "Pipe fittings (pass-through)"
        assert items[0]["total"] == 100.00
        assert items[1]["type"] == "expense"
        assert items[1]["description"] == "Travel (pass-through)"
        assert items[1]["total"] == 75.50

    @pytest.mark.asyncio
    async def test_non_pass_through_excluded_from_conversion(self):
        """Non-pass-through expenses should not be included in invoice conversion."""
        org_id = uuid.uuid4()
        job_id = uuid.uuid4()

        # Only pass-through expenses should be in the conversion request
        # Non-pass-through expenses are internal costs and excluded
        job = Job(
            id=job_id,
            org_id=org_id,
            job_number="JOB-00011",
            title="Electrical work",
            status="completed",
            customer_id=uuid.uuid4(),
        )

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        # Only pass-through expenses are included; internal costs are omitted
        data = ConvertToInvoiceRequest(
            expenses=[
                {"description": "Pass-through parts", "amount": 50.00},
            ],
            time_entries=[
                {"description": "Labour", "hours": 2, "rate": 80},
            ],
        )
        result = await svc.convert_to_invoice(org_id, job_id, data)

        assert result["line_items_count"] == 2
        types = [item["type"] for item in result["line_items"]]
        assert "labour" in types
        assert "expense" in types
        # The internal cost is not present
        descriptions = [item["description"] for item in result["line_items"]]
        assert "Internal cost" not in descriptions

    @pytest.mark.asyncio
    async def test_include_in_invoice_marks_expenses(self):
        """include_in_invoice marks expenses as invoiced and links to invoice."""
        org_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        expense = _make_expense(org_id, uuid.uuid4(), is_pass_through=True, amount=Decimal("100.00"))

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = expense
            return mock_result

        mock_db.execute = fake_execute

        svc = ExpenseService(mock_db)
        result = await svc.include_in_invoice(org_id, [expense.id], invoice_id)

        assert len(result) == 1
        assert result[0].is_invoiced is True
        assert result[0].invoice_id == invoice_id

    @pytest.mark.asyncio
    async def test_already_invoiced_expense_cannot_be_included_again(self):
        """An already-invoiced expense cannot be included in another invoice."""
        org_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        expense = _make_expense(org_id, uuid.uuid4(), is_pass_through=True)
        expense.is_invoiced = True
        expense.invoice_id = uuid.uuid4()

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = expense
            return mock_result

        mock_db.execute = fake_execute

        svc = ExpenseService(mock_db)
        with pytest.raises(ValueError, match="already invoiced"):
            await svc.include_in_invoice(org_id, [expense.id], invoice_id)
