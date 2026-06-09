"""Integration test for ``app.modules.ppsr.pdf`` (task C4 / E2).

Verifies that ``render_pdf`` builds the right Jinja context and emits
every required section in the rendered HTML before WeasyPrint
serialises it to PDF bytes:

  - rego (1.4.1 — both visual and textual signal)
  - money-owing banner with the literal headline
    ``"Money Owing — Match: Yes"`` when ``match='Y'`` (asserted by
    design.md §6.0)
  - financing-statement count + secured-party rows
  - PPSR disclaimer footer text
  - searcher block + search timestamp

Approach: we **patch ``weasyprint.HTML`` inside the pdf module** and
capture the HTML string that gets passed in. We then assert on that
string directly. This is the reliable path inside CI containers that
ship WeasyPrint native deps but not a PDF text-extraction library —
parsing real PDF bytes would require pypdf or pdfminer.six, neither of
which is in the production image. The task description explicitly
calls this strategy out:

    "If WeasyPrint is hard to test in the CI container (sometimes the
    container doesn't have system fonts), the test can use
    ``mock.patch`` on ``HTML.write_pdf`` to assert the right Jinja
    context was built rather than running real WeasyPrint. Pick
    whatever is reliable."

We also exercise the "happy path" where real WeasyPrint produces PDF
bytes — that's the ``test_real_render_returns_pdf_bytes`` case,
gated behind ``pytest.importorskip('weasyprint')`` so it skips
cleanly on machines without the native deps.

Pattern borrowed from
``tests/integration/test_payslip_pdf_integration.py``.

**Validates: Requirements R6.3 — PPSR module Phase 1, task C4.**
"""

from __future__ import annotations

# Resolve mappers eagerly — pdf.py imports Organisation + User
# transitively.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.ppsr.models  # noqa: F401

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_search_row(
    *,
    rego: str = "ABC123",
    match: str | None = "Y",
    statement_count: int = 2,
    not_found: bool = False,
    charges_cents: int | None = 50,
    forgotten_at: datetime | None = None,
):
    """Build a SimpleNamespace with all the attributes pdf.py reads.

    Using SimpleNamespace rather than the real ORM row keeps the test
    decoupled from the database (the renderer accesses fields via
    ``getattr(search, ...)`` / direct attribute access only).
    """

    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        rego=rego,
        match=match,
        statement_count=statement_count,
        not_found=not_found,
        charges_cents=charges_cents,
        carjam_request_id="cj-req-12345",
        forgotten_at=forgotten_at,
        created_at=datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc),
    )


def _sample_decrypted(*, match: str = "Y") -> dict:
    """Build a representative decrypted CarJam payload."""

    return {
        "money_owing": {
            "match": match,
            "match_description": (
                "An exact-match registered financing statement was found "
                "against this vehicle."
                if match in ("Y", "PY")
                else "No financing statement matches were found."
            ),
            "search_id": "carjam-search-001",
        },
        "basic": {
            "make": "Toyota",
            "model": "Hilux SR5",
            "year": "2018",
            "colour": "Silver",
        },
        "ppsr_details": [
            {
                "registration_number": "1234567",
                "secured_party": "Acme Finance Ltd",
                "collateral_description": (
                    "All present and after-acquired motor vehicles."
                ),
                "registration_date": "2024-02-14",
                "expiry_date": "2029-02-14",
            },
            {
                "registration_number": "7654321",
                "secured_party": "Big Bank NZ",
                "collateral_description": "Specific motor vehicle.",
                "registration_date": "2023-11-01",
                "expiry_date": "2028-11-01",
            },
        ],
        "warnings": [
            {
                "severity": "high",
                "type": "Recall",
                "description": "Open recall: airbag inflator replacement.",
                "date": "2025-09-15",
            },
        ],
        "ownership_history": [],
        "current_owner": None,
    }


