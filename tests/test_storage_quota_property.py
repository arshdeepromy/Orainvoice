"""Property-based tests for storage quota enforcement (Task 14.5).

Property 16: Storage Quota Enforcement at 100%
— verify invoice creation blocked at/above quota, other operations
  continue normally.

**Validates: Requirements 29.4, 29.5**

Uses Hypothesis to generate random storage usage and quota values, then
verifies:
  1. When storage usage >= 100% of quota, invoice creation is blocked
     (can_create_invoice is False, alert_level is "blocked")
  2. When storage usage < 100%, invoice creation succeeds
     (can_create_invoice is True)
  3. Other operations (viewing, searching, payments) continue to work
     at 100% quota — check_storage_quota returns a valid response and
     does not raise, regardless of usage level
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# Ensure relationship models are loaded for SQLAlchemy
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.storage.service import (
    BYTES_PER_GB,
    check_storage_quota,
    determine_alert_level,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Quota in GB: 1–100 (realistic range for workshop orgs)
quota_gb_strategy = st.integers(min_value=1, max_value=100)

# Usage as a percentage of quota: 0–200% (allows testing above quota)
usage_percentage_strategy = st.floats(
    min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False
)

# Percentage values that are at or above 100% (blocked territory)
blocked_percentage_strategy = st.floats(
    min_value=100.0, max_value=500.0, allow_nan=False, allow_infinity=False
)

# Percentage values strictly below 100% (allowed territory)
allowed_percentage_strategy = st.floats(
    min_value=0.0, max_value=99.99, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_for_check_quota(quota_gb: int, used_bytes: int):
    """Build a mock AsyncSession that returns the given quota and usage.

    check_storage_quota makes two DB calls:
      1. select(Organisation.storage_quota_gb, Organisation.storage_used_bytes)
         → returns (quota_gb, stored_used_bytes) via one_or_none()
      2. calculate_org_storage → internally runs 3 selects that each return
         a scalar via scalar()

    We mock both paths so the function runs without a real database.
    """
    db = AsyncMock()

    # First call: org lookup returning (quota_gb, storage_used_bytes)
    org_result = MagicMock()
    org_result.one_or_none.return_value = (quota_gb, used_bytes)

    # Subsequent calls: calculate_org_storage runs 3 selects
    # We make them return the used_bytes split across the three queries
    # (invoice_bytes, customer_bytes, vehicle_bytes)
    invoice_result = MagicMock()
    invoice_result.scalar.return_value = used_bytes

    zero_result = MagicMock()
    zero_result.scalar.return_value = 0

    db.execute = AsyncMock(
        side_effect=[org_result, invoice_result, zero_result, zero_result]
    )
    return db


# ---------------------------------------------------------------------------
# Property 16: Storage Quota Enforcement at 100%
# ---------------------------------------------------------------------------


class TestStorageQuotaEnforcementProperty:
    """Property 16: Storage Quota Enforcement at 100%.

    **Validates: Requirements 29.4, 29.5**
    """

    @given(percentage=blocked_percentage_strategy)
    @PBT_SETTINGS
    def test_invoice_creation_blocked_at_or_above_100_percent(
        self, percentage: float
    ):
        """For any usage >= 100%, determine_alert_level returns 'blocked'.

        This is the core gate that check_storage_quota uses to set
        can_create_invoice = False, which blocks invoice creation.

        **Validates: Requirements 29.4**
        """
        alert = determine_alert_level(percentage)
        assert alert == "blocked", (
            f"Expected 'blocked' at {percentage}%, got '{alert}'"
        )

    @given(percentage=allowed_percentage_strategy)
    @PBT_SETTINGS
    def test_invoice_creation_allowed_below_100_percent(
        self, percentage: float
    ):
        """For any usage < 100%, determine_alert_level is NOT 'blocked'.

        This means can_create_invoice will be True.

        **Validates: Requirements 29.4**
        """
        alert = determine_alert_level(percentage)
        assert alert != "blocked", (
            f"Expected non-blocked at {percentage}%, got '{alert}'"
        )

    @given(
        quota_gb=quota_gb_strategy,
        extra_bytes=st.integers(min_value=0, max_value=10 * BYTES_PER_GB),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_check_quota_blocks_invoice_at_full_capacity(
        self, quota_gb: int, extra_bytes: int
    ):
        """check_storage_quota sets can_create_invoice=False when usage >= quota.

        We set used_bytes = quota_bytes + extra_bytes (so usage >= 100%).

        **Validates: Requirements 29.4**
        """
        quota_bytes = quota_gb * BYTES_PER_GB
        used_bytes = quota_bytes + extra_bytes

        db = _mock_db_for_check_quota(quota_gb, used_bytes)
        org_id = uuid.uuid4()

        result = await check_storage_quota(db, org_id)

        assert result["can_create_invoice"] is False, (
            f"Invoice creation should be blocked at {result['usage_percentage']}%"
        )
        assert result["alert_level"] == "blocked"
        assert result["usage_percentage"] >= 100.0

    @given(
        quota_gb=quota_gb_strategy,
        usage_fraction=st.floats(
            min_value=0.0, max_value=0.9999,
            allow_nan=False, allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_check_quota_allows_invoice_below_capacity(
        self, quota_gb: int, usage_fraction: float
    ):
        """check_storage_quota sets can_create_invoice=True when usage < 100%.

        We set used_bytes = floor(quota_bytes * usage_fraction) so usage < 100%.

        **Validates: Requirements 29.4**
        """
        quota_bytes = quota_gb * BYTES_PER_GB
        used_bytes = int(quota_bytes * usage_fraction)
        # Ensure we're strictly below quota
        assume(used_bytes < quota_bytes)

        db = _mock_db_for_check_quota(quota_gb, used_bytes)
        org_id = uuid.uuid4()

        result = await check_storage_quota(db, org_id)

        assert result["can_create_invoice"] is True, (
            f"Invoice creation should be allowed at {result['usage_percentage']}%"
        )
        assert result["alert_level"] != "blocked"

    @given(
        quota_gb=quota_gb_strategy,
        extra_bytes=st.integers(min_value=0, max_value=10 * BYTES_PER_GB),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_other_operations_continue_at_100_percent(
        self, quota_gb: int, extra_bytes: int
    ):
        """check_storage_quota returns a valid response even at/above 100%.

        Other operations (viewing, searching, payments) rely on
        check_storage_quota returning successfully — they do NOT check
        can_create_invoice. The function must never raise for valid orgs
        regardless of usage level.

        **Validates: Requirements 29.5**
        """
        quota_bytes = quota_gb * BYTES_PER_GB
        used_bytes = quota_bytes + extra_bytes

        db = _mock_db_for_check_quota(quota_gb, used_bytes)
        org_id = uuid.uuid4()

        # Must not raise — other operations depend on this succeeding
        result = await check_storage_quota(db, org_id)

        # Response must contain all required fields for the UI
        assert "storage_used_bytes" in result
        assert "storage_quota_bytes" in result
        assert "usage_percentage" in result
        assert "alert_level" in result
        assert "can_create_invoice" in result
        assert "storage_used_display" in result
        assert "storage_quota_display" in result

        # Numeric fields must be sensible
        assert result["storage_used_bytes"] >= 0
        assert result["storage_quota_bytes"] > 0
        assert result["usage_percentage"] >= 0.0
