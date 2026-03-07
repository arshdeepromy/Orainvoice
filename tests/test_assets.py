"""Unit tests for the extended asset tracking module.

Tests:
- 45.8: Carjam integration only available for automotive trade categories
- 45.9: Asset service history shows all linked invoices, jobs, quotes

**Validates: Extended Asset Tracking**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.assets.schemas import (
    AUTOMOTIVE_FAMILIES,
    TRADE_FAMILY_ASSET_TYPE_MAP,
    CustomFieldDefinition,
    asset_type_for_trade_family,
    is_automotive_trade,
)
from app.modules.assets.service import AssetService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(**overrides):
    asset = MagicMock()
    asset.id = overrides.get("id", uuid.uuid4())
    asset.org_id = overrides.get("org_id", uuid.uuid4())
    asset.customer_id = overrides.get("customer_id", None)
    asset.asset_type = overrides.get("asset_type", "vehicle")
    asset.identifier = overrides.get("identifier", "ABC123")
    asset.make = overrides.get("make", "Toyota")
    asset.model = overrides.get("model", "Corolla")
    asset.year = overrides.get("year", 2020)
    asset.serial_number = overrides.get("serial_number", None)
    asset.custom_fields = overrides.get("custom_fields", {})
    asset.carjam_data = overrides.get("carjam_data", None)
    asset.is_active = overrides.get("is_active", True)
    asset.created_at = datetime.now(timezone.utc)
    asset.updated_at = datetime.now(timezone.utc)
    return asset


def _mock_db():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    return mock_db


# ---------------------------------------------------------------------------
# 45.8: Carjam integration only available for automotive trade categories
# ---------------------------------------------------------------------------

class TestCarjamAutomotiveOnly:
    """45.8: Carjam integration only available for automotive trade categories."""

    def test_is_automotive_trade_true_for_automotive(self):
        assert is_automotive_trade("automotive-transport") is True

    def test_is_automotive_trade_false_for_it(self):
        assert is_automotive_trade("it-technology") is False

    def test_is_automotive_trade_false_for_building(self):
        assert is_automotive_trade("building-construction") is False

    def test_is_automotive_trade_false_for_none(self):
        assert is_automotive_trade(None) is False

    def test_is_automotive_trade_false_for_empty(self):
        assert is_automotive_trade("") is False

    @pytest.mark.asyncio
    async def test_carjam_lookup_raises_for_non_automotive(self):
        """Carjam lookup raises ValueError for non-automotive trades."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()

        with pytest.raises(ValueError, match="only available for automotive"):
            await svc.carjam_lookup(org_id, asset_id, "it-technology")

    @pytest.mark.asyncio
    async def test_carjam_lookup_raises_for_none_trade(self):
        """Carjam lookup raises ValueError when trade family is None."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()

        with pytest.raises(ValueError, match="only available for automotive"):
            await svc.carjam_lookup(org_id, asset_id, None)

    @pytest.mark.asyncio
    async def test_carjam_lookup_allowed_for_automotive(self):
        """Carjam lookup does not raise for automotive trade."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()

        # Mock get_asset to return None (asset not found) — no error raised
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await svc.carjam_lookup(org_id, asset_id, "automotive-transport")
        assert result is None  # No asset found, but no ValueError


# ---------------------------------------------------------------------------
# 45.9: Asset service history shows all linked invoices, jobs, quotes
# ---------------------------------------------------------------------------

