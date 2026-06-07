"""Unit tests for ``render_body_fragment_html`` and its shared-helper
invariant with ``render_transactional_html``.

Background (bugfix: email-preview-body-mismatch)
------------------------------------------------
The Send-Email-Modal previously fed the FULL transactional document
(``<!DOCTYPE>``…``<head><title>{subject}</title></head>``…) straight into
a TipTap editor, which surfaced the ``<title>`` text as the first editable
paragraph. The fix introduces ``render_body_fragment_html`` — the inner,
editable body fragment (paragraphs + optional signature, NO document
chrome and NO CTA button) — and refactors ``render_transactional_html`` to
build its inner content from that SAME helper so the two can never drift.

These tests lock in two invariants:

  1. **Shared-helper invariant** — the body region of the full document
     (the content inside the inner ``<div>``) produced by
     ``render_transactional_html(text, signature_html=…)`` is EXACTLY the
     markup ``render_body_fragment_html(text, signature_html=…)`` produces
     (paragraphs + signature) when no CTA is present. With a CTA, the
     paragraphs and signature pieces of the fragment still appear in the
     document body (the CTA table is inserted between them).
  2. **Fragment cleanliness** — the fragment contains NO ``<!DOCTYPE>``,
     ``<html>``, ``<head>``, ``<title>``, or ``<body>`` chrome and no CTA
     button table.

**Validates: Requirements 2.1, 3.2**
"""

from __future__ import annotations

from app.integrations.email_sender import (
    render_body_fragment_html,
    render_transactional_html,
)


# The exact opening tag of the inner content ``<div>`` emitted by
# ``render_transactional_html``. Used to slice out the document's body
# region so we can compare it to the fragment.
_INNER_DIV_OPEN = (
    '<div style="max-width:640px;margin:0 auto;background:#ffffff;'
    'padding:32px;border-radius:8px">'
)
_INNER_DIV_CLOSE = "</div></body></html>"


def _inner_body_region(html: str) -> str:
    """Return the content between the inner content ``<div>`` and the
    closing ``</div></body></html>`` of a full transactional document."""
    start = html.index(_INNER_DIV_OPEN) + len(_INNER_DIV_OPEN)
    end = html.index(_INNER_DIV_CLOSE)
    return html[start:end]


# ---------------------------------------------------------------------------
# Shared-helper invariant — fragment == document body region (no CTA)
# ---------------------------------------------------------------------------


def test_fragment_equals_document_body_region_plain() -> None:
    """For a plain body with no signature and no CTA, the fragment is
    byte-identical to the document's inner body region."""
    text = "Hello world.\n\nSecond paragraph."
    fragment = render_body_fragment_html(text)
    document = render_transactional_html(text, subject="Some Subject")
    assert _inner_body_region(document) == fragment


def test_fragment_equals_document_body_region_with_signature() -> None:
    """With a signature (still no CTA), the fragment — paragraphs PLUS the
    ``<hr>`` signature block — equals the document's inner body region."""
    text = "Hi,\n\nThanks for your business."
    signature = '<p>Acme Workshop<br><a href="https://acme.test">acme.test</a></p>'
    fragment = render_body_fragment_html(text, signature_html=signature)
    document = render_transactional_html(
        text, subject="Invoice INV-0042", signature_html=signature
    )
    assert _inner_body_region(document) == fragment


def test_fragment_paragraph_markup_matches_document() -> None:
    """The ``<p>`` paragraph markup in the fragment is exactly what the
    full document uses for its body paragraphs (shared
    ``_text_to_paragraphs_html`` source)."""
    text = "First.\n\nSecond.\n\nThird with a link https://example.com/pay"
    fragment = render_body_fragment_html(text)
    document = render_transactional_html(text)
    # Every paragraph block emitted by the fragment must appear verbatim in
    # the full document body.
    assert fragment.count('<p style="margin:0 0 16px 0">') == 3
    assert fragment in _inner_body_region(document)
    # The linkified URL renders identically in both.
    assert '<a href="https://example.com/pay">' in fragment
    assert '<a href="https://example.com/pay">' in document


