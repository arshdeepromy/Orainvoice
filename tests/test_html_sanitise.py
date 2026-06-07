"""Example-based XSS unit tests for the email Body_Sanitiser.

Locks down explicit known-malicious payloads against
``app.integrations.html_sanitise.sanitise_email_html``. Complements the
Hypothesis property test (Property 2 — sanitiser strips unsafe markup and
is idempotent) added in task 1.3 to the same module.

These assertions verify the specific OWASP cheat-sheet payloads called out
by the design's Testing Strategy → "Backend example/integration tests":
``<script>alert(1)</script>``, ``<a href="javascript:alert(1)">``,
``onerror=...`` event handlers, and ``data:`` URLs — plus the
allowlist guarantees (allowed tags survive, disallowed protocols and CSS
properties are stripped, the sanitiser is idempotent).

Design ref: ``.kiro/specs/send-email-modal/design.md`` →
Testing Strategy → "Backend example/integration tests".

Requirements: 10.7, 21.6
"""

from __future__ import annotations

import pytest

from app.integrations.html_sanitise import (
    ALLOWED_PROTOCOLS,
    ALLOWED_STYLES,
    ALLOWED_TAGS,
    sanitise_email_html,
)


# ---------------------------------------------------------------------------
# Script injection (OWASP A3 — the canonical payload)
# ---------------------------------------------------------------------------


def test_script_tag_is_stripped():
    out = sanitise_email_html("hello<script>alert(1)</script>world")
    # The executable <script> markup must be gone; inner text is preserved
    # harmlessly as a plain text node (bleach strip=True, R10.2).
    assert "<script" not in out
    assert "</script" not in out
    # Surrounding text content is preserved.
    assert "hello" in out
    assert "world" in out


def test_nested_and_uppercase_script_is_stripped():
    """Case variations and broken nesting must not smuggle a script tag through."""
    out = sanitise_email_html("<SCRIPT>alert(1)</SCRIPT><ScRiPt>alert(2)</ScRiPt>")
    # No <script> tag (any case) survives; the residual text is inert.
    assert "<script" not in out.lower()
    assert "</script" not in out.lower()


def test_svg_onload_payload_is_neutralised():
    """OWASP SVG-based vector: <svg/onload=...> — tag and handler both go."""
    out = sanitise_email_html('<svg/onload=alert(1)></svg>')
    assert "<svg" not in out.lower()
    assert "onload" not in out.lower()
    assert "alert(1)" not in out


# ---------------------------------------------------------------------------
# javascript: URL in href (OWASP A3)
# ---------------------------------------------------------------------------


def test_anchor_javascript_href_is_stripped():
    out = sanitise_email_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in out.lower()
    assert 'href="javascript:alert(1)"' not in out
    # Link text is preserved even though the dangerous href is dropped.
    assert "click" in out


@pytest.mark.parametrize(
    "payload",
    [
        '<a href="JaVaScRiPt:alert(1)">x</a>',
        '<a href="  javascript:alert(1)">x</a>',
        '<a href="java\tscript:alert(1)">x</a>',
    ],
)
def test_obfuscated_javascript_href_is_stripped(payload: str):
    """Mixed case, leading whitespace, and embedded tabs must not bypass."""
    out = sanitise_email_html(payload)
    assert "alert(1)" not in out
    assert "javascript:alert" not in out.lower().replace("\t", "")


def test_image_javascript_src_is_stripped():
    out = sanitise_email_html('<img src="javascript:alert(1)">')
    assert "javascript:" not in out.lower()


# ---------------------------------------------------------------------------
# Event-handler attributes (onerror, onclick, ...) (R10.5)
# ---------------------------------------------------------------------------


def test_img_onerror_handler_is_stripped():
    """The classic <img src=x onerror=alert(1)> XSS payload."""
    out = sanitise_email_html('<img src="x" onerror="alert(1)">')
    assert "onerror" not in out.lower()
    assert "alert(1)" not in out


