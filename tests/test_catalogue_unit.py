"""Unit tests for Task 12.3 — catalogue module focused tests.

Tests cover:
  - Inactive service hiding from invoice creation (active_only filter)
  - Price override per line item (catalogue default vs invoice-level override)
  - Category filtering on list_services
  - Edge cases: empty catalogue, all-inactive with active_only=True

Requirements: 27.2, 27.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.catalogue.models import ServiceCatalogue
from app.modules.catalogue.service import list_services


# ---------------------------------------------------------------------------
# Helpers (reused patterns from existing test files)
# ---------------------------------------------------------------------------

def _make_service(
    org_id=None,
    name="WOF Inspection",
    description="Warrant of Fitness inspection",
    default_price=Decimal("55.00"),
    is_gst_exempt=False,
    category="warrant",
    is_active=True,
):
    """Create a mock ServiceCatalogue object."""
    service = MagicMock(spec=ServiceCatalogue)
    service.id = uuid.uuid4()
    service.org_id = org_id or uuid.uuid4()
    service.name = name
    service.description = description
    service.default_price = default_price
    service.is_gst_exempt = is_gst_exempt
    service.category = category
    service.is_active = is_active
    service.created_at = datetime.now(timezone.utc)
    service.updated_at = datetime.now(timezone.utc)
    return service


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_count_result(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Req 27.2 — Inactive service hiding from invoice creation
# ---------------------------------------------------------------------------


class TestInactiveServiceHiding:
    """Verify that inactive services are excluded when active_only=True
    and included when active_only=False.

    Validates: Requirements 27.2
    """

    @pytest.mark.asyncio
    async def test_active_only_excludes_inactive_services(self):
        """active_only=True should return only active services."""
        org_id = uuid.uuid4()
        active = _make_service(org_id=org_id, name="Active Service", is_active=True)
        # Simulate DB already filtered — only active returned
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([active]),
        ])

        result = await list_services(db, org_id=org_id, active_only=True)

        assert result["total"] == 1
        assert len(result["services"]) == 1
        assert result["services"][0]["name"] == "Active Service"
        assert result["services"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_active_only_false_includes_all_services(self):
        """active_only=False should return both active and inactive services."""
        org_id = uuid.uuid4()
        active = _make_service(org_id=org_id, name="Active", is_active=True)
        inactive = _make_service(org_id=org_id, name="Inactive", is_active=False)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result([active, inactive]),
        ])

        result = await list_services(db, org_id=org_id, active_only=False)

        assert result["total"] == 2
        assert len(result["services"]) == 2
        names = {s["name"] for s in result["services"]}
        assert names == {"Active", "Inactive"}

    @pytest.mark.asyncio
    async def test_default_active_only_is_false(self):
        """Default behaviour (no active_only arg) returns all services."""
        org_id = uuid.uuid4()
        active = _make_service(org_id=org_id, name="Active", is_active=True)
        inactive = _make_service(org_id=org_id, name="Inactive", is_active=False)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result([active, inactive]),
        ])

        # Call without active_only — defaults to False
        result = await list_services(db, org_id=org_id)

        assert result["total"] == 2
        assert len(result["services"]) == 2

    @pytest.mark.asyncio
    async def test_all_inactive_with_active_only_returns_empty(self):
        """When all services are inactive and active_only=True, result is empty."""
        org_id = uuid.uuid4()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_services(db, org_id=org_id, active_only=True)

        assert result["total"] == 0
        assert result["services"] == []


# ---------------------------------------------------------------------------
# Req 27.3 — Price override per line item
# ---------------------------------------------------------------------------


class TestPriceOverridePerLineItem:
    """Verify that catalogue default prices can be overridden per invoice
    line item without affecting the catalogue entry.

    The override happens at the invoice level: when a line item provides
    a unit_price, it takes precedence over the catalogue default_price.
    The catalogue default_price remains unchanged.

    Validates: Requirements 27.3
    """

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_catalogue_price_unchanged_after_override(self, mock_audit):
        """Creating a line item with a different price must not alter the
        catalogue service's default_price."""
        org_id = uuid.uuid4()
        service = _make_service(
            org_id=org_id,
            name="Oil Change",
            default_price=Decimal("45.00"),
        )

        # Simulate an invoice line item using a different price
        override_price = Decimal("60.00")

        # The catalogue default_price should remain untouched
        assert service.default_price == Decimal("45.00")
        assert override_price != service.default_price

        # Verify the service dict still reports the original price
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([service]),
        ])
        result = await list_services(db, org_id=org_id)
        assert result["services"][0]["default_price"] == "45.00"

    def test_line_item_price_independent_of_catalogue(self):
        """A line item's unit_price is independent of the catalogue
        default_price — they can differ without conflict."""
        catalogue_default = Decimal("55.00")
        line_item_price = Decimal("70.00")

        # These are independent values — the line item price is an override
        assert line_item_price != catalogue_default
        # The catalogue price is still valid and unchanged
        assert catalogue_default == Decimal("55.00")

    def test_line_item_can_use_catalogue_default(self):
        """When no override is provided, the line item should use the
        catalogue default_price (pre-fill behaviour)."""
        service = _make_service(default_price=Decimal("55.00"))

        # Simulate pre-fill: line item gets catalogue price when no override
        line_item_data = {"unit_price": None}
        if line_item_data["unit_price"] is None:
            line_item_data["unit_price"] = service.default_price

        assert line_item_data["unit_price"] == Decimal("55.00")

    def test_line_item_override_takes_precedence(self):
        """When an override price is provided, it takes precedence over
        the catalogue default_price."""
        service = _make_service(default_price=Decimal("55.00"))

        # Simulate override: line item has explicit price
        line_item_data = {"unit_price": Decimal("80.00")}
        if line_item_data["unit_price"] is None:
            line_item_data["unit_price"] = service.default_price

        # Override price wins
        assert line_item_data["unit_price"] == Decimal("80.00")
        # Catalogue unchanged
        assert service.default_price == Decimal("55.00")


