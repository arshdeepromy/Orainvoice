"""Domain auto-detection for white-label deployments.

When ``auto_detect_domain`` is enabled in platform branding, the system
can detect whether a request originates from a custom domain (white-label)
vs the default OraInvoice domain, and adjust branding accordingly.

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branding.service import BrandingService

# Default platform domains — requests from these show "Powered by"
DEFAULT_PLATFORM_DOMAINS = frozenset({
    "orainvoice.com",
    "www.orainvoice.com",
    "app.orainvoice.com",
    "localhost",
    "127.0.0.1",
})


async def detect_white_label_domain(
    db: AsyncSession,
    request_host: str,
) -> bool:
    """Return True if the request host is a custom white-label domain.

    When ``auto_detect_domain`` is enabled in branding config, any
    request from a domain NOT in the default platform domains list
    is considered a white-label deployment.
    """
    svc = BrandingService(db)
    branding = await svc.get_branding()

    if branding is None or not branding.auto_detect_domain:
        return False

    # Strip port number if present
    host = request_host.split(":")[0].lower().strip()

    return host not in DEFAULT_PLATFORM_DOMAINS
