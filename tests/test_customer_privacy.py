"""Unit tests for Task 7.4 — Privacy Act 2020 compliance.

Tests cover:
  - anonymise_customer: anonymises customer, clears PII, preserves invoices
  - export_customer_data: exports all customer data as JSON
  - PII never written to logs or audit entries
  - Edge cases: already anonymised, not found

Requirements: 13.1, 13.2, 13.3, 13.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import admin and auth models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.schemas import (
    CustomerAnonymiseResponse,
    CustomerExportResponse,
    CustomerResponse,
)
from app.modules.customers.service import (
    anonymise_customer,
    export_customer_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer(
    org_id=None,
    customer_id=None,
    first_name="Jane",
    last_name="Doe",
    email="jane@example.com",
    phone="+64 21 555 1234",
    address="42 Queen St, Auckland",
    notes="Regular customer",
    is_anonymised=False,
):
    """Create a mock Customer object."""
    customer = MagicMock(spec=Customer)
    customer.id = customer_id or uuid.uuid4()
    customer.org_id = org_id or uuid.uuid4()
    customer.first_name = first_name
    customer.last_name = last_name
    customer.email = email
    customer.phone = phone
    customer.address = address
    customer.notes = notes
    customer.is_anonymised = is_anonymised
    customer.portal_token = uuid.uuid4()
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def _make_invoice(
    org_id=None,
    customer_id=None,
    invoice_number="INV-001",
    status="issued",
    total=Decimal("230.00"),
    amount_paid=Decimal("0"),
    balance_due=Decimal("230.00"),
    invoice_data_json=None,
):
    """Create a mock Invoice object."""
    from app.modules.invoices.models import Invoice

    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = customer_id or uuid.uuid4()
    inv.invoice_number = invoice_number
    inv.status = status
    inv.issue_date = date(2024, 6, 15)
    inv.due_date = date(2024, 7, 15)
    inv.vehicle_rego = "ABC123"
    inv.subtotal = Decimal("200.00")
    inv.gst_amount = Decimal("30.00")
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.invoice_data_json = invoice_data_json or {
        "customer_name": "Jane Doe",
        "customer_email": "jane@example.com",
        "customer_phone": "+64 21 555 1234",
        "customer_address": "42 Queen St, Auckland",
    }
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    return inv


def _make_line_item(invoice_id=None, org_id=None):
    """Create a mock LineItem object."""
    from app.modules.invoices.models import LineItem

    li = MagicMock(spec=LineItem)
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id or uuid.uuid4()
    li.org_id = org_id or uuid.uuid4()
    li.item_type = "service"
    li.description = "Oil Change"
    li.quantity = Decimal("1")
    li.unit_price = Decimal("80.00")
    li.line_total = Decimal("80.00")
    li.is_gst_exempt = False
    li.sort_order = 0
    li.created_at = datetime.now(timezone.utc)
    return li


def _make_payment(invoice_id=None, org_id=None):
    """Create a mock Payment object."""
    from app.modules.payments.models import Payment

    p = MagicMock(spec=Payment)
    p.id = uuid.uuid4()
    p.invoice_id = invoice_id or uuid.uuid4()
    p.org_id = org_id or uuid.uuid4()
    p.amount = Decimal("230.00")
    p.method = "cash"
    p.is_refund = False
    p.created_at = datetime.now(timezone.utc)
    return p


def _make_customer_vehicle(customer_id=None, org_id=None, global_vehicle_id=None, org_vehicle_id=None):
    """Create a mock CustomerVehicle object."""
    from app.modules.vehicles.models import CustomerVehicle

    cv = MagicMock(spec=CustomerVehicle)
    cv.id = uuid.uuid4()
    cv.customer_id = customer_id or uuid.uuid4()
    cv.org_id = org_id or uuid.uuid4()
    cv.global_vehicle_id = global_vehicle_id
    cv.org_vehicle_id = org_vehicle_id
    cv.linked_at = datetime.now(timezone.utc)
    return cv


def _make_global_vehicle():
    """Create a mock GlobalVehicle object."""
    from app.modules.admin.models import GlobalVehicle

    gv = MagicMock(spec=GlobalVehicle)
    gv.id = uuid.uuid4()
    gv.rego = "ABC123"
    gv.make = "Toyota"
    gv.model = "Corolla"
    gv.year = 2020
    gv.colour = "Silver"
    gv.body_type = "Sedan"
    gv.fuel_type = "Petrol"
    return gv


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    """Create a mock result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# anonymise_customer tests
# ---------------------------------------------------------------------------


