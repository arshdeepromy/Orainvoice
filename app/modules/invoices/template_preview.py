"""Template preview service — renders sample invoice HTML for template previews.

Provides a render function that uses the org's real branding (name, logo, address)
combined with hardcoded sample invoice data to produce a realistic preview of any
invoice template with optional colour overrides.

Requirements: 6.2, 6.5
"""

from __future__ import annotations

import pathlib
import uuid

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.invoices.template_registry import TemplateMetadata

# ---------------------------------------------------------------------------
# Sample data — realistic invoice and customer for preview rendering
# ---------------------------------------------------------------------------

SAMPLE_INVOICE = {
    "invoice_number": "INV-0042",
    "status": "issued",
    "issue_date": "15 Jan 2026",
    "due_date": "29 Jan 2026",
    "payment_terms": "net_14",
    "currency": "NZD",
    "line_items": [
        {
            "description": "Full vehicle service",
            "item_type": "service",
            "quantity": 1,
            "unit_price": 250.00,
            "line_total": 250.00,
        },
        {
            "description": "Engine oil 5W-30 (5L)",
            "item_type": "part",
            "quantity": 1,
            "unit_price": 89.50,
            "line_total": 89.50,
            "part_number": "OIL-5W30",
        },
        {
            "description": "Oil filter",
            "item_type": "part",
            "quantity": 1,
            "unit_price": 24.00,
            "line_total": 24.00,
            "part_number": "FLT-001",
        },
        {
            "description": "Brake pad replacement \u2014 front",
            "item_type": "labour",
            "quantity": 1.5,
            "unit_price": 95.00,
            "hours": 1.5,
            "hourly_rate": 95.00,
            "line_total": 142.50,
        },
    ],
    "subtotal": 506.00,
    "discount_amount": 0,
    "gst_amount": 75.90,
    "total": 581.90,
    "balance_due": 581.90,
    "amount_paid": 0,
    "vehicle_rego": "ABC123",
    "vehicle_make": "Toyota",
    "vehicle_model": "Hilux",
    "vehicle_year": 2021,
    "notes_customer": "Next service due at 85,000 km.",
    "additional_vehicles": [],
    "payments": [],
}

SAMPLE_CUSTOMER = {
    "first_name": "James",
    "last_name": "Wilson",
    "display_name": "James Wilson",
    "company_name": "Wilson Contracting Ltd",
    "email": "james@wilsoncontracting.co.nz",
    "phone": "021 555 0123",
    "address": "42 Trade Street, Penrose, Auckland 1061",
}


# ---------------------------------------------------------------------------
# DotDict — allows dict values to be accessed via dot notation for Jinja2
# ---------------------------------------------------------------------------


class DotDict(dict):
    """Dict subclass that supports attribute access for Jinja2 dot notation.

    Jinja2 templates use ``obj.field`` syntax, so plain dicts need to be
    wrapped to support attribute-style access.  Nested dicts are also
    converted recursively, and missing attributes return ``None`` instead
    of raising ``AttributeError`` (matching Jinja2's ``Undefined`` behaviour).

    Dict keys take priority over built-in dict methods when accessed via
    attribute syntax, so ``d.items`` returns the dict value for key "items"
    rather than the ``dict.items`` method.
    """

    def __getattr__(self, key: str):
        # Dict keys always win over built-in dict methods
        if key in self:
            val = self[key]
            if isinstance(val, dict) and not isinstance(val, DotDict):
                return DotDict(val)
            return val
        # Fall back to None for missing keys (Jinja2 Undefined-like)
        return None

    def __setattr__(self, key: str, value):
        self[key] = value


def _to_dot(data: dict) -> DotDict:
    """Recursively convert a dict (and nested dicts / list-of-dicts) to DotDict."""
    result = DotDict(data)
    for key, val in result.items():
        if isinstance(val, dict) and not isinstance(val, DotDict):
            result[key] = _to_dot(val)
        elif isinstance(val, list):
            result[key] = [
                _to_dot(item) if isinstance(item, dict) else item for item in val
            ]
    return result


# ---------------------------------------------------------------------------
# Jinja2 environment setup — mirrors generate_invoice_pdf() in service.py
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"


