"""Property-based tests for invoice PDF template system.

Feature: invoice-pdf-templates
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.invoices.template_registry import (
    TEMPLATES,
    TemplateMetadata,
    validate_template_id,
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Resolve the project root (repo root) so the test works regardless of cwd
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PROJECT_ROOT / "app" / "templates" / "pdf"


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

template_id_st = st.sampled_from(list(TEMPLATES.keys()))


# ---------------------------------------------------------------------------
# Property 1: Template registry completeness
# ---------------------------------------------------------------------------


class TestTemplateRegistryCompleteness:
    """Property 1: Template registry completeness.

    # Feature: invoice-pdf-templates, Property 1: Template registry completeness

    **Validates: Requirements 1.2, 1.5**

    For any template entry in the TEMPLATES registry, all required metadata
    fields (id, display_name, description, thumbnail_path,
    default_primary_colour, default_accent_colour, default_header_bg_colour,
    logo_position, layout_type, template_file) SHALL be non-empty strings,
    and the corresponding Jinja2 template file SHALL exist in
    ``app/templates/pdf/``.
    """

    @PBT_SETTINGS
    @given(template_id=template_id_st)
    def test_all_metadata_fields_are_non_empty_strings_and_template_file_exists(
        self, template_id: str
    ):
        meta: TemplateMetadata = TEMPLATES[template_id]

        # Every metadata field must be a non-empty string
        string_fields = [
            ("id", meta.id),
            ("display_name", meta.display_name),
            ("description", meta.description),
            ("thumbnail_path", meta.thumbnail_path),
            ("default_primary_colour", meta.default_primary_colour),
            ("default_accent_colour", meta.default_accent_colour),
            ("default_header_bg_colour", meta.default_header_bg_colour),
            ("logo_position", meta.logo_position),
            ("layout_type", meta.layout_type),
            ("template_file", meta.template_file),
        ]

        for field_name, value in string_fields:
            assert isinstance(value, str), (
                f"Template '{template_id}': field '{field_name}' is not a string "
                f"(got {type(value).__name__})"
            )
            assert len(value) > 0, (
                f"Template '{template_id}': field '{field_name}' is empty"
            )

        # The corresponding Jinja2 template file must exist on disk
        template_path = _TEMPLATES_DIR / meta.template_file
        assert template_path.exists(), (
            f"Template '{template_id}': Jinja2 file '{meta.template_file}' "
            f"not found at {template_path}"
        )


# ---------------------------------------------------------------------------
# Property 4: Template ID validation
# ---------------------------------------------------------------------------


class TestTemplateIdValidation:
    """Property 4: Template ID validation.

    # Feature: invoice-pdf-templates, Property 4: Template ID validation

    **Validates: Requirements 3.3, 3.4**

    For any string that is not a key in the TEMPLATES registry, calling
    ``validate_template_id()`` SHALL raise a ValueError. For any string that
    is a key in the TEMPLATES registry, calling ``validate_template_id()``
    SHALL not raise an exception.
    """

    @PBT_SETTINGS
    @given(random_string=st.text(min_size=1, max_size=50))
    def test_random_strings_raise_valueerror_when_not_in_registry(
        self, random_string: str
    ):
        """Random strings that are not registry keys must raise ValueError."""
        if random_string in TEMPLATES:
            # Valid ID — must NOT raise
            validate_template_id(random_string)
        else:
            # Invalid ID — must raise ValueError
            with pytest.raises(ValueError):
                validate_template_id(random_string)

    @PBT_SETTINGS
    @given(template_id=st.sampled_from(list(TEMPLATES.keys())))
    def test_valid_registry_ids_do_not_raise(self, template_id: str):
        """Every key in the TEMPLATES registry must pass validation."""
        # Should complete without raising any exception
        validate_template_id(template_id)


# ---------------------------------------------------------------------------
# Property 5: Template filtering correctness
# ---------------------------------------------------------------------------

# Strategies for filter dimensions
layout_type_filter_st = st.sampled_from(["standard", "compact", "all"])
logo_position_filter_st = st.sampled_from(["left", "center", "side", "all"])


def _filter_templates(
    layout_type_filter: str,
    logo_position_filter: str,
) -> list[TemplateMetadata]:
    """Filter templates by layout_type and logo_position.

    "all" means no filter on that dimension.  Both criteria must match.
    """
    results: list[TemplateMetadata] = []
    for meta in TEMPLATES.values():
        layout_match = layout_type_filter == "all" or meta.layout_type == layout_type_filter
        logo_match = logo_position_filter == "all" or meta.logo_position == logo_position_filter
        if layout_match and logo_match:
            results.append(meta)
    return results


class TestTemplateFilteringCorrectness:
    """Property 5: Template filtering correctness.

    # Feature: invoice-pdf-templates, Property 5: Template filtering correctness

    **Validates: Requirements 4.6**

    For any combination of layout_type filter (``standard``, ``compact``, or
    ``all``) and logo_position filter (``left``, ``center``, ``side``, or
    ``all``), the filtered template list SHALL contain exactly those templates
    whose metadata matches both filter criteria, and no others.
    """

    @PBT_SETTINGS
    @given(
        layout_filter=layout_type_filter_st,
        logo_filter=logo_position_filter_st,
    )
    def test_filtered_list_matches_both_criteria_exactly(
        self,
        layout_filter: str,
        logo_filter: str,
    ):
        filtered = _filter_templates(layout_filter, logo_filter)
        filtered_ids = {t.id for t in filtered}

        # Build the expected set by checking every template individually
        expected_ids: set[str] = set()
        for tid, meta in TEMPLATES.items():
            layout_ok = layout_filter == "all" or meta.layout_type == layout_filter
            logo_ok = logo_filter == "all" or meta.logo_position == logo_filter
            if layout_ok and logo_ok:
                expected_ids.add(tid)

        assert filtered_ids == expected_ids, (
            f"Filter(layout={layout_filter!r}, logo={logo_filter!r}): "
            f"got {sorted(filtered_ids)}, expected {sorted(expected_ids)}"
        )

    @PBT_SETTINGS
    @given(
        layout_filter=layout_type_filter_st,
        logo_filter=logo_position_filter_st,
    )
    def test_every_returned_template_satisfies_both_filters(
        self,
        layout_filter: str,
        logo_filter: str,
    ):
        filtered = _filter_templates(layout_filter, logo_filter)

        for meta in filtered:
            if layout_filter != "all":
                assert meta.layout_type == layout_filter, (
                    f"Template '{meta.id}' has layout_type={meta.layout_type!r} "
                    f"but filter was {layout_filter!r}"
                )
            if logo_filter != "all":
                assert meta.logo_position == logo_filter, (
                    f"Template '{meta.id}' has logo_position={meta.logo_position!r} "
                    f"but filter was {logo_filter!r}"
                )

    @PBT_SETTINGS
    @given(
        layout_filter=layout_type_filter_st,
        logo_filter=logo_position_filter_st,
    )
    def test_no_matching_template_is_excluded(
        self,
        layout_filter: str,
        logo_filter: str,
    ):
        filtered = _filter_templates(layout_filter, logo_filter)
        filtered_ids = {t.id for t in filtered}

        for tid, meta in TEMPLATES.items():
            layout_ok = layout_filter == "all" or meta.layout_type == layout_filter
            logo_ok = logo_filter == "all" or meta.logo_position == logo_filter
            if layout_ok and logo_ok:
                assert tid in filtered_ids, (
                    f"Template '{tid}' matches both filters "
                    f"(layout={layout_filter!r}, logo={logo_filter!r}) "
                    f"but was not in the filtered result"
                )

    @PBT_SETTINGS
    @given(
        layout_filter=layout_type_filter_st,
        logo_filter=logo_position_filter_st,
    )
    def test_all_filter_returns_superset_of_specific_filters(
        self,
        layout_filter: str,
        logo_filter: str,
    ):
        """Filtering with 'all' on a dimension returns at least as many
        templates as any specific value on that dimension."""
        filtered_specific = _filter_templates(layout_filter, logo_filter)
        filtered_all_layout = _filter_templates("all", logo_filter)
        filtered_all_logo = _filter_templates(layout_filter, "all")

        specific_ids = {t.id for t in filtered_specific}
        all_layout_ids = {t.id for t in filtered_all_layout}
        all_logo_ids = {t.id for t in filtered_all_logo}

        assert specific_ids <= all_layout_ids, (
            f"Specific layout filter {layout_filter!r} returned templates "
            f"not in 'all' layout filter: {specific_ids - all_layout_ids}"
        )
        assert specific_ids <= all_logo_ids, (
            f"Specific logo filter {logo_filter!r} returned templates "
            f"not in 'all' logo filter: {specific_ids - all_logo_ids}"
        )


# ---------------------------------------------------------------------------
# Property 2: Colour resolution in rendered output
# ---------------------------------------------------------------------------

from jinja2 import Environment, FileSystemLoader
from app.modules.invoices.template_preview import (
    DotDict,
    _to_dot,
    SAMPLE_INVOICE,
    SAMPLE_CUSTOMER,
    _TEMPLATE_DIR,
    _DEFAULT_ORG,
    _build_jinja_env,
)

# Hex colour strategy — lowercase 6-digit hex
hex_colour_st = st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)


def _render_template_sync(
    template_meta: TemplateMetadata,
    colour_overrides: dict | None = None,
) -> str:
    """Render a template synchronously with sample data and optional colour overrides.

    Mirrors the logic in render_template_preview() but without async/DB access.
    """
    from app.modules.invoices.service import get_currency_symbol
    from app.core.i18n_pdf import get_pdf_context

    invoice = _to_dot(dict(SAMPLE_INVOICE))
    customer = _to_dot(dict(SAMPLE_CUSTOMER))
    org_context = _to_dot(dict(_DEFAULT_ORG))

    # Resolve colours: override > template defaults (no org settings in sync mode)
    overrides = colour_overrides or {}
    colours = {
        "primary_colour": overrides.get("primary_colour") or template_meta.default_primary_colour,
        "accent_colour": overrides.get("accent_colour") or template_meta.default_accent_colour,
        "header_bg_colour": overrides.get("header_bg_colour") or template_meta.default_header_bg_colour,
    }

    currency_symbol = get_currency_symbol(SAMPLE_INVOICE.get("currency", "NZD"))
    i18n_ctx = get_pdf_context("en")

    env = _build_jinja_env()
    template = env.get_template(template_meta.template_file)

    html = template.render(
        invoice=invoice,
        org=org_context,
        customer=customer,
        currency_symbol=currency_symbol,
        gst_percentage=15,
        payment_terms="",
        terms_and_conditions="",
        colours=_to_dot(colours),
        **i18n_ctx,
    )
    return html


class TestColourResolutionInRenderedOutput:
    """Property 2: Colour resolution in rendered output.

    # Feature: invoice-pdf-templates, Property 2: Colour resolution in rendered output

    **Validates: Requirements 2.2, 2.3, 7.3**

    For any template in the registry and for any valid hex colour triple
    (primary, accent, header_bg), rendering the template with those colours
    as overrides SHALL produce HTML containing those exact hex values.
    When no overrides are provided, the rendered HTML SHALL contain the
    template's default colour values instead.
    """

    @PBT_SETTINGS
    @given(
        template_id=template_id_st,
        primary=hex_colour_st,
        accent=hex_colour_st,
        header_bg=hex_colour_st,
    )
    def test_override_colours_appear_in_rendered_html(
        self,
        template_id: str,
        primary: str,
        accent: str,
        header_bg: str,
    ):
        """When colour overrides are provided, the rendered HTML must contain
        those exact hex values."""
        meta = TEMPLATES[template_id]
        html = _render_template_sync(
            meta,
            colour_overrides={
                "primary_colour": primary,
                "accent_colour": accent,
                "header_bg_colour": header_bg,
            },
        )

        # The base template injects colours into CSS :root as literal hex values
        assert primary in html, (
            f"Template '{template_id}': override primary colour {primary} "
            f"not found in rendered HTML"
        )
        assert accent in html, (
            f"Template '{template_id}': override accent colour {accent} "
            f"not found in rendered HTML"
        )
        assert header_bg in html, (
            f"Template '{template_id}': override header_bg colour {header_bg} "
            f"not found in rendered HTML"
        )

    @PBT_SETTINGS
    @given(template_id=template_id_st)
    def test_default_colours_appear_when_no_overrides(
        self,
        template_id: str,
    ):
        """When no colour overrides are provided, the rendered HTML must
        contain the template's default colour values."""
        meta = TEMPLATES[template_id]
        html = _render_template_sync(meta, colour_overrides=None)

        assert meta.default_primary_colour in html, (
            f"Template '{template_id}': default primary colour "
            f"{meta.default_primary_colour} not found in rendered HTML"
        )
        assert meta.default_accent_colour in html, (
            f"Template '{template_id}': default accent colour "
            f"{meta.default_accent_colour} not found in rendered HTML"
        )
        assert meta.default_header_bg_colour in html, (
            f"Template '{template_id}': default header_bg colour "
            f"{meta.default_header_bg_colour} not found in rendered HTML"
        )


