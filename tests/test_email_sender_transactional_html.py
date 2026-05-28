"""Unit tests for ``render_transactional_html``.

Why this exists: the four production sites (``email_invoice``,
``send_payment_reminder``, the quote send, and the payment receipt)
previously built HTML by ``text.replace("\\n", "<br>")``, which Gmail
treats as malformed and pairs with the financial-keyword + raw-URL
content of those messages to silently filter them post-accept. The
renderer this test covers replaces that pattern with a well-formed
HTML document, anchor-tagged URLs, and proper paragraph structure.

Tests focus on the deliverability-relevant invariants:
  * The output is a real HTML document (``<!DOCTYPE>``, ``<html>``,
    ``<head>`` with charset, ``<body>``).
  * Plain-text paragraphs become ``<p>`` blocks; soft newlines stay as
    ``<br>`` inside a paragraph.
  * URLs in the body get wrapped in ``<a href>`` anchors.
  * HTML-special characters in user content are escaped, so the renderer
    can't be turned into an XSS vector by an org-supplied org name or
    customer name that contains ``<script>``.
  * Optional org email signature is rendered after an ``<hr>``.
"""

from __future__ import annotations

from app.integrations.email_sender import render_transactional_html


# ---------------------------------------------------------------------------
# Document structure
# ---------------------------------------------------------------------------


def test_output_is_a_well_formed_html_document() -> None:
    """The renderer must produce a document with all the parts Gmail's
    content classifier expects: doctype, charset meta, viewport, body."""
    html = render_transactional_html("Hello world.")
    assert html.startswith("<!DOCTYPE html>")
    assert '<html lang="en">' in html
    assert '<meta charset="utf-8">' in html
    assert 'name="viewport"' in html
    assert "<body" in html
    assert "</body>" in html
    assert "</html>" in html


def test_subject_becomes_title() -> None:
    """The subject parameter is rendered as ``<title>`` so Gmail's
    snippet/preview rendering has something concrete to use."""
    html = render_transactional_html(
        "Hi", subject="Invoice INV-0042 from Acme"
    )
    assert "<title>Invoice INV-0042 from Acme</title>" in html


def test_subject_is_html_escaped_in_title() -> None:
    """A subject with special characters can't break out of ``<title>``."""
    html = render_transactional_html(
        "Hi", subject="Invoice <ABC> & 'co.'"
    )
    # All five HTML special chars escape correctly.
    assert "<title>Invoice &lt;ABC&gt; &amp; &#x27;co.&#x27;</title>" in html
    # And the literal angle brackets are NOT present in the title.
    assert "<title>Invoice <ABC>" not in html


def test_missing_subject_falls_back_to_generic_title() -> None:
    """No subject → a stable fallback title rather than an empty
    ``<title></title>`` (which some clients render as a blank tab)."""
    html = render_transactional_html("Hello")
    assert "<title>Notification</title>" in html


# ---------------------------------------------------------------------------
# Paragraph structure
# ---------------------------------------------------------------------------


def test_blank_lines_split_paragraphs() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    html = render_transactional_html(text)
    assert html.count("<p ") == 3
    assert "First paragraph." in html
    assert "Second paragraph." in html
    assert "Third paragraph." in html


def test_single_newline_inside_paragraph_becomes_br() -> None:
    """A single newline inside a paragraph is a soft wrap — render as
    ``<br>``, not as a paragraph split."""
    text = "Line one\nLine two"
    html = render_transactional_html(text)
    # One paragraph containing a <br>.
    assert html.count("<p ") == 1
    assert "Line one<br>Line two" in html


def test_runs_of_blank_lines_collapse_to_single_break() -> None:
    """Multiple blank lines between paragraphs are common in our
    templates (e.g. invoice fallback body). They must collapse to a
    single paragraph break, not produce empty ``<p>`` blocks."""
    text = "One\n\n\n\nTwo"
    html = render_transactional_html(text)
    assert html.count("<p ") == 2
    # No empty <p> blocks.
    assert '<p style="margin:0 0 16px 0"></p>' not in html


def test_empty_body_renders_as_empty_inner_div() -> None:
    """An empty body shouldn't crash and shouldn't produce stray
    paragraph tags — just the document chrome."""
    html = render_transactional_html("")
    assert "<!DOCTYPE html>" in html
    assert "<p " not in html


# ---------------------------------------------------------------------------
# URL linkification
# ---------------------------------------------------------------------------


def test_https_url_becomes_anchor_tag() -> None:
    """The single biggest deliverability fix: ``Pay online: https://...``
    must render as an ``<a href>`` anchor, not a raw URL string. Gmail's
    classifier weighs the latter against financial-keyword bodies."""
    text = "Pay online: https://example.com/pay/abc123"
    html = render_transactional_html(text)
    assert '<a href="https://example.com/pay/abc123">https://example.com/pay/abc123</a>' in html


def test_http_url_is_also_linkified() -> None:
    """Both ``http`` and ``https`` are linkified; we don't filter for
    https-only because some legacy environments use plain http."""
    text = "Visit http://example.com"
    html = render_transactional_html(text)
    assert '<a href="http://example.com">http://example.com</a>' in html


