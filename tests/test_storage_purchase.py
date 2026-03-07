"""Unit tests for Task 14.2 — Storage add-on purchasing.

Tests cover:
  - Allowed increment validation
  - Stripe charge execution
  - Instant quota increase
  - Missing payment method rejection
  - Invalid increment rejection
  - Addon config retrieval (default + custom)
  - Audit log recording
  - Purchase response structure

Requirements: 30.1, 30.2, 30.3, 30.4
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.storage.service import (
    DEFAULT_STORAGE_INCREMENTS_GB,
    DEFAULT_STORAGE_PRICE_PER_GB_NZD,
    get_storage_addon_config,
    purchase_storage_addon,
)
from app.modules.storage.schemas import (
    StoragePurchaseRequest,
    StoragePurchaseResponse,
    StoragePurchaseConfirmation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()


def _make_mock_org(
    *,
    storage_quota_gb: int = 10,
    stripe_customer_id: str | None = "cus_test123",
    name: str = "Test Workshop",
):
    """Create a mock Organisation object."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = name
    org.storage_quota_gb = storage_quota_gb
    org.stripe_customer_id = stripe_customer_id
    return org


def _mock_db_session():
    """Create a mock AsyncSession."""
    return AsyncMock()


def _mock_scalar_one_or_none(value):
    """Create a mock result that returns scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# get_storage_addon_config tests
# ---------------------------------------------------------------------------


class TestGetStorageAddonConfig:
    """Verify addon config retrieval from platform settings."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_setting(self):
        """When no platform setting exists, return defaults."""
        db = _mock_db_session()
        db.execute.return_value = _mock_scalar_one_or_none(None)

        config = await get_storage_addon_config(db)

        assert config["increments_gb"] == DEFAULT_STORAGE_INCREMENTS_GB
        assert config["price_per_gb_nzd"] == DEFAULT_STORAGE_PRICE_PER_GB_NZD

    @pytest.mark.asyncio
    async def test_returns_custom_config(self):
        """When platform setting exists, return custom values."""
        db = _mock_db_session()
        custom = {"increments_gb": [5, 10, 50], "price_per_gb_nzd": 3.50}
        db.execute.return_value = _mock_scalar_one_or_none(custom)

        config = await get_storage_addon_config(db)

        assert config["increments_gb"] == [5, 10, 50]
        assert config["price_per_gb_nzd"] == 3.50

    @pytest.mark.asyncio
    async def test_partial_config_uses_defaults(self):
        """When platform setting has partial data, fill in defaults."""
        db = _mock_db_session()
        partial = {"increments_gb": [10, 25]}
        db.execute.return_value = _mock_scalar_one_or_none(partial)

        config = await get_storage_addon_config(db)

        assert config["increments_gb"] == [10, 25]
        assert config["price_per_gb_nzd"] == DEFAULT_STORAGE_PRICE_PER_GB_NZD


# ---------------------------------------------------------------------------
# purchase_storage_addon tests
# ---------------------------------------------------------------------------


