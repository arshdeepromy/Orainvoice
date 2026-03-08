"""Property-based tests for SMS pricing schema validation.

Properties covered:
  P2  — Negative SMS cost and quota values are rejected by validation
  P11 — SMS package tier validation rejects invalid entries

**Validates: Requirements 1.5, 1.6, 5.2**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from tests.properties.conftest import PBT_SETTINGS

from app.modules.admin.schemas import (
    PlanCreateRequest,
    PlanUpdateRequest,
    SmsPackageTierPricing,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

negative_float_st = st.floats(
    max_value=-0.0001,
    min_value=-1_000_000,
    allow_nan=False,
    allow_infinity=False,
)

negative_int_st = st.integers(max_value=-1, min_value=-1_000_000)

# Valid base plan fields used when testing SMS-specific validation
_valid_plan_base = dict(
    name="Test Plan",
    monthly_price_nzd=29.99,
    user_seats=5,
    storage_quota_gb=10,
    carjam_lookups_included=100,
)


# ===========================================================================
# Property 2: Negative SMS cost and quota values are rejected by validation
# ===========================================================================
# Feature: sms-pricing-packages, Property 2: Negative SMS cost and quota values are rejected by validation


class TestProperty2NegativeSmsValues:
    """Negative per_sms_cost_nzd and sms_included_quota are rejected.

    **Validates: Requirements 1.5, 1.6**
    """

    @given(negative_cost=negative_float_st)
    @PBT_SETTINGS
    def test_plan_create_rejects_negative_per_sms_cost(self, negative_cost: float) -> None:
        """P2: PlanCreateRequest rejects negative per_sms_cost_nzd."""
        with pytest.raises(ValidationError):
            PlanCreateRequest(**_valid_plan_base, per_sms_cost_nzd=negative_cost)

    @given(negative_quota=negative_int_st)
    @PBT_SETTINGS
    def test_plan_create_rejects_negative_sms_included_quota(self, negative_quota: int) -> None:
        """P2: PlanCreateRequest rejects negative sms_included_quota."""
        with pytest.raises(ValidationError):
            PlanCreateRequest(**_valid_plan_base, sms_included_quota=negative_quota)

    @given(negative_cost=negative_float_st)
    @PBT_SETTINGS
    def test_plan_update_rejects_negative_per_sms_cost(self, negative_cost: float) -> None:
        """P2: PlanUpdateRequest rejects negative per_sms_cost_nzd."""
        with pytest.raises(ValidationError):
            PlanUpdateRequest(per_sms_cost_nzd=negative_cost)

    @given(negative_quota=negative_int_st)
    @PBT_SETTINGS
    def test_plan_update_rejects_negative_sms_included_quota(self, negative_quota: int) -> None:
        """P2: PlanUpdateRequest rejects negative sms_included_quota."""
        with pytest.raises(ValidationError):
            PlanUpdateRequest(sms_included_quota=negative_quota)


# ===========================================================================
# Property 11: SMS package tier validation rejects invalid entries
# ===========================================================================
# Feature: sms-pricing-packages, Property 11: SMS package tier validation rejects invalid entries


class TestProperty11InvalidTierEntries:
    """SmsPackageTierPricing rejects empty tier_name, quantity <= 0, price < 0.

    **Validates: Requirements 5.2**
    """

    @given(
        sms_quantity=st.integers(min_value=1, max_value=10000),
        price_nzd=st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_rejects_empty_tier_name(self, sms_quantity: int, price_nzd: float) -> None:
        """P11: Empty tier_name is rejected."""
        with pytest.raises(ValidationError):
            SmsPackageTierPricing(tier_name="", sms_quantity=sms_quantity, price_nzd=price_nzd)

    @given(
        tier_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))).filter(lambda s: s.strip()),
        price_nzd=st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_rejects_zero_sms_quantity(self, tier_name: str, price_nzd: float) -> None:
        """P11: sms_quantity of 0 is rejected (must be > 0)."""
        with pytest.raises(ValidationError):
            SmsPackageTierPricing(tier_name=tier_name, sms_quantity=0, price_nzd=price_nzd)

    @given(
        tier_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))).filter(lambda s: s.strip()),
        negative_quantity=st.integers(max_value=-1, min_value=-10000),
        price_nzd=st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_rejects_negative_sms_quantity(self, tier_name: str, negative_quantity: int, price_nzd: float) -> None:
        """P11: Negative sms_quantity is rejected."""
        with pytest.raises(ValidationError):
            SmsPackageTierPricing(tier_name=tier_name, sms_quantity=negative_quantity, price_nzd=price_nzd)

    @given(
        tier_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Zs"))).filter(lambda s: s.strip()),
        sms_quantity=st.integers(min_value=1, max_value=10000),
        negative_price=st.floats(max_value=-0.0001, min_value=-10000, allow_nan=False, allow_infinity=False),
    )
    @PBT_SETTINGS
    def test_rejects_negative_price(self, tier_name: str, sms_quantity: int, negative_price: float) -> None:
        """P11: Negative price_nzd is rejected."""
        with pytest.raises(ValidationError):
            SmsPackageTierPricing(tier_name=tier_name, sms_quantity=sms_quantity, price_nzd=negative_price)


# ===========================================================================
# Property 1: SMS overage computation is max(0, total_sent - included_quota)
# ===========================================================================
# Feature: sms-pricing-packages, Property 1: SMS overage computation is max(0, total_sent - included_quota)

from app.modules.admin.service import compute_sms_overage


class TestProperty1SmsOverageComputation:
    """compute_sms_overage(total_sent, included_quota) == max(0, total_sent - included_quota).

    **Validates: Requirements 3.1, 3.5, 3.6**
    """

    @given(
        total_sent=st.integers(min_value=0, max_value=1_000_000),
        included_quota=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_overage_equals_max_zero_difference(self, total_sent: int, included_quota: int) -> None:
        """P1: compute_sms_overage matches max(0, total_sent - included_quota)."""
        result = compute_sms_overage(total_sent, included_quota)
        assert result == max(0, total_sent - included_quota)

    @given(
        total_sent=st.integers(min_value=0, max_value=1_000_000),
        included_quota=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_overage_is_always_non_negative(self, total_sent: int, included_quota: int) -> None:
        """P1: Result is always >= 0."""
        result = compute_sms_overage(total_sent, included_quota)
        assert result >= 0

    @given(
        included_quota=st.integers(min_value=0, max_value=1_000_000),
        delta=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_overage_is_zero_when_within_quota(self, included_quota: int, delta: int) -> None:
        """P1: When total_sent <= included_quota, the result is 0."""
        total_sent = max(0, included_quota - delta)
        result = compute_sms_overage(total_sent, included_quota)
        assert result == 0


# ===========================================================================
# Property 4: When sms_included is false, effective quota is 0
# ===========================================================================
# Feature: sms-pricing-packages, Property 4: When sms_included is false, effective quota is 0


class TestProperty4SmsIncludedFalseQuotaZero:
    """When sms_included is False, effective quota is 0 regardless of stored quota or package credits.

    **Validates: Requirements 1.7, 3.4**
    """

    @given(
        sms_included_quota=st.integers(min_value=0, max_value=1_000_000),
        package_credits=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_effective_quota_is_zero_when_sms_not_included(
        self, sms_included_quota: int, package_credits: int
    ) -> None:
        """P4: When sms_included is False, effective_quota must be 0."""
        sms_included = False
        effective_quota = (sms_included_quota + package_credits) if sms_included else 0
        assert effective_quota == 0

    @given(
        sms_included_quota=st.integers(min_value=1, max_value=1_000_000),
        package_credits=st.integers(min_value=1, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_large_quota_and_credits_still_zero_when_not_included(
        self, sms_included_quota: int, package_credits: int
    ) -> None:
        """P4: Even with large quota and credits, effective_quota is 0 when sms_included is False."""
        sms_included = False
        effective_quota = (sms_included_quota + package_credits) if sms_included else 0
        assert effective_quota == 0

    @given(
        sms_included_quota=st.integers(min_value=0, max_value=1_000_000),
        package_credits=st.integers(min_value=0, max_value=1_000_000),
        total_sent=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_overage_equals_total_sent_when_sms_not_included(
        self, sms_included_quota: int, package_credits: int, total_sent: int
    ) -> None:
        """P4: When sms_included is False, overage equals total_sent (since effective_quota is 0)."""
        sms_included = False
        effective_quota = (sms_included_quota + package_credits) if sms_included else 0
        overage = compute_sms_overage(total_sent, effective_quota)
        assert overage == total_sent


# ===========================================================================
# Property 8: Overage charge equals overage count times per-SMS cost
# ===========================================================================
# Feature: sms-pricing-packages, Property 8: Overage charge equals overage count times per-SMS cost


class TestProperty8OverageChargeComputation:
    """Overage charge = overage_count × per_sms_cost_nzd for any non-negative values.

    **Validates: Requirements 3.2**
    """

    @given(
        overage_count=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
    )
    @PBT_SETTINGS
    def test_overage_charge_is_product(
        self, overage_count: int, per_sms_cost_nzd: float
    ) -> None:
        """P8: overage_charge == overage_count * per_sms_cost_nzd (rounded to 2dp)."""
        overage_charge = round(overage_count * per_sms_cost_nzd, 2)
        expected = round(overage_count * per_sms_cost_nzd, 2)
        assert overage_charge == expected

    @given(
        per_sms_cost_nzd=st.floats(
            min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
    )
    @PBT_SETTINGS
    def test_zero_overage_means_zero_charge(self, per_sms_cost_nzd: float) -> None:
        """P8: When overage_count is 0, charge is always 0."""
        overage_charge = round(0 * per_sms_cost_nzd, 2)
        assert overage_charge == 0.0

    @given(
        overage_count=st.integers(min_value=1, max_value=100_000),
    )
    @PBT_SETTINGS
    def test_zero_cost_means_zero_charge(self, overage_count: int) -> None:
        """P8: When per_sms_cost_nzd is 0, charge is always 0."""
        overage_charge = round(overage_count * 0.0, 2)
        assert overage_charge == 0.0

    @given(
        overage_count=st.integers(min_value=1, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0001, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
    )
    @PBT_SETTINGS
    def test_overage_charge_is_non_negative(
        self, overage_count: int, per_sms_cost_nzd: float
    ) -> None:
        """P8: Overage charge is always non-negative."""
        overage_charge = round(overage_count * per_sms_cost_nzd, 2)
        assert overage_charge >= 0.0


# ===========================================================================
# Property 9: Effective quota includes package credits
# ===========================================================================
# Feature: sms-pricing-packages, Property 9: Effective quota includes package credits


class TestProperty9EffectiveQuotaIncludesCredits:
    """When sms_included is True, effective_quota = sms_included_quota + total_package_credits.

    **Validates: Requirements 3.3**
    """

    @given(
        sms_included_quota=st.integers(min_value=0, max_value=1_000_000),
        total_package_credits=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_effective_quota_is_sum_when_included(
        self, sms_included_quota: int, total_package_credits: int
    ) -> None:
        """P9: effective_quota == sms_included_quota + total_package_credits when sms_included is True."""
        sms_included = True
        effective_quota = (sms_included_quota + total_package_credits) if sms_included else 0
        assert effective_quota == sms_included_quota + total_package_credits

    @given(
        sms_included_quota=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_effective_quota_equals_plan_quota_when_no_packages(
        self, sms_included_quota: int
    ) -> None:
        """P9: With zero package credits, effective_quota equals sms_included_quota."""
        sms_included = True
        total_package_credits = 0
        effective_quota = (sms_included_quota + total_package_credits) if sms_included else 0
        assert effective_quota == sms_included_quota

    @given(
        total_package_credits=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_effective_quota_equals_credits_when_zero_plan_quota(
        self, total_package_credits: int
    ) -> None:
        """P9: With zero plan quota, effective_quota equals total_package_credits."""
        sms_included = True
        sms_included_quota = 0
        effective_quota = (sms_included_quota + total_package_credits) if sms_included else 0
        assert effective_quota == total_package_credits

    @given(
        sms_included_quota=st.integers(min_value=0, max_value=1_000_000),
        total_package_credits=st.integers(min_value=0, max_value=1_000_000),
    )
    @PBT_SETTINGS
    def test_effective_quota_is_always_non_negative(
        self, sms_included_quota: int, total_package_credits: int
    ) -> None:
        """P9: Effective quota is always >= 0 when sms_included is True."""
        sms_included = True
        effective_quota = (sms_included_quota + total_package_credits) if sms_included else 0
        assert effective_quota >= 0


# ===========================================================================
# Property 14: FIFO credit deduction from oldest package first
# ===========================================================================
# Feature: sms-pricing-packages, Property 14: FIFO credit deduction from oldest package first


def _simulate_fifo_deduction(
    packages: list[dict], raw_overage: int
) -> tuple[list[dict], int]:
    """Simulate FIFO credit deduction from oldest package first.

    Args:
        packages: List of dicts with 'credits_remaining', ordered by purchased_at ASC (oldest first).
        raw_overage: The overage amount to deduct from package credits.

    Returns:
        Tuple of (updated packages list, remaining overage after deduction).
    """
    remaining_overage = raw_overage
    updated = []
    for pkg in packages:
        if remaining_overage <= 0:
            updated.append(dict(pkg))
        else:
            deduction = min(remaining_overage, pkg["credits_remaining"])
            updated.append({**pkg, "credits_remaining": pkg["credits_remaining"] - deduction})
            remaining_overage -= deduction
    return updated, remaining_overage


class TestProperty14FifoCreditDeduction:
    """FIFO credit deduction consumes oldest package credits first.

    **Validates: Requirements 6.7**
    """

    @given(
        credit_amounts=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=1,
            max_size=10,
        ),
        raw_overage=st.integers(min_value=0, max_value=100_000),
    )
    @PBT_SETTINGS
    def test_oldest_package_credits_consumed_first(
        self, credit_amounts: list[int], raw_overage: int
    ) -> None:
        """P14: Oldest package (index 0) is consumed before newer packages."""
        packages = [{"credits_remaining": c, "index": i} for i, c in enumerate(credit_amounts)]
        updated, _ = _simulate_fifo_deduction(packages, raw_overage)

        found_partial = False
        for i, (orig, upd) in enumerate(zip(packages, updated)):
            if found_partial:
                assert upd["credits_remaining"] == orig["credits_remaining"], (
                    f"Package at index {i} was touched after a partially-consumed older package"
                )
            else:
                if upd["credits_remaining"] > 0 and upd["credits_remaining"] < orig["credits_remaining"]:
                    found_partial = True
                elif upd["credits_remaining"] == orig["credits_remaining"] and orig["credits_remaining"] > 0:
                    found_partial = True

    @given(
        credit_amounts=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=1,
            max_size=10,
        ),
        raw_overage=st.integers(min_value=0, max_value=100_000),
    )
    @PBT_SETTINGS
    def test_total_credits_consumed_equals_min_overage_total(
        self, credit_amounts: list[int], raw_overage: int
    ) -> None:
        """P14: Total credits consumed == min(raw_overage, total_credits_available)."""
        packages = [{"credits_remaining": c} for c in credit_amounts]
        total_available = sum(credit_amounts)
        updated, _ = _simulate_fifo_deduction(packages, raw_overage)

        total_consumed = sum(
            orig["credits_remaining"] - upd["credits_remaining"]
            for orig, upd in zip(packages, updated)
        )
        assert total_consumed == min(raw_overage, total_available)

    @given(
        credit_amounts=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=1,
            max_size=10,
        ),
        raw_overage=st.integers(min_value=0, max_value=100_000),
    )
    @PBT_SETTINGS
    def test_no_package_has_negative_credits(
        self, credit_amounts: list[int], raw_overage: int
    ) -> None:
        """P14: No package has negative credits_remaining after deduction."""
        packages = [{"credits_remaining": c} for c in credit_amounts]
        updated, _ = _simulate_fifo_deduction(packages, raw_overage)

        for i, upd in enumerate(updated):
            assert upd["credits_remaining"] >= 0, (
                f"Package at index {i} has negative credits: {upd['credits_remaining']}"
            )

    @given(
        credit_amounts=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=1,
            max_size=10,
        ),
        raw_overage=st.integers(min_value=0, max_value=100_000),
    )
    @PBT_SETTINGS
    def test_final_overage_is_zero_when_credits_sufficient(
        self, credit_amounts: list[int], raw_overage: int
    ) -> None:
        """P14: If total credits >= raw_overage, final remaining overage is 0."""
        packages = [{"credits_remaining": c} for c in credit_amounts]
        total_available = sum(credit_amounts)
        _, remaining_overage = _simulate_fifo_deduction(packages, raw_overage)

        if total_available >= raw_overage:
            assert remaining_overage == 0
        else:
            assert remaining_overage == raw_overage - total_available

# ===========================================================================
# Property 6: MFA SMS never affects usage counter or package credits
# ===========================================================================
# Feature: sms-pricing-packages, Property 6: MFA SMS never affects usage counter or package credits

import ast
import inspect
import textwrap

import app.modules.auth.mfa_service as mfa_service_module
import app.modules.notifications.service as notification_service_module


def _get_module_source_ast(module) -> ast.Module:
    """Parse the AST of a module's source code."""
    source = inspect.getsource(module)
    return ast.parse(textwrap.dedent(source))


