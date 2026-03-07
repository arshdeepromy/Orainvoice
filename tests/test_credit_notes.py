"""Unit tests for Task 10.5 — credit notes.

Tests cover:
  - Schema validation for credit note create requests
  - Credit note creation against issued/paid invoices
  - Rejection for draft/voided invoices
  - Balance update on original invoice
  - Gap-free CN numbering
  - Over-credit prevention
  - Stripe refund prompting
  - Listing credit notes for an invoice

Requirements: 20.1, 20.2, 20.3, 20.4
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
    CreditNoteCreateRequest,
    CreditNoteItemCreate,
    CreditNoteResponse,
    CreditNoteCreateResponse,
    CreditNoteListResponse,
)
from app.modules.invoices.service import (
    create_credit_note,
    get_credit_notes_for_invoice,
    _get_next_credit_note_number,
)
from app.modules.invoices.models import CreditNote, Invoice, LineItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _make_invoice(
    org_id=None,
    status="issued",
    invoice_number="INV-0001",
    total=Decimal("100.00"),
    amount_paid=Decimal("0.00"),
    balance_due=Decimal("100.00"),
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.status = status
    inv.invoice_number = invoice_number
    inv.issue_date = date.today()
    inv.due_date = date.today()
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.subtotal = Decimal("86.96")
    inv.gst_amount = Decimal("13.04")
    inv.discount_amount = Decimal("0.00")
    inv.discount_type = None
    inv.discount_value = None
    inv.vehicle_rego = None
    inv.vehicle_make = None
    inv.vehicle_model = None
    inv.vehicle_year = None
    inv.vehicle_odometer = None
    inv.branch_id = None
    inv.currency = "NZD"
    inv.notes_internal = None
    inv.notes_customer = None
    inv.void_reason = None
    inv.voided_at = None
    inv.voided_by = None
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    return inv


def _make_credit_note(org_id, invoice_id, amount=Decimal("50.00"), number="CN-0001"):
    cn = MagicMock(spec=CreditNote)
    cn.id = uuid.uuid4()
    cn.org_id = org_id
    cn.invoice_id = invoice_id
    cn.credit_note_number = number
    cn.amount = amount
    cn.reason = "Test reason"
    cn.items = [{"description": "Item refund", "amount": "50.00"}]
    cn.stripe_refund_id = None
    cn.created_by = uuid.uuid4()
    cn.created_at = datetime.now(timezone.utc)
    return cn


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestCreditNoteSchemas:
    def test_valid_credit_note_request(self):
        req = CreditNoteCreateRequest(
            amount=Decimal("50.00"),
            reason="Overcharged for service",
            items=[CreditNoteItemCreate(description="Oil change refund", amount=Decimal("50.00"))],
        )
        assert req.amount == Decimal("50.00")
        assert req.reason == "Overcharged for service"
        assert len(req.items) == 1
        assert req.process_stripe_refund is False

    def test_credit_note_request_with_stripe_refund(self):
        req = CreditNoteCreateRequest(
            amount=Decimal("25.00"),
            reason="Partial refund",
            process_stripe_refund=True,
        )
        assert req.process_stripe_refund is True

    def test_zero_amount_rejected(self):
        with pytest.raises(Exception):
            CreditNoteCreateRequest(
                amount=Decimal("0.00"),
                reason="Should fail",
            )

    def test_negative_amount_rejected(self):
        with pytest.raises(Exception):
            CreditNoteCreateRequest(
                amount=Decimal("-10.00"),
                reason="Should fail",
            )

    def test_empty_reason_rejected(self):
        with pytest.raises(Exception):
            CreditNoteCreateRequest(
                amount=Decimal("10.00"),
                reason="",
            )

    def test_credit_note_without_items(self):
        req = CreditNoteCreateRequest(
            amount=Decimal("30.00"),
            reason="General correction",
        )
        assert req.items == []


# ---------------------------------------------------------------------------
# Service tests — create_credit_note
# ---------------------------------------------------------------------------


class TestCreateCreditNote:
    @pytest.mark.asyncio
    async def test_create_credit_note_on_issued_invoice(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued")
        db = _mock_db()

        # db.execute calls:
        # 1) fetch invoice, 2) fetch existing credit notes,
        # 3) CN sequence SELECT FOR UPDATE, 4) CN sequence INSERT,
        # 5) fetch line items (after commit/refresh)
        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_list_r = MagicMock()
        cn_list_r.scalars.return_value.all.return_value = []
        seq_r = MagicMock()
        seq_r.first.return_value = None  # No sequence row yet
        li_r = MagicMock()
        li_r.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_r, cn_list_r, seq_r, None, li_r]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_credit_note(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
                reason="Overcharged",
                items=[{"description": "Service refund", "amount": "50.00"}],
            )

        assert result["credit_note"] is not None
        assert result["invoice"] is not None
        assert invoice.balance_due == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_create_credit_note_on_paid_invoice(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            total=Decimal("200.00"),
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )
        db = _mock_db()

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_list_r = MagicMock()
        cn_list_r.scalars.return_value.all.return_value = []
        seq_r = MagicMock()
        seq_r.first.return_value = None
        li_r = MagicMock()
        li_r.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_r, cn_list_r, seq_r, None, li_r]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_credit_note(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
                reason="Partial refund",
                items=[],
            )

        # balance_due was 0, credit of 50 → balance_due should be clamped to 0
        assert invoice.balance_due == Decimal("0")

    @pytest.mark.asyncio
    async def test_reject_credit_note_on_draft_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="draft")
        db = _mock_db()

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]

        with pytest.raises(ValueError, match="Cannot create credit note"):
            await create_credit_note(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("10.00"),
                reason="Test",
                items=[],
            )

    @pytest.mark.asyncio
    async def test_reject_credit_note_on_voided_invoice(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="voided")
        db = _mock_db()

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        db.execute.side_effect = [inv_r]

        with pytest.raises(ValueError, match="Cannot create credit note"):
            await create_credit_note(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("10.00"),
                reason="Test",
                items=[],
            )

    @pytest.mark.asyncio
    async def test_reject_over_credit(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued", total=Decimal("100.00"))
        db = _mock_db()

        # Existing credit note of 80
        existing_cn = _make_credit_note(org_id, invoice.id, amount=Decimal("80.00"))

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_list_r = MagicMock()
        cn_list_r.scalars.return_value.all.return_value = [existing_cn]
        db.execute.side_effect = [inv_r, cn_list_r]

        with pytest.raises(ValueError, match="exceeds maximum creditable amount"):
            await create_credit_note(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("30.00"),
                reason="Too much",
                items=[],
            )

    @pytest.mark.asyncio
    async def test_invoice_not_found_raises(self):
        db = _mock_db()
        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_r]

        with pytest.raises(ValueError, match="Invoice not found"):
            await create_credit_note(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                invoice_id=uuid.uuid4(),
                amount=Decimal("10.00"),
                reason="Test",
                items=[],
            )

    @pytest.mark.asyncio
    async def test_stripe_refund_prompted_when_stripe_payment_exists(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="paid",
                                total=Decimal("100.00"),
                                amount_paid=Decimal("100.00"),
                                balance_due=Decimal("0.00"))
        db = _mock_db()

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_list_r = MagicMock()
        cn_list_r.scalars.return_value.all.return_value = []
        seq_r = MagicMock()
        seq_r.first.return_value = None

        # Stripe payment exists
        stripe_payment = MagicMock(spec=Payment)
        stripe_payment.method = "stripe"
        stripe_payment.stripe_payment_intent_id = "pi_test123"
        stripe_r = MagicMock()
        stripe_r.scalars.return_value.all.return_value = [stripe_payment]

        li_r = MagicMock()
        li_r.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_r, cn_list_r, seq_r, None, stripe_r, li_r]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
            result = await create_credit_note(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("50.00"),
                reason="Refund needed",
                items=[],
                process_stripe_refund=True,
            )

        assert result["stripe_refund_prompted"] is True

    @pytest.mark.asyncio
    async def test_audit_log_written_on_credit_note(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, status="issued")
        db = _mock_db()

        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_list_r = MagicMock()
        cn_list_r.scalars.return_value.all.return_value = []
        seq_r = MagicMock()
        seq_r.first.return_value = None
        li_r = MagicMock()
        li_r.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_r, cn_list_r, seq_r, None, li_r]

        with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await create_credit_note(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("25.00"),
                reason="Correction",
                items=[],
            )

        mock_audit.assert_called_once()
        kw = mock_audit.call_args.kwargs
        assert kw["action"] == "credit_note.created"
        assert kw["entity_type"] == "credit_note"
        assert kw["after_value"]["reason"] == "Correction"
        assert kw["after_value"]["amount"] == "25.00"


# ---------------------------------------------------------------------------
# Service tests — get_credit_notes_for_invoice
# ---------------------------------------------------------------------------


class TestGetCreditNotesForInvoice:
    @pytest.mark.asyncio
    async def test_list_credit_notes(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        cn1 = _make_credit_note(org_id, invoice.id, amount=Decimal("30.00"), number="CN-0001")
        cn2 = _make_credit_note(org_id, invoice.id, amount=Decimal("20.00"), number="CN-0002")

        db = _mock_db()
        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_r = MagicMock()
        cn_r.scalars.return_value.all.return_value = [cn1, cn2]
        db.execute.side_effect = [inv_r, cn_r]

        result = await get_credit_notes_for_invoice(
            db, org_id=org_id, invoice_id=invoice.id
        )

        assert len(result["credit_notes"]) == 2
        assert result["total_credited"] == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_empty_credit_notes_list(self):
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)

        db = _mock_db()
        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = invoice
        cn_r = MagicMock()
        cn_r.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_r, cn_r]

        result = await get_credit_notes_for_invoice(
            db, org_id=org_id, invoice_id=invoice.id
        )

        assert len(result["credit_notes"]) == 0
        assert result["total_credited"] == 0

    @pytest.mark.asyncio
    async def test_invoice_not_found_raises(self):
        db = _mock_db()
        inv_r = MagicMock()
        inv_r.scalar_one_or_none.return_value = None
        db.execute.side_effect = [inv_r]

        with pytest.raises(ValueError, match="Invoice not found"):
            await get_credit_notes_for_invoice(
                db, org_id=uuid.uuid4(), invoice_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# CN numbering tests
# ---------------------------------------------------------------------------


class TestCreditNoteNumbering:
    @pytest.mark.asyncio
    async def test_first_credit_note_gets_cn_0001(self):
        db = _mock_db()
        seq_r = MagicMock()
        seq_r.first.return_value = None  # No sequence row
        db.execute.side_effect = [seq_r, None]  # SELECT, INSERT

        number = await _get_next_credit_note_number(db, uuid.uuid4())
        assert number == "CN-0001"

    @pytest.mark.asyncio
    async def test_increments_existing_sequence(self):
        db = _mock_db()
        seq_r = MagicMock()
        seq_r.first.return_value = MagicMock(id=uuid.uuid4(), last_number=5)
        db.execute.side_effect = [seq_r, None]  # SELECT FOR UPDATE, UPDATE

        number = await _get_next_credit_note_number(db, uuid.uuid4())
        assert number == "CN-0006"
