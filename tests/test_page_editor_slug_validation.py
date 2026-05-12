"""Property-based tests for page editor slug validation (Task 2.3).

Uses Hypothesis to verify that the slug validator accepts a string if and only
if it matches the slug regex, is at most 80 characters, and does not start with
any reserved prefix.

Feature: visual-page-editor
Property 2: Slug Validation Correctness

Validates: Requirements 8.2, 8.3
"""

from __future__ import annotations

import re

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.page_editor.service import (
    RESERVED_PREFIXES,
    SLUG_PATTERN,
    validate_slug,
)


# ---------------------------------------------------------------------------
# Strategy: generate random strings (mostly arbitrary text)
# ---------------------------------------------------------------------------

arbitrary_strings = st.text(min_size=1, max_size=100)

# Strategy: generate strings likely to be valid slugs using from_regex
valid_slug_like = st.from_regex(
    re.compile(r"^/[a-z0-9-]{1,25}(/[a-z0-9-]{1,25}){0,2}$"),
    fullmatch=True,
)


# ---------------------------------------------------------------------------
# Property 2: Slug Validation Correctness
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(slug=arbitrary_strings | valid_slug_like)
def test_slug_validation_correctness(slug: str):
    """For any string input, validate_slug accepts iff regex + length + reserved check pass.

    **Validates: Requirements 8.2, 8.3**
    """
    # Determine expected outcome using the same rules as the validator
    matches_regex = bool(SLUG_PATTERN.match(slug))
    within_length = len(slug) <= 80
    not_reserved = not any(
        slug == prefix or slug.startswith(prefix + "/")
        for prefix in RESERVED_PREFIXES
    )
    should_accept = matches_regex and within_length and not_reserved

    if should_accept:
        result = validate_slug(slug)
        assert result == slug, (
            f"Expected validate_slug to accept '{slug}' but it didn't return the slug"
        )
    else:
        with pytest.raises(HTTPException) as exc_info:
            validate_slug(slug)
        # Verify appropriate status codes
        assert exc_info.value.status_code in (409, 422), (
            f"Expected 409 or 422 for rejected slug '{slug}', "
            f"got {exc_info.value.status_code}"
        )
