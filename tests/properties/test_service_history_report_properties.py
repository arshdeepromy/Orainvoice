"""Property-based tests for service history report.

Properties covered:
  P1 — Report structure matches invoice count
  P2 — Cover page contains all required fields
  P3 — TOC lists all invoices with required fields
  P6 — Date range filtering correctness

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1, 4.2, 4.4**
"""

from __future__ import annotations

from datetime import date

from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.vehicles.report_service import compute_date_cutoff


# ---------------------------------------------------------------------------
# Settings — minimum 100 iterations per the spec
# ---------------------------------------------------------------------------

PBT_SETTINGS_100 = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

range_years_strategy = st.sampled_from([0, 1, 2, 3])

issue_date_strategy = st.dates(min_value=date(2015, 1, 1), max_value=date(2030, 12, 31))

invoice_strategy = st.fixed_dictionaries({
    "invoice_number": st.from_regex(r"INV-\d{5}", fullmatch=True),
    "issue_date": issue_date_strategy,
    "status": st.sampled_from(["draft", "issued", "paid", "overdue", "cancelled"]),
    "total": st.decimals(
        min_value=0, max_value=99999, places=2,
        allow_nan=False, allow_infinity=False,
    ),
})

invoices_list_strategy = st.lists(invoice_strategy, min_size=0, max_size=20)


# ===========================================================================
# Property 6: Date range filtering correctness
# Feature: service-history-report, Property 6: Date range filtering correctness
# ===========================================================================


class TestP6DateRangeFilteringCorrectness:
    """For any set of invoices with random issue dates and any selected range
    (0, 1, 2, 3 years), every invoice in the filtered result SHALL have an
    issue_date on or after the cutoff date, and every excluded invoice SHALL
    have an issue_date before the cutoff date. When range_years is 0 (all
    time), all invoices SHALL be included.

    **Validates: Requirements 4.2, 4.4**
    """

    @given(
        invoices=invoices_list_strategy,
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    def test_included_invoices_have_issue_date_on_or_after_cutoff(
        self,
        invoices: list[dict],
        range_years: int,
    ) -> None:
        """P6: All included invoices have issue_date >= cutoff."""
        cutoff = compute_date_cutoff(range_years)

        if cutoff is None:
            # range_years=0 → all invoices included
            included = invoices
            excluded = []
        else:
            included = [inv for inv in invoices if inv["issue_date"] >= cutoff]
            excluded = [inv for inv in invoices if inv["issue_date"] < cutoff]

        for inv in included:
            if cutoff is not None:
                assert inv["issue_date"] >= cutoff, (
                    f"Included invoice {inv['invoice_number']} has issue_date "
                    f"{inv['issue_date']} before cutoff {cutoff}"
                )

        for inv in excluded:
            assert cutoff is not None
            assert inv["issue_date"] < cutoff, (
                f"Excluded invoice {inv['invoice_number']} has issue_date "
                f"{inv['issue_date']} on or after cutoff {cutoff}"
            )

    @given(
        invoices=invoices_list_strategy,
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    def test_partition_is_complete(
        self,
        invoices: list[dict],
        range_years: int,
    ) -> None:
        """P6: Included + excluded == all invoices (no invoice lost or duplicated)."""
        cutoff = compute_date_cutoff(range_years)

        if cutoff is None:
            included = invoices
            excluded = []
        else:
            included = [inv for inv in invoices if inv["issue_date"] >= cutoff]
            excluded = [inv for inv in invoices if inv["issue_date"] < cutoff]

        assert len(included) + len(excluded) == len(invoices), (
            f"Partition mismatch: {len(included)} included + {len(excluded)} "
            f"excluded != {len(invoices)} total"
        )

    @given(invoices=invoices_list_strategy)
    @PBT_SETTINGS_100
    def test_range_years_zero_includes_all(
        self,
        invoices: list[dict],
    ) -> None:
        """P6: When range_years=0, cutoff is None and all invoices are included."""
        cutoff = compute_date_cutoff(0)
        assert cutoff is None, f"Expected None for range_years=0, got {cutoff}"

        # With no cutoff, filtering should include everything
        included = [inv for inv in invoices if cutoff is None or inv["issue_date"] >= cutoff]
        assert len(included) == len(invoices)

    @given(range_years=st.sampled_from([1, 2, 3]))
    @PBT_SETTINGS_100
    def test_cutoff_date_is_correct_relative_to_today(
        self,
        range_years: int,
    ) -> None:
        """P6: compute_date_cutoff returns today - range_years years."""
        from dateutil.relativedelta import relativedelta

        cutoff = compute_date_cutoff(range_years)
        expected = date.today() - relativedelta(years=range_years)
        assert cutoff == expected, (
            f"cutoff {cutoff} != expected {expected} for range_years={range_years}"
        )


# ===========================================================================
# Property 1: Report structure matches invoice count
# Feature: service-history-report, Property 1: Report structure matches invoice count
# ===========================================================================

import pathlib

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "app"
    / "templates"
    / "pdf"
)
_JINJA_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


# Strategies for Property 1

_p1_printable = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), min_codepoint=48, max_codepoint=122),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

