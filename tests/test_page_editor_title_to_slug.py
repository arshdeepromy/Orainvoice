"""Property-based tests for page editor title-to-slug derivation (Task 2.4).

Uses Hypothesis to verify that title_to_slug() always produces a valid slug
regardless of the input Unicode string.

Feature: visual-page-editor
Property 3: Title-to-Slug Derivation Produces Valid Slugs

Validates: Requirements 8.7
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.page_editor.service import (
    SLUG_PATTERN,
    title_to_slug,
    validate_slug,
)


# ---------------------------------------------------------------------------
# Strategy: generate random Unicode strings including edge cases
# ---------------------------------------------------------------------------

unicode_titles = st.text(min_size=0, max_size=200)


# ---------------------------------------------------------------------------
# Property 3: Title-to-Slug Derivation Produces Valid Slugs
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(title=unicode_titles)
def test_title_to_slug_produces_valid_slugs(title: str):
    """For any Unicode string, title_to_slug() always produces a valid slug.

    Verifies:
    - The output passes validate_slug() without raising
    - The output always starts with /
    - The output always matches the slug regex pattern
    - The output is always <= 80 characters

    **Validates: Requirements 8.7**
    """
    slug = title_to_slug(title)

    # Output always starts with /
    assert slug.startswith("/"), (
        f"Expected slug to start with '/' but got '{slug}' for title '{title!r}'"
    )

    # Output always matches the slug regex pattern
    assert SLUG_PATTERN.match(slug), (
        f"Expected slug to match SLUG_PATTERN but '{slug}' did not match "
        f"for title '{title!r}'"
    )

    # Output is always <= 80 characters
    assert len(slug) <= 80, (
        f"Expected slug length <= 80 but got {len(slug)} for title '{title!r}'"
    )

    # Output passes validate_slug() without raising any exception
    result = validate_slug(slug)
    assert result == slug, (
        f"Expected validate_slug to accept '{slug}' but it didn't for title '{title!r}'"
    )