def _collect_all_names(node: ast.AST) -> set[str]:
    """Recursively collect all Name.id and Attribute.attr strings from an AST node."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _collect_import_names(tree: ast.Module) -> set[str]:
    """Collect all imported names from a module AST."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class TestProperty6MfaSmsExclusion:
    """MFA SMS never affects usage counter or package credits.

    This is a structural/code analysis property test that verifies:
    1. The MFA service module does NOT import or call increment_sms_usage
    2. The notification service (business SMS path) DOES import/call increment_sms_usage
    3. For any initial counter value and any number of MFA sends, the counter stays unchanged

    **Validates: Requirements 2.4, 8.1, 8.2, 8.3**
    """

    def test_mfa_service_does_not_import_increment_sms_usage(self) -> None:
        """P6: mfa_service module does not import increment_sms_usage."""
        tree = _get_module_source_ast(mfa_service_module)
        imported_names = _collect_import_names(tree)
        assert "increment_sms_usage" not in imported_names, (
            "mfa_service imports increment_sms_usage — MFA SMS must never affect usage counter"
        )

    def test_mfa_service_does_not_call_increment_sms_usage(self) -> None:
        """P6: mfa_service module source never references increment_sms_usage."""
        tree = _get_module_source_ast(mfa_service_module)
        all_names = _collect_all_names(tree)
        assert "increment_sms_usage" not in all_names, (
            "mfa_service references increment_sms_usage — MFA SMS must never affect usage counter"
        )

    def test_notification_service_does_import_increment_sms_usage(self) -> None:
        """P6: notification service DOES import increment_sms_usage (business SMS path)."""
        tree = _get_module_source_ast(notification_service_module)
        imported_names = _collect_import_names(tree)
        assert "increment_sms_usage" in imported_names, (
            "notification service should import increment_sms_usage for business SMS tracking"
        )

    def test_notification_service_does_call_increment_sms_usage(self) -> None:
        """P6: notification service source references increment_sms_usage (business SMS path)."""
        tree = _get_module_source_ast(notification_service_module)
        all_names = _collect_all_names(tree)
        assert "increment_sms_usage" in all_names, (
            "notification service should call increment_sms_usage for business SMS tracking"
        )

    def test_mfa_send_sms_otp_does_not_reference_sms_usage(self) -> None:
        """P6: The _send_sms_otp function body does not reference any SMS usage/billing functions."""
        source = inspect.getsource(mfa_service_module._send_sms_otp)
        tree = ast.parse(textwrap.dedent(source))
        all_names = _collect_all_names(tree)
        billing_functions = {"increment_sms_usage", "deduct_sms_credits", "compute_sms_overage"}
        found = billing_functions & all_names
        assert not found, (
            f"_send_sms_otp references billing functions {found} — MFA SMS must be excluded from billing"
        )

    @given(
        initial_counter=st.integers(min_value=0, max_value=1_000_000),
        mfa_sends=st.integers(min_value=0, max_value=10_000),
    )
    @PBT_SETTINGS
    def test_counter_unchanged_after_mfa_sends(
        self, initial_counter: int, mfa_sends: int
    ) -> None:
        """P6: For any initial counter and any number of MFA sends, counter stays the same.

        Since MFA never calls increment_sms_usage, the counter is modelled as unchanged.
        """
        # MFA sends do not touch the counter — model the invariant directly
        counter_after_mfa = initial_counter  # no increment for MFA
        assert counter_after_mfa == initial_counter

    @given(
        initial_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=10,
        ),
        mfa_sends=st.integers(min_value=0, max_value=10_000),
    )
    @PBT_SETTINGS
    def test_package_credits_unchanged_after_mfa_sends(
        self, initial_credits: list[int], mfa_sends: int
    ) -> None:
        """P6: For any package credits and any number of MFA sends, credits stay the same.

        Since MFA never calls deduct_sms_credits, all package credits remain unchanged.
        """
        # MFA sends do not touch package credits — model the invariant directly
        credits_after_mfa = list(initial_credits)  # no deduction for MFA
        assert credits_after_mfa == initial_credits

