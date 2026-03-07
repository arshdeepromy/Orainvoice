"""Right-to-left (RTL) support utilities.

Provides CSS direction helpers and RTL-aware PDF layout configuration
for Arabic and other RTL locales.

**Validates: Requirement 32.8**
"""

from __future__ import annotations

from app.core.i18n import RTL_LOCALES


def is_rtl_locale(locale: str) -> bool:
    """Check if the given locale uses right-to-left text direction."""
    return locale in RTL_LOCALES


def get_direction(locale: str) -> str:
    """Return 'rtl' or 'ltr' based on locale."""
    return "rtl" if is_rtl_locale(locale) else "ltr"


def get_rtl_css(locale: str) -> str:
    """Return CSS rules for RTL layout when locale is RTL.

    Returns an empty string for LTR locales.
    """
    if not is_rtl_locale(locale):
        return ""

    return """
    direction: rtl;
    text-align: right;
    unicode-bidi: embed;
    """


def get_pdf_layout_config(locale: str) -> dict:
    """Return PDF layout configuration adjusted for RTL locales.

    For RTL locales, this mirrors the layout so that:
    - Text alignment is right-aligned
    - Table columns are reversed (amount on left, description on right)
    - Logo and business info swap sides
    """
    if is_rtl_locale(locale):
        return {
            "direction": "rtl",
            "text_align": "right",
            "logo_position": "right",
            "business_info_position": "right",
            "bill_to_position": "left",
            "table_header_align": "right",
            "table_amount_align": "left",
            "column_order": "reversed",
            "css_direction": "rtl",
            "unicode_bidi": "embed",
        }
    return {
        "direction": "ltr",
        "text_align": "left",
        "logo_position": "left",
        "business_info_position": "left",
        "bill_to_position": "right",
        "table_header_align": "left",
        "table_amount_align": "right",
        "column_order": "normal",
        "css_direction": "ltr",
        "unicode_bidi": "normal",
    }


RTL_PDF_STYLES = """
/* RTL-specific PDF styles */
body[dir="rtl"] {
    direction: rtl;
    text-align: right;
    unicode-bidi: embed;
}

body[dir="rtl"] .invoice-header {
    flex-direction: row-reverse;
}

body[dir="rtl"] .invoice-table th,
body[dir="rtl"] .invoice-table td {
    text-align: right;
}

body[dir="rtl"] .invoice-table th:last-child,
body[dir="rtl"] .invoice-table td:last-child {
    text-align: left;
}

body[dir="rtl"] .invoice-totals {
    text-align: left;
    margin-left: 0;
    margin-right: auto;
}

body[dir="rtl"] .bill-to {
    text-align: left;
}

body[dir="rtl"] .business-info {
    text-align: right;
}
"""