class TestAssetServiceHistory:
    """45.9: asset service history shows all linked invoices, jobs, quotes."""

    @pytest.mark.asyncio
    async def test_service_history_returns_jobs(self):
        """Service history includes jobs linked to the asset."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        job_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Mock job query result
        job_row = (job_id, "JOB-001", "Oil change", "completed", now)
        # Mock empty results for invoices and quotes
        mock_jobs = MagicMock()
        mock_jobs.__iter__ = MagicMock(return_value=iter([job_row]))
        mock_empty = MagicMock()
        mock_empty.__iter__ = MagicMock(return_value=iter([]))

        db.execute = AsyncMock(side_effect=[mock_jobs, mock_empty, mock_empty])

        history = await svc.get_service_history(org_id, asset_id)
        assert len(history.entries) == 1
        assert history.entries[0].reference_type == "job"
        assert history.entries[0].reference_id == job_id
        assert history.entries[0].reference_number == "JOB-001"

    @pytest.mark.asyncio
    async def test_service_history_returns_invoices(self):
        """Service history includes invoices linked via jobs."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_empty = MagicMock()
        mock_empty.__iter__ = MagicMock(return_value=iter([]))
        mock_invoices = MagicMock()
        inv_row = (inv_id, "INV-001", "paid", now)
        mock_invoices.__iter__ = MagicMock(return_value=iter([inv_row]))

        db.execute = AsyncMock(side_effect=[mock_empty, mock_invoices, mock_empty])

        history = await svc.get_service_history(org_id, asset_id)
        assert len(history.entries) == 1
        assert history.entries[0].reference_type == "invoice"
        assert history.entries[0].reference_id == inv_id

    @pytest.mark.asyncio
    async def test_service_history_returns_quotes(self):
        """Service history includes quotes linked via jobs."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        quote_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        mock_empty = MagicMock()
        mock_empty.__iter__ = MagicMock(return_value=iter([]))
        mock_quotes = MagicMock()
        quote_row = (quote_id, "QUO-001", "accepted", now)
        mock_quotes.__iter__ = MagicMock(return_value=iter([quote_row]))

        db.execute = AsyncMock(side_effect=[mock_empty, mock_empty, mock_quotes])

        history = await svc.get_service_history(org_id, asset_id)
        assert len(history.entries) == 1
        assert history.entries[0].reference_type == "quote"
        assert history.entries[0].reference_id == quote_id

    @pytest.mark.asyncio
    async def test_service_history_all_types_sorted(self):
        """Service history returns all types sorted by date descending."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        from datetime import timedelta

        job_id = uuid.uuid4()
        inv_id = uuid.uuid4()
        quote_id = uuid.uuid4()

        job_row = (job_id, "JOB-001", "Brake service", "completed", now - timedelta(days=2))
        inv_row = (inv_id, "INV-001", "paid", now)
        quote_row = (quote_id, "QUO-001", "accepted", now - timedelta(days=1))

        mock_jobs = MagicMock()
        mock_jobs.__iter__ = MagicMock(return_value=iter([job_row]))
        mock_invoices = MagicMock()
        mock_invoices.__iter__ = MagicMock(return_value=iter([inv_row]))
        mock_quotes = MagicMock()
        mock_quotes.__iter__ = MagicMock(return_value=iter([quote_row]))

        db.execute = AsyncMock(side_effect=[mock_jobs, mock_invoices, mock_quotes])

        history = await svc.get_service_history(org_id, asset_id)
        assert len(history.entries) == 3
        # Most recent first
        assert history.entries[0].reference_type == "invoice"
        assert history.entries[1].reference_type == "quote"
        assert history.entries[2].reference_type == "job"

    @pytest.mark.asyncio
    async def test_service_history_empty(self):
        """Service history returns empty list when no linked records."""
        db = _mock_db()
        svc = AssetService(db)
        org_id = uuid.uuid4()
        asset_id = uuid.uuid4()

        mock_empty = MagicMock()
        mock_empty.__iter__ = MagicMock(return_value=iter([]))
        db.execute = AsyncMock(return_value=mock_empty)

        history = await svc.get_service_history(org_id, asset_id)
        assert len(history.entries) == 0
        assert history.asset_id == asset_id


# ---------------------------------------------------------------------------
# Asset type determination from trade category
# ---------------------------------------------------------------------------

class TestAssetTypeDetermination:
    """45.6: asset type determination from trade category."""

    def test_automotive_returns_vehicle(self):
        assert asset_type_for_trade_family("automotive-transport") == "vehicle"

    def test_it_returns_device(self):
        assert asset_type_for_trade_family("it-technology") == "device"

    def test_building_returns_property(self):
        assert asset_type_for_trade_family("building-construction") == "property"

    def test_food_returns_equipment(self):
        assert asset_type_for_trade_family("food-hospitality") == "equipment"

    def test_unknown_returns_equipment(self):
        assert asset_type_for_trade_family("unknown-trade") == "equipment"


# ---------------------------------------------------------------------------
# Custom field definition validation
# ---------------------------------------------------------------------------

class TestCustomFieldDefinition:
    """45.5: custom fields per asset type."""

    def test_valid_text_field(self):
        field = CustomFieldDefinition(name="Color", field_type="text")
        assert field.required is False

    def test_valid_dropdown_field(self):
        field = CustomFieldDefinition(
            name="Condition", field_type="dropdown",
            options=["New", "Used", "Refurbished"],
        )
        assert field.options == ["New", "Used", "Refurbished"]

    def test_valid_number_field(self):
        field = CustomFieldDefinition(name="Mileage", field_type="number", required=True)
        assert field.required is True

    def test_valid_date_field(self):
        field = CustomFieldDefinition(name="Purchase Date", field_type="date")
        assert field.field_type == "date"

    def test_invalid_field_type_rejected(self):
        with pytest.raises(Exception):
            CustomFieldDefinition(name="Bad", field_type="invalid")
