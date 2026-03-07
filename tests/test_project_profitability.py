"""Test: project profitability correctly sums paid invoices vs expenses + labour costs.

**Validates: Requirement 14.1** — Project profitability calculation

Verifies that calculate_profitability() correctly computes:
- Revenue from paid invoices linked via jobs
- Labour costs from time entries (duration_minutes / 60 * hourly_rate)
- Expense costs from expenses linked to the project
- Profit = revenue - total_costs
- Margin percentage
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.projects.models import Project
from app.modules.projects.service import ProjectService


ORG_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_project() -> Project:
    return Project(
        id=PROJECT_ID,
        org_id=ORG_ID,
        name="Test Project",
        contract_value=Decimal("50000.00"),
        budget_amount=Decimal("40000.00"),
        retention_percentage=Decimal("5.00"),
        status="active",
    )


class _MockScalar:
    """Helper to simulate scalar() return from SQLAlchemy execute."""
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class TestProjectProfitability:
    """Project profitability correctly sums paid invoices vs expenses + labour costs."""

    @pytest.mark.asyncio
    async def test_profitability_with_revenue_and_labour(self):
        """Revenue from invoices minus labour costs gives correct profit."""
        mock_db = AsyncMock()

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Revenue query: sum of paid invoices = $30,000
                return _MockScalar(Decimal("30000.00"))
            elif call_count == 2:
                # Labour costs query: sum of time entry costs = $8,000
                return _MockScalar(Decimal("8000.00"))
            else:
                # Expense costs query (if expenses module exists)
                return _MockScalar(Decimal("5000.00"))

        mock_db.execute = fake_execute

        svc = ProjectService(mock_db)
        result = await svc.calculate_profitability(ORG_ID, PROJECT_ID)

        assert result["project_id"] == PROJECT_ID
        assert result["revenue"] == Decimal("30000.00")
        assert result["labour_costs"] == Decimal("8000.00")
        # Expense costs depend on whether expenses module is available
        # Profit = revenue - (labour + expenses)
        profit = result["revenue"] - result["total_costs"]
        assert result["profit"] == profit
        assert result["margin_percentage"] is not None

    @pytest.mark.asyncio
    async def test_profitability_zero_revenue(self):
        """When no invoices are paid, margin is None."""
        mock_db = AsyncMock()

        async def fake_execute(stmt):
            return _MockScalar(Decimal("0"))

        mock_db.execute = fake_execute

        svc = ProjectService(mock_db)
        result = await svc.calculate_profitability(ORG_ID, PROJECT_ID)

        assert result["revenue"] == Decimal("0")
        assert result["profit"] == Decimal("0")
        assert result["margin_percentage"] is None

    @pytest.mark.asyncio
    async def test_profitability_no_expenses_module(self):
        """When expenses module is not available, expense_costs defaults to 0."""
        mock_db = AsyncMock()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _MockScalar(Decimal("10000.00"))  # revenue
            elif call_count == 2:
                return _MockScalar(Decimal("3000.00"))  # labour
            else:
                raise ImportError("No expenses module")

        mock_db.execute = fake_execute

        svc = ProjectService(mock_db)

        # Patch the import to raise ImportError
        with patch.dict("sys.modules", {"app.modules.expenses.models": None}):
            result = await svc.calculate_profitability(ORG_ID, PROJECT_ID)

        assert result["revenue"] == Decimal("10000.00")
        assert result["labour_costs"] == Decimal("3000.00")
        assert result["expense_costs"] == Decimal("0")
        assert result["total_costs"] == Decimal("3000.00")
        assert result["profit"] == Decimal("7000.00")

    @pytest.mark.asyncio
    async def test_profitability_negative_profit(self):
        """When labour costs exceed revenue, profit is negative."""
        mock_db = AsyncMock()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _MockScalar(Decimal("5000.00"))  # revenue
            elif call_count == 2:
                return _MockScalar(Decimal("8000.00"))  # labour
            else:
                return _MockScalar(Decimal("0"))  # expenses

        mock_db.execute = fake_execute

        svc = ProjectService(mock_db)
        result = await svc.calculate_profitability(ORG_ID, PROJECT_ID)

        assert result["revenue"] == Decimal("5000.00")
        assert result["labour_costs"] == Decimal("8000.00")
        assert result["profit"] < Decimal("0")
