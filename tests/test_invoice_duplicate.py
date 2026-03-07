"""Unit tests for Task 10.7 — invoice duplication.

Tests cover:
  - Duplicating an invoice creates a new Draft with same customer, vehicle, line items
  - Duplicated draft has no invoice number (Req 22.2)
  - Line item details are copied correctly
  - Totals are recalculated from copied line items
  - Audit log entry is written
  - Source invoice not found raises ValueError

Requirements: 22.1, 22.2
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

from app.modules.invoices.schemas import DuplicateInvoiceResponse, InvoiceResponse
from app.modules.invoices.service import duplicate_invoice
from app.modules.invoices.models import Invoice, LineItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_mock_org(org_id: uuid.UUID, gst_pct: int = 15) -> MagicMock:
    """Create a mock Organisation."""
    org = MagicMock()
    org.id = org_id
    org.settings = {
        "gst_percentage": gst_pct,
        "invoice_prefix": "INV-",
        "default_due_days": 14,
    }
    return org


def _make_source_invoice(org_id: uuid.UUID, customer_id: uuid.UUID) -> MagicMock:
    """Create a mock source Invoice for duplication."""
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id
    inv.customer_id = customer_id
    inv.invoice_number = "INV-0001"
    inv.vehicle_rego = "ABC123"
    inv.vehicle_make = "Toyota"
    inv.vehicle_model = "Corolla"
    inv.vehicle_year = 2020
    inv.vehicle_odometer = 85000
    inv.branch_id = None
    inv.status = "issued"
    inv.issue_date = date(2024, 1, 15)
    inv.due_date = date(2024, 2, 15)
    inv.currency = "NZD"
    inv.subtotal = Decimal("100.00")
    inv.discount_amount = Decimal("0.00")
    inv.discount_type = None
    inv.discount_value = None
    inv.gst_amount = Decimal("15.00")
    inv.total = Decimal("115.00")
    inv.amount_paid = Decimal("115.00")
    inv.balance_due = Decimal("0.00")
    inv.notes_internal = "Internal note"
    inv.notes_customer = "Customer note"
    inv.void_reason = None
    inv.voided_at = None
    inv.voided_by = None
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    return inv


def _make_source_line_items(org_id: uuid.UUID, invoice_id: uuid.UUID) -> list[MagicMock]:
    """Create mock line items for the source invoice."""
    li1 = MagicMock(spec=LineItem)
    li1.id = uuid.uuid4()
    li1.invoice_id = invoice_id
    li1.org_id = org_id
    li1.item_type = "service"
    li1.description = "WOF inspection"
    li1.catalogue_item_id = None
    li1.part_number = None
    li1.quantity = Decimal("1")
    li1.unit_price = Decimal("55.00")
    li1.hours = None
    li1.hourly_rate = None
    li1.discount_type = None
    li1.discount_value = None
    li1.is_gst_exempt = False
    li1.warranty_note = None
    li1.line_total = Decimal("55.00")
    li1.sort_order = 0

    li2 = MagicMock(spec=LineItem)
    li2.id = uuid.uuid4()
    li2.invoice_id = invoice_id
    li2.org_id = org_id
    li2.item_type = "part"
    li2.description = "Oil filter"
    li2.catalogue_item_id = None
    li2.part_number = "OF-123"
    li2.quantity = Decimal("1")
    li2.unit_price = Decimal("45.00")
    li2.hours = None
    li2.hourly_rate = None
    li2.discount_type = None
    li2.discount_value = None
    li2.is_gst_exempt = False
    li2.warranty_note = "6 month warranty"
    li2.line_total = Decimal("45.00")
    li2.sort_order = 1

    return [li1, li2]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDuplicateInvoiceService:
    """Test the duplicate_invoice service function."""

    @pytest.mark.asyncio
    async def test_duplicate_creates_draft_with_no_number(self):
        """Duplicated invoice should be a draft with no invoice number (Req 22.2)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        source = _make_source_invoice(org_id, customer_id)
        line_items = _make_source_line_items(org_id, source.id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        # Mock: source invoice lookup
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = source

        # Mock: line items lookup
        li_scalars = MagicMock()
        li_scalars.all.return_value = line_items
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        # Mock: org lookup
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [inv_result, li_result, org_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=source.id,
            )

        assert result["invoice_number"] is None
        assert result["status"] == "draft"
        assert result["issue_date"] is None
        assert result["due_date"] is None

    @pytest.mark.asyncio
    async def test_duplicate_copies_customer_and_vehicle(self):
        """Duplicated invoice should have the same customer and vehicle fields (Req 22.1)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        source = _make_source_invoice(org_id, customer_id)
        line_items = _make_source_line_items(org_id, source.id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = source

        li_scalars = MagicMock()
        li_scalars.all.return_value = line_items
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [inv_result, li_result, org_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=source.id,
            )

        assert result["customer_id"] == customer_id
        assert result["vehicle_rego"] == "ABC123"
        assert result["vehicle_make"] == "Toyota"
        assert result["vehicle_model"] == "Corolla"
        assert result["vehicle_year"] == 2020
        assert result["vehicle_odometer"] == 85000

    @pytest.mark.asyncio
    async def test_duplicate_copies_line_items(self):
        """Duplicated invoice should have the same line items (Req 22.1)."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        source = _make_source_invoice(org_id, customer_id)
        line_items = _make_source_line_items(org_id, source.id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = source

        li_scalars = MagicMock()
        li_scalars.all.return_value = line_items
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [inv_result, li_result, org_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=source.id,
            )

        assert len(result["line_items"]) == 2

        li1 = result["line_items"][0]
        assert li1["item_type"] == "service"
        assert li1["description"] == "WOF inspection"
        assert li1["quantity"] == Decimal("1")
        assert li1["unit_price"] == Decimal("55.00")

        li2 = result["line_items"][1]
        assert li2["item_type"] == "part"
        assert li2["description"] == "Oil filter"
        assert li2["part_number"] == "OF-123"
        assert li2["warranty_note"] == "6 month warranty"

    @pytest.mark.asyncio
    async def test_duplicate_recalculates_totals(self):
        """Duplicated invoice should have recalculated totals from line items."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        source = _make_source_invoice(org_id, customer_id)
        line_items = _make_source_line_items(org_id, source.id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = source

        li_scalars = MagicMock()
        li_scalars.all.return_value = line_items
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [inv_result, li_result, org_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=source.id,
            )

        # 55 + 45 = 100 subtotal, 15% GST = 15, total = 115
        assert result["subtotal"] == Decimal("100.00")
        assert result["gst_amount"] == Decimal("15.00")
        assert result["total"] == Decimal("115.00")
        assert result["amount_paid"] == Decimal("0")
        assert result["balance_due"] == Decimal("115.00")

    @pytest.mark.asyncio
    async def test_duplicate_invoice_not_found_raises(self):
        """Should raise ValueError when source invoice doesn't exist."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_session()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_result]

        with pytest.raises(ValueError, match="Invoice not found"):
            await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_duplicate_writes_audit_log(self):
        """Duplicating an invoice should write an audit log entry."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        source = _make_source_invoice(org_id, customer_id)
        line_items = _make_source_line_items(org_id, source.id)
        org = _make_mock_org(org_id)

        db = _mock_db_session()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = source

        li_scalars = MagicMock()
        li_scalars.all.return_value = line_items
        li_result = MagicMock()
        li_result.scalars.return_value = li_scalars

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute.side_effect = [inv_result, li_result, org_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await duplicate_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=source.id,
                ip_address="192.168.1.1",
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            assert call_kwargs.kwargs["action"] == "invoice.duplicated"
            assert call_kwargs.kwargs["org_id"] == org_id
            assert call_kwargs.kwargs["user_id"] == user_id
            assert call_kwargs.kwargs["ip_address"] == "192.168.1.1"
            after = call_kwargs.kwargs["after_value"]
            assert after["source_invoice_id"] == str(source.id)
            assert after["line_item_count"] == 2


class TestDuplicateInvoiceResponseSchema:
    """Test the DuplicateInvoiceResponse schema."""

    def test_schema_accepts_valid_data(self):
        """DuplicateInvoiceResponse should accept valid invoice + message."""
        resp = DuplicateInvoiceResponse(
            invoice=InvoiceResponse(
                id=uuid.uuid4(),
                org_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                status="draft",
                currency="NZD",
                subtotal=Decimal("100.00"),
                discount_amount=Decimal("0"),
                gst_amount=Decimal("15.00"),
                total=Decimal("115.00"),
                amount_paid=Decimal("0"),
                balance_due=Decimal("115.00"),
                line_items=[],
                created_by=uuid.uuid4(),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            ),
            message="Invoice duplicated as new draft",
        )
        assert resp.invoice.status == "draft"
        assert resp.invoice.invoice_number is None
        assert resp.message == "Invoice duplicated as new draft"