@pytest.mark.parametrize(
    "handler",
    ["onclick", "onmouseover", "onload", "onerror", "onfocus", "onblur"],
)
def test_event_handlers_removed_from_allowed_tags(handler: str):
    out = sanitise_email_html(f'<p {handler}="alert(1)">text</p>')
    assert handler not in out.lower()
    assert "alert(1)" not in out
    # The allowed <p> tag and its text content survive.
    assert "text" in out


# ---------------------------------------------------------------------------
# data: and other dangerous URL schemes (R10.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "data:text/html,<script>alert(1)</script>",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
    ],
)
def test_disallowed_url_schemes_dropped_from_href(bad_url: str):
    out = sanitise_email_html(f'<a href="{bad_url}">x</a>')
    scheme = bad_url.split(":", 1)[0]
    assert f"{scheme}:" not in out.lower()
    assert "alert(1)" not in out


def test_data_uri_image_src_is_stripped():
    out = sanitise_email_html(
        '<img src="data:text/html;base64,PHNjcmlwdD4=" alt="x">'
    )
    assert "data:" not in out.lower()


# ---------------------------------------------------------------------------
# Allowed content is preserved (R10.2 / R10.4 happy path)
# ---------------------------------------------------------------------------


def test_safe_https_link_is_preserved():
    out = sanitise_email_html('<a href="https://example.com">visit</a>')
    assert "https://example.com" in out
    assert "visit" in out


def test_mailto_link_is_preserved():
    out = sanitise_email_html('<a href="mailto:hi@example.com">email us</a>')
    assert "mailto:hi@example.com" in out


def test_basic_formatting_tags_survive():
    out = sanitise_email_html(
        "<p>Hello <strong>bold</strong> and <em>italic</em></p>"
        "<ul><li>one</li><li>two</li></ul>"
    )
    assert "<strong>" in out
    assert "<em>" in out
    assert "<li>" in out
    assert "bold" in out and "italic" in out


def test_allowed_protocols_constant_matches_requirement():
    """R10.4 — only http, https, mailto are permitted."""
    assert set(ALLOWED_PROTOCOLS) == {"http", "https", "mailto"}
    assert "javascript" not in ALLOWED_PROTOCOLS
    assert "data" not in ALLOWED_PROTOCOLS
    assert "file" not in ALLOWED_PROTOCOLS


# ---------------------------------------------------------------------------
# style-attribute CSS filtering (R10.3)
# ---------------------------------------------------------------------------


def test_dangerous_css_property_is_stripped_but_safe_one_kept():
    out = sanitise_email_html(
        '<p style="color: red; position: fixed; behavior: url(x)">hi</p>'
    )
    # An allowed property is retained.
    assert "color" in out
    # Disallowed CSS properties are filtered out.
    assert "position" not in out.lower()
    assert "behavior" not in out.lower()


def test_allowed_styles_excludes_position_and_behavior():
    assert "position" not in ALLOWED_STYLES
    assert "behavior" not in ALLOWED_STYLES
    assert "color" in ALLOWED_STYLES


# ---------------------------------------------------------------------------
# Idempotence + edge inputs
# ---------------------------------------------------------------------------


def test_sanitiser_is_idempotent_on_malicious_input():
    raw = '<p onclick="x">hi<script>alert(1)</script><a href="javascript:1">y</a></p>'
    once = sanitise_email_html(raw)
    twice = sanitise_email_html(once)
    assert once == twice


@pytest.mark.parametrize("empty", ["", None])
def test_empty_and_none_inputs_return_empty_string(empty):
    assert sanitise_email_html(empty) == ""  # type: ignore[arg-type]


def test_plain_text_passes_through_unchanged():
    out = sanitise_email_html("Just plain text, no tags.")
    assert "Just plain text, no tags." in out


def test_disallowed_block_tags_are_stripped_but_text_kept():
    """<style>/<iframe> markup must not survive (inner text may remain inert)."""
    out = sanitise_email_html(
        "<style>body{display:none}</style>"
        '<iframe src="https://evil.example"></iframe>'
        "<p>kept</p>"
    )
    assert "<style" not in out.lower()
    assert "<iframe" not in out.lower()
    # The iframe's dangerous src attribute must not survive as markup.
    assert "evil.example" not in out
    assert "kept" in out


