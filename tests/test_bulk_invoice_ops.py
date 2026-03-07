"""Unit tests for Task 14.3 — Bulk invoice export and archive.

Tests cover:
  - Bulk export: CSV generation from invoice dicts
  - Bulk export: date range filtering
  - Bulk export: empty result handling
  - Bulk delete: confirmation preview (confirm=False)
  - Bulk delete: actual deletion with audit log
  - Bulk delete: no matching invoices
  - Schema validation: end_date before start_date rejected

Requirements: 31.1, 31.2, 31.3
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.invoices.schemas import (
    BulkDeleteRequest,
    BulkExportRequest,
    ExportFormat,
)
from app.modules.invoices.service import (
    bulk_delete_invoices,
    bulk_export_invoices,
    invoices_to_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_invoice_dict(
    number: str = "INV-0001",
    status: str = "issued",
    issue_date: date | None = None,
    total: Decimal | None = None,
) -> dict:
    """Create a minimal invoice dict for testing."""
    return {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "invoice_number": number,
        "customer_id": uuid.uuid4(),
        "vehicle_rego": "ABC123",
        "vehicle_make": "Toyota",
        "vehicle_model": "Corolla",
        "vehicle_year": 2020,
        "currency": "NZD",
        "status": status,
        "issue_date": issue_date or date(2024, 6, 15),
        "due_date": date(2024, 7, 15),
        "subtotal": Decimal("100.00"),
        "discount_amount": Decimal("0.00"),
        "gst_amount": Decimal("15.00"),
        "total": total or Decimal("115.00"),
        "amount_paid": Decimal("0.00"),
        "balance_due": total or Decimal("115.00"),
        "notes_customer": "Thank you",
    }


def _make_mock_invoice(
    inv_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
    number: str = "INV-0001",
    status: str = "issued",
    issue_date: date | None = None,
    total: Decimal = Decimal("115.00"),
) -> MagicMock:
    """Create a mock Invoice ORM object."""
    inv = MagicMock()
    inv.id = inv_id or uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.invoice_number = number
    inv.customer_id = uuid.uuid4()
    inv.vehicle_rego = "ABC123"
    inv.vehicle_make = "Toyota"
    inv.vehicle_model = "Corolla"
    inv.vehicle_year = 2020
    inv.vehicle_odometer = 50000
    inv.branch_id = None
    inv.status = status
    inv.issue_date = issue_date or date(2024, 6, 15)
    inv.due_date = date(2024, 7, 15)
    inv.currency = "NZD"
    inv.exchange_rate_to_nzd = Decimal("1.000000")
    inv.subtotal = Decimal("100.00")
    inv.discount_amount = Decimal("0.00")
    inv.discount_type = None
    inv.discount_value = None
    inv.gst_amount = Decimal("15.00")
    inv.total = total
    inv.amount_paid = Decimal("0.00")
    inv.balance_due = total
    inv.notes_internal = None
    inv.notes_customer = "Thank you"
    inv.void_reason = None
    inv.voided_at = None
    inv.voided_by = None
    inv.line_items = []
    inv.invoice_data_json = {"test": "data", "number": number}
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime(2024, 6, 15, tzinfo=timezone.utc)
    inv.updated_at = datetime(2024, 6, 15, tzinfo=timezone.utc)
    return inv


# ---------------------------------------------------------------------------
# CSV Generation Tests
# ---------------------------------------------------------------------------


class TestInvoicesToCsv:
    """Tests for invoices_to_csv function."""

    def test_empty_list_returns_empty_string(self):
        """Empty invoice list produces empty CSV."""
        result = invoices_to_csv([])
        assert result == ""

    def test_single_invoice_csv(self):
        """Single invoice produces valid CSV with header and one data row."""
        inv = _make_invoice_dict(number="INV-0001", total=Decimal("230.00"))
        result = invoices_to_csv([inv])

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["invoice_number"] == "INV-0001"
        assert rows[0]["total"] == "230.00"
        assert rows[0]["status"] == "issued"

    def test_multiple_invoices_csv(self):
        """Multiple invoices produce correct number of rows."""
        dicts = [
            _make_invoice_dict(number=f"INV-{i:04d}")
            for i in range(1, 4)
        ]
        result = invoices_to_csv(dicts)

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 3
        assert rows[0]["invoice_number"] == "INV-0001"
        assert rows[2]["invoice_number"] == "INV-0003"

    def test_csv_header_fields(self):
        """CSV contains expected header fields."""
        inv = _make_invoice_dict()
        result = invoices_to_csv([inv])

        reader = csv.DictReader(io.StringIO(result))
        expected_fields = {
            "invoice_number", "status", "issue_date", "due_date",
            "customer_id", "vehicle_rego", "vehicle_make", "vehicle_model",
            "vehicle_year", "currency", "subtotal", "discount_amount",
            "gst_amount", "total", "amount_paid", "balance_due",
            "notes_customer",
        }
        assert set(reader.fieldnames) == expected_fields

    def test_csv_handles_none_values(self):
        """None values are serialised as empty strings."""
        inv = _make_invoice_dict()
        inv["notes_customer"] = None
        inv["vehicle_rego"] = None
        result = invoices_to_csv([inv])

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["notes_customer"] == ""
        assert rows[0]["vehicle_rego"] == ""

    def test_csv_date_formatting(self):
        """Dates are formatted as ISO strings."""
        inv = _make_invoice_dict()
        inv["issue_date"] = date(2024, 3, 15)
        result = invoices_to_csv([inv])

        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert rows[0]["issue_date"] == "2024-03-15"


# ---------------------------------------------------------------------------
# Schema Validation Tests
# ---------------------------------------------------------------------------


class TestBulkExportRequestValidation:
    """Tests for BulkExportRequest schema validation."""

    def test_valid_request(self):
        """Valid date range and format accepted."""
        req = BulkExportRequest(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            format=ExportFormat.csv,
        )
        assert req.start_date == date(2024, 1, 1)
        assert req.end_date == date(2024, 6, 30)

    def test_end_before_start_rejected(self):
        """end_date before start_date raises validation error."""
        with pytest.raises(Exception):
            BulkExportRequest(
                start_date=date(2024, 6, 30),
                end_date=date(2024, 1, 1),
                format=ExportFormat.csv,
            )

    def test_same_day_range_accepted(self):
        """Same start and end date is valid."""
        req = BulkExportRequest(
            start_date=date(2024, 6, 15),
            end_date=date(2024, 6, 15),
            format=ExportFormat.zip_pdf,
        )
        assert req.start_date == req.end_date


class TestBulkDeleteRequestValidation:
    """Tests for BulkDeleteRequest schema validation."""

    def test_valid_request(self):
        """Valid request with IDs and confirm flag."""
        req = BulkDeleteRequest(
            invoice_ids=[uuid.uuid4()],
            confirm=True,
        )
        assert req.confirm is True
        assert len(req.invoice_ids) == 1

    def test_empty_ids_rejected(self):
        """Empty invoice_ids list raises validation error."""
        with pytest.raises(Exception):
            BulkDeleteRequest(invoice_ids=[], confirm=True)

    def test_default_confirm_is_false(self):
        """confirm defaults to False."""
        req = BulkDeleteRequest(invoice_ids=[uuid.uuid4()])
        assert req.confirm is False


# ---------------------------------------------------------------------------
# Bulk Export Service Tests
# ---------------------------------------------------------------------------


class TestBulkExportInvoices:
    """Tests for bulk_export_invoices service function."""

    @pytest.mark.asyncio
    async def test_returns_invoices_in_date_range(self):
        """Invoices within date range are returned."""
        org_id = uuid.uuid4()
        mock_inv = _make_mock_invoice(org_id=org_id, number="INV-0010")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_inv]
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        dicts, invoices = await bulk_export_invoices(
            db,
            org_id=org_id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            export_format="csv",
        )

        assert len(dicts) == 1
        assert len(invoices) == 1
        assert dicts[0]["invoice_number"] == "INV-0010"

    @pytest.mark.asyncio
    async def test_empty_result(self):
        """No invoices in range returns empty lists."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        dicts, invoices = await bulk_export_invoices(
            db,
            org_id=uuid.uuid4(),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            export_format="csv",
        )

        assert dicts == []
        assert invoices == []


