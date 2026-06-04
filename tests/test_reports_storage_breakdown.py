"""Unit tests for the storage usage breakdown (reports-remediation A6).

These exercise ``app.modules.reports.service.get_storage_usage`` at the service
level (mocked DB session), asserting the per-category ``breakdown`` introduced
by the reports-remediation spec:

  - ``breakdown`` is non-empty when the org has storage data, and every row is
    shaped ``{category, bytes}`` (R7.1).
  - The breakdown is sourced from the existing storage calculation
    (``calculate_org_storage``) — only rows with ``bytes > 0`` appear (R7.1).
  - The early-return branch (org not found) yields an empty ``breakdown`` list.

Requirements: 7.1

NOTE: ``get_storage_usage`` imports ``calculate_org_storage`` LOCALLY via
``from app.modules.storage.service import calculate_org_storage`` inside the
function body, so the patch target is ``app.modules.storage.service.
calculate_org_storage`` — NOT a name re-exported from the reports module.

The service issues a single DB query before delegating to
``calculate_org_storage``:
  1. organisation storage row -> .one_or_none()
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure all ORM models are loaded for relationship resolution
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.reports.service import get_storage_usage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_row(**kwargs) -> MagicMock:
    """A mock SQLAlchemy result row exposing the given named attributes."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _org_result(storage_used_bytes: int, storage_quota_gb: int) -> MagicMock:
    """The organisation storage row consumed via ``.one_or_none()``."""
    result = MagicMock()
    result.one_or_none.return_value = _mock_row(
        storage_used_bytes=storage_used_bytes,
        storage_quota_gb=storage_quota_gb,
    )
    return result


def _org_not_found_result() -> MagicMock:
    result = MagicMock()
    result.one_or_none.return_value = None
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStorageBreakdown:
    """get_storage_usage — per-category breakdown (A6)."""

    @pytest.mark.asyncio
    async def test_breakdown_non_empty_and_shaped(self):
        """When the org has storage data, ``breakdown`` is non-empty and every
        row is shaped ``{category, bytes}`` (R7.1)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        db.execute.return_value = _org_result(
            storage_used_bytes=2_000_000, storage_quota_gb=5
        )

        calc_breakdown = [
            {"category": "Invoices", "bytes": 1_200_000},
            {"category": "Customers", "bytes": 600_000},
            {"category": "Vehicles", "bytes": 200_000},
        ]
        with patch(
            "app.modules.storage.service.calculate_org_storage",
            new_callable=AsyncMock,
            return_value={"total_bytes": 2_000_000, "breakdown": calc_breakdown},
        ) as mock_calc:
            data = await get_storage_usage(db, org_id)

        # Delegated to the existing storage calculation with the right args.
        mock_calc.assert_awaited_once_with(db, org_id)

        # breakdown is present, non-empty, and sourced from the storage calc.
        assert "breakdown" in data
        assert data["breakdown"] == calc_breakdown
        assert len(data["breakdown"]) == 3

        # Every row is shaped {category, bytes}.
        for row in data["breakdown"]:
            assert set(row.keys()) == {"category", "bytes"}
            assert isinstance(row["category"], str)
            assert isinstance(row["bytes"], int)
            assert row["bytes"] > 0

    @pytest.mark.asyncio
    async def test_breakdown_single_category(self):
        """A single populated category still yields a non-empty, well-shaped
        breakdown (R7.1)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        db.execute.return_value = _org_result(
            storage_used_bytes=500_000, storage_quota_gb=100
        )

        calc_breakdown = [{"category": "Invoices", "bytes": 500_000}]
        with patch(
            "app.modules.storage.service.calculate_org_storage",
            new_callable=AsyncMock,
            return_value={"total_bytes": 500_000, "breakdown": calc_breakdown},
        ):
            data = await get_storage_usage(db, org_id)

        assert data["breakdown"] == calc_breakdown
        assert len(data["breakdown"]) == 1
        assert set(data["breakdown"][0].keys()) == {"category", "bytes"}

    @pytest.mark.asyncio
    async def test_breakdown_empty_when_org_not_found(self):
        """The early-return branch (org row missing) returns an empty
        breakdown list without calling the storage calculation."""
        db = _mock_db()
        org_id = uuid.uuid4()
        db.execute.return_value = _org_not_found_result()

        with patch(
            "app.modules.storage.service.calculate_org_storage",
            new_callable=AsyncMock,
        ) as mock_calc:
            data = await get_storage_usage(db, org_id)

        assert data["breakdown"] == []
        # The storage calc is not reached on the not-found branch.
        mock_calc.assert_not_awaited()
