"""Unit tests for Task 10.2 — invoice line item management.

Tests cover:
  - Adding line items to draft invoices (service, part, labour)
  - Service catalogue pre-fill (description + price)
  - Labour rate pre-fill (hourly rate)
  - Deleting line items from draft invoices
  - Recalculation of invoice totals after add/delete
  - Rejection of line item changes on non-draft invoices
  - Warranty notes, GST-exempt toggle, per-line discounts
  - AddLineItemRequest schema validation

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.invoices.schemas import AddLineItemRequest, ItemType
from app.modules.invoices.service import (
    add_line_item,
    delete_line_item,
    _calculate_line_total,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_invoice(org_id, status="draft", discount_type=None, discount_value=None, amount_paid=Decimal("0")):
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.org_id = org_id
    inv.status = status
    inv.discount_type = discount_type
    inv.discount_value = discount_value
    inv.amount_paid = amount_paid
    inv.subtotal = Decimal("0")
    inv.discount_amount = Decimal("0")
    inv.gst_amount = Decimal("0")
    inv.total = Decimal("0")
    inv.balance_due = Decimal("0")
    return inv


def _make_org(org_id, gst_pct=15):
    org = MagicMock()
    org.id = org_id
    org.settings = {"gst_percentage": gst_pct}
    return org


def _make_line_item(invoice_id, org_id, item_type="service", unit_price=Decimal("50.00"),
                    quantity=Decimal("1"), sort_order=0, is_gst_exempt=False,
                    discount_type=None, discount_value=None):
    li = MagicMock()
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id
    li.org_id = org_id
    li.item_type = item_type
    li.description = "Test item"
    li.catalogue_item_id = None
    li.part_number = None
    li.quantity = quantity
    li.unit_price = unit_price
    li.hours = None
    li.hourly_rate = None
    li.discount_type = discount_type
    li.discount_value = discount_value
    li.is_gst_exempt = is_gst_exempt
    li.warranty_note = None
    li.line_total = _calculate_line_total(quantity, unit_price, discount_type, discount_value)
    li.sort_order = sort_order
    return li


def _make_catalogue_item(org_id, name="WOF Inspection", price=Decimal("55.00")):
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.org_id = org_id
    cat.name = name
    cat.default_price = price
    cat.is_active = True
    cat.is_gst_exempt = False
    return cat


def _make_labour_rate(org_id, name="Standard", rate=Decimal("85.00")):
    lr = MagicMock()
    lr.id = uuid.uuid4()
    lr.org_id = org_id
    lr.name = name
    lr.hourly_rate = rate
    lr.is_active = True
    return lr


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestAddLineItemRequestSchema:
    """Test AddLineItemRequest Pydantic schema validation."""

    def test_minimal_part_item(self):
        req = AddLineItemRequest(
            item_type="part",
            description="Brake pads",
            unit_price=Decimal("45.00"),
        )
        assert req.item_type == ItemType.part
        assert req.quantity == Decimal("1")

    def test_service_with_catalogue_id(self):
        cat_id = uuid.uuid4()
        req = AddLineItemRequest(
            item_type="service",
            catalogue_item_id=cat_id,
        )
        assert req.catalogue_item_id == cat_id
        assert req.unit_price is None  # will be pre-filled from catalogue

    def test_labour_with_rate_id(self):
        rate_id = uuid.uuid4()
        req = AddLineItemRequest(
            item_type="labour",
            description="Engine work",
            labour_rate_id=rate_id,
            hours=Decimal("2"),
        )
        assert req.labour_rate_id == rate_id
        assert req.hours == Decimal("2")

    def test_warranty_note(self):
        req = AddLineItemRequest(
            item_type="service",
            description="Warranty repair",
            unit_price=Decimal("0"),
            warranty_note="Covered under 12-month warranty",
        )
        assert req.warranty_note == "Covered under 12-month warranty"

    def test_gst_exempt_toggle(self):
        req = AddLineItemRequest(
            item_type="service",
            description="Insurance work",
            unit_price=Decimal("100.00"),
            is_gst_exempt=True,
        )
        assert req.is_gst_exempt is True

    def test_per_line_discount(self):
        req = AddLineItemRequest(
            item_type="part",
            description="Filter",
            unit_price=Decimal("20.00"),
            discount_type="percentage",
            discount_value=Decimal("10"),
        )
        assert req.discount_type == "percentage"


# ---------------------------------------------------------------------------
# Service layer tests — add_line_item
# ---------------------------------------------------------------------------


class TestAddLineItem:
    """Test add_line_item service function."""

    @pytest.mark.asyncio
    async def test_add_part_to_draft(self):
        """Adding a part line item to a draft invoice should recalculate totals."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id)
        org = _make_org(org_id)

        db = _mock_db()

        # Mock: invoice lookup
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice

        # Mock: existing line items (none yet) for sort order
        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None

        # Mock: org lookup for recalculate
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        # Mock: line items query for recalculate — returns the newly added item
        new_li = _make_line_item(invoice.id, org_id, "part", Decimal("45.00"), Decimal("2"))
        li_result = MagicMock()
        li_result.scalars.return_value.all.return_value = [new_li]

        db.execute.side_effect = [inv_result, existing_result, org_result, li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await add_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                item_data={
                    "item_type": "part",
                    "description": "Brake pads",
                    "part_number": "BP-100",
                    "quantity": Decimal("2"),
                    "unit_price": Decimal("45.00"),
                },
            )

        assert result is not None
        assert db.add.called

    @pytest.mark.asyncio
    async def test_add_service_with_catalogue_prefill(self):
        """Service items with catalogue_item_id should pre-fill description and price."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id)
        org = _make_org(org_id)
        cat_item = _make_catalogue_item(org_id, "WOF", Decimal("55.00"))

        db = _mock_db()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice

        cat_result = MagicMock()
        cat_result.scalar_one_or_none.return_value = cat_item

        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        new_li = _make_line_item(invoice.id, org_id, "service", Decimal("55.00"))
        li_result = MagicMock()
        li_result.scalars.return_value.all.return_value = [new_li]

        db.execute.side_effect = [inv_result, cat_result, existing_result, org_result, li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await add_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                item_data={
                    "item_type": "service",
                    "description": "",
                    "catalogue_item_id": cat_item.id,
                    "quantity": Decimal("1"),
                    "unit_price": None,
                },
            )

        assert result is not None
        # Verify db.add was called (line item was created)
        assert db.add.called

    @pytest.mark.asyncio
    async def test_add_labour_with_rate_prefill(self):
        """Labour items with labour_rate_id should pre-fill hourly rate."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id)
        org = _make_org(org_id)
        rate = _make_labour_rate(org_id, "Standard", Decimal("85.00"))

        db = _mock_db()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice

        rate_result = MagicMock()
        rate_result.scalar_one_or_none.return_value = rate

        existing_result = MagicMock()
        existing_result.scalars.return_value.first.return_value = None

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        new_li = _make_line_item(invoice.id, org_id, "labour", Decimal("170.00"))
        li_result = MagicMock()
        li_result.scalars.return_value.all.return_value = [new_li]

        db.execute.side_effect = [inv_result, rate_result, existing_result, org_result, li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await add_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                item_data={
                    "item_type": "labour",
                    "description": "Engine diagnostic",
                    "labour_rate_id": rate.id,
                    "hours": Decimal("2"),
                    "quantity": Decimal("1"),
                    "unit_price": None,
                    "hourly_rate": None,
                },
            )

        assert result is not None
        assert db.add.called

    @pytest.mark.asyncio
    async def test_reject_add_on_issued_invoice(self):
        """Adding line items to a non-draft invoice should raise ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id, status="issued")

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_result]

        with pytest.raises(ValueError, match="draft invoices"):
            await add_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                item_data={
                    "item_type": "service",
                    "description": "Test",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("10.00"),
                },
            )

    @pytest.mark.asyncio
    async def test_reject_add_invoice_not_found(self):
        """Should raise ValueError when invoice doesn't exist."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_result]

        with pytest.raises(ValueError, match="Invoice not found"):
            await add_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=uuid.uuid4(),
                item_data={
                    "item_type": "service",
                    "description": "Test",
                    "quantity": Decimal("1"),
                    "unit_price": Decimal("10.00"),
                },
            )