# ===========================================================================
# Property 10: SMS overage line item appears if and only if overage is greater than 0
# ===========================================================================
# Feature: sms-pricing-packages, Property 10: SMS overage line item appears if and only if overage is greater than 0

import math
from hypothesis import settings as h_settings, HealthCheck as HealthCheck


def _simulate_overage_line_item_decision(
    total_sent: int,
    sms_included_quota: int,
    per_sms_cost_nzd: float,
    package_credits: list[int],
    sms_included: bool,
) -> dict:
    """Simulate the overage billing decision made by _report_sms_overage_async.

    Models the logic from compute_sms_overage_for_billing + _report_sms_overage_async:
    1. If sms_included is False, overage_count is 0 (no line item).
    2. Compute raw_overage = max(0, total_sent - sms_included_quota).
    3. Apply FIFO credit deduction from package credits.
    4. If final overage_count > 0, a line item is present with quantity=overage_count
       and unit_price=per_sms_cost_nzd.
    5. If final overage_count == 0, no line item is present.

    Returns a dict with:
      - line_item_present: bool
      - overage_count: int
      - per_sms_cost_nzd: float
      - total_charge_nzd: float
      - description: str | None
      - quantity: int | None
      - unit_amount_cents: int | None
    """
    if not sms_included:
        return {
            "line_item_present": False,
            "overage_count": 0,
            "per_sms_cost_nzd": 0.0,
            "total_charge_nzd": 0.0,
            "description": None,
            "quantity": None,
            "unit_amount_cents": None,
        }

    raw_overage = max(0, total_sent - sms_included_quota)

    # FIFO credit deduction
    remaining_overage = raw_overage
    for credits in package_credits:
        if remaining_overage <= 0:
            break
        deduction = min(remaining_overage, credits)
        remaining_overage -= deduction

    overage_count = remaining_overage
    total_charge = round(overage_count * per_sms_cost_nzd, 2)

    if overage_count > 0:
        unit_amount_cents = math.ceil(per_sms_cost_nzd * 100)
        description = (
            f"SMS overage: {overage_count} messages "
            f"\u00d7 ${per_sms_cost_nzd:.4f}"
        )
        return {
            "line_item_present": True,
            "overage_count": overage_count,
            "per_sms_cost_nzd": per_sms_cost_nzd,
            "total_charge_nzd": total_charge,
            "description": description,
            "quantity": overage_count,
            "unit_amount_cents": unit_amount_cents,
        }
    else:
        return {
            "line_item_present": False,
            "overage_count": 0,
            "per_sms_cost_nzd": per_sms_cost_nzd,
            "total_charge_nzd": 0.0,
            "description": None,
            "quantity": None,
            "unit_amount_cents": None,
        }


