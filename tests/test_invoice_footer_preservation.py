"""Preservation property tests — Non-Footer Sections and Custom Footer Rendering.

These tests capture EXISTING CORRECT behavior on the UNFIXED code.
They MUST PASS on unfixed code (confirming baseline behavior to preserve).
After the fix is applied, they MUST STILL PASS (confirming no regressions).

**Validates: Requirements 3.1, 3.2, 3.5, 3.6**

Property 2: Preservation — Non-Footer Sections and Custom Footer Rendering Unchanged
  - For all non-empty `invoice_footer_text` strings, the `{% if org.invoice_footer %}`
    conditional renders the custom text in the footer area
  - For all invoice data with `notes_customer` content, the notes section renders unchanged
  - For all invoice data with `payment_terms_text` content, the payment terms section
    above footer renders unchanged
"""

from __future__ import annotations

import re
from pathlib import Path

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from jinja2 import Environment, FileSystemLoader
from markupsafe import escape

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "app" / "templates" / "pdf"

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty text for custom footer (printable characters, no null bytes)
non_empty_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=200,
)

# Notes text strategy
notes_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=500,
)

# Payment terms text strategy
payment_terms_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=300,
)


# ---------------------------------------------------------------------------
# Helpers (reused from test_invoice_footer_bug_condition.py)
# ---------------------------------------------------------------------------


