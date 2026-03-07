"""Email footer helper for platform branding and signup links.

Provides a reusable function that generates the branded email footer
with platform logo and signup link including UTM parameters.

Usage in any email template builder::

    from app.modules.branding.email_footer import get_email_branded_footer

    footer_html = await get_email_branded_footer(db, org)

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branding.service import BrandingService


UTM_PARAMS = {
    "utm_source": "invoice",
    "utm_medium": "email",
    "utm_campaign": "powered_by",
}


def _append_utm(url: str, utm: dict[str, str] | None = None) -> str:
    """Append UTM query parameters to a URL."""
    if not url:
        return url
    params = utm or UTM_PARAMS
    parsed = urlparse(url)
    separator = "&" if parsed.query else ""
    new_query = f"{parsed.query}{separator}{urlencode(params)}"
    return urlunparse(parsed._replace(query=new_query))


async def get_email_branded_footer(
    db: AsyncSession,
    org: Any | None = None,
) -> str:
    """Return HTML snippet for the email branded footer.

    Includes platform logo (if set), platform name, and a signup link
    with UTM parameters for attribution tracking.

    White-label orgs on Enterprise plans get an empty footer.
    """
    white_label = False
    if org is not None:
        white_label = BrandingService.is_white_label(
            getattr(org, "white_label_enabled", False),
            getattr(org, "subscription_plan", None),
        )

    svc = BrandingService(db)
    config = await svc.get_powered_by_config(org_white_label_enabled=white_label)

    if not config.show_powered_by:
        return ""

    name = config.platform_name or "OraInvoice"
    signup = _append_utm(config.signup_url or "https://orainvoice.com/signup")
    logo_html = ""
    if config.logo_url:
        logo_html = (
            f'<img src="{config.logo_url}" alt="{name}" '
            f'style="height:24px;margin-bottom:8px;" /><br/>'
        )

    return (
        f'<div style="text-align:center;margin-top:24px;padding-top:16px;'
        f'border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;">'
        f"{logo_html}"
        f'Powered by <a href="{signup}" style="color:#2563EB;'
        f'text-decoration:none;font-weight:600;">{name}</a>'
        f"</div>"
    )


def build_email_branded_footer_sync(
    platform_name: str = "OraInvoice",
    signup_url: str = "https://orainvoice.com/signup",
    logo_url: str | None = None,
    show: bool = True,
) -> str:
    """Synchronous variant for Celery tasks or non-async contexts."""
    if not show:
        return ""
    url = _append_utm(signup_url)
    logo_html = ""
    if logo_url:
        logo_html = (
            f'<img src="{logo_url}" alt="{platform_name}" '
            f'style="height:24px;margin-bottom:8px;" /><br/>'
        )
    return (
        f'<div style="text-align:center;margin-top:24px;padding-top:16px;'
        f'border-top:1px solid #e5e7eb;font-size:12px;color:#6b7280;">'
        f"{logo_html}"
        f'Powered by <a href="{url}" style="color:#2563EB;'
        f'text-decoration:none;font-weight:600;">{platform_name}</a>'
        f"</div>"
    )