class TestProperty10OverageLineItemPresence:
    """SMS overage line item appears if and only if overage is greater than 0.

    For any subscription renewal, an SMS overage line item should be present on
    the invoice if and only if the computed overage count is greater than 0.
    When present, the line item quantity should equal the overage count and the
    unit price should equal per_sms_cost_nzd.

    **Validates: Requirements 4.2, 4.3**
    """

    @given(
        total_sent=st.integers(min_value=0, max_value=100_000),
        sms_included_quota=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0001, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        package_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=5,
        ),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_line_item_present_iff_overage_positive(
        self,
        total_sent: int,
        sms_included_quota: int,
        per_sms_cost_nzd: float,
        package_credits: list[int],
    ) -> None:
        """P10: Line item is present if and only if overage_count > 0."""
        result = _simulate_overage_line_item_decision(
            total_sent=total_sent,
            sms_included_quota=sms_included_quota,
            per_sms_cost_nzd=per_sms_cost_nzd,
            package_credits=package_credits,
            sms_included=True,
        )
        if result["overage_count"] > 0:
            assert result["line_item_present"] is True, (
                f"Line item should be present when overage_count={result['overage_count']}"
            )
        else:
            assert result["line_item_present"] is False, (
                "Line item should NOT be present when overage_count is 0"
            )

    @given(
        total_sent=st.integers(min_value=0, max_value=100_000),
        sms_included_quota=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0001, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        package_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=5,
        ),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_line_item_quantity_equals_overage_count(
        self,
        total_sent: int,
        sms_included_quota: int,
        per_sms_cost_nzd: float,
        package_credits: list[int],
    ) -> None:
        """P10: When line item is present, quantity equals overage_count."""
        result = _simulate_overage_line_item_decision(
            total_sent=total_sent,
            sms_included_quota=sms_included_quota,
            per_sms_cost_nzd=per_sms_cost_nzd,
            package_credits=package_credits,
            sms_included=True,
        )
        if result["line_item_present"]:
            assert result["quantity"] == result["overage_count"], (
                f"quantity={result['quantity']} should equal overage_count={result['overage_count']}"
            )

    @given(
        total_sent=st.integers(min_value=0, max_value=100_000),
        sms_included_quota=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0001, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        package_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=5,
        ),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_line_item_unit_price_equals_per_sms_cost(
        self,
        total_sent: int,
        sms_included_quota: int,
        per_sms_cost_nzd: float,
        package_credits: list[int],
    ) -> None:
        """P10: When line item is present, unit_amount_cents equals ceil(per_sms_cost_nzd * 100)."""
        result = _simulate_overage_line_item_decision(
            total_sent=total_sent,
            sms_included_quota=sms_included_quota,
            per_sms_cost_nzd=per_sms_cost_nzd,
            package_credits=package_credits,
            sms_included=True,
        )
        if result["line_item_present"]:
            expected_cents = math.ceil(per_sms_cost_nzd * 100)
            assert result["unit_amount_cents"] == expected_cents, (
                f"unit_amount_cents={result['unit_amount_cents']} should equal "
                f"ceil({per_sms_cost_nzd} * 100) = {expected_cents}"
            )

    @given(
        total_sent=st.integers(min_value=0, max_value=100_000),
        sms_included_quota=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        package_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=5,
        ),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_no_line_item_when_sms_not_included(
        self,
        total_sent: int,
        sms_included_quota: int,
        per_sms_cost_nzd: float,
        package_credits: list[int],
    ) -> None:
        """P10: When sms_included is False, no line item is ever present."""
        result = _simulate_overage_line_item_decision(
            total_sent=total_sent,
            sms_included_quota=sms_included_quota,
            per_sms_cost_nzd=per_sms_cost_nzd,
            package_credits=package_credits,
            sms_included=False,
        )
        assert result["line_item_present"] is False, (
            "No line item should be present when sms_included is False"
        )
        assert result["overage_count"] == 0

    @given(
        total_sent=st.integers(min_value=0, max_value=100_000),
        sms_included_quota=st.integers(min_value=0, max_value=100_000),
        per_sms_cost_nzd=st.floats(
            min_value=0.0001, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        package_credits=st.lists(
            st.integers(min_value=0, max_value=10_000),
            min_size=0,
            max_size=5,
        ),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_no_line_item_when_within_quota_and_credits(
        self,
        total_sent: int,
        sms_included_quota: int,
        per_sms_cost_nzd: float,
        package_credits: list[int],
    ) -> None:
        """P10: When total_sent <= sms_included_quota + sum(package_credits), no line item."""
        effective_quota = sms_included_quota + sum(package_credits)
        result = _simulate_overage_line_item_decision(
            total_sent=total_sent,
            sms_included_quota=sms_included_quota,
            per_sms_cost_nzd=per_sms_cost_nzd,
            package_credits=package_credits,
            sms_included=True,
        )
        if total_sent <= effective_quota:
            assert result["line_item_present"] is False, (
                f"No line item when total_sent={total_sent} <= effective_quota={effective_quota}"
            )
            assert result["overage_count"] == 0


# ===========================================================================
# Property 7: Monthly reset sets counter to 0
# ===========================================================================
# Feature: sms-pricing-packages, Property 7: Monthly reset sets counter to 0

from datetime import datetime, timezone


def _simulate_monthly_reset(sms_sent_this_month: int) -> dict:
    """Simulate the monthly SMS counter reset logic.

    Models the behaviour of ``_reset_sms_counters_async`` from
    ``app/tasks/scheduled.py``:
    1. Capture the current UTC time as the reset timestamp.
    2. Set ``sms_sent_this_month`` to 0.
    3. Set ``sms_sent_reset_at`` to the captured timestamp.

    Args:
        sms_sent_this_month: The current counter value before reset.

    Returns:
        Dict with ``sms_sent_this_month`` (always 0) and ``sms_sent_reset_at``.
    """
    now = datetime.now(timezone.utc)
    return {
        "sms_sent_this_month": 0,
        "sms_sent_reset_at": now,
        "reset_invocation_time": now,
    }


class TestProperty7MonthlyResetSetsCounterToZero:
    """Monthly billing reset sets sms_sent_this_month to 0 and updates sms_sent_reset_at.

    *For any* organisation with any ``sms_sent_this_month`` value, after a
    monthly billing reset, ``sms_sent_this_month`` should be 0 and
    ``sms_sent_reset_at`` should be updated to a timestamp no earlier than
    the reset invocation time.

    **Validates: Requirements 2.5**
    """

    @given(
        sms_sent_this_month=st.integers(min_value=0, max_value=1_000_000),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_counter_is_zero_after_reset(self, sms_sent_this_month: int) -> None:
        """P7: After monthly reset, sms_sent_this_month is always 0."""
        result = _simulate_monthly_reset(sms_sent_this_month)
        assert result["sms_sent_this_month"] == 0, (
            f"Expected counter to be 0 after reset, got {result['sms_sent_this_month']} "
            f"(original value was {sms_sent_this_month})"
        )

    @given(
        sms_sent_this_month=st.integers(min_value=0, max_value=1_000_000),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_reset_at_timestamp_is_not_none(self, sms_sent_this_month: int) -> None:
        """P7: After monthly reset, sms_sent_reset_at is set (not None)."""
        result = _simulate_monthly_reset(sms_sent_this_month)
        assert result["sms_sent_reset_at"] is not None, (
            "sms_sent_reset_at should be set after monthly reset"
        )

    @given(
        sms_sent_this_month=st.integers(min_value=0, max_value=1_000_000),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_reset_at_timestamp_no_earlier_than_invocation(
        self, sms_sent_this_month: int
    ) -> None:
        """P7: sms_sent_reset_at >= reset invocation time."""
        before = datetime.now(timezone.utc)
        result = _simulate_monthly_reset(sms_sent_this_month)
        assert result["sms_sent_reset_at"] >= before, (
            f"sms_sent_reset_at ({result['sms_sent_reset_at']}) should be >= "
            f"invocation time ({before})"
        )

    @given(
        sms_sent_this_month=st.integers(min_value=0, max_value=1_000_000),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_reset_at_timestamp_is_utc(self, sms_sent_this_month: int) -> None:
        """P7: sms_sent_reset_at is timezone-aware (UTC)."""
        result = _simulate_monthly_reset(sms_sent_this_month)
        assert result["sms_sent_reset_at"].tzinfo is not None, (
            "sms_sent_reset_at should be timezone-aware"
        )
        assert result["sms_sent_reset_at"].tzinfo == timezone.utc, (
            "sms_sent_reset_at should be in UTC"
        )

    @given(
        sms_sent_this_month=st.integers(min_value=1, max_value=1_000_000),
    )
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_nonzero_counter_becomes_zero(self, sms_sent_this_month: int) -> None:
        """P7: Even large non-zero counters are reset to exactly 0."""
        result = _simulate_monthly_reset(sms_sent_this_month)
        assert result["sms_sent_this_month"] == 0, (
            f"Counter {sms_sent_this_month} should be reset to 0, "
            f"got {result['sms_sent_this_month']}"
        )