def test_allowed_tags_constant_includes_expected_tags():
    """Sanity-check the allowlist matches Requirement 10.2."""
    for tag in ("p", "br", "strong", "em", "a", "img", "table", "td"):
        assert tag in ALLOWED_TAGS
    # script / iframe / style are NOT allowlisted.
    for tag in ("script", "iframe", "style"):
        assert tag not in ALLOWED_TAGS


# ===========================================================================
# Property test (Hypothesis) — Property 2
#
# Feature: send-email-modal, Property 2: Sanitiser strips unsafe markup and is
# idempotent
#
# For ANY HTML input, the sanitised output:
#   - contains no <script> element (R10.2),
#   - contains no on* event-handler attribute (R10.5),
#   - contains no javascript:/data:/file: URL in an href/src attribute
#     (R10.4),
#   - and sanitisation is idempotent:
#     sanitise_email_html(sanitise_email_html(x)) == sanitise_email_html(x)
#     (R10.6).
#
# IMPORTANT — these assertions inspect the *parsed* markup of the output, not
# raw substrings. bleach runs with strip=True, so a payload such as
# "<script>alert(1)</script>" leaves the inert text "alert(1)" behind, and a
# benign body may legitimately contain the literal text "javascript:" as
# prose. The property is about the absence of executable *markup* (a real
# <script> tag, a real on*= attribute, a real dangerous-scheme URL inside an
# href/src attribute) — never the absence of an arbitrary text substring — so
# we parse the output with html.parser.HTMLParser and assert against the tags
# and attributes it yields.
#
# **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7**
# ===========================================================================

import re
from html.parser import HTMLParser

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


# --- Markup inspection helpers (parse output, never substring-match text) ---

#: URL schemes that must never survive inside an href/src attribute (R10.4).
_DANGEROUS_SCHEMES = {"javascript", "data", "file", "vbscript"}

#: html5lib's set of attributes whose values are URIs. Only these are
#: scheme-checked, so dangerous-looking text in non-URI attributes (or in
#: plain text) never triggers a false failure.
_URI_ATTRS = {"href", "src", "action", "background", "dynsrc", "lowsrc"}


