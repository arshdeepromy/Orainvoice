"""Comprehensive property-based tests for feature flag and wizard properties.

Properties covered:
  P8  — Feature Flag Evaluation Consistency (determinism)
  P19 — Setup Wizard Idempotency

**Validates: Requirements 8, 19**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone as tz
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import (
    PBT_SETTINGS,
    country_code_strategy,
    trade_category_strategy,
    trade_family_strategy,
    plan_tier_strategy,
)

from app.core.feature_flags import (
    OrgContext,
    TARGETING_PRIORITY,
    evaluate_flag,
)
from app.modules.setup_wizard.service import (
    SetupWizardService,
    COUNTRY_DEFAULTS,
)
from app.modules.setup_wizard.models import SetupWizardProgress


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

slug_st = st.from_regex(r"[a-z][a-z0-9_-]{2,20}", fullmatch=True)
org_id_st = st.uuids().map(str)


def _org_context_strategy():
    return st.builds(
        OrgContext,
        org_id=org_id_st,
        trade_category_slug=st.one_of(st.none(), slug_st),
        trade_family_slug=st.one_of(st.none(), slug_st),
        country_code=st.one_of(st.none(), country_code_strategy),
        plan_tier=st.one_of(st.none(), plan_tier_strategy),
    )


def _targeting_rule_strategy():
    return st.one_of(
        st.fixed_dictionaries({
            "type": st.just("org_override"), "value": org_id_st, "enabled": st.booleans(),
        }),
        st.fixed_dictionaries({
            "type": st.just("trade_category"), "value": slug_st, "enabled": st.booleans(),
        }),
        st.fixed_dictionaries({
            "type": st.just("trade_family"), "value": slug_st, "enabled": st.booleans(),
        }),
        st.fixed_dictionaries({
            "type": st.just("country"), "value": country_code_strategy, "enabled": st.booleans(),
        }),
        st.fixed_dictionaries({
            "type": st.just("plan_tier"), "value": plan_tier_strategy, "enabled": st.booleans(),
        }),
        st.fixed_dictionaries({
            "type": st.just("percentage"),
            "value": st.integers(min_value=0, max_value=100).map(str),
            "enabled": st.booleans(),
        }),
    )


# ===========================================================================
# Feature Flag Evaluation Determinism (P8)
# ===========================================================================


class TestFeatureFlagDeterminism:
    """Feature flag evaluation is deterministic given same inputs.

    **Validates: Requirements 8**
    """

    @given(
        is_active=st.booleans(),
        default_value=st.booleans(),
        targeting_rules=st.lists(_targeting_rule_strategy(), min_size=0, max_size=10),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_same_inputs_produce_same_output(
        self, is_active, default_value, targeting_rules, org_context,
    ) -> None:
        """P8: calling evaluate_flag twice with identical inputs returns same result."""
        r1 = evaluate_flag(
            is_active=is_active, default_value=default_value,
            targeting_rules=targeting_rules, org_context=org_context,
        )
        r2 = evaluate_flag(
            is_active=is_active, default_value=default_value,
            targeting_rules=targeting_rules, org_context=org_context,
        )
        assert r1 == r2

    @given(
        default_value=st.booleans(),
        targeting_rules=st.lists(_targeting_rule_strategy(), min_size=0, max_size=10),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_inactive_flag_returns_default(
        self, default_value, targeting_rules, org_context,
    ) -> None:
        """P8: inactive flag always returns default_value."""
        result = evaluate_flag(
            is_active=False, default_value=default_value,
            targeting_rules=targeting_rules, org_context=org_context,
        )
        assert result == default_value

    @given(default_value=st.booleans(), org_context=_org_context_strategy())
    @PBT_SETTINGS
    def test_no_rules_returns_default(self, default_value, org_context) -> None:
        """P8: active flag with no rules returns default_value."""
        result = evaluate_flag(
            is_active=True, default_value=default_value,
            targeting_rules=[], org_context=org_context,
        )
        assert result == default_value

    @given(
        default_value=st.booleans(),
        enabled=st.booleans(),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_org_override_takes_highest_priority(
        self, default_value, enabled, org_context,
    ) -> None:
        """P8: org_override rule matching org_id always wins."""
        rules = [
            {"type": "org_override", "value": org_context.org_id, "enabled": enabled},
            {"type": "percentage", "value": "100", "enabled": not enabled},
        ]
        result = evaluate_flag(
            is_active=True, default_value=default_value,
            targeting_rules=rules, org_context=org_context,
        )
        assert result == enabled


# ===========================================================================
# Property 19: Setup Wizard Idempotency
# ===========================================================================

country_codes_st = st.sampled_from(list(COUNTRY_DEFAULTS.keys()))
hex_colour_st = st.from_regex(r"^#[0-9a-fA-F]{6}$", fullmatch=True)


def _make_progress(org_id):
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


def _make_mock_db(progress):
    mock_db = AsyncMock()
    org_state: dict = {}

    async def fake_execute(stmt, params=None):
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
        return MagicMock()

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db, org_state


class TestP19WizardIdempotency:
    """Submitting same wizard step data twice produces same result.

    **Validates: Requirements 19**
    """

    @given(country_code=country_codes_st)
    @PBT_SETTINGS
    def test_country_step_idempotent(self, country_code: str) -> None:
        """P19: step 1 (country) is idempotent."""
        org_id = uuid.uuid4()
        data = {"country_code": country_code}

        progress1 = _make_progress(org_id)
        db1, state1 = _make_mock_db(progress1)
        svc1 = SetupWizardService(db1)
        r1 = asyncio.run(
            svc1.process_step(org_id, 1, data),
        )

        progress2 = _make_progress(org_id)
        db2, state2 = _make_mock_db(progress2)
        svc2 = SetupWizardService(db2)
        r2 = asyncio.run(
            svc2.process_step(org_id, 1, data),
        )

        assert r1.step_number == r2.step_number
        assert r1.completed == r2.completed
        assert r1.applied_defaults == r2.applied_defaults
        assert state1 == state2

    @given(branding=st.fixed_dictionaries({
        "logo_url": st.just(None) | st.text(min_size=1, max_size=50).map(lambda s: f"https://example.com/{s}"),
        "primary_colour": st.just(None) | hex_colour_st,
        "secondary_colour": st.just(None) | hex_colour_st,
    }))
    @PBT_SETTINGS
    def test_branding_step_idempotent(self, branding: dict) -> None:
        """P19: step 4 (branding) is idempotent."""
        org_id = uuid.uuid4()

        progress1 = _make_progress(org_id)
        db1, state1 = _make_mock_db(progress1)
        svc1 = SetupWizardService(db1)
        r1 = asyncio.run(
            svc1.process_step(org_id, 4, branding),
        )

        progress2 = _make_progress(org_id)
        db2, state2 = _make_mock_db(progress2)
        svc2 = SetupWizardService(db2)
        r2 = asyncio.run(
            svc2.process_step(org_id, 4, branding),
        )

        assert r1.step_number == r2.step_number
        assert r1.completed == r2.completed
