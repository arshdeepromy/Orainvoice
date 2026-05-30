# Feature: quote-settings-parity, Task 13: Quote PDF Jinja render
"""Render-time tests for ``app/templates/pdf/quote.html``.

Renders the Jinja template directly (skipping WeasyPrint) and asserts that
the Notes / Payment Terms / Terms & Conditions sections appear or are
omitted depending on the resolved context values.

Validates Requirements: 2.3, 2.4, 4.4, 4.5, 8.2, 8.3
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader


TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "app" / "templates" / "pdf"


def _parse_iso_date(value):
    """Mirror ``generate_quote_pdf``'s ``parse_date`` filter.

    Only invoked when ``additional_vehicles`` is non-empty; registered here
    so the template compiles cleanly even if a future change starts using
    the filter unconditionally.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@pytest.fixture(scope="module")
def jinja_env() -> Environment:
    """Jinja environment matching ``generate_quote_pdf`` (autoescape on)."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    env.filters["parse_date"] = _parse_iso_date
    return env


def _base_context(**overrides) -> dict:
    """Minimum context required to render ``quote.html`` without raising.

    Override the fields under test (``notes`` on the quote dict,
    ``payment_terms_text``, ``terms_and_conditions``) via kwargs.
    """
    quote: dict = {
        "id": "q-1",
        "quote_number": "QT-0001",
        "customer_id": "c-1",
        "customer_name": "Jane Doe",
        "customer_email": "j@d.com",
        "vehicle_rego": "",
        "vehicle_make": "",
        "vehicle_model": "",
        "vehicle_year": None,
        "vehicle_odometer": None,
        "vehicle_wof_expiry": None,
        "vehicle_cof_expiry": None,
        "subtotal": Decimal("100.00"),
        "gst_amount": Decimal("15.00"),
        "total": Decimal("115.00"),
        "discount_type": None,
        "discount_value": Decimal("0"),
        "discount_amount": Decimal("0"),
        "shipping_charges": Decimal("0"),
        "adjustment": Decimal("0"),
        "valid_until": date(2026, 12, 31),
        "created_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
        "status": "draft",
        "notes": "",                 # default — overridden per test
        "terms": "",
        "subject": None,
        "order_number": None,
        "salesperson_name": None,
        "line_items": [],
        "additional_vehicles": [],
        "fluid_usage": [],
    }
    # Apply overrides for any keys that belong to the quote dict.
    for k, v in overrides.items():
        if k in quote:
            quote[k] = v

    org = {
        "name": "Test Workshop",
        "logo_url": None,
        "primary_colour": "#3b5bdb",
        "secondary_colour": None,
        "address": None,
        "address_unit": None,
        "address_street": None,
        "address_city": None,
        "address_state": None,
        "address_country": None,
        "address_postcode": None,
        "phone": None,
        "email": None,
        "website": None,
        "gst_number": None,
        "invoice_footer": None,
    }

    customer = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "j@d.com",
        "phone": None,
        "address": None,
    }

    ctx = {
        "quote": quote,
        "org": org,
        "customer": customer,
        "gst_percentage": 15,
        "additional_vehicles": [],
        "fluid_usage": [],
        "payment_terms_text": "",
        "terms_and_conditions": "",
        "order_number": None,
        "salesperson_name": None,
    }
    # Apply overrides for context-level keys (anything not on ``quote``).
    for k, v in overrides.items():
        if k not in quote:
            ctx[k] = v
    return ctx


# ─── Notes ────────────────────────────────────────────────────────────────────

def test_notes_present_renders_label_and_value(jinja_env: Environment) -> None:
    """Validates Requirement 2.3: PDF renders the Notes section when notes are present."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(notes="hello"))
    assert '<div class="section-title">Notes</div>' in rendered
    # Value is rendered through Jinja's `| safe` filter (Notes can contain
    # rich-text HTML from the contentEditable editor on QuoteCreate), so the
    # literal body text appears unescaped.
    assert "hello" in rendered


def test_notes_absent_omits_label(jinja_env: Environment) -> None:
    """Validates Requirement 2.4: PDF omits the Notes section when notes are empty."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(notes=""))
    # Scope to the section-title element so the assertion is robust to
    # the literal word "Notes" appearing elsewhere in future template tweaks.
    assert '<div class="section-title">Notes</div>' not in rendered


# ─── Payment Terms ────────────────────────────────────────────────────────────

def test_payment_terms_present_renders_label_and_value(jinja_env: Environment) -> None:
    """Validates Requirements 4.4 / 8.2: PDF renders Payment Terms when set."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(payment_terms_text="Net 7"))
    assert '<div class="section-title">Payment Terms</div>' in rendered
    assert "Net 7" in rendered


def test_payment_terms_absent_omits_label(jinja_env: Environment) -> None:
    """Validates Requirements 4.5 / 8.3: PDF omits Payment Terms when empty."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(payment_terms_text=""))
    assert "Payment Terms" not in rendered


# ─── Terms & Conditions ──────────────────────────────────────────────────────

def test_terms_and_conditions_present_renders_label_and_value(
    jinja_env: Environment,
) -> None:
    """Validates Requirement 8.2: PDF renders T&C when resolved value is non-empty."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(terms_and_conditions="T&C body"))
    # The template uses the HTML entity in the label.
    assert "Terms &amp; Conditions" in rendered
    # Value is rendered through Jinja's `| safe` filter (org-level T&C is
    # stored as HTML by the rich-text editor in OrgSettings), so the literal
    # body text appears unescaped in the rendered output.
    assert "T&C body" in rendered


def test_terms_and_conditions_absent_omits_label(jinja_env: Environment) -> None:
    """Validates Requirement 8.3: PDF omits T&C when resolved value is empty."""
    tpl = jinja_env.get_template("quote.html")
    rendered = tpl.render(_base_context(terms_and_conditions=""))
    assert "Terms &amp; Conditions" not in rendered
