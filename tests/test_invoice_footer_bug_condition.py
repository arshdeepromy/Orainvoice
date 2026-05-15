"""Bug condition exploration test — Hardcoded Footer Text in PDF Templates.

This test encodes the EXPECTED behavior for the invoice PDF footer.
On UNFIXED code, these tests FAIL — proving the bug exists.
After the fix, these tests PASS — confirming the bug is resolved.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**

Bug condition tested:
  All 14 PDF invoice templates output hardcoded "Thank you for your business."
  and conditional bank transfer instructions regardless of the configurable
  `invoice_footer_text` org setting. The `org.invoice_footer` variable is
  rendered alongside hardcoded text rather than instead of it.

Property 1: Bug Condition — Hardcoded Footer Text in PDF Templates
  For any `invoice_footer_text` value (custom text, empty, None):
    - The rendered footer SHALL NOT contain "Thank you for your business."
    - The rendered footer SHALL NOT contain "Payments can be paid by direct bank transfer"
  For non-empty `invoice_footer_text`:
    - The rendered footer SHALL CONTAIN the custom text
  For empty/None `invoice_footer_text`:
    - The rendered footer SHALL contain NO text content in the footer area
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from jinja2 import Environment, FileSystemLoader

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

# Generate random invoice_footer_text values: custom text, empty string, or None
invoice_footer_text_st = st.one_of(
    st.none(),
    st.just(""),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            blacklist_characters="\x00",
        ),
        min_size=1,
        max_size=200,
    ),
)

# Non-empty footer text for the "custom text must appear" property
non_empty_footer_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_jinja_env() -> Environment:
    """Create a Jinja2 environment matching the one used by generate_invoice_pdf()."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )

    # Add the pdfdate filter (used in payment history section)
    def _pdf_format_date(value):
        if value is None:
            return ""
        return str(value)

    env.filters["pdfdate"] = _pdf_format_date
    return env


def _minimal_invoice_context() -> dict:
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
        "notes_customer": None,
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


def _render_base_template(invoice_footer_text: str | None, gst_number: str | None = "123-456-789") -> str:
    """Render the _invoice_base.html template with the given footer text."""
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
        invoice=_minimal_invoice_context(),
        org=org_ctx,
        customer=_minimal_customer_context(),
        colours=colours_ctx,
        currency_symbol="$",
        gst_percentage=15,
        payment_terms=None,
        terms_and_conditions=None,
    )


def _extract_footer_section(html: str) -> str:
    """Extract the footer section from rendered HTML.

    The footer is the last block in the template, wrapped in a div with
    border-top styling after the terms_and_conditions block.
    """
    # The footer block starts after the last section (terms & conditions)
    # and is identifiable by the border-top:1px solid #eee pattern
    import re

    # Find the footer div - it's the div with border-top:1px solid #eee and text-align:center
    footer_pattern = r'<div style="margin-top:24px; padding-top:10px; border-top:1px solid #eee; text-align:center;">(.*?)</div>\s*</body>'
    match = re.search(footer_pattern, html, re.DOTALL)
    if match:
        return match.group(1)
    # Fallback: look for any footer-text class content near end of document
    return html


# ---------------------------------------------------------------------------
# Property 1: Bug Condition — No Hardcoded Footer Text
# ---------------------------------------------------------------------------


class TestInvoiceFooterBugCondition:
    """Property 1: Bug Condition — Hardcoded Footer Text in PDF Templates.

    **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3**

    For any `invoice_footer_text` value (custom text, empty, None), the
    rendered PDF footer SHALL NOT contain hardcoded "Thank you for your
    business." or "Payments can be paid by direct bank transfer" text.
    """

    @PBT_SETTINGS
    @given(footer_text=invoice_footer_text_st)
    def test_footer_does_not_contain_hardcoded_thank_you(self, footer_text: str | None):
        """For any invoice_footer_text value, the footer SHALL NOT contain
        hardcoded 'Thank you for your business.' text.

        **Validates: Requirements 2.1, 2.2**
        """
        html = _render_base_template(footer_text)
        footer = _extract_footer_section(html)

        assert "Thank you for your business." not in footer, (
            f"Footer contains hardcoded 'Thank you for your business.' "
            f"when invoice_footer_text={footer_text!r}"
        )

    @PBT_SETTINGS
    @given(footer_text=invoice_footer_text_st)
    def test_footer_does_not_contain_hardcoded_bank_transfer(self, footer_text: str | None):
        """For any invoice_footer_text value, the footer SHALL NOT contain
        hardcoded bank transfer instructions.

        **Validates: Requirements 2.1, 2.2**
        """
        html = _render_base_template(footer_text, gst_number="123-456-789")
        footer = _extract_footer_section(html)

        assert "Payments can be paid by direct bank transfer" not in footer, (
            f"Footer contains hardcoded bank transfer text "
            f"when invoice_footer_text={footer_text!r}"
        )

    @PBT_SETTINGS
    @given(footer_text=non_empty_footer_text_st)
    def test_custom_footer_text_appears_in_footer(self, footer_text: str):
        """For non-empty invoice_footer_text, the rendered footer SHALL
        CONTAIN the custom text.

        **Validates: Requirements 2.3**
        """
        assume(footer_text.strip())  # Ensure non-whitespace-only
        html = _render_base_template(footer_text)
        footer = _extract_footer_section(html)

        # Jinja2 autoescaping will escape HTML entities, so we need to check
        # for the escaped version
        from markupsafe import escape

        escaped_text = str(escape(footer_text))
        assert escaped_text in footer, (
            f"Footer does not contain custom text {footer_text!r} "
            f"(escaped: {escaped_text!r})"
        )

    @PBT_SETTINGS
    @given(footer_text=st.one_of(st.none(), st.just("")))
    def test_empty_footer_has_no_text_content(self, footer_text: str | None):
        """For empty/None invoice_footer_text, the rendered footer SHALL
        contain NO text content (no hardcoded text, no custom text).

        **Validates: Requirements 1.3, 2.1**
        """
        html = _render_base_template(footer_text, gst_number=None)
        footer = _extract_footer_section(html)

        # Strip HTML tags and whitespace to check for any text content
        import re

        text_only = re.sub(r"<[^>]+>", "", footer).strip()
        assert text_only == "", (
            f"Footer contains text content when invoice_footer_text is "
            f"{footer_text!r}: found {text_only!r}"
        )
