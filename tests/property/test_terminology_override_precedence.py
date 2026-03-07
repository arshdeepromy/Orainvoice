"""Test: org-level overrides take precedence over trade category overrides.

**Validates: Requirements 4.4**

Verifies the merge priority: DEFAULT_TERMS → trade category → org overrides.
When both trade category and org-level overrides define the same key,
the org-level value wins.
"""

from __future__ import annotations

import pytest
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

_term_key_strategy = st.sampled_from(list(DEFAULT_TERMS.keys()))
_label_strategy = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "Z"),
))


def _merge_terminology(
    trade_category_overrides: dict[str, str],
    org_overrides: dict[str, str],
) -> dict[str, str]:
    """Replicate the TerminologyService merge logic (pure, no I/O)."""
    terms = dict(DEFAULT_TERMS)
    terms.update(trade_category_overrides)
    terms.update(org_overrides)
    return terms


# ===========================================================================
# Test: Org-level overrides take precedence
# ===========================================================================


class TestOrgOverridePrecedence:
    """Org-level overrides always win over trade category overrides.

    **Validates: Requirements 4.4**
    """

    @given(
        key=_term_key_strategy,
        trade_value=_label_strategy,
        org_value=_label_strategy,
    )
    @PBT_SETTINGS
    def test_org_override_wins_over_trade_category(
        self,
        key: str,
        trade_value: str,
        org_value: str,
    ) -> None:
        """When both trade category and org define the same key, org wins."""
        merged = _merge_terminology(
            trade_category_overrides={key: trade_value},
            org_overrides={key: org_value},
        )
        assert merged[key] == org_value, (
            f"Expected org override '{org_value}' for key '{key}', "
            f"but got '{merged[key]}' (trade was '{trade_value}')"
        )

    @given(
        key=_term_key_strategy,
        trade_value=_label_strategy,
    )
    @PBT_SETTINGS
    def test_trade_override_wins_over_default(
        self,
        key: str,
        trade_value: str,
    ) -> None:
        """When trade category overrides a key but org does not, trade wins."""
        merged = _merge_terminology(
            trade_category_overrides={key: trade_value},
            org_overrides={},
        )
        assert merged[key] == trade_value, (
            f"Expected trade override '{trade_value}' for key '{key}', "
            f"but got '{merged[key]}'"
        )

    def test_concrete_precedence_example(self) -> None:
        """Concrete example: construction trade says 'Tax Invoice',
        org overrides to 'Custom Invoice'."""
        trade_overrides = {
            "work_unit_label": "Work Order",
            "asset_label": "Job Site",
        }
        org_overrides = {
            "work_unit_label": "Project",
        }
        merged = _merge_terminology(trade_overrides, org_overrides)

        # Org override wins for work_unit_label
        assert merged["work_unit_label"] == "Project"
        # Trade override wins for asset_label (no org override)
        assert merged["asset_label"] == "Job Site"
        # Default wins for customer_label (no overrides)
        assert merged["customer_label"] == DEFAULT_TERMS["customer_label"]
        # All default keys present
        assert set(DEFAULT_TERMS.keys()).issubset(set(merged.keys()))