# ---------------------------------------------------------------------------
# Property 6: Preview rendering for any template
# ---------------------------------------------------------------------------


class TestPreviewRenderingForAnyTemplate:
    """Property 6: Preview rendering for any template.

    # Feature: invoice-pdf-templates, Property 6: Preview rendering for any template

    **Validates: Requirements 6.2, 6.5**

    For any valid template ID in the registry, the preview rendering function
    SHALL return a non-empty HTML string containing the sample invoice data
    values (sample customer name, sample invoice number, sample line item
    descriptions, vehicle rego).
    """

    @PBT_SETTINGS
    @given(template_id=template_id_st)
    def test_preview_returns_non_empty_html_with_sample_data(
        self,
        template_id: str,
    ):
        """For any template, preview rendering must return non-empty HTML
        containing the sample customer name, invoice number, line item
        descriptions, and vehicle rego."""
        meta = TEMPLATES[template_id]
        html = _render_template_sync(meta)

        # HTML must be non-empty
        assert html is not None, (
            f"Template '{template_id}': preview returned None"
        )
        assert len(html.strip()) > 0, (
            f"Template '{template_id}': preview returned empty HTML"
        )

        # Sample customer name must appear
        assert "James Wilson" in html, (
            f"Template '{template_id}': sample customer name 'James Wilson' "
            f"not found in rendered preview HTML"
        )

        # Sample invoice number must appear
        assert "INV-0042" in html, (
            f"Template '{template_id}': sample invoice number 'INV-0042' "
            f"not found in rendered preview HTML"
        )

        # Sample line item descriptions must appear
        expected_descriptions = [
            "Full vehicle service",
            "Engine oil 5W-30 (5L)",
            "Oil filter",
            "Brake pad replacement",
        ]
        for desc in expected_descriptions:
            assert desc in html, (
                f"Template '{template_id}': sample line item description "
                f"'{desc}' not found in rendered preview HTML"
            )

        # Sample vehicle rego must appear
        assert "ABC123" in html, (
            f"Template '{template_id}': sample vehicle rego 'ABC123' "
            f"not found in rendered preview HTML"
        )


