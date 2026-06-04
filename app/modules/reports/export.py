"""Server-side report export layer.

Pure CSV rendering for the org-level reports hub. Each report key registers a
builder that turns its service return-dict into a ``(header, rows)`` pair, and
``render_report_csv`` writes those into UTF-8 CSV bytes.

The CSV builders are deliberately pure (no DB/IO) so they can be exercised
directly by property-based tests (round-trip of numeric figures to 2dp).

Numeric/decimal cells are formatted to two decimal places. All access to the
report dict is defensive (``data.get(...)`` with sensible defaults and ``or []``
for list fields) so a missing or partial dict never raises.

The WeasyPrint PDF renderer (``render_report_pdf``) renders a Jinja template
(per-report, falling back to ``generic.html``) and dispatches the CPU-heavy
``HTML(...).write_pdf()`` call off the event loop via ``asyncio.to_thread``
(PERFORMANCE_AUDIT.md §B-H1; mirrors ``app/modules/{payslips,ppsr}/pdf.py`` and
the invoice/quote PDF paths). ``weasyprint`` and ``jinja2`` are imported LAZILY
inside ``render_report_pdf`` so this module stays import-safe without WeasyPrint
installed (the CSV registry + ``render_report_csv`` import fine regardless).

Requirements: 10.3, 10.4, 10.5, 20.5
Design: §"C1 — Export layer", §"Export flow (C1)" sequence diagram,
§"Performance Considerations"
"""

from __future__ import annotations

import asyncio
import csv
import io
import pathlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

# Module-local templates dir (mirrors the payslips/ppsr/invoices convention).
_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"

# Each report registers: a header row + a function turning the report dict into
# rows. The function returns ``(header, rows)``.
CsvBuilder = Callable[[dict], tuple[list[str], list[list]]]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _money(value: Any) -> str:
    """Format a numeric/decimal value to 2 decimal places, safely.

    Coerces ``None``, ints, floats, Decimals, and numeric strings. Any value
    that cannot be parsed as a number falls back to ``"0.00"`` so a partial or
    malformed dict never crashes the export.
    """
    if value is None:
        return "0.00"
    try:
        return f"{Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return "0.00"


def _text(value: Any, default: str = "") -> str:
    """Stringify a value, mapping ``None`` to a sensible default."""
    if value is None:
        return default
    return str(value)