# ---------------------------------------------------------------------------
# Bulk Delete Service Tests
# ---------------------------------------------------------------------------


class TestBulkDeleteInvoices:
    """Tests for bulk_delete_invoices service function."""

    @pytest.mark.asyncio
    async def test_deletes_matching_invoices(self):
        """Matching invoices are deleted and audit log written."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        inv1 = _make_mock_invoice(org_id=org_id, number="INV-0001")
        inv2 = _make_mock_invoice(org_id=org_id, number="INV-0002")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [inv1, inv2]
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            deleted_count, bytes_recovered = await bulk_delete_invoices(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_ids=[inv1.id, inv2.id],
                ip_address="127.0.0.1",
            )

        assert deleted_count == 2
        assert bytes_recovered > 0
        assert db.delete.call_count == 2
        mock_audit.assert_called_once()
        audit_call = mock_audit.call_args
        assert audit_call.kwargs["action"] == "invoice.bulk_delete"
        assert audit_call.kwargs["after_value"]["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_no_matching_invoices(self):
        """No matching invoices returns zero counts."""
        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        deleted_count, bytes_recovered = await bulk_delete_invoices(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            invoice_ids=[uuid.uuid4()],
        )

        assert deleted_count == 0
        assert bytes_recovered == 0
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_log_records_ip(self):
        """Audit log entry includes IP address."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        inv = _make_mock_invoice(org_id=org_id)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [inv]
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await bulk_delete_invoices(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_ids=[inv.id],
                ip_address="192.168.1.1",
            )

        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["ip_address"] == "192.168.1.1"
