"""I18n-aware PDF generation helpers.

Provides translation label injection and RTL layout support for
invoice and document PDF generation.

**Validates: Requirement 32, Task 50.7**
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import SUPPORTED_LOCALES, i18n_service
from app.core.rtl import get_pdf_layout_config, RTL_PDF_STYLES


def get_pdf_labels(locale: str) -> dict[str, str]:
    """Return translated labels for invoice PDF rendering.

    These labels replace hardcoded English strings in PDF templates.
    Falls back to English for unsupported locales.
    """
    translations = i18n_service.get_translations(locale)

    return {
        "invoice_title": translations.get("invoice.title", "Invoice"),
        "invoice_number": translations.get("invoice.number", "Invoice Number"),
        "invoice_date": translations.get("invoice.date", "Invoice Date"),
        "due_date": translations.get("invoice.due_date", "Due Date"),
        "bill_to": translations.get("invoice.bill_to", "Bill To"),
        "description": translations.get("invoice.description", "Description"),
        "quantity": translations.get("invoice.quantity", "Qty"),
        "unit_price": translations.get("invoice.unit_price", "Unit Price"),
        "amount": translations.get("invoice.amount", "Amount"),
        "subtotal": translations.get("invoice.subtotal", "Subtotal"),
        "tax": translations.get("invoice.tax", "Tax"),
        "total": translations.get("invoice.total", "Total"),
        "paid": translations.get("invoice.paid", "Paid"),
        "balance_due": translations.get("invoice.balance_due", "Balance Due"),
        "notes": translations.get("invoice.notes", "Notes"),
        "terms": translations.get("invoice.terms", "Terms & Conditions"),
    }


def get_pdf_context(locale: str) -> dict[str, Any]:
    """Return full i18n context for PDF template rendering.

    Includes translated labels, layout config, and RTL styles.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"

    labels = get_pdf_labels(locale)
    layout = get_pdf_layout_config(locale)

    return {
        "i18n_labels": labels,
        "i18n_layout": layout,
        "i18n_rtl_styles": RTL_PDF_STYLES if layout["direction"] == "rtl" else "",
        "i18n_locale": locale,
        "i18n_direction": layout["direction"],
    }