def test_fragment_paragraphs_and_signature_present_in_document_with_cta() -> None:
    """When a CTA is present the fragment (paragraphs + signature) is NOT
    contiguous in the document (the CTA table sits between them), but each
    piece still appears — the paragraphs and the signature block both come
    from the shared helpers."""
    text = "Pay your invoice.\n\nThanks."
    signature = "<p>Acme Workshop</p>"
    fragment = render_body_fragment_html(text, signature_html=signature)
    document = render_transactional_html(
        text,
        subject="Invoice",
        signature_html=signature,
        cta_url="https://example.com/pay/abc",
        cta_label="Pay Now",
    )
    # Fragment's paragraph block appears in the document body.
    paragraphs_only = render_body_fragment_html(text)
    assert paragraphs_only in document
    # Fragment's signature block appears in the document body.
    sig_block = '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">' + signature
    assert sig_block in fragment
    assert sig_block in document
    # The CTA button table is in the document but NOT in the fragment.
    assert 'role="presentation"' in document
    assert 'role="presentation"' not in fragment


# ---------------------------------------------------------------------------
# Fragment cleanliness — no document chrome, no CTA
# ---------------------------------------------------------------------------


def test_fragment_contains_no_document_chrome() -> None:
    """The editable fragment must not contain any document-head/chrome
    markup that would leak (e.g. the subject via ``<title>``) into the
    rich-text editor."""
    text = "Body content here."
    fragment = render_body_fragment_html(
        text, signature_html="<p>Sig</p>"
    )
    for forbidden in ("<!DOCTYPE", "<html", "<head", "<title", "<body"):
        assert forbidden not in fragment, f"fragment unexpectedly contains {forbidden!r}"


def test_fragment_contains_cta_link_when_cta_url_present() -> None:
    """The CTA is part of the editable fragment when a ``cta_url`` is
    supplied — it must show in the editor AND survive an edited send (the
    send path dispatches an edited fragment as-is). In the fragment it is
    a plain ``<a>`` link (TipTap-survivable), not the styled ``<table>``
    button the full document uses."""
    fragment = render_body_fragment_html(
        "Pay your invoice now.",
        cta_url="https://example.com/pay/abc",
        cta_label="Pay Now",
    )
    assert 'href="https://example.com/pay/abc"' in fragment
    assert "Pay Now" in fragment
    # The "Or copy this link" fallback link is present too.
    assert "Or copy this link" in fragment
    # The styled button TABLE is document-only — the editor cannot represent
    # a <table>, so the fragment uses plain anchors instead.
    assert "<table" not in fragment


def test_fragment_omits_cta_when_no_cta_url() -> None:
    """With no ``cta_url`` the fragment has no CTA link (a plain
    notification body)."""
    fragment = render_body_fragment_html("Just an update, no payment.")
    assert "Or copy this link" not in fragment
    assert "<table" not in fragment


def test_document_cta_uses_styled_button_table() -> None:
    """The full document keeps the styled ``<table>`` button (the sent
    email), even though the fragment uses a plain link."""
    document = render_transactional_html(
        "Pay now.",
        subject="Invoice",
        cta_url="https://example.com/pay/xyz",
        cta_label="Pay Now",
    )
    assert '<table role="presentation"' in document
    assert 'href="https://example.com/pay/xyz"' in document


def test_empty_body_and_no_signature_yields_empty_fragment() -> None:
    """An empty body with no signature produces an empty fragment (no
    stray paragraph or chrome markup)."""
    assert render_body_fragment_html("") == ""
    assert render_body_fragment_html("", signature_html="   ") == ""


def test_fragment_signature_block_matches_shared_markup() -> None:
    """The signature block in the fragment uses the same ``<hr>`` markup
    the document body uses (single source of truth)."""
    signature = "<p>Cheers, Acme</p>"
    fragment = render_body_fragment_html("Body", signature_html=signature)
    expected_sig = (
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">'
        + signature
    )
    assert expected_sig in fragment