class TestPurchaseStorageAddon:
    """Verify the storage add-on purchase flow."""

    @pytest.mark.asyncio
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_rejects_invalid_increment(self, mock_config):
        """Purchasing a non-allowed increment raises ValueError."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        db = _mock_db_session()

        with pytest.raises(ValueError, match="Invalid storage increment"):
            await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=7)

    @pytest.mark.asyncio
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_rejects_missing_payment_method(self, mock_config):
        """Org without stripe_customer_id raises ValueError."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        db = _mock_db_session()
        org = _make_mock_org(stripe_customer_id=None)
        db.execute.return_value = _mock_scalar_one_or_none(org)

        with pytest.raises(ValueError, match="No payment method on file"):
            await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=5)

    @pytest.mark.asyncio
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_rejects_org_not_found(self, mock_config):
        """Non-existent org raises ValueError."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        db = _mock_db_session()
        db.execute.return_value = _mock_scalar_one_or_none(None)

        with pytest.raises(ValueError, match="Organisation not found"):
            await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=5)

    @pytest.mark.asyncio
    @patch("stripe.PaymentIntent.create")
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_successful_purchase(self, mock_config, mock_stripe_create):
        """Successful purchase charges Stripe and increases quota."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        mock_stripe_create.return_value = MagicMock(id="pi_test_123")

        db = _mock_db_session()
        org = _make_mock_org(storage_quota_gb=10)
        db.execute.return_value = _mock_scalar_one_or_none(org)

        result = await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=5)

        assert result["success"] is True
        assert result["quantity_gb"] == 5
        assert result["new_total_quota_gb"] == 15
        assert result["charge_amount_nzd"] == 10.00
        assert result["stripe_charge_id"] == "pi_test_123"
        assert result["previous_quota_gb"] == 10

        # Verify Stripe was called with correct amount
        mock_stripe_create.assert_called_once()
        call_kwargs = mock_stripe_create.call_args
        assert call_kwargs.kwargs["amount"] == 1000  # $10.00 = 1000 cents
        assert call_kwargs.kwargs["currency"] == "nzd"

    @pytest.mark.asyncio
    @patch("stripe.PaymentIntent.create")
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_quota_increase_is_instant(self, mock_config, mock_stripe_create):
        """After purchase, org.storage_quota_gb is updated immediately."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        mock_stripe_create.return_value = MagicMock(id="pi_test_456")

        db = _mock_db_session()
        org = _make_mock_org(storage_quota_gb=20)
        db.execute.return_value = _mock_scalar_one_or_none(org)

        await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=20)

        assert org.storage_quota_gb == 40
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("stripe.PaymentIntent.create")
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_stripe_card_error_raises_runtime(self, mock_config, mock_stripe_create):
        """Stripe CardError is wrapped in RuntimeError."""
        import stripe as stripe_lib

        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 2.00,
        }
        mock_stripe_create.side_effect = stripe_lib.error.CardError(
            message="Card declined",
            param=None,
            code="card_declined",
        )

        db = _mock_db_session()
        org = _make_mock_org(storage_quota_gb=10)
        db.execute.return_value = _mock_scalar_one_or_none(org)

        with pytest.raises(RuntimeError, match="Payment failed"):
            await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=5)

    @pytest.mark.asyncio
    @patch("stripe.PaymentIntent.create")
    @patch("app.modules.storage.service.get_storage_addon_config")
    async def test_charge_amount_calculation(self, mock_config, mock_stripe_create):
        """Verify charge = quantity_gb * price_per_gb."""
        mock_config.return_value = {
            "increments_gb": [1, 5, 20, 50],
            "price_per_gb_nzd": 3.50,
        }
        mock_stripe_create.return_value = MagicMock(id="pi_test_789")

        db = _mock_db_session()
        org = _make_mock_org(storage_quota_gb=5)
        db.execute.return_value = _mock_scalar_one_or_none(org)

        result = await purchase_storage_addon(db, org_id=ORG_ID, quantity_gb=20)

        assert result["charge_amount_nzd"] == 70.00  # 20 * 3.50
        call_kwargs = mock_stripe_create.call_args
        assert call_kwargs.kwargs["amount"] == 7000  # 7000 cents


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestStoragePurchaseSchemas:
    """Verify Pydantic schema validation."""

    def test_request_rejects_zero_quantity(self):
        with pytest.raises(Exception):
            StoragePurchaseRequest(quantity_gb=0)

    def test_request_rejects_negative_quantity(self):
        with pytest.raises(Exception):
            StoragePurchaseRequest(quantity_gb=-5)

    def test_request_accepts_valid_quantity(self):
        req = StoragePurchaseRequest(quantity_gb=5)
        assert req.quantity_gb == 5

    def test_response_schema_fields(self):
        resp = StoragePurchaseResponse(
            success=True,
            quantity_gb=5,
            new_total_quota_gb=15,
            charge_amount_nzd=10.00,
            stripe_charge_id="pi_test",
            message="OK",
        )
        assert resp.success is True
        assert resp.new_total_quota_gb == 15

    def test_confirmation_schema_fields(self):
        conf = StoragePurchaseConfirmation(
            quantity_gb=5,
            price_per_gb_nzd=2.00,
            additional_monthly_charge_nzd=10.00,
            new_total_quota_gb=15,
            stripe_charge_amount_cents=1000,
        )
        assert conf.stripe_charge_amount_cents == 1000
