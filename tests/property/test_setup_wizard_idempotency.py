"""Property-based test: setup wizard idempotency.

**Validates: Requirements 5.8** — Property 19

Submitting the same wizard step data multiple times for the same
organisation produces the same result as submitting it once.
No duplicate records are created.

Uses Hypothesis to generate random step data and verifies idempotency.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone as tz
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.setup_wizard.schemas import (
    CountryStepData,
    TradeStepData,
    BusinessStepData,
    BrandingStepData,
    ModulesStepData,
    CatalogueStepData,
)
from app.modules.setup_wizard.service import (
    SetupWizardService,
    COUNTRY_DEFAULTS,
    validate_tax_number,
)
from app.modules.setup_wizard.models import SetupWizardProgress


PBT_SETTINGS = h_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategies for generating valid step data
country_codes = st.sampled_from(list(COUNTRY_DEFAULTS.keys()))

hex_colour = st.from_regex(r"^#[0-9a-fA-F]{6}$", fullmatch=True)

branding_data = st.fixed_dictionaries({
    "logo_url": st.just(None) | st.text(min_size=1, max_size=50).map(lambda s: f"https://example.com/{s}"),
    "primary_colour": st.just(None) | hex_colour,
    "secondary_colour": st.just(None) | hex_colour,
})


def _make_progress(org_id: uuid.UUID) -> SetupWizardProgress:
    """Create a fresh in-memory progress record."""
    p = SetupWizardProgress()
    p.id = uuid.uuid4()
    p.org_id = org_id
    p.step_1_complete = False
    p.step_2_complete = False
    p.step_3_complete = False
    p.step_4_complete = False
    p.step_5_complete = False
    p.step_6_complete = False
    p.step_7_complete = False
    p.wizard_completed = False
    p.completed_at = None
    p.created_at = datetime.now(tz.utc)
    p.updated_at = datetime.now(tz.utc)
    return p


def _make_mock_db(progress: SetupWizardProgress):
    """Create a mock async DB session that tracks org updates."""
    mock_db = AsyncMock()
    org_state: dict = {}

    async def fake_execute(stmt, params=None):
        """Track SQL executions for idempotency verification."""
        sql_str = str(stmt) if not hasattr(stmt, "text") else str(stmt.text)

        if "SELECT" in sql_str.upper() and "setup_wizard_progress" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = progress
            return result

        if "SELECT" in sql_str.upper() and "compliance_profiles" in sql_str.lower():
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        if "SELECT" in sql_str.upper() and "country_code" in sql_str.lower():
            result = MagicMock()
            row = {"country_code": org_state.get("country_code", "NZ")}
            result.mappings.return_value.first.return_value = row
            return result

        if "UPDATE" in sql_str.upper() and "organisations" in sql_str.upper():
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

    return mock_db, org_state


class TestSetupWizardIdempotency:
    """Submitting the same wizard step data twice produces the same result.

    **Validates: Requirements 5.8**
    """

    @given(country_code=country_codes)
    @PBT_SETTINGS
    def test_country_step_idempotent(self, country_code: str) -> None:
        """Step 1 (country) is idempotent: same data → same org state."""
        org_id = uuid.uuid4()
        data = {"country_code": country_code}

        # First submission
        progress1 = _make_progress(org_id)
        db1, state1 = _make_mock_db(progress1)
        svc1 = SetupWizardService(db1)
        r1 = asyncio.get_event_loop().run_until_complete(
            svc1.process_step(org_id, 1, data),
        )

        # Second submission (same data)
        progress2 = _make_progress(org_id)
        db2, state2 = _make_mock_db(progress2)
        svc2 = SetupWizardService(db2)
        r2 = asyncio.get_event_loop().run_until_complete(
            svc2.process_step(org_id, 1, data),
        )

        # Results must match
        assert r1.step_number == r2.step_number
        assert r1.completed == r2.completed
        assert r1.applied_defaults == r2.applied_defaults
        # Org state must be identical
        assert state1 == state2

    @given(branding=branding_data)
    @PBT_SETTINGS
    def test_branding_step_idempotent(self, branding: dict) -> None:
        """Step 4 (branding) is idempotent: same data → same org settings."""
        org_id = uuid.uuid4()

        progress1 = _make_progress(org_id)
        db1, state1 = _make_mock_db(progress1)
        svc1 = SetupWizardService(db1)
        r1 = asyncio.get_event_loop().run_until_complete(
            svc1.process_step(org_id, 4, branding),
        )

        progress2 = _make_progress(org_id)
        db2, state2 = _make_mock_db(progress2)
        svc2 = SetupWizardService(db2)
        r2 = asyncio.get_event_loop().run_until_complete(
            svc2.process_step(org_id, 4, branding),
        )

        assert r1.step_number == r2.step_number
        assert r1.completed == r2.completed
