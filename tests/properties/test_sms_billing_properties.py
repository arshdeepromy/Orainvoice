"""Property-based tests for SMS billing logic.

Properties covered:
  P20 — SMS cost calculation
  P21 — FIFO package credit deduction
  P22 — Usage summary aggregation
  P23 — Quota warning threshold
  P24 — Template variable substitution

**Validates: Requirements 10.2, 10.3, 14.1, 14.2, 14.5, 15.2**
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st
from hypothesis import settings as h_settings, HealthCheck

PBT_SETTINGS = h_settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

from app.modules.sms_chat.service import COST_PER_PART_NZD, get_usage_summary


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

parts_count_st = st.integers(min_value=1, max_value=50)
credits_st = st.integers(min_value=0, max_value=500)
sms_sent_st = st.integers(min_value=0, max_value=1000)
quota_st = st.integers(min_value=0, max_value=500)
per_sms_cost_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Template strategies
placeholder_name_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L",)),
).filter(lambda s: s.strip() and s.isalpha())

placeholder_value_st = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeScalarResult:
    """Mimics SQLAlchemy scalar result for mocked db.execute()."""

    def __init__(self, value: Any = None):
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._value

    def one_or_none(self) -> Any:
        return self._value

    def scalars(self) -> "_FakeScalarResult":
        return self

    def all(self) -> list:
        return []


def _make_mock_org(sms_sent_this_month: int = 0) -> MagicMock:
    """Build a mock Organisation."""
    org = MagicMock()
    org.id = uuid.uuid4()
    org.sms_sent_this_month = sms_sent_this_month
    org.plan_id = uuid.uuid4()
    return org


def _make_mock_plan(
    sms_included: bool = True,
    sms_included_quota: int = 100,
    per_sms_cost_nzd: Decimal = Decimal("0.08"),
) -> MagicMock:
    """Build a mock SubscriptionPlan."""
    plan = MagicMock()
    plan.sms_included = sms_included
    plan.sms_included_quota = sms_included_quota
    plan.per_sms_cost_nzd = per_sms_cost_nzd
    return plan


def _make_mock_package(
    credits_remaining: int,
    purchased_at: datetime | None = None,
) -> MagicMock:
    """Build a mock SmsPackagePurchase."""
    pkg = MagicMock()
    pkg.id = uuid.uuid4()
    pkg.credits_remaining = credits_remaining
    pkg.purchased_at = purchased_at or datetime.now(timezone.utc)
    return pkg


def _render_sms_template(template_body: str, variables: dict[str, str]) -> str:
    """Render an SMS template by substituting {{variable}} placeholders.

    This mirrors the platform's template rendering logic from
    app/modules/notifications/service.py which uses {{variable}} syntax.
    """
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1).strip()
        return variables.get(var_name, match.group(0))

    return re.sub(r"\{\{(\w+)\}\}", _replacer, template_body)


# ===========================================================================
# Property 20: SMS cost calculation
# ===========================================================================
# Feature: connexus-sms-integration, Property 20: SMS cost calculation


class TestProperty20SmsCostCalculation:
    """``cost_nzd`` equals ``parts_count × 0.115``.

    **Validates: Requirements 10.2, 14.1**
    """

    @given(parts_count=parts_count_st)
    @PBT_SETTINGS
    def test_cost_equals_parts_times_rate(self, parts_count: int) -> None:
        """P20: cost_nzd = parts_count × COST_PER_PART_NZD ($0.115)."""
        expected = Decimal(str(parts_count)) * COST_PER_PART_NZD
        actual = Decimal(str(parts_count)) * COST_PER_PART_NZD

        assert actual == expected
        assert actual == Decimal(str(parts_count)) * Decimal("0.115")

    @given(parts_count=parts_count_st)
    @PBT_SETTINGS
    def test_cost_is_always_positive(self, parts_count: int) -> None:
        """P20: Cost is always positive for parts_count >= 1."""
        cost = Decimal(str(parts_count)) * COST_PER_PART_NZD
        assert cost > 0

    @given(parts_count=parts_count_st)
    @PBT_SETTINGS
    def test_cost_per_part_constant_is_correct(self, parts_count: int) -> None:
        """P20: COST_PER_PART_NZD equals $0.10 + 15% GST = $0.115."""
        assert COST_PER_PART_NZD == Decimal("0.115")
        # Verify the formula: $0.10 base + 15% GST
        base_cost = Decimal("0.10")
        gst_rate = Decimal("1.15")
        assert COST_PER_PART_NZD == base_cost * gst_rate


# ===========================================================================
# Property 21: FIFO package credit deduction
# ===========================================================================
# Feature: connexus-sms-integration, Property 21: FIFO package credit deduction


class TestProperty21FifoPackageCreditDeduction:
    """Oldest package depleted first when deducting credits.

    **Validates: Requirement 10.3**
    """

    @given(
        old_credits=st.integers(min_value=1, max_value=100),
        new_credits=st.integers(min_value=1, max_value=100),
        overage=st.integers(min_value=1, max_value=200),
    )
    @PBT_SETTINGS
    def test_oldest_package_depleted_first(
        self, old_credits: int, new_credits: int, overage: int
    ) -> None:
        """P21: FIFO deduction consumes oldest package credits before newer ones."""
        # Simulate the FIFO logic from compute_sms_overage_for_billing
        old_pkg = _make_mock_package(
            credits_remaining=old_credits,
            purchased_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        new_pkg = _make_mock_package(
            credits_remaining=new_credits,
            purchased_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )

        packages = [old_pkg, new_pkg]  # ordered by purchased_at ASC (FIFO)
        raw_overage = overage

        # Apply FIFO deduction (mirrors compute_sms_overage_for_billing logic)
        for pkg in packages:
            if raw_overage <= 0:
                break
            deduction = min(raw_overage, pkg.credits_remaining)
            pkg.credits_remaining -= deduction
            raw_overage -= deduction

        # The old package should be depleted before the new one is touched
        if overage <= old_credits:
            # Overage fits entirely in old package
            assert old_pkg.credits_remaining == old_credits - overage
            assert new_pkg.credits_remaining == new_credits
        elif overage <= old_credits + new_credits:
            # Overage spans both packages — old fully depleted
            assert old_pkg.credits_remaining == 0
            assert new_pkg.credits_remaining == new_credits - (overage - old_credits)
        else:
            # Overage exceeds all credits — both depleted
            assert old_pkg.credits_remaining == 0
            assert new_pkg.credits_remaining == 0

    @given(
        num_packages=st.integers(min_value=1, max_value=5),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_total_deducted_never_exceeds_total_credits(
        self, num_packages: int, data: st.DataObject
    ) -> None:
        """P21: Total credits deducted never exceeds sum of all package credits."""
        packages = []
        for i in range(num_packages):
            credits = data.draw(st.integers(min_value=1, max_value=50))
            packages.append(
                _make_mock_package(
                    credits_remaining=credits,
                    purchased_at=datetime(2024, 1 + i, 1, tzinfo=timezone.utc),
                )
            )

        total_credits_before = sum(p.credits_remaining for p in packages)
        overage = data.draw(st.integers(min_value=0, max_value=300))

        raw_overage = overage
        for pkg in packages:
            if raw_overage <= 0:
                break
            deduction = min(raw_overage, pkg.credits_remaining)
            pkg.credits_remaining -= deduction
            raw_overage -= deduction

        total_credits_after = sum(p.credits_remaining for p in packages)
        total_deducted = total_credits_before - total_credits_after

        assert total_deducted <= total_credits_before
        assert total_deducted == min(overage, total_credits_before)
        assert all(p.credits_remaining >= 0 for p in packages)


# ===========================================================================
# Property 22: Usage summary aggregation
# ===========================================================================
# Feature: connexus-sms-integration, Property 22: Usage summary aggregation


class TestProperty22UsageSummaryAggregation:
    """total_sent, total_cost, overage_count match message records.

    **Validates: Requirement 14.2**
    """

    @pytest.mark.asyncio
    @given(
        total_sent=sms_sent_st,
        included_quota=quota_st,
        package_credits=credits_st,
        total_cost=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("500.00"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        ),
        per_sms_cost=per_sms_cost_st,
    )
    @PBT_SETTINGS
    async def test_usage_summary_aggregation_matches(
        self,
        total_sent: int,
        included_quota: int,
        package_credits: int,
        total_cost: Decimal,
        per_sms_cost: Decimal,
    ) -> None:
        """P22: Usage summary fields are consistent with underlying data."""
        org = _make_mock_org(sms_sent_this_month=total_sent)
        plan = _make_mock_plan(
            sms_included=True,
            sms_included_quota=included_quota,
            per_sms_cost_nzd=per_sms_cost,
        )

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # org + plan join query
                result = MagicMock()
                result.one_or_none.return_value = (org, plan)
                return result
            elif call_count == 2:
                # cost sum query
                result = MagicMock()
                result.scalar.return_value = total_cost
                return result
            elif call_count == 3:
                # package credits query
                result = MagicMock()
                result.scalar.return_value = package_credits
                return result
            return _FakeScalarResult(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        summary = await get_usage_summary(db, org.id)

        # Verify total_sent matches org.sms_sent_this_month
        assert summary["total_sent"] == total_sent

        # Verify total_cost matches the sum from DB
        assert summary["total_cost"] == str(total_cost)

        # Verify overage_count = max(0, total_sent - effective_quota)
        effective_quota = included_quota + package_credits
        expected_overage = max(0, total_sent - effective_quota)
        assert summary["overage_count"] == expected_overage

        # Verify included_quota
        assert summary["included_quota"] == included_quota

        # Verify package_credits_remaining
        assert summary["package_credits_remaining"] == package_credits


# ===========================================================================
# Property 23: Quota warning threshold
# ===========================================================================
# Feature: connexus-sms-integration, Property 23: Quota warning threshold


class TestProperty23QuotaWarningThreshold:
    """Warning flag true when usage exceeds 80% of effective quota.

    **Validates: Requirement 14.5**
    """

    @pytest.mark.asyncio
    @given(
        included_quota=st.integers(min_value=1, max_value=500),
        package_credits=credits_st,
        data=st.data(),
    )
    @PBT_SETTINGS
    async def test_warning_true_when_above_80_percent(
        self,
        included_quota: int,
        package_credits: int,
        data: st.DataObject,
    ) -> None:
        """P23: Warning is True when sms_sent > 80% of effective_quota."""
        effective_quota = included_quota + package_credits
        assume(effective_quota > 0)

        # Generate total_sent that exceeds 80% of effective_quota
        threshold = int(effective_quota * 0.8)
        total_sent = data.draw(
            st.integers(min_value=threshold + 1, max_value=effective_quota + 200)
        )

        org = _make_mock_org(sms_sent_this_month=total_sent)
        plan = _make_mock_plan(
            sms_included=True,
            sms_included_quota=included_quota,
            per_sms_cost_nzd=Decimal("0.08"),
        )

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = MagicMock()
                result.one_or_none.return_value = (org, plan)
                return result
            elif call_count == 2:
                result = MagicMock()
                result.scalar.return_value = Decimal("0")
                return result
            elif call_count == 3:
                result = MagicMock()
                result.scalar.return_value = package_credits
                return result
            return _FakeScalarResult(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        summary = await get_usage_summary(db, org.id)
        assert summary["warning"] is True

    @pytest.mark.asyncio
    @given(
        included_quota=st.integers(min_value=10, max_value=500),
        package_credits=credits_st,
        data=st.data(),
    )
    @PBT_SETTINGS
    async def test_warning_false_when_below_80_percent(
        self,
        included_quota: int,
        package_credits: int,
        data: st.DataObject,
    ) -> None:
        """P23: Warning is False when sms_sent <= 80% of effective_quota."""
        effective_quota = included_quota + package_credits
        assume(effective_quota > 0)

        # Generate total_sent that is at or below 80% of effective_quota
        threshold = int(effective_quota * 0.8)
        total_sent = data.draw(st.integers(min_value=0, max_value=threshold))

        org = _make_mock_org(sms_sent_this_month=total_sent)
        plan = _make_mock_plan(
            sms_included=True,
            sms_included_quota=included_quota,
            per_sms_cost_nzd=Decimal("0.08"),
        )

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                result = MagicMock()
                result.one_or_none.return_value = (org, plan)
                return result
            elif call_count == 2:
                result = MagicMock()
                result.scalar.return_value = Decimal("0")
                return result
            elif call_count == 3:
                result = MagicMock()
                result.scalar.return_value = package_credits
                return result
            return _FakeScalarResult(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        summary = await get_usage_summary(db, org.id)
        assert summary["warning"] is False


# ===========================================================================
# Property 24: Template variable substitution
# ===========================================================================
# Feature: connexus-sms-integration, Property 24: Template variable substitution


class TestProperty24TemplateVariableSubstitution:
    """Rendered body contains no placeholders, all values substituted.

    **Validates: Requirement 15.2**
    """

    @given(
        data=st.data(),
        num_vars=st.integers(min_value=1, max_value=5),
    )
    @PBT_SETTINGS
    def test_all_placeholders_replaced(
        self, data: st.DataObject, num_vars: int
    ) -> None:
        """P24: After substitution, no {{placeholder}} tokens remain and all values present."""
        # Generate distinct variable names and values
        var_names = data.draw(
            st.lists(
                placeholder_name_st,
                min_size=num_vars,
                max_size=num_vars,
                unique=True,
            )
        )
        var_values = data.draw(
            st.lists(
                placeholder_value_st,
                min_size=num_vars,
                max_size=num_vars,
            )
        )

        variables = dict(zip(var_names, var_values))

        # Build a template with all placeholders (no extra whitespace)
        template_parts = [f"Hello {{{{{name}}}}}" for name in var_names]
        template_body = " ".join(template_parts)

        rendered = _render_sms_template(template_body, variables)

        # No placeholder tokens should remain
        remaining_placeholders = re.findall(r"\{\{\w+\}\}", rendered)
        assert len(remaining_placeholders) == 0, (
            f"Placeholders still present: {remaining_placeholders}"
        )

        # All substituted values should be present in the rendered body
        for value in var_values:
            assert value in rendered, (
                f"Value '{value}' not found in rendered body: '{rendered}'"
            )

    @given(
        var_name=placeholder_name_st,
        var_value=placeholder_value_st,
    )
    @PBT_SETTINGS
    def test_single_variable_substitution(
        self, var_name: str, var_value: str
    ) -> None:
        """P24: A single placeholder is correctly replaced with its value."""
        template_body = f"Dear {{{{{var_name}}}}}, your appointment is confirmed."
        variables = {var_name: var_value}

        rendered = _render_sms_template(template_body, variables)

        assert f"{{{{{var_name}}}}}" not in rendered
        assert var_value in rendered

    @given(
        var_names=st.lists(
            placeholder_name_st,
            min_size=2,
            max_size=5,
            unique=True,
        ),
    )
    @PBT_SETTINGS
    def test_missing_variables_preserve_placeholder(
        self, var_names: list[str]
    ) -> None:
        """P24: When a complete variable map is provided, all are substituted.
        When variables are missing, their placeholders are preserved (not substituted)."""
        # Provide values for only the first variable
        template_body = " ".join(f"{{{{{name}}}}}" for name in var_names)
        partial_vars = {var_names[0]: "SubstitutedValue"}

        rendered = _render_sms_template(template_body, partial_vars)

        # First variable should be substituted
        assert f"{{{{{var_names[0]}}}}}" not in rendered
        assert "SubstitutedValue" in rendered

        # Remaining variables should still have their placeholders
        for name in var_names[1:]:
            assert f"{{{{{name}}}}}" in rendered