_p1_line_item_strategy = st.fixed_dictionaries({
    "description": _p1_printable,
    "quantity": st.integers(min_value=1, max_value=100),
    "unit_price": st.decimals(min_value=1, max_value=9999, places=2, allow_nan=False, allow_infinity=False),
    "line_total": st.decimals(min_value=1, max_value=99999, places=2, allow_nan=False, allow_infinity=False),
})

_p1_invoice_strategy = st.fixed_dictionaries({
    "invoice_number": st.from_regex(r"INV-\d{5}", fullmatch=True),
    "issue_date": st.dates(min_value=date(2015, 1, 1), max_value=date(2030, 12, 31)).map(
        lambda d: d.strftime("%d %b %Y")
    ),
    "status": st.sampled_from(["draft", "issued", "paid", "overdue", "cancelled"]),
    "odometer": st.one_of(st.none(), st.integers(min_value=0, max_value=999999)),
    "customer_name": _p1_printable,
    "line_items": st.lists(_p1_line_item_strategy, min_size=0, max_size=5),
    "subtotal": st.decimals(min_value=0, max_value=99999, places=2, allow_nan=False, allow_infinity=False),
    "gst_amount": st.decimals(min_value=0, max_value=99999, places=2, allow_nan=False, allow_infinity=False),
    "total": st.decimals(min_value=0, max_value=99999, places=2, allow_nan=False, allow_infinity=False),
})

_p1_invoices_list_strategy = st.lists(_p1_invoice_strategy, min_size=0, max_size=20)


class TestP1ReportStructureMatchesInvoiceCount:
    """For any vehicle with N invoices in the selected date range, the rendered
    report HTML SHALL contain exactly 1 cover page section, 1 table of contents
    section (when N > 0), and N invoice page sections. When N = 0, there SHALL
    be 1 cover page, 0 TOC sections, and 0 invoice pages.

    **Validates: Requirements 1.1**
    """

    @given(invoices=_p1_invoices_list_strategy)
    @PBT_SETTINGS_100
    def test_report_structure_matches_invoice_count(
        self,
        invoices: list[dict],
    ) -> None:
        """P1: Exactly 1 cover page, 1 TOC (when N>0), and N invoice pages."""
        n = len(invoices)

        context = {
            "org": {
                "name": "Test Workshop",
                "logo_url": None,
                "address": "1 Test St",
                "phone": "0400000000",
                "email": "test@example.com",
                "gst_number": "12-345-678-901",
            },
            "vehicle": {
                "rego": "ABC123",
                "make": "Toyota",
                "model": "Hilux",
                "year": 2020,
                "vin": "JTFST22P900012345",
                "odometer": 85000,
            },
            "customer": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0412345678",
            },
            "invoices": invoices,
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": n > 0,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        cover_count = html.count('class="cover-page"')
        toc_count = html.count('class="toc-section"')
        invoice_count = html.count('class="invoice-page"')

        assert cover_count == 1, (
            f"Expected 1 cover page, found {cover_count}"
        )

        if n == 0:
            assert toc_count == 0, (
                f"Expected 0 TOC sections for 0 invoices, found {toc_count}"
            )
            assert invoice_count == 0, (
                f"Expected 0 invoice pages for 0 invoices, found {invoice_count}"
            )
        else:
            assert toc_count == 1, (
                f"Expected 1 TOC section for {n} invoices, found {toc_count}"
            )
            assert invoice_count == n, (
                f"Expected {n} invoice pages, found {invoice_count}"
            )


# ===========================================================================
# Property 2: Cover page contains all required fields
# Feature: service-history-report, Property 2: Cover page contains all required fields
# ===========================================================================

# Strategies for Property 2

_p2_printable = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

_p2_org_strategy = st.fixed_dictionaries({
    "name": _p2_printable,
    "logo_url": st.one_of(st.none(), st.just("https://example.com/logo.png")),
    "address": st.one_of(st.none(), _p2_printable),
    "phone": st.one_of(st.none(), _p2_printable),
    "email": st.one_of(st.none(), st.just("shop@example.com")),
    "gst_number": st.one_of(st.none(), _p2_printable),
})

_p2_vehicle_strategy = st.fixed_dictionaries({
    "rego": _p2_printable,
    "make": _p2_printable,
    "model": _p2_printable,
    "year": st.one_of(st.none(), st.integers(min_value=1900, max_value=2030)),
    "vin": st.one_of(st.none(), _p2_printable),
    "odometer": st.one_of(st.none(), st.integers(min_value=1, max_value=999999)),
})

