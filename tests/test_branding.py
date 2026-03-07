"""Unit tests for the platform branding module.

Tests:
- 44.9:  non-Enterprise orgs cannot remove Powered By footer
- 44.10: UTM parameters are correctly appended to signup links in emails
- 44.11: white-label orgs can replace Powered By with own branding

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.branding.service import BrandingService
from app.modules.branding.email_footer import _append_utm, UTM_PARAMS
from app.modules.branding.pdf_footer import (
    get_pdf_powered_by_footer,
    build_pdf_powered_by_footer_sync,
)
from app.modules.branding.email_footer import (
    get_email_branded_footer,
    build_email_branded_footer_sync,
)
from app.modules.branding.domain_detection import (
    detect_white_label_domain,
    DEFAULT_PLATFORM_DOMAINS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_branding(**overrides):
    branding = MagicMock()
    branding.id = uuid.uuid4()
    branding.platform_name = overrides.get("platform_name", "OraInvoice")
    branding.logo_url = overrides.get("logo_url", "/logo.svg")
    branding.primary_colour = overrides.get("primary_colour", "#2563EB")
    branding.secondary_colour = overrides.get("secondary_colour", "#1E40AF")
    branding.website_url = overrides.get("website_url", "https://orainvoice.com")
    branding.signup_url = overrides.get("signup_url", "https://orainvoice.com/signup")
    branding.support_email = overrides.get("support_email", "support@orainvoice.com")
    branding.terms_url = overrides.get("terms_url", "https://orainvoice.com/terms")
    branding.auto_detect_domain = overrides.get("auto_detect_domain", True)
    return branding


def _make_org(white_label_enabled=False, subscription_plan="pro"):
    org = MagicMock()
    org.white_label_enabled = white_label_enabled
    org.subscription_plan = subscription_plan
    return org


def _mock_db_with_branding(branding=None):
    """Return a mock AsyncSession that returns the given branding row."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = branding
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# 44.9: non-Enterprise orgs cannot remove Powered By footer
# ---------------------------------------------------------------------------

class TestNonEnterpriseCannotRemovePoweredBy:
    """44.9: non-Enterprise orgs cannot remove Powered By footer."""

    def test_is_white_label_false_for_pro_plan(self):
        """Pro plan with white_label_enabled=True still returns False."""
        assert BrandingService.is_white_label(True, "pro") is False

    def test_is_white_label_false_for_starter_plan(self):
        assert BrandingService.is_white_label(True, "starter") is False

    def test_is_white_label_false_for_none_plan(self):
        assert BrandingService.is_white_label(True, None) is False

    def test_is_white_label_false_when_flag_off(self):
        """Enterprise plan but white_label_enabled=False."""
        assert BrandingService.is_white_label(False, "enterprise") is False

    @pytest.mark.asyncio
    async def test_pdf_footer_shown_for_non_enterprise(self):
        """PDF footer is non-empty for a non-Enterprise org."""
        branding = _make_branding()
        mock_db = _mock_db_with_branding(branding)
        org = _make_org(white_label_enabled=True, subscription_plan="pro")

        footer = await get_pdf_powered_by_footer(mock_db, org)
        assert "Powered by" in footer
        assert "OraInvoice" in footer

    @pytest.mark.asyncio
    async def test_email_footer_shown_for_non_enterprise(self):
        """Email footer is non-empty for a non-Enterprise org."""
        branding = _make_branding()
        mock_db = _mock_db_with_branding(branding)
        org = _make_org(white_label_enabled=True, subscription_plan="pro")

        footer = await get_email_branded_footer(mock_db, org)
        assert "Powered by" in footer
        assert "OraInvoice" in footer


# ---------------------------------------------------------------------------
# 44.10: UTM parameters are correctly appended to signup links in emails
# ---------------------------------------------------------------------------

