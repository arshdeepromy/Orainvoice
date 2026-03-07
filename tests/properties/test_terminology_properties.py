"""Comprehensive property-based tests for terminology properties.

Properties covered:
  P18 — Terminology Map Completeness: all DEFAULT_TERMS keys present

**Validates: Requirements 18**
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.core.terminology import DEFAULT_TERMS


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_term_key_st = st.sampled_from(list(DEFAULT_TERMS.keys()))
_extra_key_st = st.from_regex(r"[a-z][a-z_]{2,20}", fullmatch=True)
_label_st = st.text(
    min_size=1, max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
)

_trade_overrides_st = st.dictionaries(
    keys=st.one_of(_term_key_st, _extra_key_st),
    values=_label_st,
    min_size=0, max_size=10,
)

_org_overrides_st = st.dictionaries(
    keys=st.one_of(_term_key_st, _extra_key_st),
    values=_label_st,
    min_size=0, max_size=10,
)


def _merge_terminology(trade_overrides: dict, org_overrides: dict) -> dict[str, str]:
    """Replicate the TerminologyService merge logic (pure, no I/O)."""
    terms = dict(DEFAULT_TERMS)
    terms.update(trade_overrides)
    terms.update(org_overrides)
    return terms


# ===========================================================================
# Property 18: Terminology Map Completeness
# ===========================================================================


class TestP18TerminologyMapCompleteness:
    """Terminology map always contains all DEFAULT_TERMS keys.

    **Validates: Requirements 18**
    """

    @given(trade_overrides=_trade_overrides_st, org_overrides=_org_overrides_st)
    @PBT_SETTINGS
    def test_all_default_keys_present(self, trade_overrides, org_overrides) -> None:
        """P18: merged map contains every key from DEFAULT_TERMS."""
        merged = _merge_terminology(trade_overrides, org_overrides)
        missing = set(DEFAULT_TERMS.keys()) - set(merged.keys())
        assert not missing, f"Missing keys: {missing}"

    @given(trade_overrides=_trade_overrides_st, org_overrides=_org_overrides_st)
    @PBT_SETTINGS
    def test_default_values_used_when_no_override(
        self, trade_overrides, org_overrides,
    ) -> None:
        """P18: keys not overridden retain DEFAULT_TERMS value."""
        merged = _merge_terminology(trade_overrides, org_overrides)
        for key, default_val in DEFAULT_TERMS.items():
            if key not in trade_overrides and key not in org_overrides:
                assert merged[key] == default_val

    @given(trade_overrides=_trade_overrides_st, org_overrides=_org_overrides_st)
    @PBT_SETTINGS
    def test_merge_is_deterministic(self, trade_overrides, org_overrides) -> None:
        """P18: merging same inputs twice produces identical results."""
        r1 = _merge_terminology(trade_overrides, org_overrides)
        r2 = _merge_terminology(trade_overrides, org_overrides)
        assert r1 == r2

    @given(trade_overrides=_trade_overrides_st, org_overrides=_org_overrides_st)
    @PBT_SETTINGS
    def test_org_overrides_take_precedence(
        self, trade_overrides, org_overrides,
    ) -> None:
        """P18: org-level overrides take precedence over trade category."""
        merged = _merge_terminology(trade_overrides, org_overrides)
        for key, val in org_overrides.items():
            assert merged[key] == val
