"""Compliance profile service.

Implements CRUD for country-specific compliance profiles.

**Validates: Requirement 5.2**
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance_profiles.models import ComplianceProfile
from app.modules.compliance_profiles.schemas import (
    ComplianceProfileCreate,
    ComplianceProfileUpdate,
)


class ComplianceProfileService:
    """Service layer for compliance profiles."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[ComplianceProfile]:
        """Return all compliance profiles ordered by country_name."""
        stmt = (
            select(ComplianceProfile)
            .order_by(ComplianceProfile.country_name)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_country_code(
        self, country_code: str,
    ) -> ComplianceProfile | None:
        """Return a single compliance profile by country code."""
        stmt = select(ComplianceProfile).where(
            ComplianceProfile.country_code == country_code.upper(),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self, data: ComplianceProfileCreate,
    ) -> ComplianceProfile:
        """Create a new compliance profile.

        Validates that the country_code is unique.
        """
        existing = await self.get_by_country_code(data.country_code)
        if existing is not None:
            raise ValueError(
                f"Compliance profile for country '{data.country_code}' already exists",
            )

        profile = ComplianceProfile(
            country_code=data.country_code.upper(),
            country_name=data.country_name,
            tax_label=data.tax_label,
            default_tax_rates=[r.model_dump() for r in data.default_tax_rates],
            tax_number_label=data.tax_number_label,
            tax_number_regex=data.tax_number_regex,
            tax_inclusive_default=data.tax_inclusive_default,
            date_format=data.date_format,
            number_format=data.number_format,
            currency_code=data.currency_code,
            report_templates=data.report_templates,
            gdpr_applicable=data.gdpr_applicable,
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def update(
        self, country_code: str, data: ComplianceProfileUpdate,
    ) -> ComplianceProfile | None:
        """Update an existing compliance profile."""
        profile = await self.get_by_country_code(country_code)
        if profile is None:
            return None

        update_fields = data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            if field == "default_tax_rates" and value is not None:
                value = [
                    r.model_dump() if hasattr(r, "model_dump") else r
                    for r in value
                ]
            setattr(profile, field, value)

        await self.db.flush()
        return profile
