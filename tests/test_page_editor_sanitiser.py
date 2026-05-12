"""Property-based tests for page editor HTML sanitisation (Task 2.6).

Uses Hypothesis to verify that the sanitiser output contains only allowed tags
with only allowed attributes, no event handlers, and only valid href schemes.

Feature: visual-page-editor
Property 1: HTML Sanitisation Preserves Only Allowed Tags

Validates: Requirements 2.4, 2.5
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.page_editor.sanitiser import sanitise_html


# ---------------------------------------------------------------------------
# Constants: allowed tags and attributes (mirrors sanitiser.py)
# ---------------------------------------------------------------------------

ALLOWED_TAGS = {"strong", "em", "a", "br", "p"}
ALLOWED_ATTRS_BY_TAG: dict[str, set[str]] = {
    "strong": set(),
    "em": set(),
    "a": {"href", "target", "rel"},
    "br": set(),
    "p": set(),
}
ALLOWED_HREF_PREFIXES = ("http://", "https://", "mailto:", "tel:", "/")


# ---------------------------------------------------------------------------
# Strategy: generate random HTML-like strings with arbitrary tags/attributes
# ---------------------------------------------------------------------------

# Random tag names including both allowed and disallowed
random_tags = st.sampled_from([
    "div", "script", "strong", "em", "a", "p", "br", "span",
    "img", "iframe", "style", "h1", "h2", "table", "form",
])

# Random attribute names including event handlers and disallowed attrs
random_attrs = st.sampled_from([
    "onclick", "onmouseover", "onload", "onerror",
    "href", "target", "rel", "style", "class", "id", "src",
    "action", "data-x", "onfocus",
])

# Random attribute values including dangerous href schemes
random_attr_values = st.sampled_from([
    "https://example.com",
    "http://test.org",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox",
    "mailto:test@example.com",
    "tel:+1234567890",
    "/relative/path",
    "ftp://evil.com",
    "",
    "alert('xss')",
])

# Random text content
random_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=30,
)


@st.composite
def random_html_element(draw):
    """Generate a single random HTML element with random attributes."""
    tag = draw(random_tags)
    num_attrs = draw(st.integers(min_value=0, max_value=3))
    attrs_parts = []
    for _ in range(num_attrs):
        attr_name = draw(random_attrs)
        attr_value = draw(random_attr_values)
        attrs_parts.append(f'{attr_name}="{attr_value}"')
    attrs_str = " ".join(attrs_parts)
    content = draw(random_text)

    if tag == "br":
        if attrs_str:
            return f"<{tag} {attrs_str}>"
        return f"<{tag}>"
    if attrs_str:
        return f"<{tag} {attrs_str}>{content}</{tag}>"
    return f"<{tag}>{content}</{tag}>"


@st.composite
def random_html_string(draw):
    """Generate a random HTML string composed of multiple elements."""
    num_elements = draw(st.integers(min_value=1, max_value=5))
    parts = []
    for _ in range(num_elements):
        parts.append(draw(random_html_element()))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Regex patterns for verifying sanitised output
# ---------------------------------------------------------------------------

# Matches any HTML tag (opening or closing) in the output
TAG_PATTERN = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^>]*)?)(/?)>")

# Matches attributes within a tag
ATTR_PATTERN = re.compile(r'([a-zA-Z][a-zA-Z0-9_-]*)\s*(?:=\s*"([^"]*)")?')


# ---------------------------------------------------------------------------
# Property 1: HTML Sanitisation Preserves Only Allowed Tags
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(html=random_html_string())
def test_html_sanitisation_preserves_only_allowed_tags(html: str):
    """For any HTML string input, after sanitisation the output contains only
    allowed tags with only allowed attributes, no event handlers, and all href
    values use only allowed schemes.

    **Validates: Requirements 2.4, 2.5**
    """
    result = sanitise_html(html)

    # Find all tags in the output
    for match in TAG_PATTERN.finditer(result):
        is_closing = match.group(1) == "/"
        tag_name = match.group(2).lower()
        attrs_str = match.group(3).strip()

        # 1. Verify tag is in the allowed set
        assert tag_name in ALLOWED_TAGS, (
            f"Disallowed tag <{tag_name}> found in sanitised output.\n"
            f"Input: {html!r}\n"
            f"Output: {result!r}"
        )

        # For closing tags, no attributes to check
        if is_closing:
            continue

        # 2. Verify attributes are allowed for this tag
        allowed_attrs = ALLOWED_ATTRS_BY_TAG.get(tag_name, set())
        for attr_match in ATTR_PATTERN.finditer(attrs_str):
            attr_name = attr_match.group(1).lower()
            attr_value = attr_match.group(2)

            # 3. No event handlers (on*) should remain
            assert not attr_name.startswith("on"), (
                f"Event handler '{attr_name}' found on <{tag_name}> in output.\n"
                f"Input: {html!r}\n"
                f"Output: {result!r}"
            )

            # Verify attribute is allowed for this tag
            assert attr_name in allowed_attrs, (
                f"Disallowed attribute '{attr_name}' on <{tag_name}> in output.\n"
                f"Input: {html!r}\n"
                f"Output: {result!r}"
            )

            # 4. Verify href values start with allowed prefixes
            if attr_name == "href" and attr_value is not None:
                assert any(
                    attr_value.startswith(prefix)
                    for prefix in ALLOWED_HREF_PREFIXES
                ), (
                    f"Invalid href '{attr_value}' on <a> in output.\n"
                    f"Input: {html!r}\n"
                    f"Output: {result!r}"
                )
