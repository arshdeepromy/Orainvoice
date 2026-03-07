"""Unit tests for Task 25.1 — Data import (CSV parsing, validation, import).

Tests cover:
  - CSV parsing and header detection
  - Auto-mapping of CSV headers to target fields
  - Row validation for customers (required fields, email format, max length)
  - Row validation for vehicles (required fields, integer types, ranges)
  - Preview generation with valid and error rows
  - Customer import commit (skip invalid, import valid)
  - Vehicle import commit (skip invalid, import valid)
  - Error report CSV generation

Requirements: 69.1, 69.2, 69.3, 69.5
"""

from __future__ import annotations

import csv
import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.data_io.schemas import (
    FieldMapping,
    ImportCommitResponse,
    ImportPreviewResponse,
    ImportPreviewRow,
    ImportRowError,
)
from app.modules.data_io.service import (
    auto_detect_mapping,
    commit_customer_import,
    commit_vehicle_import,
    generate_error_report_csv,
    parse_csv,
    validate_import,
)


# ---------------------------------------------------------------------------
# CSV parsing tests
# ---------------------------------------------------------------------------


class TestParseCSV:
    """Tests for parse_csv function."""

    def test_basic_csv(self):
        content = "first_name,last_name,email\nJohn,Doe,john@example.com\nJane,Smith,jane@example.com"
        headers, rows = parse_csv(content)
        assert headers == ["first_name", "last_name", "email"]
        assert len(rows) == 2
        assert rows[0]["first_name"] == "John"
        assert rows[1]["last_name"] == "Smith"

    def test_empty_csv(self):
        content = ""
        headers, rows = parse_csv(content)
        assert headers == []
        assert rows == []

    def test_headers_only(self):
        content = "first_name,last_name,email"
        headers, rows = parse_csv(content)
        assert headers == ["first_name", "last_name", "email"]
        assert rows == []

    def test_csv_with_extra_whitespace(self):
        content = "first_name,last_name\n John , Doe "
        headers, rows = parse_csv(content)
        assert len(rows) == 1
        # CSV reader preserves whitespace; validation strips it
        assert rows[0]["first_name"] == " John "


# ---------------------------------------------------------------------------
# Auto-mapping tests
# ---------------------------------------------------------------------------


class TestAutoDetectMapping:
    """Tests for auto_detect_mapping function."""

    def test_customer_standard_headers(self):
        headers = ["first_name", "last_name", "email", "phone"]
        mapping = auto_detect_mapping(headers, "customers")
        target_fields = {m.target_field for m in mapping}
        assert "first_name" in target_fields
        assert "last_name" in target_fields
        assert "email" in target_fields
        assert "phone" in target_fields

    def test_customer_alias_headers(self):
        headers = ["First Name", "Last Name", "Email Address", "Mobile"]
        mapping = auto_detect_mapping(headers, "customers")
        target_fields = {m.target_field for m in mapping}
        assert "first_name" in target_fields
        assert "last_name" in target_fields
        assert "email" in target_fields
        assert "phone" in target_fields

    def test_vehicle_standard_headers(self):
        headers = ["rego", "make", "model", "year", "colour"]
        mapping = auto_detect_mapping(headers, "vehicles")
        target_fields = {m.target_field for m in mapping}
        assert "rego" in target_fields
        assert "make" in target_fields
        assert "model" in target_fields

    def test_vehicle_alias_headers(self):
        headers = ["Registration", "Color", "Seats"]
        mapping = auto_detect_mapping(headers, "vehicles")
        target_fields = {m.target_field for m in mapping}
        assert "rego" in target_fields
        assert "colour" in target_fields
        assert "num_seats" in target_fields

    def test_no_matching_headers(self):
        headers = ["unknown1", "unknown2"]
        mapping = auto_detect_mapping(headers, "customers")
        assert mapping == []


# ---------------------------------------------------------------------------
# Validation tests — Customers
# ---------------------------------------------------------------------------


