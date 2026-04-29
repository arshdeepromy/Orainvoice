"""Shared PDF rendering utilities.

Provides helpers for resolving org branding assets (logos) into formats
that WeasyPrint can render without needing HTTP access or a base_url.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)


def resolve_logo_for_pdf(org) -> str | None:
    """Resolve the org logo into a data URI suitable for WeasyPrint.

    WeasyPrint renders from an HTML string with no base_url, so relative
    URLs like ``/api/v2/setup-wizard/org-logo/{id}`` cannot be resolved.
    This function returns a ``data:`` URI with the logo bytes base64-encoded,
    or ``None`` if no logo is available.

    Priority:
    1. BYTEA logo stored in the organisations table (most reliable)
    2. Settings URL if it's an absolute ``http(s)://`` URL
    3. None (template will skip the logo)

    Args:
        org: An Organisation ORM object with ``logo_data``,
             ``logo_content_type``, and ``settings`` attributes.

    Returns:
        A data URI string or None.
    """
    # 1. BYTEA from DB — most reliable for PDF
    logo_data = getattr(org, "logo_data", None)
    logo_ct = getattr(org, "logo_content_type", None)
    if logo_data and logo_ct:
        try:
            b64 = base64.b64encode(logo_data).decode("ascii")
            return f"data:{logo_ct};base64,{b64}"
        except Exception:
            logger.warning("Failed to base64-encode org logo, skipping")

    # 2. Absolute URL from settings (e.g. legacy external URL)
    settings = getattr(org, "settings", None) or {}
    raw_url = settings.get("logo_url") or ""
    if raw_url.startswith("http"):
        return raw_url

    # 3. No usable logo
    return None