class _CapturingHTML:
    """Stand-in for ``weasyprint.HTML``.

    Records the ``string=`` keyword arg so the test can introspect the
    rendered HTML, then returns a stub that produces a minimal but
    valid PDF byte string from ``write_pdf()`` — enough to satisfy
    ``startswith(b"%PDF-")`` checks without invoking the real
    WeasyPrint pipeline.
    """

    captured_html: list[str] = []

    def __init__(self, *, string: str | None = None, **_kwargs):
        if string is not None:
            type(self).captured_html.append(string)
        self._string = string or ""

    def write_pdf(self) -> bytes:
        # Real PDFs start with `%PDF-1.x` and a binary marker comment;
        # this stub mimics the prefix so any caller doing a sanity
        # check on `pdf_bytes.startswith(b"%PDF-")` still passes.
        return b"%PDF-1.7\n% stub for tests\n"


def _patched_render(row, decrypted, db=None):
    """Deprecated sync wrapper kept for symmetry — all real call-sites
    use the async path :func:`_async_patched_render`. Raises so any
    accidental sync caller fails loudly.
    """

    raise RuntimeError(
        "Use _async_patched_render under @pytest.mark.asyncio — "
        "the renderer is async-only.",
    )


async def _async_patched_render(row, decrypted, db=None) -> tuple[bytes, str]:
    """Async-aware variant — used by the ``@pytest.mark.asyncio`` tests."""

    from app.modules.ppsr import pdf as ppsr_pdf

    _CapturingHTML.captured_html = []

    with patch("weasyprint.HTML", _CapturingHTML):
        pdf_bytes = await ppsr_pdf.render_pdf(row, decrypted, db=db)

    assert _CapturingHTML.captured_html, (
        "render_pdf did not invoke HTML(string=...)"
    )
    return pdf_bytes, _CapturingHTML.captured_html[-1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPpsrPdfRender:
    """Render the report HTML and assert every required section."""

    @pytest.mark.asyncio
    async def test_money_owing_match_y_emits_yes_banner(self):
        """``money_owing.match='Y'`` → banner emits the literal
        ``"Money Owing — Match: Yes"`` headline. The integration test
        asserts on this exact string per design.md §6.0.
        """

        row = _make_search_row(rego="ABC123", match="Y", statement_count=2)
        decrypted = _sample_decrypted(match="Y")

        pdf_bytes, html = await _async_patched_render(row, decrypted, db=None)

        assert pdf_bytes.startswith(b"%PDF-")

        # ---- Rego (uppercase, prominent in meta grid) ----
        assert "ABC123" in html

        # ---- Money-owing banner (literal headline string) ----
        # The em-dash in the headline is U+2014; the template renders
        # it verbatim. Jinja autoescape doesn't touch the em-dash.
        assert "Money Owing \u2014 Match: Yes" in html, (
            "Banner did not emit the expected headline string for "
            f"match='Y'. HTML excerpt: {html[:600]!r}"
        )

        # ---- CSS class flagging the red banner — visual wiring proof. ----
        assert "banner-red" in html

        # ---- Match description present ----
        assert "financing statement" in html

        # ---- Statement count surfaced ----
        assert "Statements: 2" in html

        # ---- Financing-statements section ----
        assert "Financing statements (2)" in html
        assert "Acme Finance Ltd" in html
        assert "Big Bank NZ" in html

        # ---- Vehicle summary ----
        assert "Toyota" in html
        assert "Hilux SR5" in html
        assert "Silver" in html
        assert "2018" in html

        # ---- Search timestamp ----
        # _format_timestamp emits "01 Jun 2026 14:30 UTC".
        assert "01 Jun 2026" in html
        assert "UTC" in html

        # ---- Searcher block (blank when db=None — safe fallback) ----
        # Renderer must not raise on the empty searcher dict.
        assert "Searched by" in html

        # ---- Disclaimer footer text ----
        assert "PPSR report was generated via the CarJam API" in html
        assert "Independent legal advice" in html

        # ---- Page X of N footer wired via WeasyPrint CSS counters. ----
        # The CSS lives inline in the rendered HTML so we can assert on
        # the counter rule directly.
        assert 'counter(page) " of " counter(pages)' in html

    @pytest.mark.asyncio
    async def test_money_owing_match_n_emits_clear_banner(self):
        """``match='N'`` → green banner with the "No Money Owing"
        headline. Confirms the CSS-class / headline lookup table covers
        the green path.
        """

        row = _make_search_row(rego="CLR999", match="N", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []

        pdf_bytes, html = await _async_patched_render(row, decrypted, db=None)
        assert pdf_bytes.startswith(b"%PDF-")

        assert "CLR999" in html
        assert "No Money Owing" in html
        # Green banner CSS class.
        assert "banner-green" in html
        # No financing-statement section when there are no statements.
        assert "Financing statements (" not in html

    @pytest.mark.asyncio
    async def test_money_owing_match_m_emits_amber_banner(self):
        """``match='M'`` → amber banner. Covers the "match found but
        no money owing" code path."""

        row = _make_search_row(rego="AMB100", match="M", statement_count=1)
        decrypted = _sample_decrypted(match="N")  # description doesn't matter
        decrypted["money_owing"]["match"] = "M"

        _, html = await _async_patched_render(row, decrypted, db=None)
        assert "banner-amber" in html
        assert "Match Found" in html

    @pytest.mark.asyncio
    async def test_money_owing_match_u_emits_grey_banner(self):
        """``match='U'`` → grey banner. Covers the unknown path."""

        row = _make_search_row(rego="UNK100", match="U", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["money_owing"]["match"] = "U"

        _, html = await _async_patched_render(row, decrypted, db=None)
        assert "banner-grey" in html
        assert "Match: Unknown" in html

    @pytest.mark.asyncio
    async def test_not_found_row_does_not_crash_and_shows_placeholder(self):
        """When CarJam returned ``not_found=true`` the renderer must
        still produce a valid HTML — the banner area renders the
        "Vehicle not found" placeholder instead of the money-owing
        banner, and the vehicle / financing sections are suppressed.
        """

        row = _make_search_row(
            rego="MISSING1",
            match=None,
            statement_count=0,
            not_found=True,
            charges_cents=None,
        )
        # Empty decrypted payload — typical for a not_found row.
        pdf_bytes, html = await _async_patched_render(row, {}, db=None)
        assert pdf_bytes.startswith(b"%PDF-")

        assert "MISSING1" in html
        # Placeholder banner.
        assert "Vehicle not found" in html
        # Money-owing-specific content must not appear inside the
        # rendered banner div. (The CSS comments in `report.css` mention
        # the headline string in their docstring — we deliberately
        # search the body section, not the inlined `<style>` block.)
        body = html.split("</style>", 1)[-1]
        assert "Money Owing \u2014 Match" not in body
        # Disclaimer must still be present even for not_found rows.
        assert "PPSR report was generated via the CarJam API" in html

    @pytest.mark.asyncio
    async def test_ownership_section_renders_when_s241_present(self):
        """Ownership table only appears when the decrypted payload has
        ``ownership_history`` rows or a ``current_owner`` dict — i.e.
        the search was an s241-authorised lookup.
        """

        row = _make_search_row(rego="OWN001", match="N", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []
        decrypted["current_owner"] = {
            "name": "Jane Owner",
            "from_date": "2022-04-01",
        }
        decrypted["ownership_history"] = [
            {
                "name": "John Previous",
                "from_date": "2018-01-15",
                "to_date": "2022-03-31",
                "status": "transferred",
            },
        ]

        _, html = await _async_patched_render(row, decrypted, db=None)

        assert "Ownership" in html
        assert "Current owner" in html
        assert "Jane Owner" in html
        assert "John Previous" in html
        assert "transferred" in html

    @pytest.mark.asyncio
    async def test_ownership_section_omitted_when_no_s241_data(self):
        """When ``ownership_history`` is empty AND ``current_owner`` is
        None, the ownership block must NOT render — the test guards
        the s241-gated content from leaking into non-authorised
        searches.
        """

        row = _make_search_row(rego="NONS241", match="N", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []
        decrypted["ownership_history"] = []
        decrypted["current_owner"] = None

        _, html = await _async_patched_render(row, decrypted, db=None)

        assert "<h2>Ownership</h2>" not in html

    @pytest.mark.asyncio
    async def test_render_pdf_third_arg_is_optional(self):
        """The ``db`` argument is optional — calling
        ``render_pdf(row, decrypted)`` (two-arg form, used by the
        service caller path) must work without raising.
        """

        from app.modules.ppsr import pdf as ppsr_pdf

        row = _make_search_row(rego="TWO001", match="N", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []

        _CapturingHTML.captured_html = []
        with patch("weasyprint.HTML", _CapturingHTML):
            # Two-arg call — `db` defaults to None.
            pdf_bytes = await ppsr_pdf.render_pdf(row, decrypted)

        assert pdf_bytes.startswith(b"%PDF-")
        assert _CapturingHTML.captured_html  # template rendered

    @pytest.mark.asyncio
    async def test_warnings_section_renders_with_severity_class(self):
        """Each warning row carries a CSS class derived from severity
        so the printed report colour-codes high-severity warnings.
        """

        row = _make_search_row(rego="WRN001", match="N", statement_count=0)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []
        decrypted["warnings"] = [
            {
                "severity": "high",
                "type": "Recall",
                "description": "Airbag recall.",
                "date": "2025-01-01",
            },
        ]

        _, html = await _async_patched_render(row, decrypted, db=None)
        assert "Warnings" in html
        assert "warning-high" in html
        assert "Airbag recall" in html

    @pytest.mark.asyncio
    async def test_charges_line_never_rendered_even_when_charges_present(self):
        """The CarJam-reported per-check charge MUST NOT appear on the
        rendered PDF — org users must not see the wholesale CarJam cost.
        The platform sets the customer-facing price via Global Admin
        settings and bills the org accordingly via ``app/tasks/subscriptions.py``.
        ``charges_cents`` stays on the DB row for that billing aggregation,
        but the PDF template's old charges line was deliberately removed
        and the PDF context dict no longer surfaces the field.

        Locks the regression: any future change that re-introduces the
        charge to the PDF will fail this test.
        """

        row = _make_search_row(rego="CHG001", match="N", charges_cents=125)
        decrypted = _sample_decrypted(match="N")
        decrypted["ppsr_details"] = []

        _, html = await _async_patched_render(row, decrypted, db=None)

        # Old "CarJam reported a charge" copy must be gone.
        assert "CarJam reported a charge" not in html
        # Defence in depth: the formatted dollar value must not leak
        # via any other surface either.
        assert "NZD 1.25" not in html
        assert "$1.25" not in html
        # The disclaimer block stays — it doesn't mention pricing.
        assert "PPSR report" in html or "CarJam API" in html

    @pytest.mark.asyncio
    async def test_real_render_returns_pdf_bytes(self):
        """**Smoke check** that real WeasyPrint produces valid PDF bytes
        without raising. We don't parse the bytes (that needs pypdf or
        pdfminer.six which aren't always installed in the CI image) —
        we just confirm the renderer wires WeasyPrint up correctly and
        emits something starting with ``%PDF-``.

        Skipped on platforms missing the native libpango / libcairo.
        """

        pytest.importorskip(
            "weasyprint",
            reason="WeasyPrint native deps (libpango / libcairo) not installed",
        )

        from app.modules.ppsr.pdf import render_pdf

        row = _make_search_row(rego="REAL001", match="Y", statement_count=1)
        decrypted = _sample_decrypted(match="Y")

        pdf_bytes = await render_pdf(row, decrypted, db=None)
        assert pdf_bytes.startswith(b"%PDF-")
        # A trivially-rendered single-page PPSR report easily exceeds
        # 2 KB; anything below that is a sign the template silently
        # returned an empty body.
        assert len(pdf_bytes) > 2000, (
            f"PDF bytes are suspiciously short ({len(pdf_bytes)}); "
            "template likely rendered an empty body"
        )