def _int(value: Any) -> int:
    """Coerce a value to int, safely (defaults to 0)."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(Decimal(str(value)))
        except (InvalidOperation, ValueError, TypeError):
            return 0


# ---------------------------------------------------------------------------
# Per-report CSV builders
# ---------------------------------------------------------------------------

def _revenue_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Month", "Revenue (NZD)"]
    rows: list[list] = [
        [_text(m.get("month")), _money(m.get("revenue"))]
        for m in (data.get("monthly_breakdown") or [])
    ]
    rows.append(["TOTAL", _money(data.get("total_inclusive", 0))])
    return header, rows


def _invoice_status_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Status", "Count", "Total (NZD)"]
    rows = [
        [_text(b.get("status")), _int(b.get("count")), _money(b.get("total"))]
        for b in (data.get("breakdown") or [])
    ]
    return header, rows


def _top_services_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Service", "Count", "Revenue (NZD)"]
    rows = [
        [_text(s.get("description")), _int(s.get("count")), _money(s.get("total_revenue"))]
        for s in (data.get("services") or [])
    ]
    return header, rows


def _outstanding_csv(data: dict) -> tuple[list[str], list[list]]:
    header = [
        "Invoice",
        "Customer",
        "Vehicle",
        "Due Date",
        "Total (NZD)",
        "Balance Due (NZD)",
        "Days Overdue",
    ]
    rows = [
        [
            _text(inv.get("invoice_number")),
            _text(inv.get("customer_name")),
            _text(inv.get("vehicle_rego")),
            _text(inv.get("due_date")),
            _money(inv.get("total")),
            _money(inv.get("balance_due")),
            _int(inv.get("days_overdue")),
        ]
        for inv in (data.get("invoices") or [])
    ]
    return header, rows


def _gst_return_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Field", "Value (NZD)"]
    fields = [
        ("Total sales", "total_sales"),
        ("Total GST collected", "total_gst_collected"),
        ("Standard-rated sales", "standard_rated_sales"),
        ("Standard-rated GST", "standard_rated_gst"),
        ("Zero-rated sales", "zero_rated_sales"),
        ("Total purchases", "total_purchases"),
        ("Total input tax", "total_input_tax"),
        ("Net GST payable", "net_gst_payable"),
    ]
    rows = [[label, _money(data.get(key))] for label, key in fields]
    return header, rows


def _fleet_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Rego", "Make", "Model", "Total Spend (NZD)", "Last Service Date"]
    rows = [
        [
            _text(v.get("rego")),
            _text(v.get("make")),
            _text(v.get("model")),
            _money(v.get("total_spend")),
            _text(v.get("last_service_date")),
        ]
        for v in (data.get("vehicles") or [])
    ]
    return header, rows


def _storage_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Category", "Bytes"]
    rows = [
        [_text(b.get("category")), _int(b.get("bytes"))]
        for b in (data.get("breakdown") or [])
    ]
    return header, rows


def _sms_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Date", "SMS Count"]
    rows = [
        [_text(p.get("date")), _int(p.get("sms_count"))]
        for p in (data.get("daily_breakdown") or [])
    ]
    return header, rows


def _carjam_csv(data: dict) -> tuple[list[str], list[list]]:
    header = ["Date", "Lookups"]
    rows = [
        [_text(p.get("date")), _int(p.get("lookups"))]
        for p in (data.get("daily_breakdown") or [])
    ]
    return header, rows


def _customer_statement_csv(data: dict) -> tuple[list[str], list[list]]:
    header = [
        "Date",
        "Description",
        "Reference",
        "Debit (NZD)",
        "Credit (NZD)",
        "Balance (NZD)",
    ]
    rows = [
        [
            _text(item.get("date")),
            _text(item.get("description")),
            _text(item.get("reference")),
            _money(item.get("debit")),
            _money(item.get("credit")),
            _money(item.get("balance")),
        ]
        for item in (data.get("items") or [])
    ]
    return header, rows


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CSV_BUILDERS: dict[str, CsvBuilder] = {
    "revenue": _revenue_csv,
    "invoice_status": _invoice_status_csv,
    "top_services": _top_services_csv,
    "outstanding": _outstanding_csv,
    "gst_return": _gst_return_csv,
    "fleet": _fleet_csv,
    "storage": _storage_csv,
    "sms": _sms_csv,
    "carjam": _carjam_csv,
    "customer_statement": _customer_statement_csv,
}


def render_report_csv(report_key: str, data: dict) -> bytes:
    """Render a report dict to UTF-8 CSV bytes.

    Pure function (no DB/IO) so it is directly property-testable.

    Raises:
        KeyError: if ``report_key`` is not a registered report.
    """
    builder = CSV_BUILDERS[report_key]
    header, rows = builder(data or {})
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# PDF rendering (WeasyPrint, off the event loop)
# ---------------------------------------------------------------------------

def _prettify_key(report_key: str) -> str:
    """Turn a report key (``invoice_status``) into a title (``Invoice Status``)."""
    return (report_key or "report").replace("_", " ").replace("-", " ").strip().title()


async def render_report_pdf(report_key: str, data: dict, org) -> bytes:
    """Render a report dict to PDF bytes via WeasyPrint, off the event loop.

    Looks up a per-report Jinja template ``{report_key}.html`` and falls back to
    ``generic.html`` when one does not exist. The rendered HTML is handed to
    WeasyPrint inside :func:`asyncio.to_thread` so the heavy ``write_pdf`` call
    never blocks the event loop (R20.5; PERFORMANCE_AUDIT.md §B-H1).

    ``weasyprint`` and ``jinja2`` are imported lazily here (not at module top)
    so importing this module — and using the pure CSV renderer — stays cheap and
    works in environments without WeasyPrint installed.

    Args:
        report_key: The report identifier (e.g. ``"revenue"``); also used to
            pick the template and the prettified title.
        data: The report service return-dict. Access is defensive in the
            template so a missing/partial dict never raises.
        org: An org-like object exposing ``.name`` (used for branding). May be
            ``None``; the template guards for it.

    Returns:
        The rendered PDF document bytes (always starts with ``b"%PDF"``).
    """
    # Lazy imports — keep WeasyPrint + Jinja2 out of the module load path so
    # importing ``app.modules.reports.export`` is cheap and import-safe without
    # WeasyPrint (mirrors app/modules/{payslips,ppsr}/pdf.py).
    from jinja2 import Environment, FileSystemLoader
    from jinja2.exceptions import TemplateNotFound
    from weasyprint import HTML

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    # Money/decimal formatting helper exposed to templates.
    env.filters["money"] = _money

    try:
        template = env.get_template(f"{report_key}.html")
    except TemplateNotFound:
        template = env.get_template("generic.html")

    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    org_name = getattr(org, "name", None) or "Organisation"

    html_content = template.render(
        data=data or {},
        org=org,
        org_name=org_name,
        report_key=report_key,
        report_title=_prettify_key(report_key),
        generated_at=generated_at,
    )

    # WeasyPrint is CPU-heavy — keep it off the event loop (R20.5).
    pdf_bytes: bytes = await asyncio.to_thread(
        lambda: HTML(string=html_content).write_pdf(),
    )
    return pdf_bytes