class TestAnonymiseCustomer:
    """Test the anonymise_customer service function.

    Requirements: 13.1, 13.2
    """

    @pytest.mark.asyncio
    async def test_anonymises_customer_fields(self):
        """Customer name replaced with 'Anonymised Customer', PII cleared."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        invoice = _make_invoice(org_id=org_id, customer_id=customer.id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),  # fetch customer
                _mock_scalars_result([invoice]),  # fetch invoices
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        assert customer.first_name == "Anonymised"
        assert customer.last_name == "Customer"
        assert customer.email is None
        assert customer.phone is None
        assert customer.address is None
        assert customer.notes is None
        assert customer.portal_token is None
        assert customer.is_anonymised is True
        assert result["is_anonymised"] is True

    @pytest.mark.asyncio
    async def test_preserves_invoice_financial_data(self):
        """Linked invoices keep their financial data intact."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        invoice = _make_invoice(
            org_id=org_id,
            customer_id=customer.id,
            total=Decimal("500.00"),
        )
        original_total = invoice.total

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([invoice]),
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        # Financial data untouched
        assert invoice.total == original_total
        assert result["invoices_preserved"] == 1

    @pytest.mark.asyncio
    async def test_anonymises_customer_pii_in_invoice_json(self):
        """Customer PII in invoice_data_json is cleared."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        invoice = _make_invoice(
            org_id=org_id,
            customer_id=customer.id,
            invoice_data_json={
                "customer_name": "Jane Doe",
                "customer_email": "jane@example.com",
                "customer_phone": "+64 21 555 1234",
                "customer_address": "42 Queen St",
                "line_items": [{"desc": "Oil Change", "total": "80.00"}],
            },
        )

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([invoice]),
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        json_data = invoice.invoice_data_json
        assert json_data["customer_name"] == "Anonymised Customer"
        assert json_data["customer_email"] is None
        assert json_data["customer_phone"] is None
        assert json_data["customer_address"] is None
        # Non-PII data preserved
        assert json_data["line_items"] == [{"desc": "Oil Change", "total": "80.00"}]

    @pytest.mark.asyncio
    async def test_already_anonymised_raises(self):
        """Raises ValueError when customer is already anonymised."""
        customer = _make_customer(is_anonymised=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(customer))

        with pytest.raises(ValueError, match="already anonymised"):
            await anonymise_customer(
                db,
                org_id=customer.org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await anonymise_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_audit_log_contains_no_pii(self):
        """Audit log entry must not contain PII (Req 13.4)."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([]),
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "customer.anonymised"

        # Verify no PII in before_value or after_value
        before = call_kwargs["before_value"]
        after = call_kwargs["after_value"]

        # before_value should only have boolean flags, not actual PII
        assert "had_email" in before
        assert "jane@example.com" not in str(before)
        assert "Jane" not in str(before)
        assert "+64" not in str(before)

        # after_value should only have anonymisation status
        assert after["is_anonymised"] is True
        assert "jane" not in str(after).lower()

    @pytest.mark.asyncio
    async def test_handles_no_linked_invoices(self):
        """Works correctly when customer has no invoices."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([]),  # no invoices
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        assert result["invoices_preserved"] == 0
        assert customer.is_anonymised is True

    @pytest.mark.asyncio
    async def test_multiple_invoices_all_anonymised(self):
        """All linked invoices have their customer PII anonymised."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        inv1 = _make_invoice(org_id=org_id, customer_id=customer.id, invoice_number="INV-001")
        inv2 = _make_invoice(org_id=org_id, customer_id=customer.id, invoice_number="INV-002")

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([inv1, inv2]),
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        assert result["invoices_preserved"] == 2
        assert inv1.invoice_data_json["customer_name"] == "Anonymised Customer"
        assert inv2.invoice_data_json["customer_name"] == "Anonymised Customer"


# ---------------------------------------------------------------------------
# export_customer_data tests
# ---------------------------------------------------------------------------


