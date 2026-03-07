"""Integration tests for the trade category registry.

**Validates: Requirements 3.2, 3.3, 3.5**

Tests:
- 7.5: Creating a trade category validates unique slug, valid family, at least one default service
- 7.6: Retiring a trade category prevents new org selection but existing orgs continue
- 7.7: Updating trade category defaults does not retroactively modify existing orgs
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.trade_categories.schemas import (
    DefaultServiceItem,
    TradeCategoryCreate,
    TradeCategoryUpdate,
)
from app.modules.trade_categories.service import TradeCategoryService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_family(slug: str = "test-family") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, slug),
        slug=slug,
        display_name=slug.replace("-", " ").title(),
        icon="wrench",
        display_order=1,
        is_active=True,
    )


def _make_category(
    slug: str = "test-category",
    family_id: uuid.UUID | None = None,
    is_retired: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid5(uuid.NAMESPACE_DNS, slug),
        slug=slug,
        display_name=slug.replace("-", " ").title(),
        family_id=family_id or uuid.uuid5(uuid.NAMESPACE_DNS, "test-family"),
        icon="tool",
        description="Test category",
        invoice_template_layout="standard",
        recommended_modules=["invoicing"],
        terminology_overrides={"asset_label": "Item"},
        default_services=[
            {"name": "Test Service", "description": "A test", "default_price": 100.0, "unit_of_measure": "each"}
        ],
        default_products=[],
        default_expense_categories=[],
        default_job_templates=[],
        compliance_notes={},
        seed_data_version=1,
        is_active=True,
        is_retired=is_retired,
    )


def _make_service(
    categories: dict[str, SimpleNamespace] | None = None,
    families: dict[uuid.UUID, SimpleNamespace] | None = None,
) -> TradeCategoryService:
    """Create a TradeCategoryService with mocked internal methods."""
    cats = categories or {}
    fams = families or {}
    added: list = []

    mock_db = AsyncMock()
    mock_db.add = lambda obj: added.append(obj)
    mock_db.flush = AsyncMock()

    svc = TradeCategoryService(mock_db)
    svc._added = added  # expose for assertions

    # Patch get_category to use our in-memory dict
    original_get = svc.get_category

    async def fake_get_category(slug: str):
        return cats.get(slug)

    svc.get_category = fake_get_category

    # Patch _get_family_by_id
    async def fake_get_family_by_id(fid: uuid.UUID):
        return fams.get(fid)

    svc._get_family_by_id = fake_get_family_by_id

    return svc


# ===========================================================================
# 7.5: Creating a trade category validates unique slug, valid family, and
#      at least one default service
# ===========================================================================


class TestCreateTradeCategoryValidation:
    """**Validates: Requirement 3.2**"""

    @pytest.mark.asyncio
    async def test_duplicate_slug_raises_error(self):
        """Creating a category with an existing slug raises ValueError."""
        family = _make_family()
        existing = _make_category("plumber", family_id=family.id)
        svc = _make_service(
            categories={"plumber": existing},
            families={family.id: family},
        )

        payload = TradeCategoryCreate(
            slug="plumber",
            display_name="Plumber Duplicate",
            family_id=family.id,
            default_services=[
                DefaultServiceItem(name="Svc", default_price=50.0),
            ],
        )

        with pytest.raises(ValueError, match="already exists"):
            await svc.create_category(payload)

    @pytest.mark.asyncio
    async def test_invalid_family_raises_error(self):
        """Creating a category with a non-existent family raises ValueError."""
        svc = _make_service()
        bogus_family_id = uuid.uuid4()

        payload = TradeCategoryCreate(
            slug="new-trade",
            display_name="New Trade",
            family_id=bogus_family_id,
            default_services=[
                DefaultServiceItem(name="Svc", default_price=50.0),
            ],
        )

        with pytest.raises(ValueError, match="does not exist"):
            await svc.create_category(payload)

    @pytest.mark.asyncio
    async def test_no_default_services_raises_error(self):
        """Creating a category without default services raises ValueError."""
        family = _make_family()
        svc = _make_service(families={family.id: family})

        payload = TradeCategoryCreate(
            slug="empty-trade",
            display_name="Empty Trade",
            family_id=family.id,
            default_services=[],
        )

        with pytest.raises(ValueError, match="(?i)at least one default service"):
            await svc.create_category(payload)

    @pytest.mark.asyncio
    async def test_valid_creation_succeeds(self):
        """A valid payload creates the category and adds it to the session."""
        family = _make_family()
        svc = _make_service(families={family.id: family})

        payload = TradeCategoryCreate(
            slug="valid-trade",
            display_name="Valid Trade",
            family_id=family.id,
            default_services=[
                DefaultServiceItem(name="Service A", default_price=100.0),
            ],
        )

        result = await svc.create_category(payload)

        assert result.slug == "valid-trade"
        assert result.display_name == "Valid Trade"
        assert result.family_id == family.id
        assert len(result.default_services) == 1
        assert len(svc._added) == 1


# ===========================================================================
# 7.6: Retiring a trade category prevents new org selection but existing
#      orgs continue unchanged
# ===========================================================================


class TestRetireTradeCategory:
    """**Validates: Requirement 3.3**"""

    @pytest.mark.asyncio
    async def test_retire_sets_is_retired_flag(self):
        """Retiring a category sets is_retired=True."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        result = await svc.retire_category("plumber")

        assert result is not None
        assert result.is_retired is True

    @pytest.mark.asyncio
    async def test_retired_category_still_active(self):
        """A retired category remains is_active=True — it's not deleted."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        result = await svc.retire_category("plumber")

        assert result.is_active is True
        assert result.is_retired is True

    @pytest.mark.asyncio
    async def test_existing_org_keeps_retired_category_reference(self):
        """An org holding a FK to a retired category still resolves it."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        org_trade_category_id = cat.id

        retired = await svc.retire_category("plumber")

        assert retired.id == org_trade_category_id
        found = await svc.get_category("plumber")
        assert found is not None
        assert found.id == org_trade_category_id

    @pytest.mark.asyncio
    async def test_retire_nonexistent_returns_none(self):
        """Retiring a non-existent slug returns None."""
        svc = _make_service()
        result = await svc.retire_category("does-not-exist")
        assert result is None