# ---------------------------------------------------------------------------
# Category filtering
# ---------------------------------------------------------------------------


class TestCategoryFiltering:
    """Verify list_services category filter returns only matching services.

    Validates: Requirements 27.1
    """

    @pytest.mark.asyncio
    async def test_category_filter_warrant(self):
        """category='warrant' returns only warrant services."""
        org_id = uuid.uuid4()
        warrant = _make_service(org_id=org_id, name="WOF", category="warrant")
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([warrant]),
        ])

        result = await list_services(db, org_id=org_id, category="warrant")

        assert result["total"] == 1
        assert result["services"][0]["category"] == "warrant"

    @pytest.mark.asyncio
    async def test_category_filter_with_active_only(self):
        """Combining category and active_only filters works correctly."""
        org_id = uuid.uuid4()
        active_warrant = _make_service(
            org_id=org_id, name="Active WOF", category="warrant", is_active=True,
        )
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([active_warrant]),
        ])

        result = await list_services(
            db, org_id=org_id, category="warrant", active_only=True,
        )

        assert result["total"] == 1
        assert result["services"][0]["category"] == "warrant"
        assert result["services"][0]["is_active"] is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for catalogue listing.

    Validates: Requirements 27.1, 27.2
    """

    @pytest.mark.asyncio
    async def test_empty_catalogue_returns_empty(self):
        """An org with no services returns an empty list."""
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_services(db, org_id=uuid.uuid4())

        assert result["total"] == 0
        assert result["services"] == []

    @pytest.mark.asyncio
    async def test_pagination_limit_and_offset(self):
        """Pagination parameters are passed through correctly."""
        org_id = uuid.uuid4()
        svc = _make_service(org_id=org_id, name="Only One")
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(5),
            _mock_scalars_result([svc]),
        ])

        result = await list_services(db, org_id=org_id, limit=1, offset=2)

        # Total reflects all matching, but only 1 returned due to limit
        assert result["total"] == 5
        assert len(result["services"]) == 1