class _MarkupCollector(HTMLParser):
    """Collects every tag name and (tag, attr_name, attr_value) the parser
    sees in a fragment, so the property can assert on real markup rather than
    on raw substrings of text content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        self.tags.append(tag.lower())
        for name, value in attrs:
            self.attrs.append((tag.lower(), name.lower(), value or ""))

    def handle_startendtag(self, tag, attrs):  # type: ignore[override]
        self.handle_starttag(tag, attrs)


def _url_scheme(value: str) -> str | None:
    """Extract the URL scheme from an attribute value, de-obfuscating the
    whitespace/control-character tricks (tabs, newlines, leading spaces) that
    XSS payloads use to hide a scheme such as ``java\\tscript:``."""
    cleaned = re.sub(r"[\s\x00-\x20]+", "", value).lower()
    match = re.match(r"^([a-z][a-z0-9+.\-]*):", cleaned)
    return match.group(1) if match else None


# --- Smart HTML-ish input generators (bias toward dangerous constructs) -----

_ALLOWED_SAMPLE_TAGS = ["p", "div", "span", "a", "img", "strong", "em", "li"]
_DISALLOWED_SAMPLE_TAGS = [
    "script", "iframe", "style", "svg", "object", "embed", "form", "input",
    "noscript", "template",
]
_EVENT_HANDLERS = [
    "onclick", "onerror", "onload", "onmouseover", "onfocus", "onblur",
    "onsubmit", "onkeydown", "onanimationstart",
]
_SAFE_SCHEMES = ["http://example.com", "https://example.com/x", "mailto:a@b.co"]


def _scheme_obfuscations(scheme: str) -> st.SearchStrategy[str]:
    """Variations of a dangerous scheme prefix: plain, mixed case, leading
    whitespace, and an embedded tab/newline (all classic bypass attempts)."""
    return st.sampled_from([
        f"{scheme}:alert(1)",
        f"{scheme.upper()}:alert(1)",
        f"  {scheme}:alert(1)",
        f"{scheme[:2]}\t{scheme[2:]}:alert(1)" if len(scheme) > 2 else f"{scheme}:x",
        f"\n{scheme}:alert(1)",
    ])


_dangerous_url = st.one_of(
    *[_scheme_obfuscations(s) for s in sorted(_DANGEROUS_SCHEMES)]
)


@st.composite
def _html_fragment(draw) -> str:
    """Generate one HTML-ish fragment biased toward unsafe constructs:
    script/iframe tags, elements carrying event handlers, anchors/images with
    dangerous-scheme URLs, plus benign text that may itself contain the bare
    words 'javascript:'/'onerror' as prose (to guard against false positives).
    """
    kind = draw(st.integers(min_value=0, max_value=6))
    if kind == 0:
        # A disallowed tag wrapping arbitrary inner content.
        tag = draw(st.sampled_from(_DISALLOWED_SAMPLE_TAGS))
        inner = draw(st.text(max_size=30))
        return f"<{tag}>{inner}</{tag}>"
    if kind == 1:
        # An allowed tag carrying an event-handler attribute.
        tag = draw(st.sampled_from(_ALLOWED_SAMPLE_TAGS))
        handler = draw(st.sampled_from(_EVENT_HANDLERS))
        return f'<{tag} {handler}="alert(1)">text</{tag}>'
    if kind == 2:
        # An anchor with a dangerous-scheme href.
        return f'<a href="{draw(_dangerous_url)}">click</a>'
    if kind == 3:
        # An image with a dangerous-scheme src and an onerror handler.
        return f'<img src="{draw(_dangerous_url)}" onerror="alert(1)">'
    if kind == 4:
        # A safe, allowed construct that must survive intact.
        return f'<a href="{draw(st.sampled_from(_SAFE_SCHEMES))}">ok</a>'
    if kind == 5:
        # Benign prose that *mentions* dangerous tokens as plain text — must
        # NOT trip the markup assertions (robustness against substring checks).
        return draw(st.sampled_from([
            "Learn javascript: a beginner guide",
            "The onerror property in JS",
            "data: rates apply",
            "file: not found",
        ]))
    # Arbitrary free text, including angle brackets and quotes.
    return draw(st.text(max_size=40))


html_input_strategy = st.lists(_html_fragment(), min_size=0, max_size=8).map(
    "".join
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(raw=html_input_strategy)
def test_sanitiser_strips_unsafe_markup_and_is_idempotent(raw: str):
    """Feature: send-email-modal, Property 2: Sanitiser strips unsafe markup
    and is idempotent.

    For any HTML input the sanitised output contains no <script> element, no
    on* attribute, and no javascript:/data:/file: URL in an href/src
    attribute; and applying the sanitiser twice equals applying it once.

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7**
    """
    out = sanitise_email_html(raw)

    collector = _MarkupCollector()
    collector.feed(out)
    collector.close()

    # R10.2 — no <script> element survives as markup.
    assert "script" not in collector.tags, (
        f"<script> markup survived sanitisation for input {raw!r} -> {out!r}"
    )

    for tag, name, value in collector.attrs:
        # R10.5 — no event-handler attribute survives on any element.
        assert not name.startswith("on"), (
            f"event-handler attribute {name!r} survived on <{tag}> "
            f"for input {raw!r} -> {out!r}"
        )
        # R10.4 — no dangerous scheme survives inside a URI attribute.
        if name in _URI_ATTRS:
            scheme = _url_scheme(value)
            assert scheme not in _DANGEROUS_SCHEMES, (
                f"dangerous URL scheme {scheme!r} survived in {name!r} of "
                f"<{tag}> for input {raw!r} -> {out!r}"
            )

    # R10.6 — idempotence: sanitising the output again changes nothing.
    assert sanitise_email_html(out) == out, (
        f"sanitiser is not idempotent for input {raw!r}: "
        f"{out!r} -> {sanitise_email_html(out)!r}"
    )
