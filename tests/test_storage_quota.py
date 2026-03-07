"""Unit tests for Task 14.1 — Storage quota calculation and enforcement.

Tests cover:
  - Storage calculation from invoice JSON, customer records, vehicle records
  - Alert level determination (none/amber/red/blocked)
  - Invoice creation blocking at 100% quota
  - Other functionality allowed at 100% quota
  - Human-readable display formatting
  - Edge cases: zero quota, empty org, boundary percentages

Requirements: 29.1, 29.2, 29.3, 29.4, 29.5
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
    BYTES_PER_GB,
    AMBER_THRESHOLD,
    RED_THRESHOLD,
    BLOCKED_THRESHOLD,
    _bytes_to_display,
    calculate_org_storage,
    check_storage_quota,
    determine_alert_level,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns a scalar value."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _mock_one_or_none_result(row):
    """Create a mock result that returns one_or_none."""
    result = MagicMock()
    result.one_or_none.return_value = row
    return result


# ---------------------------------------------------------------------------
# determine_alert_level tests
# ---------------------------------------------------------------------------


class TestDetermineAlertLevel:
    """Verify alert level thresholds.

    Validates: Requirements 29.2, 29.3, 29.4
    """

    def test_none_at_zero(self):
        assert determine_alert_level(0.0) == "none"

    def test_none_below_amber(self):
        assert determine_alert_level(79.99) == "none"

    def test_amber_at_80(self):
        assert determine_alert_level(80.0) == "amber"

    def test_amber_at_89(self):
        assert determine_alert_level(89.99) == "amber"

    def test_red_at_90(self):
        assert determine_alert_level(90.0) == "red"

    def test_red_at_99(self):
        assert determine_alert_level(99.99) == "red"

    def test_blocked_at_100(self):
        assert determine_alert_level(100.0) == "blocked"

    def test_blocked_above_100(self):
        assert determine_alert_level(150.0) == "blocked"


# ---------------------------------------------------------------------------
# _bytes_to_display tests
# ---------------------------------------------------------------------------


class TestBytesToDisplay:
    """Verify human-readable size formatting."""

    def test_bytes(self):
        assert _bytes_to_display(500) == "500 B"

    def test_kilobytes(self):
        result = _bytes_to_display(2048)
        assert result == "2.00 KB"

    def test_megabytes(self):
        result = _bytes_to_display(5 * 1_048_576)
        assert result == "5.00 MB"

    def test_gigabytes(self):
        result = _bytes_to_display(2 * BYTES_PER_GB)
        assert result == "2.00 GB"

    def test_zero_bytes(self):
        assert _bytes_to_display(0) == "0 B"


# ---------------------------------------------------------------------------
# calculate_org_storage tests
# ---------------------------------------------------------------------------


class TestCalculateOrgStorage:
    """Verify storage calculation sums invoice, customer, and vehicle data.

    Validates: Requirements 29.1
    """

    @pytest.mark.asyncio
    async def test_sums_all_record_types(self):
        """Storage = invoice JSON + customer records + vehicle records."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        # Mock three sequential execute calls: invoices, customers, vehicles
        invoice_result = _mock_scalar_result(1000)
        customer_result = _mock_scalar_result(500)
        vehicle_result = _mock_scalar_result(300)

        db.execute = AsyncMock(
            side_effect=[invoice_result, customer_result, vehicle_result]
        )

        total = await calculate_org_storage(db, org_id)
        assert total == 1800

    @pytest.mark.asyncio
    async def test_empty_org_returns_zero(self):
        """An org with no records should have zero storage."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        zero_result = _mock_scalar_result(0)
        db.execute = AsyncMock(
            side_effect=[zero_result, zero_result, zero_result]
        )

        total = await calculate_org_storage(db, org_id)
        assert total == 0

    @pytest.mark.asyncio
    async def test_null_results_treated_as_zero(self):
        """NULL from DB (no rows) should be treated as 0."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        null_result = _mock_scalar_result(None)
        db.execute = AsyncMock(
            side_effect=[null_result, null_result, null_result]
        )

        total = await calculate_org_storage(db, org_id)
        assert total == 0


# ---------------------------------------------------------------------------
# check_storage_quota tests
# ---------------------------------------------------------------------------