_p2_customer_strategy = st.fixed_dictionaries({
    "full_name": _p2_printable,
    "email": st.one_of(st.none(), st.just("customer@example.com")),
    "phone": st.one_of(st.none(), _p2_printable),
})

_p2_minimal_invoice = st.fixed_dictionaries({
    "invoice_number": st.from_regex(r"INV-\d{5}", fullmatch=True),
    "issue_date": st.dates(min_value=date(2015, 1, 1), max_value=date(2030, 12, 31)).map(
        lambda d: d.strftime("%d %b %Y")
    ),
    "status": st.sampled_from(["paid", "issued"]),
    "odometer": st.just(None),
    "customer_name": st.just("Test Customer"),
    "line_items": st.just([]),
    "subtotal": st.just(__import__("decimal").Decimal("0.00")),
    "gst_amount": st.just(__import__("decimal").Decimal("0.00")),
    "total": st.just(__import__("decimal").Decimal("0.00")),
})


class TestP2CoverPageContainsAllRequiredFields:
    """For any organisation settings (name, address, phone, email, GST number,
    logo_url), vehicle details (rego, make, model, year, VIN, odometer), and
    customer details (full name, email, phone), the rendered cover page HTML
    SHALL contain all non-null field values from each of these three data
    sources.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """

    @given(
        org=_p2_org_strategy,
        vehicle=_p2_vehicle_strategy,
        customer=_p2_customer_strategy,
        invoice=_p2_minimal_invoice,
    )
    @PBT_SETTINGS_100
    def test_cover_page_contains_all_non_null_fields(
        self,
        org: dict,
        vehicle: dict,
        customer: dict,
        invoice: dict,
    ) -> None:
        """P2: All non-null org/vehicle/customer field values appear in the cover page HTML."""
        context = {
            "org": org,
            "vehicle": vehicle,
            "customer": customer,
            "invoices": [invoice],
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": True,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        # Extract cover page section
        cover_start = html.index('class="cover-page"')
        cover_end = html.index('class="toc-section"')
        cover_html = html[cover_start:cover_end]

        # Org fields
        assert org["name"] in cover_html, (
            f"Cover page missing org name {org['name']!r}"
        )
        if org["address"] is not None:
            assert org["address"] in cover_html, (
                f"Cover page missing org address {org['address']!r}"
            )
        if org["phone"] is not None:
            assert org["phone"] in cover_html, (
                f"Cover page missing org phone {org['phone']!r}"
            )
        if org["email"] is not None:
            assert org["email"] in cover_html, (
                f"Cover page missing org email {org['email']!r}"
            )
        if org["gst_number"] is not None:
            assert org["gst_number"] in cover_html, (
                f"Cover page missing org gst_number {org['gst_number']!r}"
            )

        # Vehicle fields
        assert vehicle["rego"] in cover_html, (
            f"Cover page missing vehicle rego {vehicle['rego']!r}"
        )
        assert vehicle["make"] in cover_html, (
            f"Cover page missing vehicle make {vehicle['make']!r}"
        )
        assert vehicle["model"] in cover_html, (
            f"Cover page missing vehicle model {vehicle['model']!r}"
        )
        if vehicle["year"] is not None:
            assert str(vehicle["year"]) in cover_html, (
                f"Cover page missing vehicle year {vehicle['year']!r}"
            )
        if vehicle["vin"] is not None:
            assert vehicle["vin"] in cover_html, (
                f"Cover page missing vehicle vin {vehicle['vin']!r}"
            )
        if vehicle["odometer"] is not None:
            # Template formats odometer with commas: "{:,}".format(odometer)
            formatted_odo = f"{vehicle['odometer']:,}"
            assert formatted_odo in cover_html, (
                f"Cover page missing vehicle odometer {formatted_odo!r}"
            )

        # Customer fields
        assert customer["full_name"] in cover_html, (
            f"Cover page missing customer full_name {customer['full_name']!r}"
        )
        if customer["email"] is not None:
            assert customer["email"] in cover_html, (
                f"Cover page missing customer email {customer['email']!r}"
            )
        if customer["phone"] is not None:
            assert customer["phone"] in cover_html, (
                f"Cover page missing customer phone {customer['phone']!r}"
            )


# ===========================================================================
# Property 3: TOC lists all invoices with required fields
# Feature: service-history-report, Property 3: TOC lists all invoices with required fields
# ===========================================================================

# Strategy: reuse _p1_invoice_strategy for invoices with all required fields
_p3_invoices_list_strategy = st.lists(_p1_invoice_strategy, min_size=1, max_size=20)


class TestP3TocListsAllInvoicesWithRequiredFields:
    """For any set of invoices included in the report, the rendered table of
    contents SHALL contain every invoice's invoice number, issue date, status,
    and total amount.

    **Validates: Requirements 2.1**
    """

    @given(invoices=_p3_invoices_list_strategy)
    @PBT_SETTINGS_100
    def test_toc_lists_all_invoices_with_required_fields(
        self,
        invoices: list[dict],
    ) -> None:
        """P3: TOC contains invoice_number, issue_date, status, and total for every invoice."""
        context = {
            "org": {
                "name": "Test Workshop",
                "logo_url": None,
                "address": "1 Test St",
                "phone": "0400000000",
                "email": "test@example.com",
                "gst_number": "12-345-678-901",
            },
            "vehicle": {
                "rego": "ABC123",
                "make": "Toyota",
                "model": "Hilux",
                "year": 2020,
                "vin": "JTFST22P900012345",
                "odometer": 85000,
            },
            "customer": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0412345678",
            },
            "invoices": invoices,
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": True,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        # Extract the TOC section (between toc-section and first invoice-page)
        toc_start = html.index('class="toc-section"')
        toc_end = html.index('class="invoice-page"')
        toc_html = html[toc_start:toc_end]

        for inv in invoices:
            # Invoice number must appear in TOC
            assert inv["invoice_number"] in toc_html, (
                f"TOC missing invoice_number {inv['invoice_number']!r}"
            )

            # Issue date must appear in TOC
            assert inv["issue_date"] in toc_html, (
                f"TOC missing issue_date {inv['issue_date']!r}"
            )

            # Status: template renders as {{ inv.status | replace('_', ' ') | title }}
            expected_status = inv["status"].replace("_", " ").title()
            assert expected_status in toc_html, (
                f"TOC missing status {expected_status!r} (raw: {inv['status']!r})"
            )

            # Total: template renders as {{ "%.2f" | format(inv.total | float) }}
            expected_total = "%.2f" % float(inv["total"])
            assert expected_total in toc_html, (
                f"TOC missing total {expected_total!r} for invoice {inv['invoice_number']!r}"
            )


# ===========================================================================
# Property 4: Table of contents ordering
# Feature: service-history-report, Property 4: Table of contents ordering
# ===========================================================================

import re as _re

# Strategy: generate invoices with UNIQUE invoice numbers so we can track order.
# We use st.lists with unique_by to guarantee uniqueness.
_p4_invoice_strategy = st.fixed_dictionaries({
    "invoice_number": st.from_regex(r"INV-[0-9]{5}", fullmatch=True),
    "issue_date": st.dates(min_value=date(2015, 1, 1), max_value=date(2030, 12, 31)),
    "status": st.sampled_from(["draft", "issued", "paid", "overdue", "cancelled"]),
    "odometer": st.just(None),
    "customer_name": st.just("Test Customer"),
    "line_items": st.just([]),
    "subtotal": st.just(__import__("decimal").Decimal("0.00")),
    "gst_amount": st.just(__import__("decimal").Decimal("0.00")),
    "total": st.decimals(min_value=0, max_value=99999, places=2, allow_nan=False, allow_infinity=False),
})

_p4_invoices_list_strategy = st.lists(
    _p4_invoice_strategy,
    min_size=2,
    max_size=15,
    unique_by=lambda inv: inv["invoice_number"],
)


class TestP4TocOrdering:
    """For any set of invoices with distinct issue dates, the table of contents
    SHALL list them in descending order by issue date (most recent first).

    The backend sorts invoices by issue_date descending before passing them to
    the template. This test replicates that: generate random invoices, sort by
    issue_date descending, render the template, then verify the TOC shows
    invoice numbers in that same descending-date order.

    **Validates: Requirements 2.2**
    """

    @given(invoices=_p4_invoices_list_strategy)
    @PBT_SETTINGS_100
    def test_toc_ordering_matches_descending_date_sort(
        self,
        invoices: list[dict],
    ) -> None:
        """P4: TOC invoice numbers appear in descending issue_date order."""
        # Sort invoices by issue_date descending (as the backend would)
        sorted_invoices = sorted(
            invoices,
            key=lambda inv: inv["issue_date"],
            reverse=True,
        )

        # Format issue_date strings for the template (e.g. "01 Jan 2025")
        template_invoices = []
        for inv in sorted_invoices:
            template_inv = dict(inv)
            template_inv["issue_date"] = inv["issue_date"].strftime("%d %b %Y")
            template_invoices.append(template_inv)

        expected_order = [inv["invoice_number"] for inv in sorted_invoices]

        context = {
            "org": {
                "name": "Test Workshop",
                "logo_url": None,
                "address": "1 Test St",
                "phone": "0400000000",
                "email": "test@example.com",
                "gst_number": "12-345-678-901",
            },
            "vehicle": {
                "rego": "ABC123",
                "make": "Toyota",
                "model": "Hilux",
                "year": 2020,
                "vin": "JTFST22P900012345",
                "odometer": 85000,
            },
            "customer": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0412345678",
            },
            "invoices": template_invoices,
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": True,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        # Extract the TOC section
        toc_start = html.index('class="toc-section"')
        toc_end = html.index('class="invoice-page"')
        toc_html = html[toc_start:toc_end]

        # Extract invoice numbers from the TOC in rendered order.
        # The template renders: <td style="color:#1a1a1a; font-weight:600;">INV-XXXXX</td>
        rendered_numbers = _re.findall(r"INV-\d{5}", toc_html)

        assert rendered_numbers == expected_order, (
            f"TOC order {rendered_numbers} does not match expected "
            f"descending-date order {expected_order}"
        )


# ===========================================================================
# Property 5: Invoice page contains all required fields
# Feature: service-history-report, Property 5: Invoice page contains all required fields
# ===========================================================================

# Strategy: 1-5 invoices each with 1-5 line items (keeps tests fast)
_p5_invoices_list_strategy = st.lists(_p1_invoice_strategy, min_size=1, max_size=5)


class TestP5InvoicePageCompleteness:
    """For any invoice with line items, the rendered invoice page SHALL contain
    the invoice number, issue date, status, odometer, customer name, and for
    each line item: description, quantity, unit price, and line total, plus the
    invoice subtotal, tax amount, and grand total.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(invoices=_p5_invoices_list_strategy)
    @PBT_SETTINGS_100
    def test_invoice_page_contains_all_required_fields(
        self,
        invoices: list[dict],
    ) -> None:
        """P5: Each invoice page contains all required fields."""
        context = {
            "org": {
                "name": "Test Workshop",
                "logo_url": None,
                "address": "1 Test St",
                "phone": "0400000000",
                "email": "test@example.com",
                "gst_number": "12-345-678-901",
            },
            "vehicle": {
                "rego": "ABC123",
                "make": "Toyota",
                "model": "Hilux",
                "year": 2020,
                "vin": "JTFST22P900012345",
                "odometer": 85000,
            },
            "customer": {
                "full_name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "0412345678",
            },
            "invoices": invoices,
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": True,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        # Split HTML into individual invoice page sections
        parts = html.split('class="invoice-page"')
        # First part is everything before the first invoice page; skip it
        invoice_page_parts = parts[1:]

        assert len(invoice_page_parts) == len(invoices), (
            f"Expected {len(invoices)} invoice pages, found {len(invoice_page_parts)}"
        )

        for idx, inv in enumerate(invoices):
            page_html = invoice_page_parts[idx]

            # Invoice number
            assert inv["invoice_number"] in page_html, (
                f"Invoice page {idx} missing invoice_number {inv['invoice_number']!r}"
            )

            # Issue date (already a formatted string from the strategy)
            assert inv["issue_date"] in page_html, (
                f"Invoice page {idx} missing issue_date {inv['issue_date']!r}"
            )

            # Status: template renders as {{ inv.status | replace('_', ' ') | title }}
            expected_status = inv["status"].replace("_", " ").title()
            assert expected_status in page_html, (
                f"Invoice page {idx} missing status {expected_status!r}"
            )

            # Odometer (when not None, formatted with commas)
            if inv["odometer"] is not None:
                formatted_odo = f"{inv['odometer']:,}"
                assert formatted_odo in page_html, (
                    f"Invoice page {idx} missing odometer {formatted_odo!r}"
                )

            # Customer name
            assert inv["customer_name"] in page_html, (
                f"Invoice page {idx} missing customer_name {inv['customer_name']!r}"
            )

            # Line items
            for li_idx, item in enumerate(inv["line_items"]):
                assert item["description"] in page_html, (
                    f"Invoice page {idx} missing line item {li_idx} description {item['description']!r}"
                )
                assert str(item["quantity"]) in page_html, (
                    f"Invoice page {idx} missing line item {li_idx} quantity {item['quantity']!r}"
                )
                expected_unit_price = "%.2f" % float(item["unit_price"])
                assert expected_unit_price in page_html, (
                    f"Invoice page {idx} missing line item {li_idx} unit_price {expected_unit_price!r}"
                )
                expected_line_total = "%.2f" % float(item["line_total"])
                assert expected_line_total in page_html, (
                    f"Invoice page {idx} missing line item {li_idx} line_total {expected_line_total!r}"
                )

            # Subtotal
            expected_subtotal = "%.2f" % float(inv["subtotal"])
            assert expected_subtotal in page_html, (
                f"Invoice page {idx} missing subtotal {expected_subtotal!r}"
            )

            # GST amount
            expected_gst = "%.2f" % float(inv["gst_amount"])
            assert expected_gst in page_html, (
                f"Invoice page {idx} missing gst_amount {expected_gst!r}"
            )

            # Grand total
            expected_total = "%.2f" % float(inv["total"])
            assert expected_total in page_html, (
                f"Invoice page {idx} missing total {expected_total!r}"
            )


# ---------------------------------------------------------------------------
# Imports for Property 7
# ---------------------------------------------------------------------------

from app.modules.vehicles.report_service import _DATE_RANGE_LABELS


# ---------------------------------------------------------------------------
# Strategies for Property 7
# ---------------------------------------------------------------------------

_printable_nonempty = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), min_codepoint=48, max_codepoint=122),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

org_strategy = st.fixed_dictionaries({
    "name": _printable_nonempty,
    "logo_url": st.one_of(st.none(), st.just("https://example.com/logo.png")),
    "address": st.one_of(st.none(), _printable_nonempty),
    "phone": st.one_of(st.none(), _printable_nonempty),
    "email": st.one_of(st.none(), st.just("shop@example.com")),
})

vehicle_email_strategy = st.fixed_dictionaries({
    "rego": _printable_nonempty,
    "make": _printable_nonempty,
    "model": _printable_nonempty,
    "year": st.one_of(st.none(), st.integers(min_value=1900, max_value=2030)),
})


# ===========================================================================
# Property 7: Email content completeness
# Feature: service-history-report, Property 7: Email content completeness
# ===========================================================================


# ===========================================================================
# Property 2: Cover page contains all required fields
# Feature: service-history-report, Property 2: Cover page contains all required fields
# ===========================================================================

# Strategies for Property 2

_p2_printable = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

_p2_org_strategy = st.fixed_dictionaries({
    "name": _p2_printable,
    "logo_url": st.one_of(st.none(), st.just("https://example.com/logo.png")),
    "address": st.one_of(st.none(), _p2_printable),
    "phone": st.one_of(st.none(), _p2_printable),
    "email": st.one_of(st.none(), st.just("shop@example.com")),
    "gst_number": st.one_of(st.none(), _p2_printable),
})

_p2_vehicle_strategy = st.fixed_dictionaries({
    "rego": _p2_printable,
    "make": _p2_printable,
    "model": _p2_printable,
    "year": st.one_of(st.none(), st.integers(min_value=1900, max_value=2030)),
    "vin": st.one_of(st.none(), _p2_printable),
    "odometer": st.one_of(st.none(), st.integers(min_value=1, max_value=999999)),
})

_p2_customer_strategy = st.fixed_dictionaries({
    "full_name": _p2_printable,
    "email": st.one_of(st.none(), st.just("customer@example.com")),
    "phone": st.one_of(st.none(), _p2_printable),
})

_p2_minimal_invoice = st.fixed_dictionaries({
    "invoice_number": st.from_regex(r"INV-\d{5}", fullmatch=True),
    "issue_date": st.dates(min_value=date(2015, 1, 1), max_value=date(2030, 12, 31)).map(
        lambda d: d.strftime("%d %b %Y")
    ),
    "status": st.sampled_from(["paid", "issued"]),
    "odometer": st.just(None),
    "customer_name": st.just("Test Customer"),
    "line_items": st.just([]),
    "subtotal": st.just(__import__("decimal").Decimal("0.00")),
    "gst_amount": st.just(__import__("decimal").Decimal("0.00")),
    "total": st.just(__import__("decimal").Decimal("0.00")),
})


class TestP2CoverPageContainsAllRequiredFields:
    """For any organisation settings (name, address, phone, email, GST number,
    logo_url), vehicle details (rego, make, model, year, VIN, odometer), and
    customer details (full name, email, phone), the rendered cover page HTML
    SHALL contain all non-null field values from each of these three data
    sources.

    **Validates: Requirements 1.2, 1.3, 1.4**
    """

    @given(
        org=_p2_org_strategy,
        vehicle=_p2_vehicle_strategy,
        customer=_p2_customer_strategy,
        invoice=_p2_minimal_invoice,
    )
    @PBT_SETTINGS_100
    def test_cover_page_contains_all_non_null_fields(
        self,
        org: dict,
        vehicle: dict,
        customer: dict,
        invoice: dict,
    ) -> None:
        """P2: All non-null org/vehicle/customer field values appear in the cover page HTML."""
        context = {
            "org": org,
            "vehicle": vehicle,
            "customer": customer,
            "invoices": [invoice],
            "date_range_label": "Last 1 Year",
            "generated_date": "01 Jan 2025",
            "has_invoices": True,
        }

        template = _JINJA_ENV.get_template("service_history_report.html")
        html = template.render(**context)

        # Extract cover page section
        cover_start = html.index('class="cover-page"')
        cover_end = html.index('class="toc-section"')
        cover_html = html[cover_start:cover_end]

        # Org fields
        assert org["name"] in cover_html, (
            f"Cover page missing org name {org['name']!r}"
        )
        if org["address"] is not None:
            assert org["address"] in cover_html, (
                f"Cover page missing org address {org['address']!r}"
            )
        if org["phone"] is not None:
            assert org["phone"] in cover_html, (
                f"Cover page missing org phone {org['phone']!r}"
            )
        if org["email"] is not None:
            assert org["email"] in cover_html, (
                f"Cover page missing org email {org['email']!r}"
            )
        if org["gst_number"] is not None:
            assert org["gst_number"] in cover_html, (
                f"Cover page missing org gst_number {org['gst_number']!r}"
            )

        # Vehicle fields
        assert vehicle["rego"] in cover_html, (
            f"Cover page missing vehicle rego {vehicle['rego']!r}"
        )
        assert vehicle["make"] in cover_html, (
            f"Cover page missing vehicle make {vehicle['make']!r}"
        )
        assert vehicle["model"] in cover_html, (
            f"Cover page missing vehicle model {vehicle['model']!r}"
        )
        if vehicle["year"] is not None:
            assert str(vehicle["year"]) in cover_html, (
                f"Cover page missing vehicle year {vehicle['year']!r}"
            )
        if vehicle["vin"] is not None:
            assert vehicle["vin"] in cover_html, (
                f"Cover page missing vehicle vin {vehicle['vin']!r}"
            )
        if vehicle["odometer"] is not None:
            # Template formats odometer with commas: "{:,}".format(odometer)
            formatted_odo = f"{vehicle['odometer']:,}"
            assert formatted_odo in cover_html, (
                f"Cover page missing vehicle odometer {formatted_odo!r}"
            )

        # Customer fields
        assert customer["full_name"] in cover_html, (
            f"Cover page missing customer full_name {customer['full_name']!r}"
        )
        if customer["email"] is not None:
            assert customer["email"] in cover_html, (
                f"Cover page missing customer email {customer['email']!r}"
            )
        if customer["phone"] is not None:
            assert customer["phone"] in cover_html, (
                f"Cover page missing customer phone {customer['phone']!r}"
            )


# ===========================================================================
# Property 7: Email content completeness
# Feature: service-history-report, Property 7: Email content completeness
# ===========================================================================

class TestP7EmailContentCompleteness:
    """For any organisation settings, vehicle (rego, make, model, year), and
    date range, the email subject SHALL contain the vehicle's registration
    number and "Service History Report", and the email body SHALL contain the
    vehicle registration, make, model, year (when not None), and date range
    label.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(
        org=org_strategy,
        vehicle=vehicle_email_strategy,
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    def test_email_subject_contains_rego_and_report_title(
        self,
        org: dict,
        vehicle: dict,
        range_years: int,
    ) -> None:
        """P7: Email subject contains rego and 'Service History Report'."""
        rego = vehicle["rego"]
        subject = f"{rego} - Service History Report"

        assert rego in subject, (
            f"Subject {subject!r} does not contain rego {rego!r}"
        )
        assert "Service History Report" in subject, (
            f"Subject {subject!r} does not contain 'Service History Report'"
        )

    @given(
        org=org_strategy,
        vehicle=vehicle_email_strategy,
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    def test_email_body_contains_vehicle_details_and_date_range(
        self,
        org: dict,
        vehicle: dict,
        range_years: int,
    ) -> None:
        """P7: Email body contains rego, make, model, year (when set), and date range label."""
        date_range_label = _DATE_RANGE_LABELS.get(range_years, f"Last {range_years} Years")
        generated_date = date.today().strftime("%d %b %Y")

        email_template = _JINJA_ENV.get_template("service_history_email.html")
        body = email_template.render(
            org=org,
            vehicle=vehicle,
            date_range_label=date_range_label,
            generated_date=generated_date,
        )

        rego = vehicle["rego"]
        make = vehicle["make"]
        model = vehicle["model"]
        year = vehicle["year"]

        assert rego in body, (
            f"Email body does not contain rego {rego!r}"
        )
        assert make in body, (
            f"Email body does not contain make {make!r}"
        )
        assert model in body, (
            f"Email body does not contain model {model!r}"
        )
        if year is not None:
            assert str(year) in body, (
                f"Email body does not contain year {year!r}"
            )
        assert date_range_label in body, (
            f"Email body does not contain date_range_label {date_range_label!r}"
        )


import re


# ---------------------------------------------------------------------------
# Strategies for Property 8
# ---------------------------------------------------------------------------

# Non-empty alphanumeric-ish rego strings (letters, digits, hyphens, spaces)
rego_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=48, max_codepoint=122),
    min_size=1,
    max_size=15,
).filter(lambda s: s.strip() != "")

generation_date_strategy = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))