class TestUTMParameters:
    """44.10: UTM parameters are correctly appended to signup links."""

    def test_utm_appended_to_clean_url(self):
        url = _append_utm("https://orainvoice.com/signup")
        assert "utm_source=invoice" in url
        assert "utm_medium=email" in url
        assert "utm_campaign=powered_by" in url

    def test_utm_appended_to_url_with_existing_params(self):
        url = _append_utm("https://orainvoice.com/signup?ref=abc")
        assert "ref=abc" in url
        assert "utm_source=invoice" in url

    def test_utm_empty_url_unchanged(self):
        assert _append_utm("") == ""

    def test_sync_email_footer_contains_utm(self):
        footer = build_email_branded_footer_sync()
        assert "utm_source=invoice" in footer
        assert "utm_medium=email" in footer
        assert "utm_campaign=powered_by" in footer

    @pytest.mark.asyncio
    async def test_async_email_footer_contains_utm(self):
        branding = _make_branding()
        mock_db = _mock_db_with_branding(branding)

        footer = await get_email_branded_footer(mock_db)
        assert "utm_source=invoice" in footer
        assert "utm_medium=email" in footer
        assert "utm_campaign=powered_by" in footer


# ---------------------------------------------------------------------------
# 44.11: white-label orgs can replace Powered By with own branding
# ---------------------------------------------------------------------------

class TestWhiteLabelOrgs:
    """44.11: white-label orgs can replace Powered By with own branding."""

    def test_is_white_label_true_for_enterprise(self):
        assert BrandingService.is_white_label(True, "enterprise") is True

    def test_is_white_label_true_case_variants(self):
        assert BrandingService.is_white_label(True, "Enterprise") is True
        assert BrandingService.is_white_label(True, "ENTERPRISE") is True

    @pytest.mark.asyncio
    async def test_pdf_footer_empty_for_white_label(self):
        """Enterprise org with white_label_enabled gets empty PDF footer."""
        branding = _make_branding()
        mock_db = _mock_db_with_branding(branding)
        org = _make_org(white_label_enabled=True, subscription_plan="enterprise")

        footer = await get_pdf_powered_by_footer(mock_db, org)
        assert footer == ""

    @pytest.mark.asyncio
    async def test_email_footer_empty_for_white_label(self):
        """Enterprise org with white_label_enabled gets empty email footer."""
        branding = _make_branding()
        mock_db = _mock_db_with_branding(branding)
        org = _make_org(white_label_enabled=True, subscription_plan="enterprise")

        footer = await get_email_branded_footer(mock_db, org)
        assert footer == ""

    def test_sync_pdf_footer_hidden_when_show_false(self):
        footer = build_pdf_powered_by_footer_sync(show=False)
        assert footer == ""

    def test_sync_email_footer_hidden_when_show_false(self):
        footer = build_email_branded_footer_sync(show=False)
        assert footer == ""


# ---------------------------------------------------------------------------
# Domain auto-detection tests
# ---------------------------------------------------------------------------

class TestDomainAutoDetection:
    """44.8: domain auto-detection for white-label deployments."""

    @pytest.mark.asyncio
    async def test_default_domain_not_white_label(self):
        branding = _make_branding(auto_detect_domain=True)
        mock_db = _mock_db_with_branding(branding)
        result = await detect_white_label_domain(mock_db, "app.orainvoice.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_custom_domain_is_white_label(self):
        branding = _make_branding(auto_detect_domain=True)
        mock_db = _mock_db_with_branding(branding)
        result = await detect_white_label_domain(mock_db, "invoicing.mybusiness.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_auto_detect_disabled(self):
        branding = _make_branding(auto_detect_domain=False)
        mock_db = _mock_db_with_branding(branding)
        result = await detect_white_label_domain(mock_db, "invoicing.mybusiness.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_strips_port_from_host(self):
        branding = _make_branding(auto_detect_domain=True)
        mock_db = _mock_db_with_branding(branding)
        result = await detect_white_label_domain(mock_db, "localhost:8000")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_branding_returns_false(self):
        mock_db = _mock_db_with_branding(None)
        result = await detect_white_label_domain(mock_db, "custom.domain.com")
        assert result is False
