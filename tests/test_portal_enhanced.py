"""Unit tests for the enhanced Customer Portal module.

Tests:
- 46.8: Portal token authentication with configurable expiry
- 46.9: Portal displays correct loyalty balance

**Validates: Requirement 49 — Customer Portal Enhancements**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.portal.service import (
    _resolve_token,
    get_portal_loyalty,
    get_portal_quotes,
    accept_portal_quote,
    get_portal_assets,
    get_portal_bookings,
)
from app.modules.portal.schemas import (
    PortalBranding,
    PortalLoyaltyResponse,
    PoweredByFooter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_customer(
    org_id: uuid.UUID,
    portal_token: uuid.UUID | None = None,
    is_anonymised: bool = False,
) -> MagicMock:
    c = MagicMock()
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = "Jane"
    c.last_name = "Doe"
    c.email = "jane@example.com"
    c.phone = "+6421000000"
    c.portal_token = portal_token
    c.is_anonymised = is_anonymised
    c.portal_token_expires_at = None
    return c


def _make_org(org_id: uuid.UUID | None = None) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    org.name = "Test Workshop"
    org.settings = {
        "logo_url": "https://example.com/logo.png",
        "primary_colour": "#FF0000",
        "secondary_colour": "#00FF00",
    }
    org.locale = "en-NZ"
    org.white_label_enabled = False
    return org


def _make_loyalty_config(org_id: uuid.UUID, is_active: bool = True) -> MagicMock:
    cfg = MagicMock()
    cfg.id = uuid.uuid4()
    cfg.org_id = org_id
    cfg.earn_rate = Decimal("1.0")
    cfg.redemption_rate = Decimal("0.01")
    cfg.is_active = is_active
    return cfg


def _make_tier(name: str, threshold: int, discount: Decimal = Decimal("0")) -> MagicMock:
    tier = MagicMock()
    tier.id = uuid.uuid4()
    tier.name = name
    tier.threshold_points = threshold
    tier.discount_percent = discount
    tier.benefits = {}
    tier.display_order = 0
    return tier


def _make_transaction(
    tx_type: str, points: int, balance_after: int,
    ref_type: str | None = None,
) -> MagicMock:
    tx = MagicMock()
    tx.transaction_type = tx_type
    tx.points = points
    tx.balance_after = balance_after
    tx.reference_type = ref_type
    tx.created_at = datetime.now(timezone.utc)
    return tx


# ---------------------------------------------------------------------------
# 46.8: Portal token authentication with configurable expiry
# ---------------------------------------------------------------------------

class TestPortalTokenAuth:
    """46.8: Portal token authentication with configurable expiry."""

    @pytest.mark.asyncio
    async def test_valid_token_resolves_customer(self) -> None:
        """A valid portal token returns the customer and org."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)
        org = _make_org(org_id)

        mock_db = AsyncMock()
        # First query: customer lookup
        mock_cust_result = MagicMock()
        mock_cust_result.scalar_one_or_none.return_value = customer
        # Second query: org lookup
        mock_org_result = MagicMock()
        mock_org_result.scalar_one_or_none.return_value = org

        mock_db.execute = AsyncMock(side_effect=[mock_cust_result, mock_org_result])

        result_customer, result_org = await _resolve_token(mock_db, token)
        assert result_customer.id == customer.id
        assert result_org.id == org.id

    @pytest.mark.asyncio
    async def test_invalid_token_raises_error(self) -> None:
        """An invalid portal token raises ValueError."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Invalid or expired portal token"):
            await _resolve_token(mock_db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_anonymised_customer_rejected(self) -> None:
        """An anonymised customer's token is rejected."""
        mock_db = AsyncMock()
        # The query filters is_anonymised=False, so it returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Invalid or expired portal token"):
            await _resolve_token(mock_db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_missing_org_raises_error(self) -> None:
        """If the customer's org doesn't exist, raise ValueError."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)

        mock_db = AsyncMock()
        mock_cust_result = MagicMock()
        mock_cust_result.scalar_one_or_none.return_value = customer
        mock_org_result = MagicMock()
        mock_org_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[mock_cust_result, mock_org_result])

        with pytest.raises(ValueError, match="Organisation not found"):
            await _resolve_token(mock_db, token)


# ---------------------------------------------------------------------------
# 46.9: Portal displays correct loyalty balance
# ---------------------------------------------------------------------------

class TestPortalLoyaltyBalance:
    """46.9: Portal displays correct loyalty balance."""

    @pytest.mark.asyncio
    async def test_loyalty_balance_with_tier(self) -> None:
        """Portal returns correct points, current tier, next tier, and transactions."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)
        org = _make_org(org_id)
        config = _make_loyalty_config(org_id)

        silver_tier = _make_tier("Silver", 100, Decimal("5"))
        gold_tier = _make_tier("Gold", 500, Decimal("10"))

        transactions = [
            _make_transaction("earn", 200, 200, "invoice"),
            _make_transaction("redeem", -50, 150, "invoice"),
        ]

        with (
            patch("app.modules.portal.service._resolve_token", new_callable=AsyncMock) as mock_resolve,
            patch("app.modules.portal.service._get_powered_by", new_callable=AsyncMock) as mock_powered,
            patch("app.modules.loyalty.service.LoyaltyService.get_config", new_callable=AsyncMock) as mock_config,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_balance", new_callable=AsyncMock) as mock_balance,
            patch("app.modules.loyalty.service.LoyaltyService.check_tier_upgrade", new_callable=AsyncMock) as mock_tier,
            patch("app.modules.loyalty.service.LoyaltyService.get_next_tier", new_callable=AsyncMock) as mock_next,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_transactions", new_callable=AsyncMock) as mock_txns,
        ):
            mock_resolve.return_value = (customer, org)
            mock_powered.return_value = PoweredByFooter(platform_name="OraInvoice")
            mock_config.return_value = config
            mock_balance.return_value = 150
            mock_tier.return_value = silver_tier
            mock_next.return_value = gold_tier
            mock_txns.return_value = transactions

            mock_db = AsyncMock()
            result = await get_portal_loyalty(mock_db, token)

            assert isinstance(result, PortalLoyaltyResponse)
            assert result.total_points == 150
            assert result.current_tier is not None
            assert result.current_tier.name == "Silver"
            assert result.current_tier.discount_percent == Decimal("5")
            assert result.next_tier is not None
            assert result.next_tier.name == "Gold"
            assert result.points_to_next_tier == 350  # 500 - 150
            assert len(result.transactions) == 2
            assert result.transactions[0].transaction_type == "earn"
            assert result.transactions[0].points == 200
            assert result.transactions[1].transaction_type == "redeem"
            assert result.transactions[1].points == -50

    @pytest.mark.asyncio
    async def test_loyalty_inactive_returns_zero(self) -> None:
        """When loyalty is not active, return zero points."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)
        org = _make_org(org_id)

        with (
            patch("app.modules.portal.service._resolve_token", new_callable=AsyncMock) as mock_resolve,
            patch("app.modules.portal.service._get_powered_by", new_callable=AsyncMock) as mock_powered,
            patch("app.modules.loyalty.service.LoyaltyService.get_config", new_callable=AsyncMock) as mock_config,
        ):
            mock_resolve.return_value = (customer, org)
            mock_powered.return_value = PoweredByFooter(platform_name="OraInvoice")
            mock_config.return_value = None  # No loyalty config

            mock_db = AsyncMock()
            result = await get_portal_loyalty(mock_db, token)

            assert result.total_points == 0
            assert result.current_tier is None
            assert result.next_tier is None
            assert result.points_to_next_tier is None
            assert len(result.transactions) == 0

    @pytest.mark.asyncio
    async def test_loyalty_no_next_tier(self) -> None:
        """When customer is at the highest tier, next_tier is None."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)
        org = _make_org(org_id)
        config = _make_loyalty_config(org_id)

        gold_tier = _make_tier("Gold", 500, Decimal("10"))

        with (
            patch("app.modules.portal.service._resolve_token", new_callable=AsyncMock) as mock_resolve,
            patch("app.modules.portal.service._get_powered_by", new_callable=AsyncMock) as mock_powered,
            patch("app.modules.loyalty.service.LoyaltyService.get_config", new_callable=AsyncMock) as mock_config,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_balance", new_callable=AsyncMock) as mock_balance,
            patch("app.modules.loyalty.service.LoyaltyService.check_tier_upgrade", new_callable=AsyncMock) as mock_tier,
            patch("app.modules.loyalty.service.LoyaltyService.get_next_tier", new_callable=AsyncMock) as mock_next,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_transactions", new_callable=AsyncMock) as mock_txns,
        ):
            mock_resolve.return_value = (customer, org)
            mock_powered.return_value = PoweredByFooter(platform_name="OraInvoice")
            mock_config.return_value = config
            mock_balance.return_value = 1000
            mock_tier.return_value = gold_tier
            mock_next.return_value = None  # No higher tier
            mock_txns.return_value = []

            mock_db = AsyncMock()
            result = await get_portal_loyalty(mock_db, token)

            assert result.total_points == 1000
            assert result.current_tier.name == "Gold"
            assert result.next_tier is None
            assert result.points_to_next_tier is None

    @pytest.mark.asyncio
    async def test_loyalty_branding_included(self) -> None:
        """Loyalty response includes org branding and Powered By footer."""
        org_id = uuid.uuid4()
        token = uuid.uuid4()
        customer = _make_customer(org_id, portal_token=token)
        org = _make_org(org_id)
        config = _make_loyalty_config(org_id)

        with (
            patch("app.modules.portal.service._resolve_token", new_callable=AsyncMock) as mock_resolve,
            patch("app.modules.portal.service._get_powered_by", new_callable=AsyncMock) as mock_powered,
            patch("app.modules.loyalty.service.LoyaltyService.get_config", new_callable=AsyncMock) as mock_config,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_balance", new_callable=AsyncMock) as mock_balance,
            patch("app.modules.loyalty.service.LoyaltyService.check_tier_upgrade", new_callable=AsyncMock) as mock_tier,
            patch("app.modules.loyalty.service.LoyaltyService.get_next_tier", new_callable=AsyncMock) as mock_next,
            patch("app.modules.loyalty.service.LoyaltyService.get_customer_transactions", new_callable=AsyncMock) as mock_txns,
        ):
            mock_resolve.return_value = (customer, org)
            mock_powered.return_value = PoweredByFooter(
                platform_name="OraInvoice",
                show_powered_by=True,
            )
            mock_config.return_value = config
            mock_balance.return_value = 0
            mock_tier.return_value = None
            mock_next.return_value = None
            mock_txns.return_value = []

            mock_db = AsyncMock()
            result = await get_portal_loyalty(mock_db, token)

            assert result.branding.org_name == "Test Workshop"
            assert result.branding.powered_by is not None
            assert result.branding.powered_by.platform_name == "OraInvoice"
            assert result.branding.powered_by.show_powered_by is True
            assert result.branding.language == "en-NZ"