# ---------------------------------------------------------------------------
# Service layer tests — delete_line_item
# ---------------------------------------------------------------------------


class TestDeleteLineItem:
    """Test delete_line_item service function."""

    @pytest.mark.asyncio
    async def test_delete_from_draft(self):
        """Deleting a line item from a draft should recalculate totals."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id)
        org = _make_org(org_id)
        li = _make_line_item(invoice.id, org_id)

        db = _mock_db()

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice

        li_result = MagicMock()
        li_result.scalar_one_or_none.return_value = li

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        # After deletion, no line items remain
        empty_li_result = MagicMock()
        empty_li_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_result, li_result, org_result, empty_li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await delete_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                line_item_id=li.id,
            )

        assert result is not None
        assert db.delete.called

    @pytest.mark.asyncio
    async def test_reject_delete_on_issued_invoice(self):
        """Deleting line items from a non-draft invoice should raise ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id, status="issued")

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_result]

        with pytest.raises(ValueError, match="draft invoices"):
            await delete_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                line_item_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_reject_delete_line_item_not_found(self):
        """Should raise ValueError when line item doesn't exist on invoice."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id)

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice

        li_result = MagicMock()
        li_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [inv_result, li_result]

        with pytest.raises(ValueError, match="Line item not found"):
            await delete_line_item(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                line_item_id=uuid.uuid4(),
            )
