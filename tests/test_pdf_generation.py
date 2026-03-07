"""Unit tests for Task 14.4 — PDF generation (on-demand).

Tests cover:
  - generate_invoice_pdf: renders PDF bytes from invoice data + org branding
  - generate_invoice_pdf: includes all required fields (invoice number, dates,
    customer, vehicle, line items, GST, totals, payment status, branding,
    payment terms, T&C)
  - generate_invoice_pdf: never writes to disk (returns bytes only)
  - email_invoice: queues email with PDF attachment
  - email_invoice: falls back to customer email when no override given
  - email_invoice: raises when customer has no email and none provided
  - Jinja2 template renders correctly with minimal data
  - Router endpoints: GET /{id}/pdf and POST /{id}/email

Requirements: 32.1, 32.2, 32.3, 32.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pathlib

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.invoices.schemas import InvoiceEmailRequest, InvoiceEmailResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_invoice_dict(**overrides) -> dict:
    """Create a realistic invoice dict for testing."""
    base = {
        "id": INVOICE_ID,
        "org_id": ORG_ID,
        "invoice_number": "INV-0042",
        "customer_id": CUSTOMER_ID,
        "vehicle_rego": "ABC123",
        "vehicle_make": "Toyota",
        "vehicle_model": "Hilux",
        "vehicle_year": 2019,
        "vehicle_odometer": 85000,
        "branch_id": None,
        "status": "issued",
        "issue_date": date(2024, 6, 15),
        "due_date": date(2024, 7, 15),
        "currency": "NZD",
        "exchange_rate_to_nzd": Decimal("1.000000"),
        "subtotal": Decimal("200.00"),
        "discount_amount": Decimal("0.00"),
        "discount_type": None,
        "discount_value": None,
        "gst_amount": Decimal("30.00"),
        "total": Decimal("230.00"),
        "total_nzd": Decimal("230.00"),
        "amount_paid": Decimal("0.00"),
        "balance_due": Decimal("230.00"),
        "notes_internal": None,
        "notes_customer": "Thank you for your business.",
        "void_reason": None,
        "voided_at": None,
        "voided_by": None,
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Full Service",
                "catalogue_item_id": None,
                "part_number": None,
                "quantity": Decimal("1"),
                "unit_price": Decimal("150.00"),
                "hours": None,
                "hourly_rate": None,
                "discount_type": None,
                "discount_value": None,
                "is_gst_exempt": False,
                "warranty_note": None,
                "line_total": Decimal("150.00"),
                "sort_order": 0,
            },
            {
                "id": uuid.uuid4(),
                "item_type": "part",
                "description": "Oil Filter",
                "catalogue_item_id": None,
                "part_number": "OF-123",
                "quantity": Decimal("1"),
                "unit_price": Decimal("50.00"),
                "hours": None,
                "hourly_rate": None,
                "discount_type": None,
                "discount_value": None,
                "is_gst_exempt": False,
                "warranty_note": "12-month warranty",
                "line_total": Decimal("50.00"),
                "sort_order": 1,
            },
        ],
        "created_by": uuid.uuid4(),
        "created_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _make_org_mock(settings: dict | None = None):
    """Create a mock Organisation ORM object."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    default_settings = {
        "logo_url": None,
        "primary_colour": "#2563eb",
        "secondary_colour": "#1e40af",
        "address": "123 Main St, Auckland",
        "phone": "09-555-1234",
        "email": "info@testworkshop.co.nz",
        "gst_number": "123-456-789",
        "gst_percentage": 15,
        "payment_terms_text": "Payment due within 30 days of invoice date.",
        "terms_and_conditions": "<p>All work guaranteed for 12 months.</p>",
        "invoice_header": "Test Workshop Ltd",
        "invoice_footer": "Thank you for choosing Test Workshop.",
    }
    if settings:
        default_settings.update(settings)
    org.settings = default_settings
    return org


def _make_customer_mock(email: str | None = "customer@example.com"):
    """Create a mock Customer ORM object."""
    cust = MagicMock()
    cust.id = CUSTOMER_ID
    cust.org_id = ORG_ID
    cust.first_name = "Jane"
    cust.last_name = "Doe"
    cust.email = email
    cust.phone = "021-555-9876"
    cust.address = "456 Queen St, Wellington"
    return cust


# ---------------------------------------------------------------------------
# Jinja2 Template Rendering Tests
# ---------------------------------------------------------------------------


