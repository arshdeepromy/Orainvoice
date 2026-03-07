"""Unit tests for Task 10.3 - invoice status lifecycle.
Requirements: 19.1-19.7
"""
from __future__ import annotations
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.schemas import InvoiceStatus
from app.modules.invoices.service import (
    issue_invoice, void_invoice, update_invoice_notes, mark_invoices_overdue,
    get_invoice, _validate_transition, VALID_TRANSITIONS, add_line_item, delete_line_item,
)
from app.modules.invoices.models import Invoice, LineItem


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_invoice(org_id=None, status="draft", invoice_number=None,
                  balance_due=Decimal("100.00"), due_date=None,
                  notes_internal=None, notes_customer=None):
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
    inv.notes_internal = notes_internal
    inv.notes_customer = notes_customer
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


def _make_org(org_id, prefix="INV-"):
    org = MagicMock()
    org.id = org_id
    org.name = "Test Workshop"
    org.settings = {"gst_percentage": 15, "gst_number": "123-456-789", "invoice_prefix": prefix, "default_due_days": 14}
    return org


def _mock_customer_result():
    """Return a mock db.execute result for customer lookup (tax compliance)."""
    cust = MagicMock()
    cust.first_name = "John"
    cust.last_name = "Doe"
    cust.address = "123 Main St, Auckland"
    r = MagicMock()
    r.scalar_one_or_none.return_value = cust
    return r


# --- State machine tests ---

class TestValidateTransition:
    def test_draft_to_issued(self):
        _validate_transition("draft", "issued")

    def test_draft_to_voided(self):
        _validate_transition("draft", "voided")

    def test_issued_to_partially_paid(self):
        _validate_transition("issued", "partially_paid")

    def test_issued_to_overdue(self):
        _validate_transition("issued", "overdue")

    def test_issued_to_voided(self):
        _validate_transition("issued", "voided")

    def test_partially_paid_to_paid(self):
        _validate_transition("partially_paid", "paid")

    def test_partially_paid_to_overdue(self):
        _validate_transition("partially_paid", "overdue")

    def test_overdue_to_paid(self):
        _validate_transition("overdue", "paid")

    def test_overdue_to_partially_paid(self):
        _validate_transition("overdue", "partially_paid")

    def test_paid_to_voided(self):
        _validate_transition("paid", "voided")

    def test_voided_is_terminal(self):
        for t in ["draft", "issued", "partially_paid", "paid", "overdue"]:
            with pytest.raises(ValueError, match="Invalid status transition"):
                _validate_transition("voided", t)

    def test_draft_to_paid_rejected(self):
        with pytest.raises(ValueError):
            _validate_transition("draft", "paid")

    def test_paid_to_draft_rejected(self):
        with pytest.raises(ValueError):
            _validate_transition("paid", "draft")

    def test_issued_to_draft_rejected(self):
        with pytest.raises(ValueError):
            _validate_transition("issued", "draft")

    def test_all_non_voided_can_void(self):
        for s in ["draft", "issued", "partially_paid", "paid", "overdue"]:
            assert "voided" in VALID_TRANSITIONS[s]


# --- Issue invoice tests ---

