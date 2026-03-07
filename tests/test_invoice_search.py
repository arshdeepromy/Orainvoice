"""Unit tests for Task 10.6 — invoice search and filtering.

Tests cover:
  - Schema validation for search query params and list response
  - search_invoices service: text search, status filter, date range, pagination
  - Stackable filters (combining search + status + date range)
  - Customer name/phone/email search via join

Requirements: 21.1, 21.2, 21.3, 21.4
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.invoices.schemas import (
    InvoiceListResponse,
    InvoiceSearchResult,
)
from app.modules.invoices.service import search_invoices


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestInvoiceSearchResultSchema:
    """Validates: Requirements 21.4"""

    def test_minimal_search_result(self):
        result = InvoiceSearchResult(
            id=uuid.uuid4(),
            total=Decimal("100.00"),
            status="draft",
        )
        assert result.invoice_number is None
        assert result.customer_name is None
        assert result.vehicle_rego is None
        assert result.issue_date is None

    def test_full_search_result(self):
        result = InvoiceSearchResult(
            id=uuid.uuid4(),
            invoice_number="INV-0001",
            customer_name="John Smith",
            vehicle_rego="ABC123",
            total=Decimal("230.00"),
            status="issued",
            issue_date=date(2024, 6, 15),
        )
        assert result.invoice_number == "INV-0001"
        assert result.customer_name == "John Smith"
        assert result.vehicle_rego == "ABC123"
        assert result.total == Decimal("230.00")
        assert result.status == "issued"
        assert result.issue_date == date(2024, 6, 15)


class TestInvoiceListResponseSchema:
    """Validates: Requirements 21.1, 21.4"""

    def test_empty_list_response(self):
        resp = InvoiceListResponse(
            invoices=[], total=0, limit=25, offset=0
        )
        assert resp.invoices == []
        assert resp.total == 0

    def test_list_response_with_results(self):
        items = [
            InvoiceSearchResult(
                id=uuid.uuid4(),
                invoice_number=f"INV-{i:04d}",
                customer_name=f"Customer {i}",
                total=Decimal("100.00"),
                status="issued",
            )
            for i in range(3)
        ]
        resp = InvoiceListResponse(
            invoices=items, total=50, limit=25, offset=0
        )
        assert len(resp.invoices) == 3
        assert resp.total == 50
        assert resp.limit == 25
        assert resp.offset == 0


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_search_row(
    *,
    inv_id=None,
    invoice_number=None,
    first_name="John",
    last_name="Smith",
    vehicle_rego="ABC123",
    total=Decimal("115.00"),
    status="issued",
    issue_date=date(2024, 6, 15),
):
    """Create a mock row matching the search query column order."""
    row = MagicMock()
    row.id = inv_id or uuid.uuid4()
    row.invoice_number = invoice_number
    row.first_name = first_name
    row.last_name = last_name
    row.vehicle_rego = vehicle_rego
    row.total = total
    row.status = status
    row.issue_date = issue_date
    return row


class TestSearchInvoicesService:
    """Validates: Requirements 21.1, 21.2, 21.3, 21.4"""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_invoices(self):
        """No invoices → empty list with total=0."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        # Count query returns 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        # Data query returns empty
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(db, org_id=org_id)

        assert result["invoices"] == []
        assert result["total"] == 0
        assert result["limit"] == 25
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_returns_invoices_with_customer_name(self):
        """Results include concatenated customer first+last name."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        row = _make_search_row(
            invoice_number="INV-0001",
            first_name="Jane",
            last_name="Doe",
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([row]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(db, org_id=org_id)

        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["customer_name"] == "Jane Doe"
        assert result["invoices"][0]["invoice_number"] == "INV-0001"
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_pagination_params_passed_through(self):
        """Limit and offset are reflected in the response."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        count_result = MagicMock()
        count_result.scalar.return_value = 100
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(
            db, org_id=org_id, limit=10, offset=20
        )

        assert result["limit"] == 10
        assert result["offset"] == 20
        assert result["total"] == 100

    @pytest.mark.asyncio
    async def test_customer_name_none_when_both_names_empty(self):
        """If customer first_name and last_name are both empty, customer_name is None."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        row = _make_search_row(first_name="", last_name="")

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([row]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(db, org_id=org_id)

        assert result["invoices"][0]["customer_name"] is None

    @pytest.mark.asyncio
    async def test_customer_name_when_only_first_name(self):
        """If only first_name is set, customer_name is just the first name."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        row = _make_search_row(first_name="Alice", last_name="")

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([row]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(db, org_id=org_id)

        assert result["invoices"][0]["customer_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_search_builds_query_with_text_filter(self):
        """When search param is provided, the query is executed (smoke test)."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(
            db, org_id=org_id, search="INV-0001"
        )

        assert result["total"] == 0
        # Two execute calls: count + data
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_status_filter_accepted(self):
        """Status filter is accepted without error."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(
            db, org_id=org_id, status="overdue"
        )

        assert result["total"] == 0
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_date_range_filter_accepted(self):
        """Date range filters are accepted without error."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(
            db,
            org_id=org_id,
            issue_date_from=date(2024, 1, 1),
            issue_date_to=date(2024, 12, 31),
        )

        assert result["total"] == 0
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_stacked_filters_accepted(self):
        """All filters combined (search + status + date range) work together.

        Validates: Requirement 21.3 — stackable filters.
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        row = _make_search_row(
            invoice_number="INV-0005",
            status="overdue",
            issue_date=date(2024, 3, 15),
        )

        count_result = MagicMock()
        count_result.scalar.return_value = 1
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([row]))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(
            db,
            org_id=org_id,
            search="INV-0005",
            status="overdue",
            issue_date_from=date(2024, 1, 1),
            issue_date_to=date(2024, 6, 30),
        )

        assert result["total"] == 1
        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["status"] == "overdue"

    @pytest.mark.asyncio
    async def test_multiple_results_returned(self):
        """Multiple rows are returned correctly."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        rows = [
            _make_search_row(invoice_number=f"INV-{i:04d}", first_name=f"Cust{i}")
            for i in range(5)
        ]

        count_result = MagicMock()
        count_result.scalar.return_value = 5
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter(rows))

        db.execute = AsyncMock(side_effect=[count_result, data_result])

        result = await search_invoices(db, org_id=org_id)

        assert len(result["invoices"]) == 5
        assert result["total"] == 5