# ===========================================================================
# Property 8: PDF attachment filename format
# Feature: service-history-report, Property 8: PDF attachment filename format
# ===========================================================================


class TestP8PdfAttachmentFilenameFormat:
    """For any vehicle registration string and generation date, the PDF
    attachment filename SHALL match the pattern
    `{rego}_service_history_{YYYY-MM-DD}.pdf`.

    **Validates: Requirements 7.4**
    """

    @given(
        rego=rego_strategy,
        gen_date=generation_date_strategy,
    )
    @PBT_SETTINGS_100
    def test_filename_matches_expected_pattern(
        self,
        rego: str,
        gen_date: date,
    ) -> None:
        """P8: Filename matches ^.+_service_history_\\d{4}-\\d{2}-\\d{2}\\.pdf$."""
        filename = f"{rego}_service_history_{gen_date.strftime('%Y-%m-%d')}.pdf"

        pattern = r"^.+_service_history_\d{4}-\d{2}-\d{2}\.pdf$"
        assert re.match(pattern, filename), (
            f"Filename {filename!r} does not match pattern {pattern!r}"
        )


# ===========================================================================
# Property 9: 404 for non-existent or wrong-org vehicle
# Feature: service-history-report, Property 9: 404 for non-existent or wrong-org vehicle
# ===========================================================================

