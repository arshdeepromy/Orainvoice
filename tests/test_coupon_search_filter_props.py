# Feature: org-coupon-application, Property 2: Coupon search filter returns only matching coupons
"""Property-based tests for coupon search filter logic.

Property 2: Coupon search filter returns only matching coupons

**Validates: Requirements 2.4**

Uses Hypothesis to generate lists of coupon dicts with code and description
fields, and arbitrary search strings, then verifies the filter function
returns only matching coupons.
"""

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Pure function: mirrors the client-side coupon search filter logic
# ---------------------------------------------------------------------------


def filter_coupons(coupons: list[dict], search: str) -> list[dict]:
    """Filter coupons where search (case-insensitive) appears in code or description.

    If search is empty, return all coupons.
    """
    if not search:
        return list(coupons)
    lower_search = search.lower()
    return [
        c
        for c in coupons
        if lower_search in c.get("code", "").lower()
        or lower_search in c.get("description", "").lower()
    ]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

coupon_strategy = st.fixed_dictionaries(
    {
        "code": st.text(min_size=0, max_size=50),
        "description": st.text(min_size=0, max_size=200),
    }
)

coupon_list_strategy = st.lists(coupon_strategy, min_size=0, max_size=30)

search_strategy = st.text(min_size=0, max_size=50)


# ---------------------------------------------------------------------------
# Property 2: Coupon search filter returns only matching coupons
# **Validates: Requirements 2.4**
# ---------------------------------------------------------------------------


class TestCouponSearchFilter:
    """Verify coupon search filter returns only matching coupons for all inputs."""

    @settings(max_examples=100)
    @given(coupons=coupon_list_strategy, search=search_strategy)
    def test_coupon_search_filter_returns_only_matching_coupons(
        self, coupons: list[dict], search: str
    ):
        """Property 2: Coupon search filter returns only matching coupons —
        for any list of coupons and any search string, the filtered list is a
        subset of the original, every included item matches, and no excluded
        item matches.

        **Validates: Requirements 2.4**
        """
        filtered = filter_coupons(coupons, search)

        # 1. Filtered list is a subset of the original list
        for item in filtered:
            assert item in coupons, (
                f"Filtered item {item} not found in original coupon list"
            )

        # 2. Every item in filtered list matches the search criteria
        if search:
            lower_search = search.lower()
            for item in filtered:
                code_match = lower_search in item.get("code", "").lower()
                desc_match = lower_search in item.get("description", "").lower()
                assert code_match or desc_match, (
                    f"Filtered item does not match search '{search}': {item}"
                )

        # 3. No item excluded from filtered list matches the search criteria
        if search:
            lower_search = search.lower()
            excluded = [c for c in coupons if c not in filtered]
            for item in excluded:
                code_match = lower_search in item.get("code", "").lower()
                desc_match = lower_search in item.get("description", "").lower()
                assert not (code_match or desc_match), (
                    f"Excluded item matches search '{search}' but was not included: {item}"
                )

        # 4. When search is empty, all coupons are returned
        if not search:
            assert len(filtered) == len(coupons), (
                f"Empty search should return all {len(coupons)} coupons, got {len(filtered)}"
            )