class TestExportCustomerData:
    """Test the export_customer_data service function.

    Requirements: 13.3
    """

    @pytest.mark.asyncio
    async def test_exports_customer_record(self):
        """Export includes the full customer record."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),  # fetch customer
                _mock_scalars_result([]),  # vehicles
                _mock_scalars_result([]),  # invoices
            ]
        )

        result = await export_customer_data(
            db, org_id=org_id, customer_id=customer.id
        )

        assert result["customer"]["first_name"] == "Jane"
        assert result["customer"]["last_name"] == "Doe"
        assert result["customer"]["email"] == "jane@example.com"
        assert "exported_at" in result

    @pytest.mark.asyncio
    async def test_exports_linked_vehicles(self):
        """Export includes linked vehicles with details."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        gv = _make_global_vehicle()
        cv = _make_customer_vehicle(
            customer_id=customer.id,
            org_id=org_id,
            global_vehicle_id=gv.id,
        )

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),  # fetch customer
                _mock_scalars_result([cv]),  # customer vehicles
                _mock_scalar_result(gv),  # global vehicle lookup
                _mock_scalars_result([]),  # invoices
            ]
        )

        result = await export_customer_data(
            db, org_id=org_id, customer_id=customer.id
        )

        assert len(result["vehicles"]) == 1
        assert result["vehicles"][0]["rego"] == "ABC123"
        assert result["vehicles"][0]["make"] == "Toyota"
        assert result["vehicles"][0]["source"] == "global"

    @pytest.mark.asyncio
    async def test_exports_invoices_with_line_items_and_payments(self):
        """Export includes invoices with their line items and payments."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)
        invoice = _make_invoice(org_id=org_id, customer_id=customer.id)
        line_item = _make_line_item(invoice_id=invoice.id, org_id=org_id)
        payment = _make_payment(invoice_id=invoice.id, org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),  # fetch customer
                _mock_scalars_result([]),  # no vehicles
                _mock_scalars_result([invoice]),  # invoices
                _mock_scalars_result([line_item]),  # line items for invoice
                _mock_scalars_result([payment]),  # payments for invoice
            ]
        )

        result = await export_customer_data(
            db, org_id=org_id, customer_id=customer.id
        )

        assert len(result["invoices"]) == 1
        inv_data = result["invoices"][0]
        assert inv_data["invoice_number"] == "INV-001"
        assert inv_data["total"] == "230.00"
        assert len(inv_data["line_items"]) == 1
        assert inv_data["line_items"][0]["description"] == "Oil Change"
        assert len(inv_data["payments"]) == 1
        assert inv_data["payments"][0]["amount"] == "230.00"

    @pytest.mark.asyncio
    async def test_export_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await export_customer_data(
                db, org_id=uuid.uuid4(), customer_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_export_empty_customer(self):
        """Export works for customer with no vehicles, invoices, or payments."""
        org_id = uuid.uuid4()
        customer = _make_customer(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([]),  # no vehicles
                _mock_scalars_result([]),  # no invoices
            ]
        )

        result = await export_customer_data(
            db, org_id=org_id, customer_id=customer.id
        )

        assert result["customer"]["id"] == str(customer.id)
        assert result["vehicles"] == []
        assert result["invoices"] == []


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPrivacySchemas:
    """Test Pydantic schema validation for privacy endpoints."""

    def test_anonymise_response(self):
        """AnonymiseResponse has expected fields."""
        resp = CustomerAnonymiseResponse(
            message="Customer anonymised successfully",
            customer_id=str(uuid.uuid4()),
            is_anonymised=True,
            invoices_preserved=3,
        )
        assert resp.is_anonymised is True
        assert resp.invoices_preserved == 3

    def test_export_response(self):
        """ExportResponse has expected structure."""
        cust = CustomerResponse(
            id=str(uuid.uuid4()),
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            is_anonymised=False,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        resp = CustomerExportResponse(
            customer=cust,
            vehicles=[],
            invoices=[],
            exported_at="2024-06-15T12:00:00+00:00",
        )
        assert resp.customer.first_name == "Jane"
        assert resp.exported_at == "2024-06-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# PII logging tests (Req 13.4)
# ---------------------------------------------------------------------------


class TestPIINotInLogs:
    """Verify PII is never written to application logs.

    Requirements: 13.4
    """

    @pytest.mark.asyncio
    async def test_anonymise_log_message_has_no_pii(self):
        """Logger.info call during anonymisation must not contain PII."""
        org_id = uuid.uuid4()
        customer = _make_customer(
            org_id=org_id,
            first_name="Sensitive",
            last_name="Person",
            email="sensitive@private.nz",
            phone="+64 21 999 0000",
        )

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(customer),
                _mock_scalars_result([]),
            ]
        )

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.customers.service.logger"
        ) as mock_logger:
            await anonymise_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                customer_id=customer.id,
            )

        # Check the logger.info call
        mock_logger.info.assert_called_once()
        log_args = str(mock_logger.info.call_args)

        # PII must not appear in log output
        assert "Sensitive" not in log_args
        assert "Person" not in log_args
        assert "sensitive@private.nz" not in log_args
        assert "+64 21 999 0000" not in log_args