class TestValidateCustomerImport:
    """Tests for validate_import with entity_type='customers'."""

    def _mapping(self):
        return [
            FieldMapping(csv_column="first_name", target_field="first_name"),
            FieldMapping(csv_column="last_name", target_field="last_name"),
            FieldMapping(csv_column="email", target_field="email"),
            FieldMapping(csv_column="phone", target_field="phone"),
        ]

    def test_valid_rows(self):
        headers = ["first_name", "last_name", "email", "phone"]
        rows = [
            {"first_name": "John", "last_name": "Doe", "email": "john@example.com", "phone": "021123456"},
            {"first_name": "Jane", "last_name": "Smith", "email": "", "phone": ""},
        ]
        result = validate_import(headers, rows, self._mapping(), "customers")
        assert result.total_rows == 2
        assert len(result.valid_rows) == 2
        assert len(result.error_rows) == 0

    def test_missing_required_first_name(self):
        headers = ["first_name", "last_name", "email", "phone"]
        rows = [
            {"first_name": "", "last_name": "Doe", "email": "john@example.com", "phone": ""},
        ]
        result = validate_import(headers, rows, self._mapping(), "customers")
        assert len(result.valid_rows) == 0
        assert len(result.error_rows) >= 1
        assert any(e.field == "first_name" for e in result.error_rows)

    def test_invalid_email_format(self):
        headers = ["first_name", "last_name", "email", "phone"]
        rows = [
            {"first_name": "John", "last_name": "Doe", "email": "not-an-email", "phone": ""},
        ]
        result = validate_import(headers, rows, self._mapping(), "customers")
        assert len(result.valid_rows) == 0
        assert any(e.field == "email" for e in result.error_rows)

    def test_mixed_valid_and_invalid(self):
        """Req 69.5: skip invalid rows, continue processing."""
        headers = ["first_name", "last_name", "email", "phone"]
        rows = [
            {"first_name": "John", "last_name": "Doe", "email": "john@example.com", "phone": ""},
            {"first_name": "", "last_name": "", "email": "", "phone": ""},  # invalid
            {"first_name": "Jane", "last_name": "Smith", "email": "", "phone": "021999"},
        ]
        result = validate_import(headers, rows, self._mapping(), "customers")
        assert len(result.valid_rows) == 2
        assert len(result.error_rows) >= 1
        assert result.total_rows == 3

    def test_first_name_exceeds_max_length(self):
        headers = ["first_name", "last_name", "email", "phone"]
        rows = [
            {"first_name": "A" * 101, "last_name": "Doe", "email": "", "phone": ""},
        ]
        result = validate_import(headers, rows, self._mapping(), "customers")
        assert len(result.valid_rows) == 0
        assert any(e.field == "first_name" and "max length" in e.error for e in result.error_rows)


# ---------------------------------------------------------------------------
# Validation tests — Vehicles
# ---------------------------------------------------------------------------


class TestValidateVehicleImport:
    """Tests for validate_import with entity_type='vehicles'."""

    def _mapping(self):
        return [
            FieldMapping(csv_column="rego", target_field="rego"),
            FieldMapping(csv_column="make", target_field="make"),
            FieldMapping(csv_column="model", target_field="model"),
            FieldMapping(csv_column="year", target_field="year"),
            FieldMapping(csv_column="colour", target_field="colour"),
        ]

    def test_valid_vehicle_rows(self):
        headers = ["rego", "make", "model", "year", "colour"]
        rows = [
            {"rego": "ABC123", "make": "Toyota", "model": "Corolla", "year": "2020", "colour": "White"},
        ]
        result = validate_import(headers, rows, self._mapping(), "vehicles")
        assert len(result.valid_rows) == 1
        assert len(result.error_rows) == 0

    def test_missing_required_rego(self):
        headers = ["rego", "make", "model", "year", "colour"]
        rows = [
            {"rego": "", "make": "Toyota", "model": "Corolla", "year": "2020", "colour": "White"},
        ]
        result = validate_import(headers, rows, self._mapping(), "vehicles")
        assert len(result.valid_rows) == 0
        assert any(e.field == "rego" for e in result.error_rows)

    def test_invalid_year_not_integer(self):
        headers = ["rego", "make", "model", "year", "colour"]
        rows = [
            {"rego": "ABC123", "make": "Toyota", "model": "Corolla", "year": "twenty", "colour": "White"},
        ]
        result = validate_import(headers, rows, self._mapping(), "vehicles")
        assert len(result.valid_rows) == 0
        assert any(e.field == "year" and "integer" in e.error for e in result.error_rows)

    def test_year_out_of_range(self):
        headers = ["rego", "make", "model", "year", "colour"]
        rows = [
            {"rego": "ABC123", "make": "Toyota", "model": "Corolla", "year": "1800", "colour": "White"},
        ]
        result = validate_import(headers, rows, self._mapping(), "vehicles")
        assert len(result.valid_rows) == 0
        assert any(e.field == "year" for e in result.error_rows)

    def test_optional_fields_empty(self):
        headers = ["rego", "make", "model", "year", "colour"]
        rows = [
            {"rego": "XYZ789", "make": "", "model": "", "year": "", "colour": ""},
        ]
        result = validate_import(headers, rows, self._mapping(), "vehicles")
        assert len(result.valid_rows) == 1
        assert len(result.error_rows) == 0


