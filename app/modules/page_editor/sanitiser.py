"""HTML sanitisation for Puck_Data content.

Provides allow-list-based HTML sanitisation that strips disallowed tags,
attributes, and inline event handlers. Validates href values to prevent
javascript: and data: URI injection.

Uses Python's built-in html.parser.HTMLParser — no external dependencies.

Requirements: 2.4, 2.5
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

# ---------------------------------------------------------------------------
# Allow-list configuration
# ---------------------------------------------------------------------------

# Tags allowed through sanitisation, mapped to their allowed attributes.
ALLOWED_TAGS: dict[str, set[str]] = {
    "strong": set(),
    "em": set(),
    "a": {"href", "target", "rel"},
    "br": set(),
    "p": set(),
}

# Valid href prefixes — anything else causes the <a> tag to be stripped
# (inner text is kept).
ALLOWED_HREF_PREFIXES = ("http://", "https://", "mailto:", "tel:", "/")

# Self-closing tags that should not have a closing tag emitted.
VOID_ELEMENTS = {"br"}


# ---------------------------------------------------------------------------
# Sanitiser implementation
# ---------------------------------------------------------------------------


class _HTMLSanitiser(HTMLParser):
    """Custom HTMLParser that emits only allowed tags and attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._output: list[str] = []
        # Stack to track tags we're skipping (e.g. <a> with bad href).
        # When > 0, we still emit text content but suppress the tag itself.
        self._skip_tag_depth: int = 0

    def reset_output(self) -> None:
        self._output = []
        self._skip_tag_depth = 0

    @property
    def result(self) -> str:
        return "".join(self._output)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()

        if tag_lower not in ALLOWED_TAGS:
            # Disallowed tag — skip it entirely but keep processing children
            return

        # Filter attributes to only allowed ones, stripping event handlers
        allowed_attrs = ALLOWED_TAGS[tag_lower]
        filtered_attrs: list[tuple[str, str | None]] = []

        for attr_name, attr_value in attrs:
            attr_name_lower = attr_name.lower()

            # Strip any event handler (on*)
            if attr_name_lower.startswith("on"):
                continue

            # Only keep explicitly allowed attributes
            if attr_name_lower not in allowed_attrs:
                continue

            filtered_attrs.append((attr_name_lower, attr_value))

        # Special handling for <a> — validate href
        if tag_lower == "a":
            href_value = None
            for attr_name, attr_value in filtered_attrs:
                if attr_name == "href":
                    href_value = attr_value
                    break

            if href_value is not None and not _is_valid_href(href_value):
                # Invalid href — skip the <a> tag but keep inner text
                self._skip_tag_depth += 1
                return

        if self._skip_tag_depth > 0:
            # We're inside a skipped parent tag — don't emit nested tags
            return

        # Emit the tag
        if tag_lower in VOID_ELEMENTS:
            attr_str = _format_attrs(filtered_attrs)
            self._output.append(f"<{tag_lower}{attr_str} />")
        else:
            attr_str = _format_attrs(filtered_attrs)
            self._output.append(f"<{tag_lower}{attr_str}>")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()

        if tag_lower not in ALLOWED_TAGS:
            return

        if tag_lower in VOID_ELEMENTS:
            return

        # Handle skipped <a> tags with invalid href
        if tag_lower == "a" and self._skip_tag_depth > 0:
            self._skip_tag_depth -= 1
            return

        if self._skip_tag_depth > 0:
            return

        self._output.append(f"</{tag_lower}>")

    def handle_data(self, data: str) -> None:
        self._output.append(_escape_html(data))

    def handle_entityref(self, name: str) -> None:
        self._output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._output.append(f"&#{name};")


def _is_valid_href(href: str) -> bool:
    """Check if an href value uses an allowed scheme/prefix.

    Allowed: http://, https://, mailto:, tel:, or path starting with /
    """
    href_stripped = href.strip()
    return href_stripped.startswith(ALLOWED_HREF_PREFIXES)


def _escape_html(text: str) -> str:
    """Escape HTML special characters in text content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_attrs(attrs: list[tuple[str, str | None]]) -> str:
    """Format a list of (name, value) attribute pairs into an HTML string."""
    if not attrs:
        return ""
    parts = []
    for name, value in attrs:
        if value is None:
            parts.append(f" {name}")
        else:
            # Escape attribute value
            escaped = value.replace("&", "&amp;").replace('"', "&quot;")
            parts.append(f' {name}="{escaped}"')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitise_html(html: str) -> str:
    """Sanitise an HTML string using the allow-list.

    Strips disallowed tags, attributes, and inline event handlers.
    Validates href values — removes <a> tags with invalid hrefs (keeps text).

    Args:
        html: Raw HTML string to sanitise.

    Returns:
        Sanitised HTML string containing only allowed tags and attributes.
    """
    parser = _HTMLSanitiser()
    parser.reset_output()
    parser.feed(html)
    return parser.result


def sanitise_puck_content(content: dict) -> dict:
    """Recursively walk a Puck_Data JSON structure and sanitise HTML strings.

    Finds all string values that might contain HTML (contain < character)
    and runs them through sanitise_html().

    Args:
        content: A Puck_Data dictionary (the JSON structure produced by Puck).

    Returns:
        A new dictionary with all HTML string values sanitised.
    """
    return _walk_and_sanitise(content)


def _walk_and_sanitise(obj: Any) -> Any:
    """Recursively walk a data structure and sanitise HTML in string values."""
    if isinstance(obj, dict):
        return {key: _walk_and_sanitise(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_sanitise(item) for item in obj]
    elif isinstance(obj, str):
        # Only sanitise strings that look like they contain HTML
        if "<" in obj:
            return sanitise_html(obj)
        return obj
    else:
        # Numbers, booleans, None — pass through unchanged
        return obj
