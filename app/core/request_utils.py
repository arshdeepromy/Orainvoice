"""Request URL helpers for the email-link bugfix spec (Bug 3).

This module exposes ``extract_request_base_url(request)``, which
returns the absolute base URL the client used to reach the API.
Email-link sites (invitation, password reset, customer portal,
Stripe Checkout success/cancel) call this helper at the router
boundary and pass the result as ``base_url=...`` to the underlying
service so embedded URLs match the host the user is actually on
(see Bug 3 in
``.kiro/specs/email-delivery-visibility-fixes/bugfix.md``).
"""

from __future__ import annotations

from fastapi import Request


def extract_request_base_url(request: Request) -> str | None:
    """Return the absolute base URL (scheme://host) the client used.

    Prefers the ``Origin`` header (set by browsers on cross-origin
    requests). Falls back to ``request.url.scheme`` + ``Host`` header
    when ``Origin`` is absent (server-to-server callers, redirected
    forms). Returns ``None`` when neither is present so callers can
    fall back to ``settings.frontend_base_url``.

    The returned value has no trailing slash so callers can use
    f-string concatenation ``f"{base_url}/path"`` without
    introducing a double slash (Requirement 4.13).
    """
    origin = (request.headers.get("origin") or "").strip()
    if origin:
        return origin.rstrip("/")
    host = (request.headers.get("host") or "").strip()
    if host:
        scheme = request.url.scheme or "https"
        return f"{scheme}://{host}".rstrip("/")
    return None
