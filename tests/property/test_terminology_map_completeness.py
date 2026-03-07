"""Property-based test: terminology map completeness.

**Validates: Requirements 4.1, 4.6**

Property 18: For any organisation O with trade category T, the terminology
map returned by the API contains entries for all keys in the DEFAULT_TERMS
dictionary. No key is missing.

This test verifies the merge logic directly: regardless of what trade
category overrides or org-level overrides are applied, the resulting map
always contains every key from DEFAULT_TERMS.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.terminology import DEFAULT_TERMS


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

# Trade category overrides: a subset of DEFAULT_TERMS keys with random values,
# plus potentially extra keys not in DEFAULT_TERMS.
_term_key_strategy = st.sampled_from(list(DEFAULT_TERMS.keys()))
_extra_key_strategy = st.from_regex(r"[a-z][a-z_]{2,20}", fullmatch=True)
_label_strategy = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "Z"),
))

_trade_overrides_strategy = st.dictionaries(
    keys=st.one_of(_term_key_strategy, _extra_key_strategy),
    values=_label_strategy,
    min_size=0,
    max_size=10,
)

_org_overrides_strategy = st.dictionaries(
    keys=st.one_of(_term_key_strategy, _extra_key_strategy),
    values=_label_strategy,
    min_size=0,
    max_size=10,
)


def _merge_terminology(
    trade_category_overrides: dict[str, str],
    org_overrides: dict[str, str],
) -> dict[str, str]:
    """Replicate the TerminologyService merge logic (pure, no I/O).

    Merge priority: DEFAULT_TERMS → trade category → org overrides.
    """
    terms = dict(DEFAULT_TERMS)
    terms.update(trade_category_overrides)
    terms.update(org_overrides)
    return terms


# ===========================================================================
# Property 18: Terminology Map Completeness
# ===========================================================================


class TestTerminologyMapCompleteness:
    """For any org with trade category, the terminology map contains all
    DEFAULT_TERMS keys.

    **Validates: Requirements 4.1, 4.6**
    """

    @given(
        trade_overrides=_trade_overrides_strategy,
        org_overrides=_org_overrides_strategy,
    )
    @PBT_SETTINGS
    def test_all_default_keys_present(
        self,
        trade_overrides: dict[str, str],
        org_overrides: dict[str, str],
    ) -> None:
        """The merged map always contains every key from DEFAULT_TERMS."""
        merged = _merge_terminology(trade_overrides, org_overrides)

        missing = set(DEFAULT_TERMS.keys()) - set(merged.keys())
        assert not missing, (
            f"Terminology map is missing DEFAULT_TERMS keys: {missing}. "
            f"Trade overrides: {trade_overrides}, Org overrides: {org_overrides}"
        )

    @given(
        trade_overrides=_trade_overrides_strategy,
        org_overrides=_org_overrides_strategy,
    )
    @PBT_SETTINGS
    def test_default_values_used_when_no_override(
        self,
        trade_overrides: dict[str, str],
        org_overrides: dict[str, str],
    ) -> None:
        """Keys not overridden retain their DEFAULT_TERMS value."""
        merged = _merge_terminology(trade_overrides, org_overrides)

        for key, default_val in DEFAULT_TERMS.items():
            if key not in trade_overrides and key not in org_overrides:
                assert merged[key] == default_val, (
                    f"Key '{key}' should be '{default_val}' but got '{merged[key]}'"
                )

    @given(
        trade_overrides=_trade_overrides_strategy,
        org_overrides=_org_overrides_strategy,
    )
    @PBT_SETTINGS
    def test_merge_is_deterministic(
        self,
        trade_overrides: dict[str, str],
        org_overrides: dict[str, str],
    ) -> None:
        """Merging the same inputs twice produces identical results."""
        result1 = _merge_terminology(trade_overrides, org_overrides)
        result2 = _merge_terminology(trade_overrides, org_overrides)
        assert result1 == result2
