"""Integration tests for compliance profiles.

**Validates: Requirement 5.2**

Tests:
- 8.4: Selecting NZ sets GST 15%, tax_inclusive=True, date_format=dd/MM/yyyy
- 8.5: Selecting UK sets VAT with standard/reduced/zero rates
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.compliance_profiles.schemas import (
    ComplianceProfileCreate,
    ComplianceProfileUpdate,
    TaxRate,
)
from app.modules.compliance_profiles.service import ComplianceProfileService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(
    country_code: str = "NZ",
    country_name: str = "New Zealand",
    tax_label: str = "GST",
    default_tax_rates: list | None = None,
    tax_number_label: str | None = "GST Number",
    tax_number_regex: str | None = r"^\d{2,3}-?\d{3}-?\d{3}$",
    tax_inclusive_default: bool = True,
    date_format: str = "dd/MM/yyyy",
    number_format: str = "en-NZ",
    currency_code: str = "NZD",
    report_templates: list | None = None,
    gdpr_applicable: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, country_code),
        country_code=country_code,
        country_name=country_name,
        tax_label=tax_label,
        default_tax_rates=default_tax_rates or [{"name": "GST", "rate": 15.0, "is_default": True}],
        tax_number_label=tax_number_label,
        tax_number_regex=tax_number_regex,
        tax_inclusive_default=tax_inclusive_default,
        date_format=date_format,
        number_format=number_format,
        currency_code=currency_code,
        report_templates=report_templates or ["gst_return"],
        gdpr_applicable=gdpr_applicable,
    )


NZ_PROFILE = _make_profile()

UK_PROFILE = _make_profile(
    country_code="GB",
    country_name="United Kingdom",
    tax_label="VAT",
    default_tax_rates=[
        {"name": "Standard", "rate": 20.0, "is_default": True},
        {"name": "Reduced", "rate": 5.0, "is_default": False},
        {"name": "Zero", "rate": 0.0, "is_default": False},
    ],
    tax_number_label="VAT Number",
    tax_number_regex=r"^GB\d{9}$|^GB\d{12}$|^GBGD\d{3}$|^GBHA\d{3}$",
    tax_inclusive_default=True,
    date_format="dd/MM/yyyy",
    number_format="en-GB",
    currency_code="GBP",
    report_templates=["vat_return"],
    gdpr_applicable=True,
)


def _make_service(
    profiles: dict[str, SimpleNamespace] | None = None,
) -> ComplianceProfileService:
    """Create a ComplianceProfileService with mocked DB."""
    profs = profiles or {}
    added: list = []

    mock_db = AsyncMock()
    mock_db.add = lambda obj: added.append(obj)
    mock_db.flush = AsyncMock()

    svc = ComplianceProfileService(mock_db)
    svc._added = added

    original_get = svc.get_by_country_code

    async def fake_get_by_country_code(code: str):
        return profs.get(code.upper())

    svc.get_by_country_code = fake_get_by_country_code

    return svc


# ===========================================================================
# 8.4: Selecting NZ sets GST 15%, tax_inclusive=True, date_format=dd/MM/yyyy
# ===========================================================================


class TestNZComplianceProfile:
    """**Validates: Requirement 5.2** — NZ compliance profile."""

    @pytest.mark.asyncio
    async def test_nz_profile_has_gst_label(self):
        """NZ profile uses GST as the tax label."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        assert profile.tax_label == "GST"

    @pytest.mark.asyncio
    async def test_nz_profile_has_15_percent_rate(self):
        """NZ profile has a default tax rate of 15%."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        rates = profile.default_tax_rates
        default_rate = next(r for r in rates if r.get("is_default", False))
        assert default_rate["rate"] == 15.0

    @pytest.mark.asyncio
    async def test_nz_profile_is_tax_inclusive(self):
        """NZ profile defaults to tax-inclusive pricing."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        assert profile.tax_inclusive_default is True

    @pytest.mark.asyncio
    async def test_nz_profile_date_format(self):
        """NZ profile uses dd/MM/yyyy date format."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        assert profile.date_format == "dd/MM/yyyy"

    @pytest.mark.asyncio
    async def test_nz_profile_currency(self):
        """NZ profile uses NZD currency."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        assert profile.currency_code == "NZD"

    @pytest.mark.asyncio
    async def test_nz_profile_complete_configuration(self):
        """NZ profile has all expected fields configured correctly."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})
        profile = await svc.get_by_country_code("NZ")
        assert profile is not None
        assert profile.tax_label == "GST"
        assert profile.tax_inclusive_default is True
        assert profile.date_format == "dd/MM/yyyy"
        assert profile.currency_code == "NZD"
        assert profile.number_format == "en-NZ"
        default_rate = next(
            r for r in profile.default_tax_rates if r.get("is_default")
        )
        assert default_rate["rate"] == 15.0
        assert default_rate["name"] == "GST"


# ===========================================================================
# 8.5: Selecting UK sets VAT with standard/reduced/zero rates
# ===========================================================================


class TestUKComplianceProfile:
    """**Validates: Requirement 5.2** — UK compliance profile."""

    @pytest.mark.asyncio
    async def test_uk_profile_has_vat_label(self):
        """UK profile uses VAT as the tax label."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        assert profile.tax_label == "VAT"

    @pytest.mark.asyncio
    async def test_uk_profile_has_three_rates(self):
        """UK profile has standard, reduced, and zero VAT rates."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        rates = profile.default_tax_rates
        assert len(rates) == 3
        rate_names = {r["name"] for r in rates}
        assert rate_names == {"Standard", "Reduced", "Zero"}

    @pytest.mark.asyncio
    async def test_uk_standard_rate_is_20(self):
        """UK standard VAT rate is 20%."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        standard = next(r for r in profile.default_tax_rates if r["name"] == "Standard")
        assert standard["rate"] == 20.0
        assert standard["is_default"] is True

    @pytest.mark.asyncio
    async def test_uk_reduced_rate_is_5(self):
        """UK reduced VAT rate is 5%."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        reduced = next(r for r in profile.default_tax_rates if r["name"] == "Reduced")
        assert reduced["rate"] == 5.0

    @pytest.mark.asyncio
    async def test_uk_zero_rate_is_0(self):
        """UK zero VAT rate is 0%."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        zero = next(r for r in profile.default_tax_rates if r["name"] == "Zero")
        assert zero["rate"] == 0.0

    @pytest.mark.asyncio
    async def test_uk_profile_uses_gbp(self):
        """UK profile uses GBP currency."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        assert profile.currency_code == "GBP"

    @pytest.mark.asyncio
    async def test_uk_profile_is_gdpr_applicable(self):
        """UK profile has GDPR applicable flag set."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        assert profile.gdpr_applicable is True

    @pytest.mark.asyncio
    async def test_uk_standard_is_default_rate(self):
        """UK standard rate is marked as the default."""
        svc = _make_service(profiles={"GB": UK_PROFILE})
        profile = await svc.get_by_country_code("GB")
        assert profile is not None
        default_rates = [r for r in profile.default_tax_rates if r.get("is_default")]
        assert len(default_rates) == 1
        assert default_rates[0]["name"] == "Standard"
        assert default_rates[0]["rate"] == 20.0