def test_trailing_punctuation_not_swallowed_into_url() -> None:
    """A URL at the end of a sentence (``...example.com.``) should
    keep the period outside the anchor tag — otherwise links break."""
    text = "See https://example.com."
    html = render_transactional_html(text)
    assert '<a href="https://example.com">https://example.com</a>.' in html


def test_url_inside_parentheses_strips_paren_from_href() -> None:
    """``(https://example.com)`` → anchor href is ``https://example.com``,
    not ``https://example.com)`` (which is technically a valid URL but
    almost never the intent in transactional copy)."""
    text = "see (https://example.com) for details"
    html = render_transactional_html(text)
    assert '<a href="https://example.com">https://example.com</a>' in html
    # The closing paren stays in the rendered text.
    assert "</a>) for details" in html


def test_multiple_urls_in_one_paragraph_all_linkified() -> None:
    text = "First https://a.test then https://b.test then done."
    html = render_transactional_html(text)
    assert '<a href="https://a.test">https://a.test</a>' in html
    assert '<a href="https://b.test">https://b.test</a>' in html


def test_non_url_token_is_not_linkified() -> None:
    """Plain words like ``Hi,`` or ``Amount`` must never become anchors —
    only tokens that begin with ``http://`` or ``https://``."""
    text = "Hi, Amount Due: 100"
    html = render_transactional_html(text)
    assert "<a " not in html


def test_url_with_querystring_ampersand_renders_safely() -> None:
    """Ampersands in querystrings must HTML-escape in the anchor's
    visible label — otherwise the rendered link looks broken in some
    clients. The href value keeps the literal & since it's inside an
    attribute (browsers parse that fine)."""
    text = "Pay: https://example.com/pay?id=42&token=abc"
    html = render_transactional_html(text)
    # The visible label has the escaped form (it went through
    # _escape_html before the linkifier ran).
    assert "https://example.com/pay?id=42&amp;token=abc</a>" in html


# ---------------------------------------------------------------------------
# HTML escaping (XSS guard)
# ---------------------------------------------------------------------------


def test_special_chars_in_body_are_escaped() -> None:
    """An org name with ``<>&"'`` must not be able to inject markup."""
    text = "From <Acme & Co. \"the best\">"
    html = render_transactional_html(text)
    assert "&lt;Acme &amp; Co. &quot;the best&quot;&gt;" in html
    # The literal unescaped form must NOT appear inside the document
    # body — only inside the doctype/structure.
    assert "<Acme & Co." not in html


def test_script_tag_in_body_does_not_create_script_block() -> None:
    """An attacker-controlled customer name can't smuggle a ``<script>``
    block into the rendered document."""
    text = "Hi <script>alert(1)</script>"
    html = render_transactional_html(text)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>" not in html


# ---------------------------------------------------------------------------
# Email signature
# ---------------------------------------------------------------------------


def test_signature_html_appended_with_hr() -> None:
    """When the org has an email signature configured, it's rendered
    after a thin ``<hr>`` so the visual separation matches the legacy
    ``<hr>...signature`` pattern."""
    html = render_transactional_html(
        "Body",
        signature_html='<p>Acme Workshop<br><a href="https://acme.test">acme.test</a></p>',
    )
    assert "<hr" in html
    assert 'Acme Workshop' in html
    # Signature HTML is rendered verbatim (it's admin-trusted, escaped
    # at config save time, not at render time).
    assert '<a href="https://acme.test">acme.test</a>' in html


def test_signature_none_or_blank_omits_hr() -> None:
    """No signature → no ``<hr>`` (otherwise we'd render an orphan
    horizontal rule at the bottom of every transactional message)."""
    html_no_sig = render_transactional_html("Body", signature_html=None)
    html_blank = render_transactional_html("Body", signature_html="   ")
    assert "<hr" not in html_no_sig
    assert "<hr" not in html_blank


# ---------------------------------------------------------------------------
# Real-world invoice body smoke test
# ---------------------------------------------------------------------------


def test_invoice_body_smoke() -> None:
    """End-to-end check on the actual invoice fallback body: paragraph
    structure preserved, payment URL becomes an anchor, no malformed
    HTML left over from the legacy ``<br>`` pattern."""
    body = (
        "Hi,\n\n"
        "Please find attached invoice INV-0042 from Acme Workshop.\n\n"
        "Amount Due: NZD 123.45\n\n"
        "Pay online: https://oraflows.co.nz/pay/abc123\n\n"
        "If you have any questions, please don't hesitate to contact us.\n\n"
        "Thank you for your business.\n\n"
        "Acme Workshop\n"
    )
    html = render_transactional_html(
        body, subject="Invoice INV-0042 from Acme Workshop"
    )

    # Document chrome present.
    assert "<!DOCTYPE html>" in html
    assert "<title>Invoice INV-0042 from Acme Workshop</title>" in html

    # The payment URL is anchor-tagged.
    assert (
        '<a href="https://oraflows.co.nz/pay/abc123">'
        'https://oraflows.co.nz/pay/abc123</a>'
    ) in html

    # Multiple paragraphs (each blank-line-separated block becomes <p>).
    assert html.count("<p ") >= 6

    # NO legacy pattern left: there should be no naked text run that
    # contains the URL outside an anchor tag.
    assert "Pay online: https://oraflows.co.nz" not in html or "<a href=" in html

    # Apostrophe in the body is escaped.
    assert "don&#x27;t" in html
