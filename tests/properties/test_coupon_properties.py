"""Property-based tests for the coupon system.

Tests the calculate_effective_price utility using Hypothesis.
Feature: coupon-system
"""

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.admin.service import calculate_effective_price


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

plan_price_st = st.floats(min_value=0, max_value=100000, allow_nan=False, allow_infinity=False)
discount_type_st = st.sampled_from(["percentage", "fixed_amount", "trial_extension"])
discount_value_st = st.floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False)
percentage_st = st.floats(min_value=1, max_value=100, allow_nan=False, allow_infinity=False)
fixed_amount_st = st.floats(min_value=0.01, max_value=10000, allow_nan=False, allow_infinity=False)
trial_days_st = st.floats(min_value=1, max_value=365, allow_nan=False, allow_infinity=False)


# Feature: coupon-system, Property 2: Effective price calculation bounds
@given(
    plan_price=plan_price_st,
    data=st.data(),
    is_expired=st.booleans(),
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_effective_price_bounds(plan_price, data, is_expired):
    """For any valid inputs, 0 <= result <= plan_price.
    **Validates: Requirements 11.2–11.6**
    """
    discount_type = data.draw(discount_type_st)
    # Constrain discount_value to valid range per type
    if discount_type == "percentage":
        discount_value = data.draw(percentage_st)
    elif discount_type == "fixed_amount":
        discount_value = data.draw(fixed_amount_st)
    else:
        discount_value = data.draw(trial_days_st)

    result = calculate_effective_price(plan_price, discount_type, discount_value, is_expired)
    assert 0 <= result <= plan_price, (
        f"Expected 0 <= {result} <= {plan_price} for "
        f"type={discount_type}, value={discount_value}, expired={is_expired}"
    )




# Feature: coupon-system, Property 3: Percentage discount calculation
@given(plan_price=plan_price_st, pct=percentage_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_percentage_discount_calculation(plan_price, pct):
    """Percentage discount: result == round(plan_price * (1 - pct/100), 2)."""
    result = calculate_effective_price(plan_price, "percentage", pct, False)
    expected = round(plan_price * (1 - pct / 100), 2)
    assert result == expected, f"Expected {expected}, got {result} for price={plan_price}, pct={pct}"


# Feature: coupon-system, Property 4: Fixed amount discount calculation
@given(plan_price=plan_price_st, amount=fixed_amount_st)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_fixed_amount_discount_calculation(plan_price, amount):
    """Fixed amount discount: result == max(0, round(plan_price - amount, 2))."""
    result = calculate_effective_price(plan_price, "fixed_amount", amount, False)
    expected = round(max(0.0, plan_price - amount), 2)
    assert result == expected, f"Expected {expected}, got {result} for price={plan_price}, amount={amount}"


# Feature: coupon-system, Property 5: Expired coupon returns full price
@given(
    plan_price=plan_price_st,
    discount_type=discount_type_st,
    discount_value=discount_value_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_expired_coupon_returns_full_price(plan_price, discount_type, discount_value):
    """When is_expired=True, result == plan_price."""
    result = calculate_effective_price(plan_price, discount_type, discount_value, True)
    assert result == plan_price, (
        f"Expected {plan_price}, got {result} for expired coupon "
        f"type={discount_type}, value={discount_value}"
    )


# Feature: coupon-system, Property 6: Trial extension does not affect price
@given(plan_price=plan_price_st, trial_days=trial_days_st, is_expired=st.booleans())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_trial_extension_does_not_affect_price(plan_price, trial_days, is_expired):
    """Trial extension: result == plan_price regardless of is_expired."""
    result = calculate_effective_price(plan_price, "trial_extension", trial_days, is_expired)
    assert result == plan_price, (
        f"Expected {plan_price}, got {result} for trial_extension "
        f"days={trial_days}, expired={is_expired}"
    )
