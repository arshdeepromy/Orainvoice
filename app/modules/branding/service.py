"""Business logic for the platform branding module.

Provides:
- get_branding(): fetch the singleton branding row
- update_branding(): update branding fields
- get_powered_by_config(): branding subset for PDF/email footers
- is_white_label(): check if an org can remove Powered By

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branding.models import PlatformBranding
from app.modules.branding.schemas import PoweredByConfig


class BrandingService:
    """Service layer for platform branding operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_branding(self) -> PlatformBranding | None:
        """Return the singleton platform branding row."""
        result = await self._db.execute(
            select(PlatformBranding).order_by(PlatformBranding.created_at).limit(1)
        )
        return result.scalar_one_or_none()

    async def update_branding(self, **kwargs: object) -> PlatformBranding:
        """Update branding fields. Only non-None values are applied."""
        branding = await self.get_branding()
        if branding is None:
            raise ValueError("Platform branding not configured")

        fields = {k: v for k, v in kwargs.items() if v is not None}
        if not fields:
            return branding

        fields["updated_at"] = datetime.now(timezone.utc)
        await self._db.execute(
            update(PlatformBranding)
            .where(PlatformBranding.id == branding.id)
            .values(**fields)
        )
        await self._db.flush()
        # Re-fetch to get updated values
        result = await self._db.execute(
            select(PlatformBranding).where(PlatformBranding.id == branding.id)
        )
        return result.scalar_one()

    async def get_powered_by_config(
        self,
        org_white_label_enabled: bool = False,
    ) -> PoweredByConfig:
        """Return the branding subset used in PDF/email footers.

        If the org has white-label enabled, ``show_powered_by`` is False.
        """
        branding = await self.get_branding()
        if branding is None:
            return PoweredByConfig(
                platform_name="OraInvoice",
                show_powered_by=not org_white_label_enabled,
            )
        return PoweredByConfig(
            platform_name=branding.platform_name,
            logo_url=branding.logo_url,
            signup_url=branding.signup_url,
            website_url=branding.website_url,
            show_powered_by=not org_white_label_enabled,
        )

    @staticmethod
    def is_white_label(
        white_label_enabled: bool,
        subscription_plan: str | None = None,
    ) -> bool:
        """Check whether an org qualifies for white-label (no Powered By).

        Only Enterprise-tier orgs with ``white_label_enabled=True`` qualify.
        """
        enterprise_plans = {"enterprise", "Enterprise", "ENTERPRISE"}
        if subscription_plan not in enterprise_plans:
            return False
        return white_label_enabled
