"""Unit tests for Task 10.4 — gap-free invoice numbering.

Requirements: 23.1, 23.2, 23.3
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem
from app.modules.invoices.service import (
    _get_next_invoice_number,
    issue_invoice,
    update_invoice,
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


def _make_invoice(
    org_id=None,
    status="draft",
    invoice_number=None,
    balance_due=Decimal("100.00"),
    due_date=None,
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.status = status
    inv.invoice_number = invoice_number
    inv.issue_date = date.today() if status != "draft" else None
    inv.due_date = due_date
    inv.balance_due = balance_due
    inv.amount_paid = Decimal("0.00")
    inv.total = Decimal("100.00")
    inv.subtotal = Decimal("86.96")
    inv.gst_amount = Decimal("13.04")
    inv.discount_amount = Decimal("0.00")
    inv.discount_type = None
    inv.discount_value = None
    inv.currency = "NZD"
    inv.vehicle_rego = "ABC123"
    inv.vehicle_make = "Toyota"
    inv.vehicle_model = "Corolla"
    inv.vehicle_year = 2020
    inv.vehicle_odometer = 50000
    inv.branch_id = None
    inv.notes_internal = None
    inv.notes_customer = None
    inv.void_reason = None
    inv.voided_at = None
    inv.voided_by = None
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    inv.line_items = []
    inv.credit_notes = []
    inv.payments = []
    return inv


def _make_org(org_id, prefix="INV-"):
    org = MagicMock()
    org.id = org_id
    org.name = "Test Workshop"
    org.settings = {
        "gst_percentage": 15,
        "gst_number": "123-456-789",
        "invoice_prefix": prefix,
        "default_due_days": 14,
    }
    return org


def _make_line_item(invoice_id=None):
    li = MagicMock(spec=LineItem)
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id or uuid.uuid4()
    li.item_type = "service"
    li.description = "WOF inspection"
    li.catalogue_item_id = None
    li.part_number = None
    li.quantity = Decimal("1")
    li.unit_price = Decimal("55.00")
    li.hours = None
    li.hourly_rate = None
    li.discount_type = None
    li.discount_value = None
    li.is_gst_exempt = False
    li.warranty_note = None
    li.line_total = Decimal("55.00")
    li.sort_order = 0
    return li


# ---------------------------------------------------------------------------
# Req 23.1 — Gap-free invoice numbering with SELECT ... FOR UPDATE
# ---------------------------------------------------------------------------


class TestGapFreeNumbering:
    """Verify _get_next_invoice_number uses FOR UPDATE and produces contiguous numbers."""

    @pytest.mark.asyncio
    async def test_first_invoice_creates_sequence_row(self):
        """First invoice for an org creates the sequence row with number 1."""
        db = _mock_db()
        org_id = uuid.uuid4()

        # Simulate no existing sequence row
        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute.return_value = mock_result

        number = await _get_next_invoice_number(db, org_id, "INV-")

        assert number == "INV-0001"
        # Should have called execute twice: SELECT FOR UPDATE + INSERT
        assert db.execute.call_count == 2
        # Verify the SELECT uses FOR UPDATE
        first_call_sql = str(db.execute.call_args_list[0][0][0].text)
        assert "FOR UPDATE" in first_call_sql

    @pytest.mark.asyncio
    async def test_subsequent_invoice_increments(self):
        """Subsequent invoices increment the sequence counter."""
        db = _mock_db()
        org_id = uuid.uuid4()
        seq_id = uuid.uuid4()

        # Simulate existing sequence row with last_number=5
        mock_row = MagicMock()
        mock_row.last_number = 5
        mock_row.id = seq_id
        mock_result = MagicMock()
        mock_result.first.return_value = mock_row
        db.execute.return_value = mock_result

        number = await _get_next_invoice_number(db, org_id, "INV-")

        assert number == "INV-0006"
        # Should have called execute twice: SELECT FOR UPDATE + UPDATE
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_org_prefix(self):
        """Invoice number uses the org-configured prefix."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute.return_value = mock_result

        number = await _get_next_invoice_number(db, org_id, "WS-")

        assert number == "WS-0001"
        assert number.startswith("WS-")

    @pytest.mark.asyncio
    async def test_numbers_are_zero_padded(self):
        """Invoice numbers are zero-padded to 4 digits."""
        db = _mock_db()
        org_id = uuid.uuid4()
        seq_id = uuid.uuid4()

        mock_row = MagicMock()
        mock_row.last_number = 99
        mock_row.id = seq_id
        mock_result = MagicMock()
        mock_result.first.return_value = mock_row
        db.execute.return_value = mock_result

        number = await _get_next_invoice_number(db, org_id, "INV-")

        assert number == "INV-0100"

    @pytest.mark.asyncio
    async def test_select_for_update_in_query(self):
        """The SELECT query must include FOR UPDATE for row-level locking."""
        db = _mock_db()
        org_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.first.return_value = None
        db.execute.return_value = mock_result

        await _get_next_invoice_number(db, org_id, "INV-")

        # First call is the SELECT ... FOR UPDATE
        first_call = db.execute.call_args_list[0]
        sql_text = str(first_call[0][0].text)
        assert "FOR UPDATE" in sql_text
        assert "invoice_sequences" in sql_text


