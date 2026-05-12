"""Example-based unit tests for the HTML sanitiser.

Complements the property-based tests in test_page_editor_sanitiser.py by
locking down explicit known cases (allowed tags preserved verbatim,
disallowed tags stripped, href schemes filtered, event handlers removed).

Requirements: 2.4, 2.5
"""

from __future__ import annotations

import pytest

from app.modules.page_editor.sanitiser import sanitise_html, sanitise_puck_content


# ---------------------------------------------------------------------------
# Allowed tags preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        "<strong>bold</strong>",
        "<em>italic</em>",
        "<p>para</p>",
        "<br>",
        '<a href="https://example.com">link</a>',
        '<a href="/relative/path" target="_blank" rel="noopener">link</a>',
        '<a href="mailto:hi@example.com">email</a>',
        '<a href="tel:+6491234567">call</a>',
    ],
)
def test_allowed_tags_round_trip(html: str):
    """Allowed tags with allowed attributes pass through (whitespace tolerated)."""
    out = sanitise_html(html)
    # The exact substring may differ in whitespace/quoting, but the tag
    # name must appear and dangerous content must not.
    assert "<script" not in out
    assert "javascript:" not in out
    # Spot check key markers
    if "strong" in html:
        assert "<strong>" in out
    if "em>" in html:
        assert "<em>" in out
    if "<br" in html:
        assert "<br" in out
    if 'href="https' in html:
        assert "https://example.com" in out


# ---------------------------------------------------------------------------
# Disallowed tags stripped
# ---------------------------------------------------------------------------


def test_script_tag_removed():
    out = sanitise_html("hello<script>alert(1)</script>world")
    assert "<script" not in out
    assert "</script" not in out


def test_iframe_removed():
    out = sanitise_html('<iframe src="javascript:alert(1)"></iframe>')
    assert "<iframe" not in out
    assert "javascript:" not in out


def test_div_removed_but_text_preserved():
    out = sanitise_html("<div>kept text</div>")
    assert "<div" not in out
    assert "kept text" in out


def test_style_block_stripped():
    out = sanitise_html("<style>body{display:none}</style><p>hi</p>")
    assert "<style" not in out
    assert "display:none" not in out
    assert "hi" in out


# ---------------------------------------------------------------------------
# href scheme validation (Requirement 2.5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_href",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox",
        "ftp://example.com",
        "file:///etc/passwd",
    ],
)
def test_disallowed_href_schemes_dropped(bad_href: str):
    out = sanitise_html(f'<a href="{bad_href}">x</a>')
    # The dangerous scheme must not appear in output
    scheme = bad_href.split(":", 1)[0]
    # Some sanitisers keep <a> but drop href; either is acceptable so long
    # as the dangerous scheme value is gone.
    assert f'href="{bad_href}"' not in out
    assert f"{scheme}:" not in out


# ---------------------------------------------------------------------------
# Event handler removal (Requirement 2.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evt",
    ["onclick", "onmouseover", "onload", "onerror", "onfocus"],
)
def test_event_handlers_removed_from_allowed_tags(evt: str):
    out = sanitise_html(f'<p {evt}="alert(1)">x</p>')
    assert evt not in out
    assert "alert(1)" not in out


# ---------------------------------------------------------------------------
# Puck content walker
# ---------------------------------------------------------------------------


def test_sanitise_puck_content_walks_text_strings():
    """sanitise_puck_content should recursively sanitise string values."""
    payload = {
        "content": [
            {
                "type": "RichText",
                "props": {
                    "text": '<p>safe</p><script>alert(1)</script>',
                },
            }
        ],
        "root": {"props": {}},
    }
    out = sanitise_puck_content(payload)
    text_value = out["content"][0]["props"]["text"]
    assert "<script" not in text_value
    assert "safe" in text_value