def _build_jinja_env() -> Environment:
    """Create a Jinja2 environment matching the one used by generate_invoice_pdf()."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )

    def _pdf_format_date(value):
        """Format a date/datetime/ISO string for PDF display."""
        if not value:
            return ""
        if isinstance(value, str):
            if not value.startswith("20") or "T" not in value:
                return value
            try:
                from datetime import datetime as _dt

                dt = _dt.fromisoformat(value)
                return dt.strftime("%d %b %Y %I:%M %p")
            except (ValueError, TypeError):
                return value
        if hasattr(value, "strftime"):
            return value.strftime("%d %b %Y")
        return str(value)

    env.filters["pdfdate"] = _pdf_format_date
    return env


# ---------------------------------------------------------------------------
# Default org branding — used when no org context is available
# ---------------------------------------------------------------------------

_DEFAULT_ORG = {
    "name": "Your Business Name",
    "logo_url": None,
    "primary_colour": "#1a1a1a",
    "secondary_colour": None,
    "address": "123 Main Street, Auckland 1010",
    "address_unit": None,
    "address_street": "123 Main Street",
    "address_city": "Auckland",
    "address_state": None,
    "address_country": "New Zealand",
    "address_postcode": "1010",
    "phone": "09 555 0100",
    "email": "hello@yourbusiness.co.nz",
    "website": "www.yourbusiness.co.nz",
    "gst_number": "123-456-789",
    "invoice_header": None,
    "invoice_footer": None,
}


# ---------------------------------------------------------------------------
# Main preview render function
# ---------------------------------------------------------------------------


async def render_template_preview(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    template_meta: TemplateMetadata,
    colour_overrides: dict,
) -> str:
    """Render a template with sample invoice data for preview.

    Uses the org's real branding (name, logo, address) but fake invoice data
    (sample customer, 4 line items, sample totals) so the preview is realistic.

    Colour resolution order: override > org settings > template defaults.

    Requirements: 6.2, 6.5
    """
    # 1. Load org branding from DB (or use defaults if no org context) -----
    org_context: dict
    org_settings: dict = {}

    if org_id is not None:
        from app.modules.admin.models import Organisation

        result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = result.scalar_one_or_none()

        if org is not None:
            org_settings = org.settings or {}

            # Resolve country code to full name
            _raw_country = org_settings.get("address_country") or ""
            _COUNTRY_NAMES = {
                "NZ": "New Zealand", "AU": "Australia", "US": "United States",
                "GB": "United Kingdom", "CA": "Canada", "IE": "Ireland",
                "SG": "Singapore", "ZA": "South Africa", "IN": "India",
                "PH": "Philippines", "FJ": "Fiji", "WS": "Samoa", "TO": "Tonga",
            }
            _display_country = _COUNTRY_NAMES.get(_raw_country.upper(), _raw_country) if len(_raw_country) == 2 else _raw_country

            org_context = {
                "name": org.name,
                "logo_url": org_settings.get("logo_url"),
                "primary_colour": org_settings.get("primary_colour", "#1a1a1a"),
                "secondary_colour": org_settings.get("secondary_colour"),
                "address": ", ".join(
                    filter(
                        None,
                        [
                            org_settings.get("address_unit"),
                            org_settings.get("address_street"),
                            org_settings.get("address_city"),
                            org_settings.get("address_state"),
                            org_settings.get("address_postcode"),
                        ],
                    )
                )
                or org_settings.get("address"),
                "address_unit": org_settings.get("address_unit"),
                "address_street": org_settings.get("address_street"),
                "address_city": org_settings.get("address_city"),
                "address_state": org_settings.get("address_state"),
                "address_country": _display_country if _display_country else None,
                "address_postcode": org_settings.get("address_postcode"),
                "phone": org_settings.get("phone"),
                "email": org_settings.get("email"),
                "website": org_settings.get("website"),
                "gst_number": org_settings.get("gst_number"),
                "invoice_header": org_settings.get("invoice_header_text"),
                "invoice_footer": org_settings.get("invoice_footer_text"),
            }
        else:
            org_context = dict(_DEFAULT_ORG)
    else:
        org_context = dict(_DEFAULT_ORG)

    # 2. Build sample invoice and customer as DotDicts ---------------------
    invoice = _to_dot(dict(SAMPLE_INVOICE))
    customer = _to_dot(dict(SAMPLE_CUSTOMER))

    # 3. Resolve colour values: override > org settings > template defaults
    org_template_colours = org_settings.get("invoice_template_colours") or {}

    colours = {
        "primary_colour": (
            colour_overrides.get("primary_colour")
            or org_template_colours.get("primary_colour")
            or template_meta.default_primary_colour
        ),
        "accent_colour": (
            colour_overrides.get("accent_colour")
            or org_template_colours.get("accent_colour")
            or template_meta.default_accent_colour
        ),
        "header_bg_colour": (
            colour_overrides.get("header_bg_colour")
            or org_template_colours.get("header_bg_colour")
            or template_meta.default_header_bg_colour
        ),
    }

    # 4. Standard context values matching generate_invoice_pdf() -----------
    gst_percentage = org_settings.get("gst_percentage", 15)
    payment_terms = org_settings.get("payment_terms_text", "")
    terms_and_conditions = org_settings.get("terms_and_conditions", "")

    from app.modules.invoices.service import get_currency_symbol

    currency_symbol = get_currency_symbol(
        SAMPLE_INVOICE.get("currency", "NZD")
    )

    # I18n labels for PDF
    from app.core.i18n_pdf import get_pdf_context

    i18n_ctx = get_pdf_context("en")

    # 5. Load and render the Jinja2 template with full context -------------
    env = _build_jinja_env()
    template = env.get_template(template_meta.template_file)

    html = template.render(
        invoice=invoice,
        org=_to_dot(org_context),
        customer=customer,
        currency_symbol=currency_symbol,
        gst_percentage=gst_percentage,
        payment_terms=payment_terms,
        terms_and_conditions=terms_and_conditions,
        colours=_to_dot(colours),
        **i18n_ctx,
    )

    # Inject preview-mode CSS to fix negative margins that work in PDF
    # but clip content in browser iframe preview.  We override @page margins
    # to zero (browser ignores @page anyway) and clamp all negative margins
    # so full-width header/footer bands stay within the visible area.
    preview_css = """<style>
      @page { margin: 0 !important; }
      body {
        padding: 18mm 14mm 22mm 14mm !important;
        overflow: visible !important;
      }
    </style>"""
    # Insert just before </head>
    html = html.replace("</head>", preview_css + "\n</head>", 1)

    return html