# ---------------------------------------------------------------------------
# Property 3: Template data rendering completeness
# ---------------------------------------------------------------------------

# Payment statuses the templates must handle
_PAYMENT_STATUSES = ["issued", "paid", "overdue", "voided", "refunded", "partially_refunded"]


# --- Hypothesis strategies for diverse invoice data -----------------------

_payment_status_st = st.sampled_from(_PAYMENT_STATUSES)

_line_item_st = st.fixed_dictionaries(
    {
        "description": st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=3,
            max_size=40,
        ),
        "item_type": st.sampled_from(["service", "part", "labour"]),
        "quantity": st.floats(min_value=0.5, max_value=100.0, allow_nan=False, allow_infinity=False),
        "unit_price": st.floats(min_value=1.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        "line_total": st.floats(min_value=0.5, max_value=50000.0, allow_nan=False, allow_infinity=False),
    },
    optional={
        "part_number": st.text(min_size=3, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"),
        "hours": st.floats(min_value=0.25, max_value=20.0, allow_nan=False, allow_infinity=False),
        "hourly_rate": st.floats(min_value=10.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    },
)

_vehicle_st = st.fixed_dictionaries(
    {
        "rego": st.text(min_size=3, max_size=8, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        "make": st.sampled_from(["Toyota", "Ford", "Holden", "Mazda", "Nissan", "BMW"]),
        "model": st.sampled_from(["Hilux", "Ranger", "Commodore", "CX-5", "Navara", "X5"]),
        "year": st.integers(min_value=1990, max_value=2026),
    },
)

_payment_entry_st = st.fixed_dictionaries(
    {
        "date": st.sampled_from(["2026-01-20T10:00:00", "2026-02-01T14:30:00", "2026-03-15T09:00:00"]),
        "amount": st.floats(min_value=10.0, max_value=5000.0, allow_nan=False, allow_infinity=False),
        "method": st.sampled_from(["cash", "card", "bank_transfer", "stripe"]),
        "is_refund": st.just(False),
    },
)


@st.composite
def invoice_data_st(draw):
    """Generate diverse invoice data with optional fields for property testing."""
    status = draw(_payment_status_st)
    line_items = draw(st.lists(_line_item_st, min_size=0, max_size=5))

    subtotal = sum(item["line_total"] for item in line_items) if line_items else 0.0
    discount_amount = draw(st.sampled_from([0, 0, 0, 10.0, 25.50, 50.0]))  # often zero
    gst_amount = round((subtotal - discount_amount) * 0.15, 2) if subtotal > discount_amount else 0.0
    total = round(subtotal - discount_amount + gst_amount, 2)

    # Payment amounts depend on status
    if status == "paid":
        amount_paid = total
        balance_due = 0.0
    elif status in ("refunded", "partially_refunded"):
        amount_paid = total
        balance_due = 0.0
    else:
        amount_paid = 0.0
        balance_due = total

    invoice_number = draw(st.from_regex(r"INV-[0-9]{4}", fullmatch=True))

    invoice = {
        "invoice_number": invoice_number,
        "status": status,
        "issue_date": "15 Jan 2026",
        "due_date": "29 Jan 2026",
        "payment_terms": draw(st.sampled_from(["net_14", "net_30", "due_on_receipt", ""])),
        "currency": "NZD",
        "line_items": line_items,
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "gst_amount": gst_amount,
        "total": total,
        "balance_due": balance_due,
        "amount_paid": amount_paid,
        "payments": [],
        "additional_vehicles": [],
    }

    # Optional vehicle info
    has_vehicle = draw(st.booleans())
    if has_vehicle:
        vehicle = draw(_vehicle_st)
        invoice["vehicle_rego"] = vehicle["rego"]
        invoice["vehicle_make"] = vehicle["make"]
        invoice["vehicle_model"] = vehicle["model"]
        invoice["vehicle_year"] = vehicle["year"]
    else:
        invoice["vehicle_rego"] = None
        invoice["vehicle_make"] = None
        invoice["vehicle_model"] = None
        invoice["vehicle_year"] = None

    # Optional additional vehicles
    has_additional = draw(st.booleans())
    if has_additional:
        additional = draw(st.lists(_vehicle_st, min_size=1, max_size=3))
        invoice["additional_vehicles"] = additional

    # Optional payment history (only for paid/refunded statuses)
    if status in ("paid", "partially_refunded", "refunded") and amount_paid > 0:
        has_payments = draw(st.booleans())
        if has_payments:
            payments = draw(st.lists(_payment_entry_st, min_size=1, max_size=3))
            invoice["payments"] = payments

    # Optional notes
    has_notes = draw(st.booleans())
    if has_notes:
        invoice["notes_customer"] = draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
                min_size=5,
                max_size=80,
            )
        )
    else:
        invoice["notes_customer"] = None

    return invoice


@st.composite
def customer_data_st(draw):
    """Generate customer data with required and optional fields."""
    first_name = draw(st.sampled_from(["James", "Sarah", "Mike", "Emma", "Liam"]))
    last_name = draw(st.sampled_from(["Wilson", "Smith", "Brown", "Taylor", "Jones"]))
    display_name = f"{first_name} {last_name}"

    customer = {
        "first_name": first_name,
        "last_name": last_name,
        "display_name": display_name,
    }

    # Optional fields
    has_company = draw(st.booleans())
    if has_company:
        customer["company_name"] = draw(
            st.sampled_from(["Wilson Contracting Ltd", "Smith Plumbing", "Brown Electrical"])
        )
    else:
        customer["company_name"] = None

    customer["email"] = draw(st.sampled_from(["test@example.com", None]))
    customer["phone"] = draw(st.sampled_from(["021 555 0123", None]))
    customer["address"] = draw(
        st.sampled_from(["42 Trade Street, Auckland 1061", None])
    )

    return customer


@st.composite
def org_data_st(draw):
    """Generate org data with optional logo."""
    has_logo = draw(st.booleans())
    org_name = draw(st.sampled_from([
        "Your Business Name", "Acme Motors", "Pro Plumbing Ltd", "Spark Electrical"
    ]))

    org = dict(_DEFAULT_ORG)
    org["name"] = org_name
    org["logo_url"] = "https://example.com/logo.png" if has_logo else None

    return org


def _render_template_with_data_sync(
    template_meta: TemplateMetadata,
    invoice_data: dict,
    customer_data: dict,
    org_data: dict,
    payment_terms_text: str = "",
    terms_and_conditions_text: str = "",
) -> str:
    """Render a template synchronously with custom invoice/customer/org data.

    A more flexible version of _render_template_sync() that accepts arbitrary
    data for property-based testing of data rendering completeness.
    """
    from app.modules.invoices.service import get_currency_symbol
    from app.core.i18n_pdf import get_pdf_context

    invoice = _to_dot(dict(invoice_data))
    customer = _to_dot(dict(customer_data))
    org_context = _to_dot(dict(org_data))

    colours = {
        "primary_colour": template_meta.default_primary_colour,
        "accent_colour": template_meta.default_accent_colour,
        "header_bg_colour": template_meta.default_header_bg_colour,
    }

    currency_symbol = get_currency_symbol(invoice_data.get("currency", "NZD"))
    i18n_ctx = get_pdf_context("en")

    env = _build_jinja_env()
    template = env.get_template(template_meta.template_file)

    html = template.render(
        invoice=invoice,
        org=org_context,
        customer=customer,
        currency_symbol=currency_symbol,
        gst_percentage=15,
        payment_terms=payment_terms_text,
        terms_and_conditions=terms_and_conditions_text,
        colours=_to_dot(colours),
        **i18n_ctx,
    )
    return html


class TestTemplateDataRenderingCompleteness:
    """Property 3: Template data rendering completeness.

    # Feature: invoice-pdf-templates, Property 3: Template data rendering completeness

    **Validates: Requirements 2.4, 9.1, 9.2, 9.3, 9.4, 9.6**

    For any template in the registry and for any valid invoice data (including
    edge cases: zero line items, absent optional fields, no logo, any payment
    status, additional vehicles), the template SHALL render without errors and
    the output HTML SHALL contain all data values that were provided in the
    input context (org name, customer name, invoice number, line item
    descriptions, totals).
    """

    @PBT_SETTINGS
    @given(
        template_id=template_id_st,
        invoice=invoice_data_st(),
        customer=customer_data_st(),
        org=org_data_st(),
        payment_terms_text=st.sampled_from(["", "Payment due within 14 days of invoice date."]),
        terms_and_conditions_text=st.sampled_from(["", "All work guaranteed for 12 months."]),
    )
    def test_template_renders_all_provided_data_without_errors(
        self,
        template_id: str,
        invoice: dict,
        customer: dict,
        org: dict,
        payment_terms_text: str,
        terms_and_conditions_text: str,
    ):
        """For any template and any generated invoice data, the template must
        render without errors and the output must contain all key data values."""
        meta = TEMPLATES[template_id]

        # Rendering must not raise any exception
        html = _render_template_with_data_sync(
            meta,
            invoice_data=invoice,
            customer_data=customer,
            org_data=org,
            payment_terms_text=payment_terms_text,
            terms_and_conditions_text=terms_and_conditions_text,
        )

        # HTML must be non-empty
        assert html is not None and len(html.strip()) > 0, (
            f"Template '{template_id}': rendered empty HTML"
        )

        # Org name must appear
        assert org["name"] in html, (
            f"Template '{template_id}': org name '{org['name']}' not in HTML"
        )

        # Customer display name must appear
        assert customer["display_name"] in html, (
            f"Template '{template_id}': customer name "
            f"'{customer['display_name']}' not in HTML"
        )

        # Invoice number must appear
        assert invoice["invoice_number"] in html, (
            f"Template '{template_id}': invoice number "
            f"'{invoice['invoice_number']}' not in HTML"
        )

        # Line item descriptions must appear (if any)
        for item in invoice["line_items"]:
            desc = item["description"]
            # Jinja2 autoescaping may convert special chars; check the first
            # line of the description (split on newline) is present
            first_line = desc.split("\n")[0] if desc else ""
            if first_line.strip():
                # HTML-escape the description for comparison since autoescape is on
                from markupsafe import escape as _escape
                escaped = str(_escape(first_line))
                assert escaped in html, (
                    f"Template '{template_id}': line item description "
                    f"'{first_line}' (escaped: '{escaped}') not in HTML"
                )

        # Total must appear (formatted to 2dp)
        total_str = "%.2f" % invoice["total"]
        assert total_str in html, (
            f"Template '{template_id}': total '{total_str}' not in HTML"
        )

        # Vehicle rego must appear when provided
        if invoice.get("vehicle_rego"):
            assert invoice["vehicle_rego"] in html, (
                f"Template '{template_id}': vehicle rego "
                f"'{invoice['vehicle_rego']}' not in HTML"
            )

        # Additional vehicle regos must appear when provided
        for av in invoice.get("additional_vehicles", []):
            if av.get("rego"):
                assert av["rego"] in html, (
                    f"Template '{template_id}': additional vehicle rego "
                    f"'{av['rego']}' not in HTML"
                )

        # Payment terms text must appear when provided
        if payment_terms_text:
            from markupsafe import escape as _escape
            escaped_pt = str(_escape(payment_terms_text))
            assert escaped_pt in html, (
                f"Template '{template_id}': payment terms text not in HTML"
            )

        # Terms and conditions must appear when provided
        if terms_and_conditions_text:
            assert terms_and_conditions_text in html, (
                f"Template '{template_id}': terms and conditions not in HTML"
            )

        # Zero line items should show placeholder
        if len(invoice["line_items"]) == 0:
            assert "No line items" in html, (
                f"Template '{template_id}': 'No line items' placeholder "
                f"not found when line_items is empty"
            )

        # Notes must appear when provided
        if invoice.get("notes_customer"):
            from markupsafe import escape as _escape
            escaped_notes = str(_escape(invoice["notes_customer"]))
            assert escaped_notes in html, (
                f"Template '{template_id}': customer notes not in HTML"
            )

        # Payment status banners for non-issued statuses
        status = invoice["status"]
        if status == "paid":
            assert "PAID" in html.upper()
        elif status == "overdue":
            assert "OVERDUE" in html.upper()
        elif status == "voided":
            assert "VOIDED" in html.upper()
        elif status == "refunded":
            assert "REFUNDED" in html.upper()
        elif status == "partially_refunded":
            assert "PARTIALLY REFUNDED" in html.upper() or "PARTIALLY_REFUNDED" in html.upper()


# ---------------------------------------------------------------------------
# Property 7: Thumbnail file integrity
# ---------------------------------------------------------------------------

from PIL import Image


class TestThumbnailFileIntegrity:
    """Property 7: Thumbnail file integrity.

    # Feature: invoice-pdf-templates, Property 7: Thumbnail file integrity

    **Validates: Requirements 8.1, 8.2**

    For any template in the registry, the thumbnail file referenced by
    ``thumbnail_path`` SHALL exist in ``frontend/public/``, SHALL be a valid
    PNG or WebP image, and SHALL be at least 400 pixels wide.
    """

    @PBT_SETTINGS
    @given(template_id=template_id_st)
    def test_thumbnail_exists_is_valid_image_and_at_least_400px_wide(
        self,
        template_id: str,
    ):
        """For any template, the thumbnail file must exist in
        frontend/public/, be a valid PNG or WebP image, and be at least
        400px wide."""
        meta = TEMPLATES[template_id]

        # 1. Thumbnail file must exist at frontend/public/{thumbnail_path}
        thumbnail_full_path = _PROJECT_ROOT / "frontend" / "public" / meta.thumbnail_path
        assert thumbnail_full_path.exists(), (
            f"Template '{template_id}': thumbnail file not found at "
            f"{thumbnail_full_path}"
        )

        # 2. File must be a valid PNG or WebP image (check magic bytes)
        with open(thumbnail_full_path, "rb") as f:
            header = f.read(16)

        png_magic = b"\x89PNG\r\n\x1a\n"
        webp_magic = b"RIFF"
        webp_format = b"WEBP"

        is_png = header[:8] == png_magic
        is_webp = header[:4] == webp_magic and header[8:12] == webp_format

        assert is_png or is_webp, (
            f"Template '{template_id}': thumbnail at '{meta.thumbnail_path}' "
            f"is not a valid PNG or WebP image (header bytes: {header[:12].hex()})"
        )

        # 3. Image must be at least 400px wide
        img = Image.open(thumbnail_full_path)
        width, _height = img.size
        assert width >= 400, (
            f"Template '{template_id}': thumbnail width is {width}px, "
            f"expected at least 400px"
        )
