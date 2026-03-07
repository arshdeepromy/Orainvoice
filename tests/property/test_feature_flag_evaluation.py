"""Property-based tests for feature flag evaluation.

**Validates: Requirement 2.3** — Feature flag evaluation consistency (Property 8).

Uses Hypothesis to verify that for any flag configuration and org context,
evaluation is deterministic given the same targeting rules.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.core.feature_flags import (
    OrgContext,
    TARGETING_PRIORITY,
    evaluate_flag,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

org_id_strategy = st.uuids().map(str)

slug_strategy = st.from_regex(r"[a-z][a-z0-9_-]{2,20}", fullmatch=True)

country_code_strategy = st.sampled_from(["NZ", "AU", "UK", "US", "CA", "DE", "FR"])

plan_tier_strategy = st.sampled_from(["free", "starter", "professional", "enterprise"])

rule_type_strategy = st.sampled_from(TARGETING_PRIORITY)

percentage_strategy = st.integers(min_value=0, max_value=100).map(str)


def _org_context_strategy():
    """Strategy that generates random OrgContext instances."""
    return st.builds(
        OrgContext,
        org_id=org_id_strategy,
        trade_category_slug=st.one_of(st.none(), slug_strategy),
        trade_family_slug=st.one_of(st.none(), slug_strategy),
        country_code=st.one_of(st.none(), country_code_strategy),
        plan_tier=st.one_of(st.none(), plan_tier_strategy),
    )


def _targeting_rule_strategy(org_context_st=None):
    """Strategy that generates a single targeting rule."""
    return st.one_of(
        # org_override rule
        st.fixed_dictionaries({
            "type": st.just("org_override"),
            "value": org_id_strategy,
            "enabled": st.booleans(),
        }),
        # trade_category rule
        st.fixed_dictionaries({
            "type": st.just("trade_category"),
            "value": slug_strategy,
            "enabled": st.booleans(),
        }),
        # trade_family rule
        st.fixed_dictionaries({
            "type": st.just("trade_family"),
            "value": slug_strategy,
            "enabled": st.booleans(),
        }),
        # country rule
        st.fixed_dictionaries({
            "type": st.just("country"),
            "value": country_code_strategy,
            "enabled": st.booleans(),
        }),
        # plan_tier rule
        st.fixed_dictionaries({
            "type": st.just("plan_tier"),
            "value": plan_tier_strategy,
            "enabled": st.booleans(),
        }),
        # percentage rule
        st.fixed_dictionaries({
            "type": st.just("percentage"),
            "value": percentage_strategy,
            "enabled": st.booleans(),
        }),
    )


# ===========================================================================
# Property Test 4.6: Evaluation is deterministic
# ===========================================================================


class TestFeatureFlagDeterminism:
    """For any flag and org context, evaluation is deterministic given the
    same targeting rules.

    **Validates: Requirements 2.3**
    """

    @given(
        is_active=st.booleans(),
        default_value=st.booleans(),
        targeting_rules=st.lists(_targeting_rule_strategy(), min_size=0, max_size=10),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_same_inputs_produce_same_output(
        self,
        is_active: bool,
        default_value: bool,
        targeting_rules: list,
        org_context: OrgContext,
    ) -> None:
        """Calling evaluate_flag twice with identical inputs must return
        the same result."""
        result1 = evaluate_flag(
            is_active=is_active,
            default_value=default_value,
            targeting_rules=targeting_rules,
            org_context=org_context,
        )
        result2 = evaluate_flag(
            is_active=is_active,
            default_value=default_value,
            targeting_rules=targeting_rules,
            org_context=org_context,
        )
        assert result1 == result2, (
            f"Non-deterministic evaluation: {result1} != {result2} "
            f"for flag (active={is_active}, default={default_value}) "
            f"with {len(targeting_rules)} rules"
        )

    @given(
        default_value=st.booleans(),
        targeting_rules=st.lists(_targeting_rule_strategy(), min_size=0, max_size=10),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_inactive_flag_returns_default(
        self,
        default_value: bool,
        targeting_rules: list,
        org_context: OrgContext,
    ) -> None:
        """An inactive flag always returns its default_value regardless of rules."""
        result = evaluate_flag(
            is_active=False,
            default_value=default_value,
            targeting_rules=targeting_rules,
            org_context=org_context,
        )
        assert result == default_value, (
            f"Inactive flag returned {result} instead of default {default_value}"
        )

    @given(
        default_value=st.booleans(),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_no_rules_returns_default(
        self,
        default_value: bool,
        org_context: OrgContext,
    ) -> None:
        """An active flag with no targeting rules returns its default_value."""
        result = evaluate_flag(
            is_active=True,
            default_value=default_value,
            targeting_rules=[],
            org_context=org_context,
        )
        assert result == default_value, (
            f"Flag with no rules returned {result} instead of default {default_value}"
        )

    @given(
        default_value=st.booleans(),
        enabled=st.booleans(),
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_org_override_takes_highest_priority(
        self,
        default_value: bool,
        enabled: bool,
        org_context: OrgContext,
    ) -> None:
        """An org_override rule matching the org_id always wins over other rules."""
        rules = [
            {"type": "org_override", "value": org_context.org_id, "enabled": enabled},
            {"type": "percentage", "value": "100", "enabled": not enabled},
        ]
        result = evaluate_flag(
            is_active=True,
            default_value=default_value,
            targeting_rules=rules,
            org_context=org_context,
        )
        assert result == enabled, (
            f"org_override should win but got {result} instead of {enabled}"
        )

    @given(
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_percentage_100_always_matches(
        self,
        org_context: OrgContext,
    ) -> None:
        """A percentage rule with value=100 always matches any org."""
        result = evaluate_flag(
            is_active=True,
            default_value=False,
            targeting_rules=[{"type": "percentage", "value": "100", "enabled": True}],
            org_context=org_context,
        )
        assert result is True, "percentage=100 should always match"

    @given(
        org_context=_org_context_strategy(),
    )
    @PBT_SETTINGS
    def test_percentage_0_never_matches(
        self,
        org_context: OrgContext,
    ) -> None:
        """A percentage rule with value=0 never matches any org."""
        result = evaluate_flag(
            is_active=True,
            default_value=False,
            targeting_rules=[{"type": "percentage", "value": "0", "enabled": True}],
            org_context=org_context,
        )
        assert result is False, "percentage=0 should never match"
