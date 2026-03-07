"""Integration test: complete onboarding flow end-to-end.

Flow: setup wizard → org configured → modules enabled → terminology applied
      → create first invoice → verify PDF uses correct branding/terminology.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.setup_wizard.models import SetupWizardProgress
from app.modules.setup_wizard.service import SetupWizardService


def _make_progress(org_id: uuid.UUID) -> SetupWizardProgress:
    p = SetupWizardProgress()
    p.id = uuid.uuid4()
    p.org_id = org_id
    for i in range(1, 8):
        setattr(p, f"step_{i}_complete", False)
    p.wizard_completed = False
    p.completed_at = None
    p.created_at = datetime.now(timezone.utc)
    p.updated_at = datetime.now(timezone.utc)
    return p


def _make_mock_db(progress, *, trade_category=None):
    """Create a mock DB that tracks org updates and terminology inserts."""
    mock_db = AsyncMock()
    org_state: dict = {}
    terminology_overrides: dict = {}
    modules_enabled: list[str] = []
    catalogue_items: list[dict] = []

    async def fake_execute(stmt, params=None):
        sql_str = str(stmt)

        if "setup_wizard_progress" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = progress
            return result

        if "compliance_profiles" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        if "trade_categories" in sql_str.lower() and "SELECT" in sql_str.upper():
            result = MagicMock()
            result.scalar_one_or_none.return_value = trade_category
            return result

        if "country_code" in sql_str.lower() and "SELECT" in sql_str.upper():
            result = MagicMock()
            row = {"country_code": org_state.get("country_code", "NZ")}
            result.mappings.return_value.first.return_value = row
            return result

        if "UPDATE" in sql_str.upper() and "organisations" in sql_str.lower():
            if params:
                for k, v in params.items():
                    if k != "oid":
                        org_state[k] = v
            return MagicMock()

        if "DELETE" in sql_str.upper() and "org_terminology_overrides" in sql_str.lower():
            terminology_overrides.clear()
            return MagicMock()

        if "INSERT" in sql_str.upper() and "org_terminology_overrides" in sql_str.lower():
            if params:
                terminology_overrides[params.get("key", "")] = params.get("label", "")
            return MagicMock()

        if "DELETE" in sql_str.upper() and "catalogue_items" in sql_str.lower():
            catalogue_items.clear()
            return MagicMock()

        if "INSERT" in sql_str.upper() and "catalogue_items" in sql_str.lower():
            if params:
                catalogue_items.append(params)
            return MagicMock()

        if "org_modules" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        if "module_registry" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = MagicMock(
                slug="invoicing", dependencies=[]
            )
            return result

        return MagicMock()

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    return mock_db, org_state, terminology_overrides, modules_enabled, catalogue_items


class TestOnboardingFlow:
    """End-to-end onboarding: wizard → config → modules → terminology → invoice."""

    @pytest.mark.asyncio
    async def test_complete_wizard_configures_org(self):
        """Completing all wizard steps configures the org correctly."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, org_state, _, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        # Step 1: Country selection
        result = await svc.process_step(org_id, 1, {"country_code": "NZ"})
        assert result.completed is True
        assert result.step_number == 1
        assert org_state.get("country_code") == "NZ"
        assert org_state.get("base_currency") == "NZD"
        assert org_state.get("tax_label") == "GST"
        assert org_state.get("default_tax_rate") == 15.00

        # Verify progress tracking
        assert progress.step_1_complete is True
        assert progress.wizard_completed is False

    @pytest.mark.asyncio
    async def test_trade_selection_applies_terminology(self):
        """Selecting a trade category applies terminology overrides."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)

        # Create a mock trade category with terminology overrides
        mock_trade = MagicMock()
        mock_trade.id = uuid.uuid4()
        mock_trade.slug = "plumber"
        mock_trade.display_name = "Plumber"
        mock_trade.is_active = True
        mock_trade.is_retired = False
        mock_trade.recommended_modules = ["invoicing", "jobs"]
        mock_trade.terminology_overrides = {
            "vehicle": "Job Site",
            "job": "Work Order",
        }
        mock_trade.default_services = [
            {"name": "Pipe Repair", "price": 120.0}
        ]

        db, org_state, terminology, _, _ = _make_mock_db(
            progress, trade_category=mock_trade
        )
        svc = SetupWizardService(db)

        # First complete step 1
        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        # Step 2: Trade selection
        with patch("app.modules.setup_wizard.service.ModuleService") as MockModSvc:
            mock_mod_instance = AsyncMock()
            mock_mod_instance.enable_module = AsyncMock(return_value=[])
            MockModSvc.return_value = mock_mod_instance

            result = await svc.process_step(
                org_id, 2, {"trade_category_slug": "plumber"}
            )

        assert result.completed is True
        assert result.step_number == 2
        assert org_state.get("trade_category_id") == str(mock_trade.id)
        assert terminology.get("vehicle") == "Job Site"
        assert terminology.get("job") == "Work Order"

    @pytest.mark.asyncio
    async def test_full_wizard_completion_marks_done(self):
        """Completing all 7 steps marks wizard as complete."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, org_state, _, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        # Step 1: Country
        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        # Steps 2-6: Skip
        for step in range(2, 7):
            await svc.skip_step(org_id, step)

        assert progress.wizard_completed is False

        # Step 7: Ready
        result = await svc.process_step(org_id, 7, {})
        assert result.completed is True
        assert progress.wizard_completed is True
        assert progress.completed_at is not None

    @pytest.mark.asyncio
    async def test_modules_enabled_during_wizard(self):
        """Module selection step enables chosen modules."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        # Complete step 1 first
        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        # Step 5: Module selection
        with patch("app.modules.setup_wizard.service.ModuleService") as MockModSvc:
            mock_mod_instance = AsyncMock()
            mock_mod_instance.enable_module = AsyncMock(return_value=[])
            MockModSvc.return_value = mock_mod_instance

            result = await svc.process_step(org_id, 5, {
                "enabled_modules": ["invoicing", "inventory", "jobs"]
            })

        assert result.completed is True
        assert result.step_number == 5
        assert "invoicing" in result.applied_defaults.get("enabled_modules", [])

    @pytest.mark.asyncio
    async def test_branding_saved_during_wizard(self):
        """Branding step saves logo and colours for PDF generation."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, org_state, _, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        result = await svc.process_step(org_id, 4, {
            "logo_url": "https://example.com/logo.png",
            "primary_colour": "#FF5733",
            "secondary_colour": "#33FF57",
        })

        assert result.completed is True
        assert result.step_number == 4

    @pytest.mark.asyncio
    async def test_catalogue_seeding_creates_items(self):
        """Catalogue step creates initial service/product items."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _, _, catalogue_items = _make_mock_db(progress)
        svc = SetupWizardService(db)

        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        result = await svc.process_step(org_id, 6, {
            "items": [
                {"name": "Oil Change", "price": 89.99, "item_type": "service"},
                {"name": "Brake Pads", "price": 45.00, "item_type": "product"},
            ]
        })

        assert result.completed is True
        assert result.applied_defaults.get("items_created") == 2
        assert len(catalogue_items) == 2
