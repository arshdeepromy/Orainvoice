"""Integration tests for the setup wizard service.

Tests:
- Skipping all steps creates a usable org with NZ defaults
- Wizard progress is persisted and resumable

**Validates: Requirement 5.6, 5.7, 5.8**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone as tz
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.setup_wizard.models import SetupWizardProgress
from app.modules.setup_wizard.service import (
    SetupWizardService,
    COUNTRY_DEFAULTS,
    NZ_DEFAULTS,
    validate_tax_number,
    _abn_check_digit_valid,
)


def _make_progress(org_id: uuid.UUID) -> SetupWizardProgress:
    """Create a fresh in-memory progress record."""
    p = SetupWizardProgress()
    p.id = uuid.uuid4()
    p.org_id = org_id
    for i in range(1, 8):
        setattr(p, f"step_{i}_complete", False)
    p.wizard_completed = False
    p.completed_at = None
    p.created_at = datetime.now(tz.utc)
    p.updated_at = datetime.now(tz.utc)
    return p


def _make_mock_db(progress: SetupWizardProgress):
    """Create a mock DB that tracks org updates."""
    mock_db = AsyncMock()
    org_state: dict = {}
    org_settings: dict = {}

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

        if "DELETE" in sql_str.upper():
            return MagicMock()

        if "INSERT" in sql_str.upper():
            return MagicMock()

        return MagicMock()

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()

    return mock_db, org_state, org_settings


class TestSkipAllSteps:
    """Skipping all steps still creates a usable org with NZ defaults.

    **Validates: Requirement 5.7**
    """

    @pytest.mark.asyncio
    async def test_skip_all_steps_applies_nz_defaults(self):
        """Skipping all 7 steps should mark wizard complete and apply NZ defaults."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, org_state, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        # Skip all 7 steps
        for step in range(1, 8):
            result = await svc.skip_step(org_id, step)
            assert result.completed is True
            assert result.skipped is True

        # Wizard should be marked complete
        assert progress.wizard_completed is True
        assert progress.completed_at is not None

        # All steps should be marked complete
        for i in range(1, 8):
            assert getattr(progress, f"step_{i}_complete") is True

        # Step 1 skip should have applied NZ defaults
        assert org_state.get("country_code") == "NZ"
        assert org_state.get("base_currency") == "NZD"
        assert org_state.get("tax_label") == "GST"
        assert org_state.get("default_tax_rate") == 15.00
        assert org_state.get("timezone") == "Pacific/Auckland"

    @pytest.mark.asyncio
    async def test_skip_step_returns_correct_step_number(self):
        """Each skip returns the correct step number."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        for step in range(1, 8):
            result = await svc.skip_step(org_id, step)
            assert result.step_number == step

    @pytest.mark.asyncio
    async def test_invalid_step_number_raises(self):
        """Step numbers outside 1-7 should raise ValueError."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        with pytest.raises(ValueError, match="Invalid step number"):
            await svc.skip_step(org_id, 0)

        with pytest.raises(ValueError, match="Invalid step number"):
            await svc.skip_step(org_id, 8)


class TestWizardProgressPersistence:
    """Wizard progress is persisted and resumable.

    **Validates: Requirement 5.8**
    """

    @pytest.mark.asyncio
    async def test_progress_persisted_after_step(self):
        """After completing step 1, progress shows step 1 complete."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        await svc.process_step(org_id, 1, {"country_code": "NZ"})

        assert progress.step_1_complete is True
        assert progress.step_2_complete is False
        assert progress.wizard_completed is False

    @pytest.mark.asyncio
    async def test_progress_resumable_after_partial_completion(self):
        """Completing steps 1 and 3 leaves 2,4,5,6,7 incomplete."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        await svc.process_step(org_id, 1, {"country_code": "AU"})
        await svc.skip_step(org_id, 3)

        assert progress.step_1_complete is True
        assert progress.step_2_complete is False
        assert progress.step_3_complete is True
        assert progress.step_4_complete is False
        assert progress.wizard_completed is False

    @pytest.mark.asyncio
    async def test_wizard_completes_when_all_steps_done(self):
        """Wizard is marked complete only when all 7 steps are done."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        # Complete steps 1-6
        await svc.process_step(org_id, 1, {"country_code": "NZ"})
        for step in range(2, 7):
            await svc.skip_step(org_id, step)

        assert progress.wizard_completed is False

        # Complete step 7
        await svc.process_step(org_id, 7, {})
        assert progress.wizard_completed is True
        assert progress.completed_at is not None

    @pytest.mark.asyncio
    async def test_get_or_create_returns_existing(self):
        """get_or_create_progress returns existing record if present."""
        org_id = uuid.uuid4()
        progress = _make_progress(org_id)
        progress.step_1_complete = True
        db, _, _ = _make_mock_db(progress)
        svc = SetupWizardService(db)

        result = await svc.get_or_create_progress(org_id)
        assert result.step_1_complete is True
        assert result.org_id == org_id


class TestTaxNumberValidation:
    """Tax identifier validation per country.

    **Validates: Requirement 5.10**
    """

    def test_nz_gst_valid(self):
        assert validate_tax_number("NZ", "12-345-678") is True

    def test_nz_gst_invalid(self):
        assert validate_tax_number("NZ", "123456789") is False
        assert validate_tax_number("NZ", "12-34-567") is False

    def test_au_abn_valid_format(self):
        assert validate_tax_number("AU", "12345678901") is True

    def test_au_abn_invalid_format(self):
        assert validate_tax_number("AU", "1234567890") is False  # 10 digits
        assert validate_tax_number("AU", "123456789012") is False  # 12 digits

    def test_uk_vat_valid(self):
        assert validate_tax_number("GB", "GB123456789") is True
        assert validate_tax_number("GB", "GB123456789012") is True

    def test_uk_vat_invalid(self):
        assert validate_tax_number("GB", "123456789") is False
        assert validate_tax_number("GB", "GB12345678") is False  # 8 digits

    def test_unknown_country_accepts_anything(self):
        assert validate_tax_number("JP", "anything") is True

    def test_abn_check_digit_valid(self):
        # 51 824 753 556 is a known valid ABN
        assert _abn_check_digit_valid("51824753556") is True

    def test_abn_check_digit_invalid(self):
        assert _abn_check_digit_valid("12345678901") is False

    def test_abn_check_digit_wrong_length(self):
        assert _abn_check_digit_valid("1234") is False
        assert _abn_check_digit_valid("") is False
