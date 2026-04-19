# Feature: org-coupon-application, Property 1: Benefit description format matches coupon type
"""Property-based tests for generate_coupon_benefit_description().

Property 1: Benefit description format matches coupon type

**Validates: Requirements 5.1, 5.2, 5.3**

Uses Hypothesis to generate random discount types, values, and durations,
then verifies the output string matches the expected format for each type.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.admin.service import (
    generate_coupon_benefit_description,
    _format_discount_value,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

discount_types = st.sampled_from(["percentage", "fixed_amount", "trial_extension"])

discount_values = st.floats(min_value=0.01, max_value=10000, allow_nan=False)

duration_months = st.one_of(st.none(), st.integers(min_value=1, max_value=120))


# ---------------------------------------------------------------------------
# Property 1: Benefit description format matches coupon type
# **Validates: Requirements 5.1, 5.2, 5.3**
# ---------------------------------------------------------------------------


class TestBenefitDescriptionFormat:
    """Verify benefit description format matches coupon type for all inputs."""

    @settings(max_examples=100)
    @given(
        discount_type=discount_types,
        discount_value=discount_values,
        dur=duration_months,
    )
    def test_benefit_description_format_matches_coupon_type(
        self, discount_type, discount_value, dur
    ):
        """Property 1: Benefit description format matches coupon type —
        for any valid discount_type, discount_value, and optional
        duration_months, the description is non-empty and contains the
        expected markers for that type.

        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        result = generate_coupon_benefit_description(
            discount_type=discount_type,
            discount_value=discount_value,
            duration_months=dur,
        )

        # Result is a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0

        # Result contains the formatted discount value
        formatted_value = _format_discount_value(discount_value)
        assert formatted_value in result, (
            f"Expected formatted value '{formatted_value}' in '{result}'"
        )

        # Type-specific assertions
        if discount_type == "percentage":
            assert "%" in result, f"percentage type missing '%' in '{result}'"
            assert "discount on your subscription" in result, (
                f"percentage type missing 'discount on your subscription' in '{result}'"
            )
        elif discount_type == "fixed_amount":
            assert "$" in result, f"fixed_amount type missing '$' in '{result}'"
            assert "off per billing cycle" in result, (
                f"fixed_amount type missing 'off per billing cycle' in '{result}'"
            )
        elif discount_type == "trial_extension":
            assert "Trial extended by" in result, (
                f"trial_extension type missing 'Trial extended by' in '{result}'"
            )
            assert "days" in result, (
                f"trial_extension type missing 'days' in '{result}'"
            )

        # Duration assertions (only for non-trial_extension types)
        if discount_type != "trial_extension":
            if dur is not None:
                assert f"for {dur} months" in result, (
                    f"Expected 'for {dur} months' in '{result}'"
                )
            else:
                assert "ongoing" in result, (
                    f"Expected 'ongoing' in '{result}'"
                )