class TestCheckStorageQuota:
    """Verify quota status calculation and enforcement.

    Validates: Requirements 29.1, 29.2, 29.3, 29.4, 29.5
    """

    @pytest.mark.asyncio
    async def test_below_amber_threshold(self):
        """Usage below 80% → alert_level='none', can_create_invoice=True."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        # Org has 1 GB quota
        org_row = (1, 0)  # (storage_quota_gb, storage_used_bytes)
        org_result = _mock_one_or_none_result(org_row)

        # Actual usage: 50% of 1 GB
        used_bytes = int(0.5 * BYTES_PER_GB)
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "none"
        assert status["can_create_invoice"] is True
        assert status["usage_percentage"] == 50.0

    @pytest.mark.asyncio
    async def test_amber_threshold(self):
        """Usage at 80% → alert_level='amber', can_create_invoice=True.

        Validates: Requirement 29.2
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (1, 0)
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = int(0.8 * BYTES_PER_GB)
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "amber"
        assert status["can_create_invoice"] is True

    @pytest.mark.asyncio
    async def test_red_threshold(self):
        """Usage at 90% → alert_level='red', can_create_invoice=True.

        Validates: Requirement 29.3
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (1, 0)
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = int(0.9 * BYTES_PER_GB)
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "red"
        assert status["can_create_invoice"] is True

    @pytest.mark.asyncio
    async def test_blocked_at_100_percent(self):
        """Usage at 100% → alert_level='blocked', can_create_invoice=False.

        Validates: Requirement 29.4
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (1, 0)
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = BYTES_PER_GB  # exactly 100%
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "blocked"
        assert status["can_create_invoice"] is False

    @pytest.mark.asyncio
    async def test_blocked_above_100_percent(self):
        """Usage above 100% → still blocked.

        Validates: Requirement 29.4
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (1, 0)
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = int(1.5 * BYTES_PER_GB)
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "blocked"
        assert status["can_create_invoice"] is False
        assert status["usage_percentage"] == 150.0

    @pytest.mark.asyncio
    async def test_other_ops_allowed_at_100_percent(self):
        """At 100%, only invoice creation is blocked — other fields remain valid.

        Validates: Requirement 29.5
        """
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (1, 0)
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = BYTES_PER_GB
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        # The response still contains valid usage data for display
        assert status["storage_used_bytes"] == BYTES_PER_GB
        assert status["storage_quota_bytes"] == BYTES_PER_GB
        assert "storage_used_display" in status
        assert "storage_quota_display" in status

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Missing org raises ValueError."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_result = _mock_one_or_none_result(None)
        db.execute = AsyncMock(return_value=org_result)

        with pytest.raises(ValueError, match="Organisation not found"):
            await check_storage_quota(db, org_id)

    @pytest.mark.asyncio
    async def test_zero_quota_with_usage(self):
        """Zero quota with any usage → 100% → blocked."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (0, 0)  # 0 GB quota
        org_result = _mock_one_or_none_result(org_row)

        invoice_result = _mock_scalar_result(100)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "blocked"
        assert status["can_create_invoice"] is False

    @pytest.mark.asyncio
    async def test_zero_quota_zero_usage(self):
        """Zero quota with zero usage → 0% → none."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (0, 0)
        org_result = _mock_one_or_none_result(org_row)

        invoice_result = _mock_scalar_result(0)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["alert_level"] == "none"
        assert status["usage_percentage"] == 0.0

    @pytest.mark.asyncio
    async def test_display_fields_present(self):
        """Response includes human-readable display strings."""
        db = _mock_db_session()
        org_id = uuid.uuid4()

        org_row = (5, 0)  # 5 GB quota
        org_result = _mock_one_or_none_result(org_row)

        used_bytes = 2 * BYTES_PER_GB  # 2 GB used
        invoice_result = _mock_scalar_result(used_bytes)
        customer_result = _mock_scalar_result(0)
        vehicle_result = _mock_scalar_result(0)

        db.execute = AsyncMock(
            side_effect=[org_result, invoice_result, customer_result, vehicle_result]
        )

        status = await check_storage_quota(db, org_id)
        assert status["storage_used_display"] == "2.00 GB"
        assert status["storage_quota_display"] == "5.00 GB"
