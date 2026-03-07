"""Unit tests for Task 10.8 — NZ tax invoice compliance.

Requirements: 80.1, 80.2, 80.3
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
from app.modules.customers.models import Customer
from app.modules.invoices.service import (
    validate_tax_invoice_compliance,
    get_line_item_tax_details,
    issue_invoice,
    NZ_HIGH_VALUE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_invoice(
    org_id=None,
    status="issued",
    total=Decimal("115.00"),
    gst_amount=Decimal("15.00"),
    issue_date=None,
    customer_id=None,
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = customer_id or uuid.uuid4()
    inv.status = status
    inv.invoice_number = "INV-0001" if status != "draft" else None
    inv.issue_date = issue_date or date.today()
    inv.due_date = date.today()
    inv.total = total
    inv.gst_amount = gst_amount
    inv.subtotal = (total - gst_amount) if total is not None and gst_amount is not None else Decimal("0.00")
    inv.discount_amount = Decimal("0.00")
    inv.discount_type = None
    inv.discount_value = None
    inv.currency = "NZD"
    inv.balance_due = total
    inv.amount_paid = Decimal("0.00")
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


def _make_line_item(
    invoice_id=None,
    description="WOF inspection",
    is_gst_exempt=False,
    line_total=Decimal("55.00"),
):
    li = MagicMock(spec=LineItem)
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id or uuid.uuid4()
    li.item_type = "service"
    li.description = description
    li.catalogue_item_id = None
    li.part_number = None
    li.quantity = Decimal("1")
    li.unit_price = line_total
    li.hours = None
    li.hourly_rate = None
    li.discount_type = None
    li.discount_value = None
    li.is_gst_exempt = is_gst_exempt
    li.warranty_note = None
    li.line_total = line_total
    li.sort_order = 0
    return li


def _make_customer(first_name="John", last_name="Doe", address="123 Main St, Auckland"):
    cust = MagicMock(spec=Customer)
    cust.id = uuid.uuid4()
    cust.first_name = first_name
    cust.last_name = last_name
    cust.address = address
    return cust


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_org(org_id, gst_number="123-456-789", name="Test Workshop"):
    org = MagicMock()
    org.id = org_id
    org.name = name
    org.settings = {
        "gst_number": gst_number,
        "gst_percentage": 15,
        "invoice_prefix": "INV-",
        "default_due_days": 14,
    }
    return org


# ---------------------------------------------------------------------------
# Req 80.1 — Mandatory fields on every tax invoice
# ---------------------------------------------------------------------------


class TestMandatoryTaxInvoiceFields:
    """Every issued invoice must include: 'Tax Invoice' label, supplier name +
    GST number, invoice date, description of goods/services, total incl. GST,
    GST amount."""

    def test_compliant_invoice_passes(self):
        inv = _make_invoice()
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is True
        assert result["issues"] == []
        assert result["document_label"] == "Tax Invoice"

    def test_missing_org_name_fails(self):
        inv = _make_invoice()
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name=None,
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "supplier_name" in fields

    def test_empty_org_name_fails(self):
        inv = _make_invoice()
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "supplier_name" in fields

    def test_missing_gst_number_fails(self):
        inv = _make_invoice()
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number=None,
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "gst_number" in fields

    def test_missing_issue_date_fails(self):
        inv = _make_invoice(issue_date=None)
        inv.issue_date = None
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "issue_date" in fields

    def test_no_line_items_fails(self):
        inv = _make_invoice()
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "line_items" in fields

    def test_empty_description_line_item_fails(self):
        inv = _make_invoice()
        li = _make_line_item(invoice_id=inv.id, description="")
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "line_items[0].description" in fields

    def test_missing_total_fails(self):
        inv = _make_invoice(total=None)
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "total" in fields

    def test_missing_gst_amount_fails(self):
        inv = _make_invoice(gst_amount=None)
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "gst_amount" in fields

    def test_all_issues_reported_together(self):
        """Multiple missing fields should all be reported in one call."""
        inv = _make_invoice(total=None, gst_amount=None, issue_date=None)
        inv.issue_date = None
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[],
            org_name=None,
            gst_number=None,
        )
        assert result["is_compliant"] is False
        assert len(result["issues"]) >= 5  # name, gst, date, items, total, gst_amount

    def test_requirement_field_populated(self):
        """Each issue should reference the requirement number."""
        inv = _make_invoice()
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[],
            org_name=None,
            gst_number=None,
        )
        for issue in result["issues"]:
            assert "requirement" in issue
            assert issue["requirement"] in ("80.1", "80.2")


# ---------------------------------------------------------------------------
# Req 80.2 — High-value invoices (>$1,000 NZD) need buyer details
# ---------------------------------------------------------------------------


class TestHighValueInvoiceBuyerDetails:
    """Invoices over $1,000 NZD (incl. GST) must include buyer name + address."""

    def test_under_threshold_no_buyer_required(self):
        inv = _make_invoice(total=Decimal("999.99"))
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is True
        assert result["is_high_value"] is False

    def test_exactly_threshold_not_high_value(self):
        inv = _make_invoice(total=Decimal("1000.00"))
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        # $1,000 exactly is NOT over the threshold
        assert result["is_high_value"] is False
        assert result["is_compliant"] is True

    def test_over_threshold_with_buyer_details_passes(self):
        inv = _make_invoice(total=Decimal("1500.00"))
        customer = _make_customer()
        inv._compliance_customer = customer
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is True
        assert result["is_high_value"] is True

    def test_over_threshold_missing_buyer_name_fails(self):
        inv = _make_invoice(total=Decimal("1500.00"))
        customer = _make_customer(first_name="", last_name="")
        inv._compliance_customer = customer
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "customer_name" in fields

    def test_over_threshold_missing_buyer_address_fails(self):
        inv = _make_invoice(total=Decimal("1500.00"))
        customer = _make_customer(address=None)
        inv._compliance_customer = customer
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        fields = [i["field"] for i in result["issues"]]
        assert "customer_address" in fields

    def test_over_threshold_no_customer_object_fails(self):
        inv = _make_invoice(total=Decimal("1500.00"))
        # No _compliance_customer set
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        assert result["is_compliant"] is False
        assert result["is_high_value"] is True
        fields = [i["field"] for i in result["issues"]]
        assert "customer_name" in fields
        assert "customer_address" in fields

    def test_high_value_issues_reference_req_80_2(self):
        inv = _make_invoice(total=Decimal("2000.00"))
        li = _make_line_item(invoice_id=inv.id)
        result = validate_tax_invoice_compliance(
            invoice=inv,
            line_items=[li],
            org_name="Test Workshop",
            gst_number="123-456-789",
        )
        for issue in result["issues"]:
            assert issue["requirement"] == "80.2"


# ---------------------------------------------------------------------------
# Req 80.3 — Distinguish taxable vs GST-exempt line items
# ---------------------------------------------------------------------------


class TestLineItemTaxDetails:
    """Line items must be clearly distinguished as taxable or GST-exempt."""

    def test_taxable_item_has_gst(self):
        li = _make_line_item(line_total=Decimal("100.00"), is_gst_exempt=False)
        details = get_line_item_tax_details([li], Decimal("15"))
        assert len(details) == 1
        d = details[0]
        assert d["is_gst_exempt"] is False
        assert d["gst_amount"] == Decimal("15.00")
        assert d["tax_label"] == "GST 15%"

    def test_exempt_item_has_zero_gst(self):
        li = _make_line_item(line_total=Decimal("100.00"), is_gst_exempt=True)
        details = get_line_item_tax_details([li], Decimal("15"))
        assert len(details) == 1
        d = details[0]
        assert d["is_gst_exempt"] is True
        assert d["gst_amount"] == Decimal("0.00")
        assert d["tax_label"] == "GST Exempt"

    def test_mixed_items_distinguished(self):
        li_taxable = _make_line_item(
            description="Oil change", line_total=Decimal("80.00"), is_gst_exempt=False
        )
        li_exempt = _make_line_item(
            description="Insurance admin fee", line_total=Decimal("50.00"), is_gst_exempt=True
        )
        details = get_line_item_tax_details([li_taxable, li_exempt], Decimal("15"))
        assert len(details) == 2
        assert details[0]["tax_label"] == "GST 15%"
        assert details[0]["gst_amount"] == Decimal("12.00")
        assert details[1]["tax_label"] == "GST Exempt"
        assert details[1]["gst_amount"] == Decimal("0.00")

    def test_custom_gst_percentage(self):
        li = _make_line_item(line_total=Decimal("200.00"), is_gst_exempt=False)
        details = get_line_item_tax_details([li], Decimal("9"))
        d = details[0]
        assert d["gst_amount"] == Decimal("18.00")
        assert d["tax_label"] == "GST 9%"

    def test_empty_line_items(self):
        details = get_line_item_tax_details([], Decimal("15"))
        assert details == []

    def test_detail_includes_description_and_id(self):
        li = _make_line_item(description="Brake pad replacement")
        details = get_line_item_tax_details([li], Decimal("15"))
        d = details[0]
        assert d["description"] == "Brake pad replacement"
        assert d["line_item_id"] == li.id


# ---------------------------------------------------------------------------
# Integration: issue_invoice enforces compliance
# ---------------------------------------------------------------------------


class TestIssueInvoiceComplianceIntegration:
    """issue_invoice should reject invoices that fail NZ tax compliance."""

    @pytest.mark.asyncio
    async def test_issue_rejects_missing_gst_number(self):
        """Issuing an invoice without org GST number should raise ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        inv = _make_invoice(org_id=org_id, status="draft")
        inv.invoice_number = None
        inv.issue_date = None
        li = _make_line_item(invoice_id=inv.id)

        org = _make_org(org_id, gst_number=None, name="Test Workshop")

        customer = _make_customer()

        db = _mock_db()

        # Setup execute returns: invoice, org, line_items, customer
        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # invoice lookup
                result.scalar_one_or_none.return_value = inv
            elif call_count == 2:  # org lookup
                result.scalar_one_or_none.return_value = org
            elif call_count == 3:  # line items
                result.scalars.return_value.all.return_value = [li]
            elif call_count == 4:  # customer lookup
                result.scalar_one_or_none.return_value = customer
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        with patch("app.modules.invoices.service._get_next_invoice_number", new_callable=AsyncMock, return_value="INV-0001"):
            with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
                with pytest.raises(ValueError, match="NZ tax invoice requirements"):
                    await issue_invoice(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        invoice_id=inv.id,
                    )

    @pytest.mark.asyncio
    async def test_issue_rejects_high_value_without_buyer_address(self):
        """Issuing a >$1,000 invoice without buyer address should raise ValueError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        inv = _make_invoice(
            org_id=org_id,
            status="draft",
            total=Decimal("1500.00"),
            gst_amount=Decimal("195.65"),
        )
        inv.invoice_number = None
        inv.issue_date = None
        li = _make_line_item(invoice_id=inv.id, line_total=Decimal("1304.35"))

        org = _make_org(org_id)
        customer = _make_customer(address=None)  # Missing address

        db = _mock_db()

        call_count = 0
        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = inv
            elif call_count == 2:
                result.scalar_one_or_none.return_value = org
            elif call_count == 3:
                result.scalars.return_value.all.return_value = [li]
            elif call_count == 4:
                result.scalar_one_or_none.return_value = customer
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        with patch("app.modules.invoices.service._get_next_invoice_number", new_callable=AsyncMock, return_value="INV-0001"):
            with patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock):
                with pytest.raises(ValueError, match="NZ tax invoice requirements"):
                    await issue_invoice(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        invoice_id=inv.id,
                    )
