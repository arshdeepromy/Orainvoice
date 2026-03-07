"""Unit tests for Task 10.1 — invoice creation endpoint.

Tests cover:
  - Schema validation for invoice create requests
  - Line item total calculation (with discounts)
  - Invoice totals calculation (subtotal, GST, total)
  - Draft creation (no invoice number)
  - Issued creation (sequential number assigned)
  - Gap-free numbering via InvoiceSequence
  - Customer validation (must belong to org)

Requirements: 17.1, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

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

from app.modules.invoices.schemas import (
    InvoiceCreateRequest,
    InvoiceStatus,
    LineItemCreate,
    LineItemResponse,
    InvoiceResponse,
    InvoiceCreateResponse,
)
from app.modules.invoices.service import (
    _calculate_line_total,
    _calculate_invoice_totals,
    create_invoice,
)


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestLineItemCreateSchema:
    """Test LineItemCreate Pydantic schema validation."""

    def test_valid_service_line_item(self):
        li = LineItemCreate(
            item_type="service",
            description="Oil change",
            unit_price=Decimal("50.00"),
        )
        assert li.item_type.value == "service"
        assert li.quantity == Decimal("1")
        assert li.is_gst_exempt is False

    def test_valid_part_line_item(self):
        li = LineItemCreate(
            item_type="part",
            description="Brake pads",
            part_number="BP-1234",
            quantity=Decimal("2"),
            unit_price=Decimal("45.50"),
        )
        assert li.part_number == "BP-1234"
        assert li.quantity == Decimal("2")

    def test_valid_labour_line_item(self):
        li = LineItemCreate(
            item_type="labour",
            description="Engine diagnostic",
            unit_price=Decimal("85.00"),
            hours=Decimal("1.5"),
            hourly_rate=Decimal("85.00"),
        )
        assert li.hours == Decimal("1.5")

    def test_invalid_item_type_rejected(self):
        with pytest.raises(Exception):
            LineItemCreate(
                item_type="invalid",
                description="Test",
                unit_price=Decimal("10.00"),
            )

    def test_empty_description_rejected(self):
        with pytest.raises(Exception):
            LineItemCreate(
                item_type="service",
                description="",
                unit_price=Decimal("10.00"),
            )

    def test_negative_quantity_rejected(self):
        with pytest.raises(Exception):
            LineItemCreate(
                item_type="service",
                description="Test",
                quantity=Decimal("-1"),
                unit_price=Decimal("10.00"),
            )

    def test_gst_exempt_flag(self):
        li = LineItemCreate(
            item_type="service",
            description="Insurance work",
            unit_price=Decimal("100.00"),
            is_gst_exempt=True,
        )
        assert li.is_gst_exempt is True

    def test_discount_on_line_item(self):
        li = LineItemCreate(
            item_type="part",
            description="Filter",
            unit_price=Decimal("20.00"),
            discount_type="percentage",
            discount_value=Decimal("10"),
        )
        assert li.discount_type == "percentage"
        assert li.discount_value == Decimal("10")


class TestInvoiceCreateRequestSchema:
    """Test InvoiceCreateRequest Pydantic schema validation."""

    def test_minimal_draft_request(self):
        req = InvoiceCreateRequest(
            customer_id=uuid.uuid4(),
        )
        assert req.status == InvoiceStatus.draft
        assert req.line_items == []
        assert req.vehicle_rego is None

    def test_full_issued_request(self):
        req = InvoiceCreateRequest(
            customer_id=uuid.uuid4(),
            vehicle_rego="ABC123",
            status=InvoiceStatus.issued,
            due_date=date(2025, 7, 15),
            line_items=[
                LineItemCreate(
                    item_type="service",
                    description="WOF",
                    unit_price=Decimal("55.00"),
                ),
            ],
            notes_customer="Thanks for your business",
        )
        assert req.status == InvoiceStatus.issued
        assert len(req.line_items) == 1


# ---------------------------------------------------------------------------
# Calculation tests
# ---------------------------------------------------------------------------


class TestLineItemCalculation:
    """Test _calculate_line_total function."""

    def test_simple_total(self):
        result = _calculate_line_total(
            Decimal("2"), Decimal("50.00"), None, None
        )
        assert result == Decimal("100.00")

    def test_percentage_discount(self):
        result = _calculate_line_total(
            Decimal("1"), Decimal("100.00"), "percentage", Decimal("10")
        )
        assert result == Decimal("90.00")

    def test_fixed_discount(self):
        result = _calculate_line_total(
            Decimal("1"), Decimal("100.00"), "fixed", Decimal("25.00")
        )
        assert result == Decimal("75.00")

    def test_discount_cannot_go_negative(self):
        result = _calculate_line_total(
            Decimal("1"), Decimal("10.00"), "fixed", Decimal("50.00")
        )
        assert result == Decimal("0")

    def test_fractional_quantity(self):
        result = _calculate_line_total(
            Decimal("1.5"), Decimal("80.00"), None, None
        )
        assert result == Decimal("120.00")


class TestInvoiceTotalsCalculation:
    """Test _calculate_invoice_totals function."""

    def test_single_taxable_item_15_percent_gst(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
        ]
        result = _calculate_invoice_totals(items, Decimal("15"))
        assert result["subtotal"] == Decimal("100.00")
        assert result["gst_amount"] == Decimal("15.00")
        assert result["total"] == Decimal("115.00")
        assert result["discount_amount"] == Decimal("0.00")

    def test_multiple_items(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
            {"quantity": Decimal("2"), "unit_price": Decimal("50.00"), "is_gst_exempt": False},
        ]
        result = _calculate_invoice_totals(items, Decimal("15"))
        assert result["subtotal"] == Decimal("200.00")
        assert result["gst_amount"] == Decimal("30.00")
        assert result["total"] == Decimal("230.00")

    def test_gst_exempt_item_no_gst(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": True},
        ]
        result = _calculate_invoice_totals(items, Decimal("15"))
        assert result["subtotal"] == Decimal("100.00")
        assert result["gst_amount"] == Decimal("0.00")
        assert result["total"] == Decimal("100.00")

    def test_mixed_taxable_and_exempt(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("100.00"), "is_gst_exempt": False},
            {"quantity": Decimal("1"), "unit_price": Decimal("50.00"), "is_gst_exempt": True},
        ]
        result = _calculate_invoice_totals(items, Decimal("15"))
        assert result["subtotal"] == Decimal("150.00")
        assert result["gst_amount"] == Decimal("15.00")
        assert result["total"] == Decimal("165.00")

    def test_invoice_level_percentage_discount(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("200.00"), "is_gst_exempt": False},
        ]
        result = _calculate_invoice_totals(
            items, Decimal("15"), "percentage", Decimal("10")
        )
        assert result["subtotal"] == Decimal("200.00")
        assert result["discount_amount"] == Decimal("20.00")
        # GST on 180.00 = 27.00
        assert result["gst_amount"] == Decimal("27.00")
        assert result["total"] == Decimal("207.00")

    def test_invoice_level_fixed_discount(self):
        items = [
            {"quantity": Decimal("1"), "unit_price": Decimal("200.00"), "is_gst_exempt": False},
        ]
        result = _calculate_invoice_totals(
            items, Decimal("15"), "fixed", Decimal("50.00")
        )
        assert result["subtotal"] == Decimal("200.00")
        assert result["discount_amount"] == Decimal("50.00")
        # GST on 150.00 = 22.50
        assert result["gst_amount"] == Decimal("22.50")
        assert result["total"] == Decimal("172.50")

    def test_empty_line_items(self):
        result = _calculate_invoice_totals([], Decimal("15"))
        assert result["subtotal"] == Decimal("0.00")
        assert result["gst_amount"] == Decimal("0.00")
        assert result["total"] == Decimal("0.00")

    def test_line_item_with_discount(self):
        items = [
            {
                "quantity": Decimal("1"),
                "unit_price": Decimal("100.00"),
                "is_gst_exempt": False,
                "discount_type": "percentage",
                "discount_value": Decimal("20"),
            },
        ]
        result = _calculate_invoice_totals(items, Decimal("15"))
        # Line total: 100 - 20% = 80
        assert result["subtotal"] == Decimal("80.00")
        assert result["gst_amount"] == Decimal("12.00")
        assert result["total"] == Decimal("92.00")


# ---------------------------------------------------------------------------
# Service layer tests (with mocked DB)
# ---------------------------------------------------------------------------


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_mock_customer(org_id: uuid.UUID) -> MagicMock:
    """Create a mock Customer."""
    from app.modules.customers.models import Customer
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id
    customer.first_name = "Jane"
    customer.last_name = "Doe"
    return customer


def _make_mock_org(org_id: uuid.UUID, gst_pct: int = 15, prefix: str = "INV-") -> MagicMock:
    """Create a mock Organisation."""
    org = MagicMock()
    org.id = org_id
    org.settings = {
        "gst_percentage": gst_pct,
        "invoice_prefix": prefix,
        "default_due_days": 14,
    }
    return org


class TestCreateInvoiceService:
    """Test the create_invoice service function."""

    @pytest.mark.asyncio
    async def test_create_draft_no_invoice_number(self):
        """Draft invoices should not have an invoice number assigned."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(org_id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        # Mock customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        # Mock org lookup
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [cust_result, org_result, None]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                status="draft",
                line_items_data=[
                    {
                        "item_type": "service",
                        "description": "WOF inspection",
                        "quantity": Decimal("1"),
                        "unit_price": Decimal("55.00"),
                    },
                ],
            )

        assert result["invoice_number"] is None
        assert result["status"] == "draft"
        assert result["subtotal"] == Decimal("55.00")
        assert result["gst_amount"] == Decimal("8.25")
        assert result["total"] == Decimal("63.25")

    @pytest.mark.asyncio
    async def test_create_issued_assigns_number(self):
        """Issued invoices should get a sequential invoice number."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(org_id)
        org = _make_mock_org(org_id, prefix="WS-")

        db = _mock_db_session()

        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        # Mock sequence query — no existing sequence (first invoice)
        seq_result = MagicMock()
        seq_result.first.return_value = None

        db.execute.side_effect = [cust_result, org_result, seq_result, None, None]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                status="issued",
                line_items_data=[
                    {
                        "item_type": "service",
                        "description": "Full service",
                        "quantity": Decimal("1"),
                        "unit_price": Decimal("200.00"),
                    },
                ],
            )

        assert result["invoice_number"] == "WS-0001"
        assert result["status"] == "issued"
        assert result["issue_date"] is not None

    @pytest.mark.asyncio
    async def test_customer_not_found_raises(self):
        """Should raise ValueError when customer doesn't exist in org."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_session()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [cust_result]

        with pytest.raises(ValueError, match="Customer not found"):
            await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=uuid.uuid4(),
                status="draft",
            )

    @pytest.mark.asyncio
    async def test_gst_calculation_with_org_rate(self):
        """GST should use the org's configured rate."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(org_id)
        org = _make_mock_org(org_id, gst_pct=10)  # 10% GST

        db = _mock_db_session()

        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [cust_result, org_result, None]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                status="draft",
                line_items_data=[
                    {
                        "item_type": "part",
                        "description": "Oil filter",
                        "quantity": Decimal("1"),
                        "unit_price": Decimal("100.00"),
                    },
                ],
            )

        assert result["gst_amount"] == Decimal("10.00")
        assert result["total"] == Decimal("110.00")

    @pytest.mark.asyncio
    async def test_issued_invoice_gets_due_date_from_org_settings(self):
        """Issued invoice without explicit due_date should use org default."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(org_id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        seq_result = MagicMock()
        seq_result.first.return_value = None

        db.execute.side_effect = [cust_result, org_result, seq_result, None, None]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                status="issued",
            )

        assert result["due_date"] is not None
        assert result["issue_date"] is not None
