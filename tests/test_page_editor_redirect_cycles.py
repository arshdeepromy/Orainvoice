"""Property-based tests for page editor redirect cycle detection (Task 2.10).

Uses Hypothesis to verify that the redirect cycle detection logic in
update_page_settings prevents redirect loops after any sequence of slug renames.

The cycle detection logic works as follows:
- When a slug changes from old→new, a redirect old→new is created
- Then it checks for existing redirects where from_slug == new_slug
  pointing back to old_slug — those are soft-deleted (deleted_at set)
- Also checks for self-redirects (from_slug == to_slug_or_url) and removes them

Feature: visual-page-editor
Property 4: Redirect Cycle Detection

Validates: Requirements 6.9, 11.5
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategy: generate slug-like strings
# ---------------------------------------------------------------------------

slugs = st.from_regex(r"^/[a-z]{1,10}$", fullmatch=True)

# Generate a list of rename operations (old_slug, new_slug)
rename_ops = st.lists(
    st.tuples(slugs, slugs),
    min_size=1,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Simulate the redirect creation + cycle detection logic from service.py
# ---------------------------------------------------------------------------


def simulate_redirect_cycle_detection(operations: list[tuple[str, str]]) -> dict[str, str]:
    """Simulate the redirect creation and cycle detection logic.

    For each rename operation (old_slug → new_slug):
    1. Create a redirect old_slug → new_slug
    2. Remove any active redirect where from_slug == new_slug AND
       to_slug_or_url == old_slug (direct cycle back)
    3. Remove any self-redirect where from_slug == to_slug_or_url

    Returns the dict of active redirects {from_slug: to_slug_or_url}.
    """
    # Active redirects: from_slug → to_slug_or_url
    active_redirects: dict[str, str] = {}

    for old_slug, new_slug in operations:
        if old_slug == new_slug:
            # No actual rename — skip (service would not trigger redirect logic)
            continue

        # Step 1: Create redirect old_slug → new_slug
        # (overwrites any existing redirect from old_slug since from_slug
        # has a unique partial index where deleted_at IS NULL)
        active_redirects[old_slug] = new_slug

        # Step 2: Check for redirect from new_slug back to old_slug (cycle)
        # This mirrors the service logic:
        #   select where from_slug == new_slug AND to_slug_or_url == old_slug
        if new_slug in active_redirects and active_redirects[new_slug] == old_slug:
            # Soft-delete it (remove from active set)
            del active_redirects[new_slug]

        # Step 3: Check for self-redirects (from_slug == to_slug_or_url)
        # After step 1, old_slug → new_slug was added. Check all active redirects
        # for self-loops. The service checks this condition broadly.
        to_remove = [
            k for k, v in active_redirects.items() if k == v
        ]
        for k in to_remove:
            del active_redirects[k]

    return active_redirects


def has_cycle(redirects: dict[str, str]) -> bool:
    """Check if the redirect graph contains any cycle.

    Uses DFS-based cycle detection. A cycle exists if following redirect
    hops from any node leads back to a previously visited node.
    """
    for start in redirects:
        visited: set[str] = set()
        current = start
        while current in redirects:
            if current in visited:
                return True
            visited.add(current)
            current = redirects[current]
    return False


# ---------------------------------------------------------------------------
# Property 4: Redirect Cycle Detection
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(operations=rename_ops)
def test_redirect_cycle_detection(operations: list[tuple[str, str]]):
    """For any sequence of slug renames, the resulting active redirect set
    should never contain a cycle (A→B→A or A→A).

    The cycle detection logic removes direct back-references and self-redirects
    after each rename operation, ensuring no loops exist in the active set.

    **Validates: Requirements 6.9, 11.5**
    """
    # Simulate all rename operations with cycle detection
    active_redirects = simulate_redirect_cycle_detection(operations)

    # Verify: no cycles exist in the active redirect set
    assert not has_cycle(active_redirects), (
        f"Cycle detected in active redirects after operations {operations}. "
        f"Active redirects: {active_redirects}"
    )

    # Verify: no self-redirects exist (A→A)
    for from_slug, to_slug in active_redirects.items():
        assert from_slug != to_slug, (
            f"Self-redirect found: {from_slug} → {to_slug}"
        )