import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.modules.vehicles.report_service import generate_service_history_pdf


def _mock_scalar_none():
    """Return a mock execute result where scalar_one_or_none() returns None."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    return result


class TestP9NotFoundForNonExistentOrWrongOrgVehicle:
    """For any randomly generated vehicle UUID that does not exist in the
    database, or any vehicle that belongs to a different organisation, the
    report generation function SHALL raise an HTTPException with status_code
    404.

    **Validates: Requirements 8.3**
    """

    @given(
        vehicle_id=st.uuids(),
        org_id=st.uuids(),
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    @pytest.mark.asyncio
    async def test_random_uuids_return_404(
        self,
        vehicle_id: _uuid.UUID,
        org_id: _uuid.UUID,
        range_years: int,
    ) -> None:
        """P9: Random UUIDs that don't exist in DB produce 404."""
        import sys
        from unittest.mock import patch

        # Ensure weasyprint can be imported even if not installed (the
        # function imports it at the top of its body, before the DB queries).
        weasyprint_mock = MagicMock()
        modules_patch = {
            "weasyprint": weasyprint_mock,
        }

        # Mock an AsyncSession where all queries return None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_none())

        with patch.dict(sys.modules, modules_patch):
            with pytest.raises(HTTPException) as exc_info:
                await generate_service_history_pdf(
                    db,
                    org_id=org_id,
                    vehicle_id=vehicle_id,
                    range_years=range_years,
                )

        assert exc_info.value.status_code == 404, (
            f"Expected 404, got {exc_info.value.status_code} for "
            f"vehicle_id={vehicle_id}, org_id={org_id}"
        )