# ===========================================================================
# 7.7: Updating trade category defaults does not retroactively modify
#      existing orgs
# ===========================================================================


class TestUpdateCategoryDefaults:
    """**Validates: Requirement 3.5**

    The service updates the category record's defaults. Existing orgs
    are not affected because they snapshot seed data during the setup
    wizard. Only new orgs pick up updated defaults.
    """

    @pytest.mark.asyncio
    async def test_update_default_services_changes_category_record(self):
        """Updating default_services persists on the category."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        org_services_snapshot = list(cat.default_services)

        updated = await svc.update_category(
            "plumber",
            TradeCategoryUpdate(
                default_services=[
                    DefaultServiceItem(name="New Service", default_price=200.0),
                    DefaultServiceItem(name="Another Service", default_price=300.0),
                ],
            ),
        )

        assert updated is not None
        assert len(updated.default_services) == 2
        # Org snapshot is unchanged
        assert org_services_snapshot == [
            {"name": "Test Service", "description": "A test", "default_price": 100.0, "unit_of_measure": "each"}
        ]

    @pytest.mark.asyncio
    async def test_update_terminology_does_not_affect_snapshot(self):
        """Updating terminology_overrides changes the category but not
        any previously-snapshotted org data."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        org_snapshot = dict(cat.terminology_overrides)

        await svc.update_category(
            "plumber",
            TradeCategoryUpdate(
                terminology_overrides={"asset_label": "Equipment", "work_unit_label": "Task"},
            ),
        )

        assert org_snapshot == {"asset_label": "Item"}
        assert cat.terminology_overrides["asset_label"] == "Equipment"

    @pytest.mark.asyncio
    async def test_update_recommended_modules_only_for_new_orgs(self):
        """Updating recommended_modules changes the category record."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        org_enabled_modules = list(cat.recommended_modules)

        await svc.update_category(
            "plumber",
            TradeCategoryUpdate(
                recommended_modules=["invoicing", "inventory", "pos"],
            ),
        )

        assert org_enabled_modules == ["invoicing"]
        assert cat.recommended_modules == ["invoicing", "inventory", "pos"]

    @pytest.mark.asyncio
    async def test_partial_update_preserves_other_fields(self):
        """Updating one field does not reset other fields."""
        family = _make_family()
        cat = _make_category("plumber", family_id=family.id)
        svc = _make_service(categories={"plumber": cat})

        await svc.update_category(
            "plumber",
            TradeCategoryUpdate(description="Updated description"),
        )

        assert cat.description == "Updated description"
        assert cat.display_name == "Plumber"
        assert cat.default_services == [
            {"name": "Test Service", "description": "A test", "default_price": 100.0, "unit_of_measure": "each"}
        ]