# ===========================================================================
# Service CRUD tests
# ===========================================================================


class TestComplianceProfileServiceCRUD:
    """Additional service-level tests for create/update."""

    @pytest.mark.asyncio
    async def test_create_duplicate_country_raises_error(self):
        """Creating a profile for an existing country raises ValueError."""
        svc = _make_service(profiles={"NZ": NZ_PROFILE})

        payload = ComplianceProfileCreate(
            country_code="NZ",
            country_name="New Zealand Duplicate",
            tax_label="GST",
            default_tax_rates=[TaxRate(name="GST", rate=15.0, is_default=True)],
            date_format="dd/MM/yyyy",
            number_format="en-NZ",
            currency_code="NZD",
        )

        with pytest.raises(ValueError, match="already exists"):
            await svc.create(payload)

    @pytest.mark.asyncio
    async def test_create_new_country_succeeds(self):
        """Creating a profile for a new country succeeds."""
        svc = _make_service()

        payload = ComplianceProfileCreate(
            country_code="US",
            country_name="United States",
            tax_label="Sales Tax",
            default_tax_rates=[TaxRate(name="State Tax", rate=8.0, is_default=True)],
            date_format="MM/dd/yyyy",
            number_format="en-US",
            currency_code="USD",
        )

        result = await svc.create(payload)
        assert result.country_code == "US"
        assert result.tax_label == "Sales Tax"
        assert len(svc._added) == 1

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self):
        """Updating a non-existent profile returns None."""
        svc = _make_service()
        result = await svc.update("ZZ", ComplianceProfileUpdate(tax_label="New"))
        assert result is None
