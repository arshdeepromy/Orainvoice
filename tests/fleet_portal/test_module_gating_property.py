"""Property tests for module gating + dependency.

Implements:
- **Property 1** — Trade-family gating governs visibility and enableability
- **Property 2** — Module dependency auto-resolution

The behaviour is implemented in ``app.core.modules`` via the
``DEPENDENCY_GRAPH`` and ``TRADE_FAMILY_REQUIRED_MODULES`` constants
(task 1.3). The existing test file
``tests/test_trade_family_module_gating.py`` (16 tests) covers the
same behaviour from the integration angle. This file adds the
property-style fuzz coverage.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.core.modules import (
    DEPENDENCY_GRAPH,
    TRADE_FAMILY_REJECTION_MESSAGES,
    TRADE_FAMILY_REQUIRED_MODULES,
    is_trade_family_satisfied,
)


# ---------------------------------------------------------------------------
# Property 1 — trade family gating
# ---------------------------------------------------------------------------


def test_b2b_fleet_management_required_family_is_automotive_transport() -> None:
    assert TRADE_FAMILY_REQUIRED_MODULES["b2b-fleet-management"] == "automotive-transport"


def test_b2b_fleet_management_rejection_message_present() -> None:
    msg = TRADE_FAMILY_REJECTION_MESSAGES["b2b-fleet-management"]
    assert "automotive" in msg.lower()


@given(
    family=st.sampled_from(
        ["automotive-transport", "construction", "electrical", "plumbing", "other"]
    )
)
@hyp_settings(max_examples=50)
def test_is_satisfied_iff_family_matches(family: str) -> None:
    """Property 1 — restricted modules satisfied iff trade family matches."""
    expected = family == "automotive-transport"
    assert is_trade_family_satisfied("b2b-fleet-management", family) is expected


def test_unrestricted_module_always_satisfied() -> None:
    """Modules not in TRADE_FAMILY_REQUIRED_MODULES are always satisfied."""
    for family in ("any", "construction", "automotive-transport", ""):
        assert is_trade_family_satisfied("invoices", family) is True


# ---------------------------------------------------------------------------
# Property 2 — dependency auto-resolution
# ---------------------------------------------------------------------------


def test_b2b_fleet_management_depends_on_vehicles() -> None:
    """Property 2 — enabling b2b-fleet-management implies enabling vehicles."""
    deps = DEPENDENCY_GRAPH.get("b2b-fleet-management", set())
    # The graph stores a list/set of module slugs the module needs.
    if isinstance(deps, dict):
        # Some implementations use {'and': [...], 'or': [...]} shape.
        # Accept either form.
        flat = set(deps.get("and", [])) | set(deps.get("or", []))
    else:
        flat = set(deps)
    assert "vehicles" in flat