# ---------------------------------------------------------------------------
# Error report CSV generation
# ---------------------------------------------------------------------------


class TestErrorReportCSV:
    """Tests for generate_error_report_csv."""

    def test_generates_valid_csv(self):
        errors = [
            ImportRowError(row_number=2, field="email", value="bad", error="Invalid format"),
            ImportRowError(row_number=5, field="first_name", value="", error="Required"),
        ]
        csv_text = generate_error_report_csv(errors)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        assert rows[0] == ["row_number", "field", "value", "error"]
        assert len(rows) == 3  # header + 2 error rows
        assert rows[1][0] == "2"
        assert rows[2][3] == "Required"

    def test_empty_errors(self):
        csv_text = generate_error_report_csv([])
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)
        assert len(rows) == 1  # header only


# ---------------------------------------------------------------------------
# Commit import tests (with mocked DB)
# ---------------------------------------------------------------------------


class TestCommitCustomerImport:
    """Tests for commit_customer_import service function."""

    @pytest.mark.asyncio
    async def test_imports_valid_rows(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        org_id = uuid.uuid4()
        mapping = [
            FieldMapping(csv_column="first_name", target_field="first_name"),
            FieldMapping(csv_column="last_name", target_field="last_name"),
            FieldMapping(csv_column="email", target_field="email"),
        ]
        rows = [
            {"first_name": "John", "last_name": "Doe", "email": "john@example.com"},
            {"first_name": "Jane", "last_name": "Smith", "email": ""},
        ]

        result = await commit_customer_import(db, org_id, rows, mapping)
        assert result.imported_count == 2
        assert result.skipped_count == 0
        assert db.add.call_count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_invalid_rows(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        org_id = uuid.uuid4()
        mapping = [
            FieldMapping(csv_column="first_name", target_field="first_name"),
            FieldMapping(csv_column="last_name", target_field="last_name"),
        ]
        rows = [
            {"first_name": "John", "last_name": "Doe"},
            {"first_name": "", "last_name": ""},  # invalid — both required
            {"first_name": "Jane", "last_name": "Smith"},
        ]

        result = await commit_customer_import(db, org_id, rows, mapping)
        assert result.imported_count == 2
        assert result.skipped_count == 1
        assert len(result.errors) >= 1


class TestCommitVehicleImport:
    """Tests for commit_vehicle_import service function."""

    @pytest.mark.asyncio
    async def test_imports_valid_vehicles(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        org_id = uuid.uuid4()
        mapping = [
            FieldMapping(csv_column="rego", target_field="rego"),
            FieldMapping(csv_column="make", target_field="make"),
            FieldMapping(csv_column="year", target_field="year"),
        ]
        rows = [
            {"rego": "ABC123", "make": "Toyota", "year": "2020"},
            {"rego": "XYZ789", "make": "Honda", "year": "2019"},
        ]

        result = await commit_vehicle_import(db, org_id, rows, mapping)
        assert result.imported_count == 2
        assert result.skipped_count == 0
        assert db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_invalid_vehicles(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        org_id = uuid.uuid4()
        mapping = [
            FieldMapping(csv_column="rego", target_field="rego"),
            FieldMapping(csv_column="year", target_field="year"),
        ]
        rows = [
            {"rego": "ABC123", "year": "2020"},
            {"rego": "", "year": "bad"},  # invalid rego + bad year
            {"rego": "DEF456", "year": ""},
        ]

        result = await commit_vehicle_import(db, org_id, rows, mapping)
        assert result.imported_count == 2
        assert result.skipped_count == 1
        assert len(result.errors) >= 1


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

from datetime import datetime, date, timezone
from decimal import Decimal
from unittest.mock import PropertyMock

from app.modules.data_io.service import (
    export_customers_csv,
    export_vehicles_csv,
    export_invoices_csv,
    CUSTOMER_EXPORT_HEADERS,
    VEHICLE_EXPORT_HEADERS,
    INVOICE_EXPORT_HEADERS,
)


def _make_customer(org_id, first_name="John", last_name="Doe", email="john@example.com", phone="021123"):
    """Create a mock customer object."""
    c = MagicMock()
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = first_name
    c.last_name = last_name
    c.email = email
    c.phone = phone
    c.address = "123 Test St"
    c.notes = "VIP"
    c.is_anonymised = False
    c.created_at = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    return c


def _make_org_vehicle(org_id, rego="ABC123"):
    """Create a mock org vehicle object."""
    v = MagicMock()
    v.id = uuid.uuid4()
    v.org_id = org_id
    v.rego = rego
    v.make = "Toyota"
    v.model = "Corolla"
    v.year = 2020
    v.colour = "White"
    v.body_type = "Sedan"
    v.fuel_type = "Petrol"
    v.engine_size = "1.8L"
    v.num_seats = 5
    v.is_manual_entry = True
    v.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
    return v


def _make_invoice(org_id, customer_id, number="INV-001", status="issued"):
    """Create a mock invoice object."""
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.org_id = org_id
    inv.customer_id = customer_id
    inv.invoice_number = number
    inv.status = status
    inv.vehicle_rego = "ABC123"
    inv.issue_date = date(2024, 2, 1)
    inv.due_date = date(2024, 3, 1)
    inv.currency = "NZD"
    inv.subtotal = Decimal("100.00")
    inv.discount_amount = Decimal("0.00")
    inv.gst_amount = Decimal("15.00")
    inv.total = Decimal("115.00")
    inv.amount_paid = Decimal("0.00")
    inv.balance_due = Decimal("115.00")
    inv.created_at = datetime(2024, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    return inv


def _mock_scalars(items):
    """Create a mock result that returns items from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result.scalars.return_value = scalars_mock
    return result


class TestExportCustomersCSV:
    """Tests for export_customers_csv service function."""

    @pytest.mark.asyncio
    async def test_exports_customers_as_csv(self):
        org_id = uuid.uuid4()
        customers = [
            _make_customer(org_id, "John", "Doe", "john@example.com", "021123"),
            _make_customer(org_id, "Jane", "Smith", "jane@example.com", "021456"),
        ]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars(customers))

        csv_text = await export_customers_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == CUSTOMER_EXPORT_HEADERS
        assert len(rows) == 3  # header + 2 customers
        assert rows[1][1] == "John"
        assert rows[1][2] == "Doe"
        assert rows[2][1] == "Jane"

    @pytest.mark.asyncio
    async def test_exports_empty_when_no_customers(self):
        org_id = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([]))

        csv_text = await export_customers_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == CUSTOMER_EXPORT_HEADERS
        assert len(rows) == 1  # header only


class TestExportVehiclesCSV:
    """Tests for export_vehicles_csv service function."""

    @pytest.mark.asyncio
    async def test_exports_org_vehicles(self):
        org_id = uuid.uuid4()
        vehicle = _make_org_vehicle(org_id, "ABC123")

        # Mock db.execute to return different results for different queries
        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalars([vehicle])  # org vehicles
            elif call_count == 2:
                return _mock_scalars([])  # global vehicles
            elif call_count == 3:
                return _mock_scalars([])  # customer_vehicles links
            else:
                return _mock_scalars([])  # customers

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        csv_text = await export_vehicles_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == VEHICLE_EXPORT_HEADERS
        assert len(rows) == 2  # header + 1 vehicle
        assert rows[1][1] == "ABC123"
        assert rows[1][10] == "manual"

    @pytest.mark.asyncio
    async def test_exports_empty_when_no_vehicles(self):
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([]))

        csv_text = await export_vehicles_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == VEHICLE_EXPORT_HEADERS
        assert len(rows) == 1


class TestExportInvoicesCSV:
    """Tests for export_invoices_csv service function."""

    @pytest.mark.asyncio
    async def test_exports_invoices_as_csv(self):
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        invoices = [
            _make_invoice(org_id, cust_id, "INV-001", "issued"),
            _make_invoice(org_id, cust_id, "INV-002", "paid"),
        ]
        customer = _make_customer(org_id, "John", "Doe")
        customer.id = cust_id

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalars(invoices)
            else:
                return _mock_scalars([customer])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        csv_text = await export_invoices_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == INVOICE_EXPORT_HEADERS
        assert len(rows) == 3  # header + 2 invoices
        assert rows[1][1] == "INV-001"
        assert rows[1][2] == "issued"
        assert rows[2][1] == "INV-002"
        assert rows[2][2] == "paid"

    @pytest.mark.asyncio
    async def test_exports_empty_when_no_invoices(self):
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([]))

        csv_text = await export_invoices_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[0] == INVOICE_EXPORT_HEADERS
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_customer_name_in_export(self):
        """Verify customer name is resolved and included in the CSV."""
        org_id = uuid.uuid4()
        cust_id = uuid.uuid4()
        invoice = _make_invoice(org_id, cust_id, "INV-010", "issued")
        customer = _make_customer(org_id, "Alice", "Wonder")
        customer.id = cust_id

        call_count = 0
        async def mock_execute(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalars([invoice])
            else:
                return _mock_scalars([customer])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        csv_text = await export_invoices_csv(db, org_id)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        assert rows[1][3] == "Alice Wonder"