# ---------------------------------------------------------------------------
# Req 23.2 — Invoice number immutability
# ---------------------------------------------------------------------------


class TestInvoiceNumberImmutability:
    """Verify that assigned invoice numbers cannot be modified via API."""

    @pytest.mark.asyncio
    async def test_cannot_modify_assigned_invoice_number(self):
        """Attempting to change an assigned invoice number raises ValueError."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")

        # Mock db.execute to return the invoice
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invoice number cannot be modified once assigned"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"invoice_number": "INV-9999"},
            )

    @pytest.mark.asyncio
    async def test_cannot_manually_set_number_on_draft(self):
        """Even drafts cannot have invoice numbers manually assigned."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft", invoice_number=None)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="system-assigned and cannot be set manually"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"invoice_number": "CUSTOM-001"},
            )

    @pytest.mark.asyncio
    async def test_update_draft_without_number_succeeds(self):
        """Updating allowed fields on a draft invoice works fine."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft", invoice_number=None)
        line_item = _make_line_item(invoice_id=invoice.id)

        # First call returns invoice, second returns line items
        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = invoice

        mock_li_result = MagicMock()
        mock_li_scalars = MagicMock()
        mock_li_scalars.all.return_value = [line_item]
        mock_li_result.scalars.return_value = mock_li_scalars

        db.execute.side_effect = [mock_inv_result, mock_li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"notes_customer": "Updated note"},
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_update_issued_invoice_rejected(self):
        """Updating structural fields on an issued invoice is rejected."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Only draft invoices can be updated"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"notes_customer": "test"},
            )

    @pytest.mark.asyncio
    async def test_update_nonexistent_invoice_raises(self):
        """Updating a non-existent invoice raises ValueError."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Invoice not found"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=uuid.uuid4(),
                updates={"notes_customer": "test"},
            )


# ---------------------------------------------------------------------------
# Req 23.3 — Audit log with before/after values
# ---------------------------------------------------------------------------


class TestAuditLogStateChanges:
    """Verify all state changes are recorded in the audit log with before/after values."""

    @pytest.mark.asyncio
    async def test_issue_invoice_audit_has_before_after(self):
        """Issuing an invoice records before (draft, no number) and after (issued, number)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft", invoice_number=None)
        org = _make_org(org_id)
        line_item = _make_line_item(invoice_id=invoice.id)

        # Sequence: invoice lookup, org lookup, sequence SELECT FOR UPDATE,
        # sequence INSERT, flush, audit, line items
        call_count = [0]
        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = invoice

        mock_org_result = MagicMock()
        mock_org_result.scalar_one_or_none.return_value = org

        # Sequence row (first invoice)
        mock_seq_result = MagicMock()
        mock_seq_result.first.return_value = None

        mock_li_result = MagicMock()
        mock_li_scalars = MagicMock()
        mock_li_scalars.all.return_value = [line_item]
        mock_li_result.scalars.return_value = mock_li_scalars

        # Customer mock for NZ tax compliance check (Req 80.2)
        mock_cust_result = MagicMock()
        mock_customer = MagicMock()
        mock_customer.first_name = "John"
        mock_customer.last_name = "Doe"
        mock_customer.address = "123 Main St"
        mock_cust_result.scalar_one_or_none.return_value = mock_customer

        db.execute.side_effect = [
            mock_inv_result,   # invoice lookup
            mock_org_result,   # org lookup
            mock_seq_result,   # SELECT FOR UPDATE
            MagicMock(),       # INSERT sequence
            mock_li_result,    # line items
            mock_cust_result,  # customer lookup (tax compliance)
        ]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            result = await issue_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]

            assert call_kwargs["action"] == "invoice.issued"
            assert call_kwargs["before_value"]["status"] == "draft"
            assert call_kwargs["before_value"]["invoice_number"] is None
            assert call_kwargs["after_value"]["status"] == "issued"
            assert call_kwargs["after_value"]["invoice_number"] is not None
            assert "issue_date" in call_kwargs["after_value"]
            assert "due_date" in call_kwargs["after_value"]

    @pytest.mark.asyncio
    async def test_update_invoice_audit_has_before_after(self):
        """Updating a draft invoice records before and after values."""
        db = _mock_db()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft", invoice_number=None)
        line_item = _make_line_item(invoice_id=invoice.id)

        mock_inv_result = MagicMock()
        mock_inv_result.scalar_one_or_none.return_value = invoice

        mock_li_result = MagicMock()
        mock_li_scalars = MagicMock()
        mock_li_scalars.all.return_value = [line_item]
        mock_li_result.scalars.return_value = mock_li_scalars

        db.execute.side_effect = [mock_inv_result, mock_li_result]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"notes_customer": "New note"},
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]

            assert call_kwargs["action"] == "invoice.updated"
            assert "before_value" in call_kwargs
            assert "after_value" in call_kwargs
            assert call_kwargs["after_value"]["notes_customer"] == "New note"