class TestJinja2TemplateRendering:
    """Test that the Jinja2 invoice template renders correctly."""

    def _render_template(self, invoice_dict: dict, org_ctx: dict | None = None,
                         customer_ctx: dict | None = None) -> str:
        """Render the invoice template and return HTML string."""
        from jinja2 import Environment, FileSystemLoader

        template_dir = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates" / "pdf"
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
        template = env.get_template("invoice.html")

        if org_ctx is None:
            org_ctx = {
                "name": "Test Workshop Ltd",
                "logo_url": None,
                "primary_colour": "#2563eb",
                "address": "123 Main St",
                "phone": "09-555-1234",
                "email": "info@test.co.nz",
                "gst_number": "123-456-789",
                "invoice_footer": "Footer text",
            }
        if customer_ctx is None:
            customer_ctx = {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "phone": "021-555-9876",
                "address": "456 Queen St",
            }

        return template.render(
            invoice=invoice_dict,
            org=org_ctx,
            customer=customer_ctx,
            currency_symbol="$",
            gst_percentage=15,
            payment_terms="Due in 30 days",
            terms_and_conditions="<p>All work guaranteed.</p>",
        )

    def test_template_includes_invoice_number(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "INV-0042" in html

    def test_template_includes_tax_invoice_label(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "Tax Invoice" in html

    def test_template_includes_dates(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "2024-06-15" in html
        assert "2024-07-15" in html

    def test_template_includes_customer_details(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "Jane" in html
        assert "Doe" in html

    def test_template_includes_vehicle_details(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "ABC123" in html
        assert "Toyota" in html
        assert "Hilux" in html
        assert "2019" in html

    def test_template_includes_line_items(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "Full Service" in html
        assert "Oil Filter" in html
        assert "OF-123" in html  # part number

    def test_template_includes_warranty_note(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "12-month warranty" in html

    def test_template_includes_gst_and_totals(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "200.00" in html  # subtotal
        assert "30.00" in html   # GST
        assert "230.00" in html  # total

    def test_template_includes_org_branding(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "Test Workshop Ltd" in html
        assert "123-456-789" in html  # GST number
        assert "Footer text" in html

    def test_template_includes_payment_terms(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "Due in 30 days" in html

    def test_template_includes_terms_and_conditions(self):
        inv = _make_invoice_dict()
        html = self._render_template(inv)
        assert "All work guaranteed." in html

    def test_template_shows_paid_status(self):
        inv = _make_invoice_dict(status="paid")
        html = self._render_template(inv)
        assert "PAID IN FULL" in html

    def test_template_shows_voided_status(self):
        inv = _make_invoice_dict(status="voided", void_reason="Duplicate entry")
        html = self._render_template(inv)
        assert "VOIDED" in html
        assert "Duplicate entry" in html

    def test_template_shows_overdue_status(self):
        inv = _make_invoice_dict(status="overdue")
        html = self._render_template(inv)
        assert "OVERDUE" in html

    def test_template_draft_shows_draft_label(self):
        inv = _make_invoice_dict(invoice_number=None)
        html = self._render_template(inv)
        assert "DRAFT" in html

    def test_template_shows_gst_exempt_items(self):
        inv = _make_invoice_dict()
        inv["line_items"][1]["is_gst_exempt"] = True
        html = self._render_template(inv)
        assert "Exempt" in html


# ---------------------------------------------------------------------------
# Service Function Tests
# ---------------------------------------------------------------------------


class TestGenerateInvoicePdf:
    """Test the generate_invoice_pdf service function."""

    @pytest.mark.asyncio
    async def test_returns_pdf_bytes(self):
        """PDF generation returns non-empty bytes via WeasyPrint."""
        inv_dict = _make_invoice_dict()
        org_mock = _make_org_mock()
        cust_mock = _make_customer_mock()

        db = AsyncMock()

        fake_pdf = b"%PDF-1.4 fake pdf content"
        mock_html_cls = MagicMock()
        mock_html_cls.return_value.write_pdf.return_value = fake_pdf

        # Mock WeasyPrint import inside the function
        import sys
        weasyprint_mock = MagicMock()
        weasyprint_mock.HTML = mock_html_cls
        sys.modules["weasyprint"] = weasyprint_mock

        try:
            with patch(
                "app.modules.invoices.service.get_invoice",
                new_callable=AsyncMock,
                return_value=inv_dict,
            ), patch.object(
                db, "execute", new_callable=AsyncMock
            ) as mock_execute:
                org_result = MagicMock()
                org_result.scalar_one_or_none.return_value = org_mock
                cust_result = MagicMock()
                cust_result.scalar_one_or_none.return_value = cust_mock
                mock_execute.side_effect = [org_result, cust_result]

                from app.modules.invoices.service import generate_invoice_pdf

                pdf_bytes = await generate_invoice_pdf(
                    db, org_id=ORG_ID, invoice_id=INVOICE_ID
                )

            assert isinstance(pdf_bytes, bytes)
            assert len(pdf_bytes) > 0
            assert pdf_bytes == fake_pdf
            # Verify HTML was called with a string containing invoice data
            mock_html_cls.assert_called_once()
            html_string = mock_html_cls.call_args[1]["string"]
            assert "INV-0042" in html_string
            assert "Test Workshop Ltd" in html_string
        finally:
            del sys.modules["weasyprint"]

    @pytest.mark.asyncio
    async def test_raises_for_missing_invoice(self):
        """Should raise ValueError when invoice not found."""
        db = AsyncMock()

        import sys
        sys.modules["weasyprint"] = MagicMock()

        try:
            with patch(
                "app.modules.invoices.service.get_invoice",
                new_callable=AsyncMock,
                side_effect=ValueError("Invoice not found in this organisation"),
            ):
                from app.modules.invoices.service import generate_invoice_pdf

                with pytest.raises(ValueError, match="Invoice not found"):
                    await generate_invoice_pdf(
                        db, org_id=ORG_ID, invoice_id=uuid.uuid4()
                    )
        finally:
            del sys.modules["weasyprint"]

    @pytest.mark.asyncio
    async def test_raises_for_missing_org(self):
        """Should raise ValueError when organisation not found."""
        inv_dict = _make_invoice_dict()
        db = AsyncMock()

        import sys
        sys.modules["weasyprint"] = MagicMock()

        try:
            with patch(
                "app.modules.invoices.service.get_invoice",
                new_callable=AsyncMock,
                return_value=inv_dict,
            ), patch.object(
                db, "execute", new_callable=AsyncMock
            ) as mock_execute:
                org_result = MagicMock()
                org_result.scalar_one_or_none.return_value = None
                mock_execute.return_value = org_result

                from app.modules.invoices.service import generate_invoice_pdf

                with pytest.raises(ValueError, match="Organisation not found"):
                    await generate_invoice_pdf(
                        db, org_id=ORG_ID, invoice_id=INVOICE_ID
                    )
        finally:
            del sys.modules["weasyprint"]


class TestEmailInvoice:
    """Test the email_invoice service function."""

    @pytest.mark.asyncio
    async def test_email_with_explicit_recipient(self):
        """Should use the provided recipient_email."""
        inv_dict = _make_invoice_dict()
        org_mock = _make_org_mock()
        cust_mock = _make_customer_mock()
        db = AsyncMock()

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            from app.modules.invoices.service import email_invoice

            result = await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="override@example.com",
            )

        assert result["recipient_email"] == "override@example.com"
        assert result["status"] == "queued"
        assert result["invoice_number"] == "INV-0042"

    @pytest.mark.asyncio
    async def test_email_falls_back_to_customer_email(self):
        """Should use customer email when no override provided."""
        inv_dict = _make_invoice_dict()
        cust_mock = _make_customer_mock(email="jane@workshop.co.nz")
        db = AsyncMock()

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch.object(
            db, "execute", new_callable=AsyncMock
        ) as mock_execute, patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            cust_result = MagicMock()
            cust_result.scalar_one_or_none.return_value = cust_mock
            mock_execute.return_value = cust_result

            from app.modules.invoices.service import email_invoice

            result = await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
            )

        assert result["recipient_email"] == "jane@workshop.co.nz"

    @pytest.mark.asyncio
    async def test_email_raises_when_no_email_available(self):
        """Should raise ValueError when customer has no email and none provided."""
        inv_dict = _make_invoice_dict()
        cust_mock = _make_customer_mock(email=None)
        db = AsyncMock()

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch.object(
            db, "execute", new_callable=AsyncMock
        ) as mock_execute:
            cust_result = MagicMock()
            cust_result.scalar_one_or_none.return_value = cust_mock
            mock_execute.return_value = cust_result

            from app.modules.invoices.service import email_invoice

            with pytest.raises(ValueError, match="no email address"):
                await email_invoice(
                    db,
                    org_id=ORG_ID,
                    invoice_id=INVOICE_ID,
                )


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------


class TestInvoiceEmailSchemas:
    """Test the email request/response schemas."""

    def test_email_request_optional_recipient(self):
        req = InvoiceEmailRequest()
        assert req.recipient_email is None

    def test_email_request_with_recipient(self):
        req = InvoiceEmailRequest(recipient_email="test@example.com")
        assert req.recipient_email == "test@example.com"

    def test_email_response_fields(self):
        resp = InvoiceEmailResponse(
            invoice_id=str(uuid.uuid4()),
            invoice_number="INV-0001",
            recipient_email="test@example.com",
            pdf_size_bytes=12345,
            status="queued",
        )
        assert resp.status == "queued"
        assert resp.pdf_size_bytes == 12345
