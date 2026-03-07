"""PDF footer helper for "Powered by OraInvoice" branding.

Provides a reusable function that generates the powered-by footer
HTML/text for inclusion in all PDF templates (invoice, quote, credit
note, PO, progress claim, variation, receipt).

Usage in any PDF generator::

    from app.modules.branding.pdf_footer import get_pdf_powered_by_footer

    footer_html = await get_pdf_powered_by_footer(db, org)

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branding.service import BrandingService


async def get_pdf_powered_by_footer(
    db: AsyncSession,
    org: Any | None = None,
) -> str:
    """Return HTML snippet for the PDF powered-by footer.

    If the org has ``white_label_enabled=True`` and is on an Enterprise
    plan, the footer is empty (white-label orgs can remove it).

    Parameters
    ----------
    db : AsyncSession
        Active database session.
    org : object, optional
        Organisation object with ``white_label_enabled`` and
        ``subscription_plan`` attributes.  If None, the footer is shown.
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

    website = config.website_url or "https://orainvoice.com"
    name = config.platform_name or "OraInvoice"

    return (
        f'<div style="text-align:center;margin-top:16px;padding-top:8px;'
        f'border-top:1px solid #e5e7eb;font-size:9px;color:#9ca3af;">'
        f'Powered by <a href="{website}" style="color:#2563EB;'
        f'text-decoration:none;">{name}</a>'
        f"</div>"
    )


def build_pdf_powered_by_footer_sync(
    platform_name: str = "OraInvoice",
    website_url: str = "https://orainvoice.com",
    show: bool = True,
) -> str:
    """Synchronous variant for use in Celery tasks or non-async contexts."""
    if not show:
        return ""
    return (
        f'<div style="text-align:center;margin-top:16px;padding-top:8px;'
        f'border-top:1px solid #e5e7eb;font-size:9px;color:#9ca3af;">'
        f'Powered by <a href="{website_url}" style="color:#2563EB;'
        f'text-decoration:none;">{platform_name}</a>'
        f"</div>"
    )