# ===========================================================================
# Property 10: 422 for invalid email format
# Feature: service-history-report, Property 10: 422 for invalid email format
# ===========================================================================

from app.modules.vehicles.report_service import email_service_history_report


# Strategy: generate strings that are NOT valid emails.
# The regex used by the service is:
#   r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
# We generate several categories of invalid strings:
#   - strings without @ symbol
#   - strings with @ but no domain part (e.g. "user@")
#   - strings with @ but no TLD (e.g. "user@host")
#   - empty strings
#   - strings with spaces

_no_at_symbol = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=40,
).filter(lambda s: "@" not in s)

_at_no_domain = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=15,
).map(lambda s: f"{s}@")

_at_no_tld = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=1,
    max_size=15,
).map(lambda local: f"{local}@hostonly")

_with_spaces = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        min_codepoint=48,
        max_codepoint=122,
    ),
    min_size=2,
    max_size=30,
).filter(lambda s: " " in s).map(lambda s: f"{s}@example.com")

_empty_string = st.just("")

_invalid_email_strategy = st.one_of(
    _no_at_symbol,
    _at_no_domain,
    _at_no_tld,
    _with_spaces,
    _empty_string,
)


class TestP10InvalidEmailFormat422:
    """For any string that is not a valid email address (missing @, missing
    domain, etc.), the email endpoint SHALL return a 422 validation error.

    **Validates: Requirements 8.4**
    """

    @given(
        invalid_email=_invalid_email_strategy,
        vehicle_id=st.uuids(),
        org_id=st.uuids(),
        range_years=range_years_strategy,
    )
    @PBT_SETTINGS_100
    @pytest.mark.asyncio
    async def test_invalid_email_returns_422(
        self,
        invalid_email: str,
        vehicle_id: _uuid.UUID,
        org_id: _uuid.UUID,
        range_years: int,
    ) -> None:
        """P10: Non-email strings produce HTTPException with status_code 422."""
        # The function validates email format before any DB interaction,
        # so a mock AsyncSession is sufficient.
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await email_service_history_report(
                db,
                org_id=org_id,
                vehicle_id=vehicle_id,
                range_years=range_years,
                recipient_email=invalid_email,
            )

        assert exc_info.value.status_code == 422, (
            f"Expected 422, got {exc_info.value.status_code} for "
            f"invalid email {invalid_email!r}"
        )
        assert "Invalid email format" in exc_info.value.detail, (
            f"Expected 'Invalid email format' in detail, got {exc_info.value.detail!r}"
        )