class TestIssueInvoice:
    @pytest.mark.asyncio
    async def test_issue_assigns_number_and_date(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")
        org = _make_org(org_id, prefix="WS-")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        org_r = MagicMock(); org_r.scalar_one_or_none.return_value = org
        seq_r = MagicMock(); seq_r.first.return_value = None
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = [_make_line_item(invoice.id)]
        db.execute.side_effect = [inv_r, org_r, seq_r, None, li_r, _mock_customer_result()]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await issue_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id)
        assert invoice.status == "issued"
        assert invoice.invoice_number == "WS-0001"
        assert invoice.issue_date == date.today()

    @pytest.mark.asyncio
    async def test_issue_sets_due_date_from_org(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")
        invoice.due_date = None
        org = _make_org(org_id)
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        org_r = MagicMock(); org_r.scalar_one_or_none.return_value = org
        seq_r = MagicMock(); seq_r.first.return_value = None
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = [_make_line_item(invoice.id)]
        db.execute.side_effect = [inv_r, org_r, seq_r, None, li_r, _mock_customer_result()]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await issue_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id)
        assert invoice.due_date == date.today() + timedelta(days=14)

    @pytest.mark.asyncio
    async def test_issue_non_draft_raises(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError, match="Invalid status transition"):
            await issue_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id)

    @pytest.mark.asyncio
    async def test_issue_not_found_raises(self):
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError, match="Invoice not found"):
            await issue_invoice(db, org_id=uuid.uuid4(), user_id=uuid.uuid4(), invoice_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_issue_writes_audit_log(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")
        org = _make_org(org_id)
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        org_r = MagicMock(); org_r.scalar_one_or_none.return_value = org
        seq_r = MagicMock(); seq_r.first.return_value = None
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = [_make_line_item(invoice.id)]
        db.execute.side_effect = [inv_r, org_r, seq_r, None, li_r, _mock_customer_result()]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as m:
            await issue_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id)
        m.assert_called_once()
        assert m.call_args.kwargs["action"] == "invoice.issued"


# --- Void invoice tests ---

class TestVoidInvoice:
    @pytest.mark.asyncio
    async def test_void_issued_invoice(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await void_invoice(db, org_id=org_id, user_id=user_id, invoice_id=invoice.id, reason="Customer cancelled")
        assert invoice.status == "voided"
        assert invoice.void_reason == "Customer cancelled"
        assert invoice.voided_at is not None
        assert invoice.voided_by == user_id

    @pytest.mark.asyncio
    async def test_void_retains_invoice_number(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0005")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await void_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, reason="Duplicate")
        assert invoice.invoice_number == "INV-0005"

    @pytest.mark.asyncio
    async def test_void_already_voided_raises(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError, match="Invalid status transition"):
            await void_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, reason="Test")

    @pytest.mark.asyncio
    async def test_void_draft_allowed(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await void_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, reason="Not needed")
        assert invoice.status == "voided"

    @pytest.mark.asyncio
    async def test_void_writes_audit_log(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="paid")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as m:
            await void_invoice(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, reason="Refund")
        m.assert_called_once()
        kw = m.call_args.kwargs
        assert kw["action"] == "invoice.voided"
        assert kw["before_value"]["status"] == "paid"
        assert kw["after_value"]["status"] == "voided"


# --- Update notes tests ---

class TestUpdateInvoiceNotes:
    @pytest.mark.asyncio
    async def test_update_notes_on_issued(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", notes_internal="Old", notes_customer="Old cust")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await update_invoice_notes(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id,
                                       notes_internal="New", notes_customer="New cust")
        assert invoice.notes_internal == "New"
        assert invoice.notes_customer == "New cust"

    @pytest.mark.asyncio
    async def test_update_notes_on_voided_raises(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError, match="Cannot update notes on a voided invoice"):
            await update_invoice_notes(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, notes_internal="Fail")

    @pytest.mark.asyncio
    async def test_partial_notes_update(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", notes_internal="Keep", notes_customer="Keep too")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, li_r]
        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            await update_invoice_notes(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, notes_internal="Changed")
        assert invoice.notes_internal == "Changed"
        assert invoice.notes_customer == "Keep too"


# --- Overdue auto-detection tests ---

class TestMarkInvoicesOverdue:
    @pytest.mark.asyncio
    async def test_overdue_when_past_due(self):
        inv1 = _make_invoice(status="issued", due_date=date.today() - timedelta(days=1), balance_due=Decimal("50.00"))
        inv2 = _make_invoice(status="partially_paid", due_date=date.today() - timedelta(days=5), balance_due=Decimal("25.00"))
        db = _mock_db()
        r = MagicMock(); r.scalars.return_value.all.return_value = [inv1, inv2]
        db.execute.return_value = r
        count = await mark_invoices_overdue(db)
        assert count == 2
        assert inv1.status == "overdue"
        assert inv2.status == "overdue"

    @pytest.mark.asyncio
    async def test_no_overdue_when_none_qualify(self):
        db = _mock_db()
        r = MagicMock(); r.scalars.return_value.all.return_value = []
        db.execute.return_value = r
        count = await mark_invoices_overdue(db)
        assert count == 0

    @pytest.mark.asyncio
    async def test_overdue_with_custom_date(self):
        inv = _make_invoice(status="issued", due_date=date(2025, 6, 1), balance_due=Decimal("100.00"))
        db = _mock_db()
        r = MagicMock(); r.scalars.return_value.all.return_value = [inv]
        db.execute.return_value = r
        count = await mark_invoices_overdue(db, as_of_date=date(2025, 6, 2))
        assert count == 1
        assert inv.status == "overdue"


# --- Get invoice tests ---

class TestGetInvoice:
    @pytest.mark.asyncio
    async def test_get_existing_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")
        li = _make_line_item(invoice.id)
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalars.return_value.all.return_value = [li]
        db.execute.side_effect = [inv_r, li_r]
        result = await get_invoice(db, org_id=org_id, invoice_id=invoice.id)
        assert result["id"] == invoice.id
        assert result["status"] == "issued"
        assert len(result["line_items"]) == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_raises(self):
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError, match="Invoice not found"):
            await get_invoice(db, org_id=uuid.uuid4(), invoice_id=uuid.uuid4())


# --- Structural edit rejection on issued invoices ---

class TestIssuedInvoiceRejectsEdits:
    @pytest.mark.asyncio
    async def test_add_line_item_to_issued_rejected(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]
        with pytest.raises(ValueError):
            await add_line_item(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id,
                                item_data={"item_type": "service", "description": "Extra", "quantity": Decimal("1"), "unit_price": Decimal("50.00")})

    @pytest.mark.asyncio
    async def test_delete_line_item_from_issued_rejected(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", invoice_number="INV-0001")
        li = _make_line_item(invoice.id)
        db = _mock_db()
        inv_r = MagicMock(); inv_r.scalar_one_or_none.return_value = invoice
        li_r = MagicMock(); li_r.scalar_one_or_none.return_value = li
        db.execute.side_effect = [inv_r, li_r]
        with pytest.raises(ValueError):
            await delete_line_item(db, org_id=org_id, user_id=uuid.uuid4(), invoice_id=invoice.id, line_item_id=li.id)
