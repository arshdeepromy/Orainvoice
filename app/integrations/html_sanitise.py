"""Body_Sanitiser — allowlist-based HTML sanitiser for outbound email bodies.

This module is the single server-side sanitisation point for the
``send-email-modal`` feature. Any user-supplied or template-stored
``body_html`` is passed through :func:`sanitise_email_html` before it
reaches ``email_sender.send_email`` (override path) and before the
default body is returned by the Email_Preview_Endpoint. It strips
anything outside the allowlists below so that edited content cannot
introduce XSS into rendered email previews or injection into provider
REST APIs.

Implemented with ``bleach`` (allowlist cleaner) plus ``bleach[css]``'s
``CSSSanitizer`` (backed by ``tinycss2``) for the ``style``-attribute
property allowlist.

Security guarantees (Requirement 10):

- Only ``ALLOWED_TAGS`` survive; every other tag is stripped with its
  text content preserved (``strip=True``). (R10.2)
- Only ``ALLOWED_ATTRIBUTES`` survive per element; ``on*`` event-handler
  attributes are removed because they appear in no allowlist. (R10.3, R10.5)
- Only ``ALLOWED_PROTOCOLS`` (``http``, ``https``, ``mailto``) are kept in
  URL attributes; ``javascript:``, ``data:``, and ``file:`` URLs are
  stripped. (R10.4)
- The ``style`` attribute is filtered to ``ALLOWED_STYLES`` CSS
  properties. (R10.3)
- :func:`sanitise_email_html` is idempotent:
  ``sanitise_email_html(sanitise_email_html(x)) == sanitise_email_html(x)``.

Design ref: ``.kiro/specs/send-email-modal/design.md`` →
"Body_Sanitiser — app/integrations/html_sanitise.py".

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
"""

from __future__ import annotations

import bleach
from bleach.css_sanitizer import CSSSanitizer

# --- Allowlists (module-level constants, unit-tested against XSS payloads) ---

#: Tags permitted in a sanitised email body. Everything else is stripped
#: (text content preserved). (R10.2)
ALLOWED_TAGS: list[str] = [
    "p", "br", "hr", "strong", "em", "u", "s", "b", "i", "ul", "ol", "li",
    "blockquote", "pre", "code", "h1", "h2", "h3", "h4", "h5", "h6", "a",
    "img", "table", "thead", "tbody", "tr", "th", "td", "span", "div",
]

#: Attributes permitted per element. ``on*`` handlers are absent from every
#: list and are therefore always removed. (R10.3, R10.5)
ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height", "style"],
    "td": ["colspan", "rowspan", "width", "align", "style"],
    "th": ["colspan", "rowspan", "width", "align", "style"],
    "table": ["colspan", "rowspan", "width", "align", "style"],
    "*": ["style", "class"],
}

#: URL protocols permitted in ``href`` / ``src``. ``javascript:``, ``data:``,
#: and ``file:`` are excluded and therefore stripped. (R10.4)
ALLOWED_PROTOCOLS: list[str] = ["http", "https", "mailto"]

#: CSS properties permitted inside a ``style`` attribute. Filtered via the
#: ``CSSSanitizer`` (tinycss2). (R10.3)
ALLOWED_STYLES: list[str] = [
    "color", "background-color", "font-weight", "font-style",
    "text-decoration", "text-align", "padding", "margin", "border",
    "font-size",
]


def sanitise_email_html(raw: str) -> str:
    """Allowlist-sanitise untrusted HTML for use as an email body.

    Strips ``on*`` handler attributes, ``javascript:``/``data:``/``file:``
    URLs, and any disallowed tags, attributes, or CSS style properties.
    The operation is idempotent — running it on already-sanitised output
    returns that output unchanged.

    Args:
        raw: The untrusted HTML string (may be ``None`` or empty).

    Returns:
        A sanitised HTML string safe to hand to ``email_sender.send_email``
        and to render in the modal preview.
    """
    css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_STYLES)
    cleaner = bleach.Cleaner(
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        css_sanitizer=css_sanitizer,
    )
    return cleaner.clean(raw or "")