def _build_jinja_env() -> Environment:
    """Create a Jinja2 environment matching the one used by generate_invoice_pdf()."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )

    def _pdf_format_date(value):
        if value is None:
            return ""
        return str(value)

    env.filters["pdfdate"] = _pdf_format_date
    return env


def _minimal_invoice_context(
    notes_customer: str | None = None,
) -> dict:
    """Return a minimal invoice context sufficient to render the base template."""
    return {
        "invoice_number": "INV-TEST-001",
        "balance_due": 100.00,
        "subtotal": 86.96,
        "gst_amount": 13.04,
        "total": 100.00,
        "status": "sent",
        "line_items": [
            {
                "description": "Test service",
                "quantity": 1,
                "unit_price": 86.96,
                "line_total": 86.96,
                "item_type": "service",
            }
        ],
        "issue_date": "2024-06-15",
        "due_date": "2024-07-15",
        "payment_terms": "net_30",
        "notes_customer": notes_customer,
        "vehicle": None,
        "vehicle_rego": None,
        "additional_vehicles": [],
        "payments": [],
        "amount_paid": 0,
        "discount_amount": 0,
    }


def _minimal_customer_context() -> dict:
    """Return a minimal customer context."""
    return {
        "display_name": "Test Customer",
        "first_name": "Test",
        "last_name": "Customer",
        "company_name": None,
        "billing_address": "123 Test St",
        "address": "123 Test St",
        "email": "test@example.com",
        "phone": "021-555-0000",
    }


def _render_base_template(
    invoice_footer_text: str | None = None,
    notes_customer: str | None = None,
    payment_terms_text: str | None = None,
    terms_and_conditions: str | None = None,
    gst_number: str | None = "123-456-789",
) -> str:
    """Render the _invoice_base.html template with the given context."""
    env = _build_jinja_env()
    template = env.get_template("_invoice_base.html")

    org_ctx = {
        "name": "Test Workshop Ltd",
        "logo_url": None,
        "address_street": "123 Main St",
        "address_city": "Auckland",
        "address_state": None,
        "address_postcode": "1010",
        "address_country": "New Zealand",
        "address_unit": None,
        "address": None,
        "phone": "09-555-1234",
        "email": "info@test.co.nz",
        "website": "https://test.co.nz",
        "gst_number": gst_number,
        "invoice_footer": invoice_footer_text,
    }

    colours_ctx = {
        "primary_colour": "#2563eb",
        "accent_colour": "#1e40af",
        "header_bg_colour": "#ffffff",
    }

    return template.render(
        invoice=_minimal_invoice_context(notes_customer=notes_customer),
        org=org_ctx,
        customer=_minimal_customer_context(),
        colours=colours_ctx,
        currency_symbol="$",
        gst_percentage=15,
        payment_terms=payment_terms_text,
        terms_and_conditions=terms_and_conditions,
    )


def _extract_footer_section(html: str) -> str:
    """Extract the footer section from rendered HTML.

    The footer is the last block in the template, wrapped in a div with
    border-top styling after the terms_and_conditions block.
    """
    footer_pattern = r'<div style="margin-top:24px; padding-top:10px; border-top:1px solid #eee; text-align:center;">(.*?)</div>\s*</body>'
    match = re.search(footer_pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    return html


def _extract_notes_section(html: str) -> str:
    """Extract the notes section from rendered HTML."""
    # The notes section has a section-title "Notes" followed by a paragraph
    notes_pattern = r'<div class="section-title">Notes</div>\s*<p[^>]*>(.*?)</p>'
    match = re.search(notes_pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    return ""


def _extract_payment_terms_section(html: str) -> str:
    """Extract the payment terms section from rendered HTML."""
    # The payment terms section has a section-title "Payment Terms" followed by a paragraph
    pt_pattern = r'<div class="section-title">Payment Terms</div>\s*<p[^>]*>(.*?)</p>'
    match = re.search(pt_pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# Property 2: Preservation — Custom Footer Text Renders in Footer Area
# ---------------------------------------------------------------------------


class TestCustomFooterPreservation:
    """Property 2a: For all non-empty invoice_footer_text strings, the
    {% if org.invoice_footer %} conditional renders the custom text in the
    footer area.

    **Validates: Requirements 3.1, 3.2**

    This captures existing correct behavior: when org.invoice_footer is set,
    the custom text appears in the footer div. This must remain true after fix.
    """

    @PBT_SETTINGS
    @given(footer_text=non_empty_text_st)
    def test_custom_footer_text_rendered_in_footer(self, footer_text: str):
        """For all non-empty invoice_footer_text, the custom text SHALL appear
        in the rendered footer area.

        **Validates: Requirements 3.1**
        """
        assume(footer_text.strip())  # Ensure non-whitespace-only

        html = _render_base_template(invoice_footer_text=footer_text)
        footer = _extract_footer_section(html)

        # Jinja2 autoescaping will escape HTML entities
        escaped_text = str(escape(footer_text))
        assert escaped_text in footer, (
            f"Custom footer text not found in footer area. "
            f"Expected {footer_text!r} (escaped: {escaped_text!r}) "
            f"to appear in footer section."
        )


# ---------------------------------------------------------------------------
# Property 2: Preservation — Notes Section Renders Unchanged
# ---------------------------------------------------------------------------


class TestNotesPreservation:
    """Property 2b: For all invoice data with notes_customer content, the
    notes section renders unchanged.

    **Validates: Requirements 3.2, 3.6**

    This captures existing correct behavior: when notes_customer is set,
    the Notes section appears with the content. This must remain true after fix.
    """

    @PBT_SETTINGS
    @given(notes=notes_text_st)
    def test_notes_section_renders_when_content_present(self, notes: str):
        """For all non-empty notes_customer content, the Notes section SHALL
        render with the notes text.

        **Validates: Requirements 3.2**
        """
        assume(notes.strip())  # Ensure non-whitespace-only

        html = _render_base_template(notes_customer=notes)

        # The notes section title must be present
        assert "Notes</div>" in html, (
            f"Notes section title not found in rendered HTML "
            f"when notes_customer={notes!r}"
        )

        # The notes content must appear (escaped by Jinja2 autoescape)
        escaped_notes = str(escape(notes))
        notes_section = _extract_notes_section(html)
        assert escaped_notes in notes_section, (
            f"Notes content not found in notes section. "
            f"Expected {notes!r} (escaped: {escaped_notes!r}) "
            f"to appear in notes section."
        )

    @PBT_SETTINGS
    @given(notes=notes_text_st, footer_text=non_empty_text_st)
    def test_notes_section_independent_of_footer(self, notes: str, footer_text: str):
        """Notes section renders regardless of what footer text is configured.

        **Validates: Requirements 3.6**
        """
        assume(notes.strip())
        assume(footer_text.strip())

        html = _render_base_template(
            invoice_footer_text=footer_text,
            notes_customer=notes,
        )

        # Notes section must still render
        escaped_notes = str(escape(notes))
        notes_section = _extract_notes_section(html)
        assert escaped_notes in notes_section, (
            f"Notes content not found when footer text is also set. "
            f"notes={notes!r}, footer_text={footer_text!r}"
        )


# ---------------------------------------------------------------------------
# Property 2: Preservation — Payment Terms Section Renders Unchanged
# ---------------------------------------------------------------------------


class TestPaymentTermsPreservation:
    """Property 2c: For all invoice data with payment_terms_text content, the
    payment terms section above footer renders unchanged.

    **Validates: Requirements 3.5, 3.6**

    This captures existing correct behavior: when payment_terms is set,
    the Payment Terms section appears above the footer. This must remain
    true after fix.
    """

    @PBT_SETTINGS
    @given(pt_text=payment_terms_text_st)
    def test_payment_terms_section_renders_when_content_present(self, pt_text: str):
        """For all non-empty payment_terms_text content, the Payment Terms
        section SHALL render with the payment terms text.

        **Validates: Requirements 3.5**
        """
        assume(pt_text.strip())  # Ensure non-whitespace-only

        html = _render_base_template(payment_terms_text=pt_text)

        # The payment terms section title must be present
        assert "Payment Terms</div>" in html, (
            f"Payment Terms section title not found in rendered HTML "
            f"when payment_terms_text={pt_text!r}"
        )

        # The payment terms content must appear (escaped by Jinja2 autoescape)
        escaped_pt = str(escape(pt_text))
        pt_section = _extract_payment_terms_section(html)
        assert escaped_pt in pt_section, (
            f"Payment terms content not found in payment terms section. "
            f"Expected {pt_text!r} (escaped: {escaped_pt!r}) "
            f"to appear in payment terms section."
        )

    @PBT_SETTINGS
    @given(pt_text=payment_terms_text_st, footer_text=non_empty_text_st)
    def test_payment_terms_section_independent_of_footer(self, pt_text: str, footer_text: str):
        """Payment terms section renders regardless of what footer text is configured.

        **Validates: Requirements 3.6**
        """
        assume(pt_text.strip())
        assume(footer_text.strip())

        html = _render_base_template(
            invoice_footer_text=footer_text,
            payment_terms_text=pt_text,
        )

        # Payment terms section must still render
        escaped_pt = str(escape(pt_text))
        pt_section = _extract_payment_terms_section(html)
        assert escaped_pt in pt_section, (
            f"Payment terms content not found when footer text is also set. "
            f"pt_text={pt_text!r}, footer_text={footer_text!r}"
        )
