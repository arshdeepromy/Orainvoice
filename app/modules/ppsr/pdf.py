"""WeasyPrint PPSR PDF rendering (task C4 — design.md §4.3 + §4.3a).

Renders a saved :class:`PpsrSearch` into a branded PDF report using the
project-standard module-local Jinja templates pattern (mirrors
``app/modules/payslips/pdf.py`` and the invoice/quote PDF paths in
``app/modules/{invoices,quotes}/service.py``).

Sections rendered (per design.md §4.3a):

  - Org logo (resolved via :func:`app.core.pdf_utils.resolve_logo_for_pdf`),
    org name + address sourced from ``organisations.settings`` JSONB
    (the org has no ``address_line_*`` columns — every address field
    lives inside the JSONB blob).
  - Searcher name + email (loaded from the ``users`` row referenced by
    ``ppsr_searches.user_id``).
  - Search timestamp (UTC, formatted ``DD MMM YYYY HH:MM UTC``).
  - Rego + basic vehicle summary (make / model / year / colour) drawn
    from the decrypted CarJam ``basic`` payload.
  - Money-owing banner — the banner colour is driven by the
    ``money_owing.match`` flag (``Y``/``PY`` red, ``M``/``PM`` amber,
    ``U`` grey, ``N`` green); when the row is ``not_found=true`` a
    "Vehicle not found" placeholder renders in place of the banner.
    The exact string ``"Money Owing — Match: Yes"`` is emitted when
    ``match='Y'`` (asserted by the integration test).
  - Financing-statement table (when ``ppsr_details`` is non-empty).
  - Warnings rows (when present).
  - Ownership history table (when ``ownership_history`` is non-empty
    or ``current_owner`` is set — i.e. an s241-authorised lookup).
  - Footer with PPSR disclaimer + ``Page X of N`` via WeasyPrint CSS
    counters.

WeasyPrint is CPU-heavy (200-1500 ms per page) so the actual
``HTML(string=...).write_pdf()`` call is dispatched off the event loop
via :func:`asyncio.to_thread`. Pattern borrowed from
``app/modules/quotes/service.py:1162-1165`` and
``app/modules/invoices/service.py:4449-4452``.

The third ``db`` argument is optional (the public surface declared by
the service caller is ``render_pdf(row, decrypted)``); when supplied,
the renderer loads the org + user rows so the header / searcher block
populates with real branding. When ``db is None`` (or a load fails)
the renderer still emits a valid PDF using sensible blank fallbacks —
the test environment uses this path to avoid spinning up a full DB.

Refs: requirements R6.3; design.md §4.3 / §4.3a; tasks.md C4.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pdf_utils import resolve_logo_for_pdf
from app.modules.admin.models import Organisation
from app.modules.auth.models import User
from app.modules.ppsr.models import PpsrSearch

logger = logging.getLogger(__name__)


__all__ = ["render_pdf"]


# ---------------------------------------------------------------------------
# Module-local template directory (mirrors payslip/quote/invoice convention)
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"
_TEMPLATE_FILE = "report.html"
_CSS_FILE = "report.css"


# ---------------------------------------------------------------------------
# CSS class lookup for the money-owing banner (design.md §6.0 traffic light)
# ---------------------------------------------------------------------------

# Maps CarJam ``money_owing.match`` codes to the CSS class on the banner.
# Y = matched, money owing → red.
# PY = possible match, money owing → red-amber (sits with red).
# M = matched, no money owing → amber.
# PM = possible match, no money owing → amber.
# U = unknown / could not determine → grey.
# N = no match (clear) → green.
_MATCH_CSS = {
    "Y": "banner-red",
    "PY": "banner-red",
    "M": "banner-amber",
    "PM": "banner-amber",
    "U": "banner-grey",
    "N": "banner-green",
}

# Human-readable headline for each match. The "Yes"/"No"/etc. wording is
# what the test asserts on for ``match='Y'`` (the banner emits the literal
# string ``"Money Owing — Match: Yes"``).
_MATCH_HEADLINE = {
    "Y": "Money Owing — Match: Yes",
    "PY": "Money Owing — Match: Possibly Yes",
    "M": "Match Found — No Money Owing",
    "PM": "Possible Match — No Money Owing",
    "U": "Match: Unknown",
    "N": "No Money Owing — Clear",
}


# ---------------------------------------------------------------------------
# Org context builder (design.md §4.3a — `settings` JSONB only, no columns)
# ---------------------------------------------------------------------------


def _build_org_ctx(org: Organisation | None) -> dict[str, Any]:
    """Build the ``org_ctx`` dict consumed by the Jinja template.

    Per design.md §4.3a the organisation has no ``address_line_*``
    columns — every address field lives inside the ``settings`` JSONB
    blob. Mirrors the same shape used by the invoice / quote PDF paths
    (`app/modules/invoices/service.py:4257-4297`).
    """

    if org is None:
        return {
            "name": "",
            "logo_url": None,
            "address_unit": None,
            "address_street": None,
            "address_city": None,
            "address_state": None,
            "address_postcode": None,
            "address_country": None,
            "phone": None,
            "email": None,
            "website": None,
            "gst_number": None,
            "primary_colour": "#1a1a1a",
        }

    settings = getattr(org, "settings", None) or {}
    return {
        "name": getattr(org, "name", "") or "",
        "logo_url": resolve_logo_for_pdf(org),
        "address_unit": settings.get("address_unit"),
        "address_street": settings.get("address_street"),
        "address_city": settings.get("address_city"),
        "address_state": settings.get("address_state"),
        "address_postcode": settings.get("address_postcode"),
        "address_country": settings.get("address_country"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "website": settings.get("website"),
        "gst_number": settings.get("gst_number"),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
    }


def _build_searcher_ctx(user: User | None) -> dict[str, Any]:
    """Build the searcher block (name + email) for the report header."""

    if user is None:
        return {"name": "", "email": ""}

    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "last_name", None) or "").strip()
    full = f"{first} {last}".strip()
    return {
        "name": full or first or last or (getattr(user, "email", "") or ""),
        "email": getattr(user, "email", "") or "",
    }


def _build_money_owing_ctx(money_owing: Any, *, not_found: bool) -> dict[str, Any]:
    """Resolve banner-styling + headline for the money-owing block.

    Returns ``None``-safe values so the template can render a blank
    "vehicle not found" placeholder when the upstream lookup found no
    record. The headline string is exact-match asserted on by the
    integration test for ``match='Y'``.
    """

    if not_found:
        return {
            "show_banner": False,
            "css_class": "banner-grey",
            "headline": "Vehicle not found",
            "description": (
                "CarJam returned no record for this rego. "
                "No PPSR check was performed."
            ),
            "match": None,
        }

    mo = money_owing if isinstance(money_owing, dict) else {}
    raw_match = mo.get("match")
    match_code = (str(raw_match).strip().upper() if raw_match else "") or "U"
    css_class = _MATCH_CSS.get(match_code, "banner-grey")
    headline = _MATCH_HEADLINE.get(match_code, f"Match: {match_code}")
    description = mo.get("match_description") or ""
    return {
        "show_banner": True,
        "css_class": css_class,
        "headline": headline,
        "description": description,
        "match": match_code,
    }


def _format_timestamp(value: datetime | None) -> str:
    """Format a search timestamp for the PDF header."""

    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def render_pdf(
    search: PpsrSearch,
    decrypted: dict[str, Any] | None,
    db: AsyncSession | None = None,
) -> bytes:
    """Render a PPSR search to PDF bytes.

    Parameters
    ----------
    search:
        The :class:`PpsrSearch` ORM row. ``rego``, ``match``,
        ``statement_count``, ``created_at``, ``not_found``,
        ``charges_cents``, ``carjam_request_id`` are read directly off
        the row.
    decrypted:
        The decrypted CarJam payload (a dict — typically the
        ``json.loads(envelope_decrypt_str(...))`` of
        ``response_encrypted``). May be ``None`` or empty when the row
        is forgotten / not_found.
    db:
        Optional async session used to load the org + user records for
        branding + searcher attribution. When ``None`` the renderer
        emits the report with blank fallbacks. The third argument is
        optional because the service caller invokes ``render_pdf(row,
        decrypted)``; the router passes ``self.db`` so the production
        path always has full org branding.

    Returns
    -------
    bytes
        The rendered PDF document. Always starts with ``b"%PDF-"``.
    """

    decrypted = decrypted or {}

    # Lazy-import jinja + weasyprint so importing this module is cheap
    # for tests that don't render (mirrors the payslip pattern).
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    # ---- Load org + user rows when a session is available ----
    org: Organisation | None = None
    user: User | None = None
    if db is not None:
        try:
            org_q = await db.execute(
                select(Organisation).where(Organisation.id == search.org_id),
            )
            org = org_q.scalar_one_or_none()
        except Exception as exc:  # pragma: no cover — best-effort branding
            logger.warning(
                "PPSR PDF: failed to load org %s for branding: %s",
                search.org_id,
                exc,
            )
        try:
            user_q = await db.execute(
                select(User).where(User.id == search.user_id),
            )
            user = user_q.scalar_one_or_none()
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "PPSR PDF: failed to load user %s for searcher block: %s",
                search.user_id,
                exc,
            )

    org_ctx = _build_org_ctx(org)
    searcher_ctx = _build_searcher_ctx(user)

    # ---- Pull structured sections out of the decrypted payload ----
    money_owing_raw = decrypted.get("money_owing")
    money_owing_ctx = _build_money_owing_ctx(
        money_owing_raw,
        not_found=bool(getattr(search, "not_found", False)),
    )

    basic = decrypted.get("basic") if isinstance(decrypted.get("basic"), dict) else {}
    ppsr_details = list(decrypted.get("ppsr_details") or [])
    warnings = list(decrypted.get("warnings") or [])
    ownership_history = list(decrypted.get("ownership_history") or [])
    current_owner = decrypted.get("current_owner") if isinstance(
        decrypted.get("current_owner"), dict,
    ) else None
    has_ownership = bool(ownership_history) or current_owner is not None

    # ---- Inline CSS so the template is self-contained ----
    css_path = _TEMPLATE_DIR / _CSS_FILE
    inline_css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    # ---- Jinja env (module-local templates dir) ----
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template(_TEMPLATE_FILE)

    html_content = template.render(
        org=org_ctx,
        searcher=searcher_ctx,
        search={
            "rego": getattr(search, "rego", ""),
            "match": getattr(search, "match", None),
            "statement_count": int(getattr(search, "statement_count", 0) or 0),
            "charges_cents": getattr(search, "charges_cents", None),
            "carjam_request_id": getattr(search, "carjam_request_id", None),
            "not_found": bool(getattr(search, "not_found", False)),
            "created_at_display": _format_timestamp(
                getattr(search, "created_at", None),
            ),
        },
        basic=basic or {},
        money_owing=money_owing_ctx,
        ppsr_details=ppsr_details,
        warnings=warnings,
        ownership_history=ownership_history,
        current_owner=current_owner,
        has_ownership=has_ownership,
        inline_css=inline_css,
    )

    # WeasyPrint is CPU-heavy — keep it off the event loop
    # (PERFORMANCE_AUDIT.md §B-H1; mirrors invoices/quotes pattern).
    pdf_bytes: bytes = await asyncio.to_thread(
        lambda: HTML(string=html_content).write_pdf(),
    )
    return pdf_bytes
