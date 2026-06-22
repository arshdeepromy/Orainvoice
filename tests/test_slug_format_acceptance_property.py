"""Property-based test: slug format acceptance.

# Feature: organisation-employee-portal, Property 4: Slug format acceptance

**Validates: Requirements 2.2, 2.3**

R2.2 says the Org_Settings accepts an Org_Slug only when ALL of the following
hold: the value contains only lowercase letters (a-z), digits (0-9), and
hyphens; each hyphen is single and internal; the value does not begin or end
with a hyphen; and the length is between 3 and 63 characters inclusive.

R2.3 says that when a submitted slug fails any condition in R2.2, the value is
rejected without being stored AND a human-readable message describing the
violated format rule is returned.

The function under test, ``validate_slug_format(slug) -> (ok, message)`` in
``app/modules/organisations/slug_service.py``, is a pure, DB-free helper, so it
is exercised directly with no database (nothing is ever stored by this layer).
We draw candidate strings from a wide mix of valid and invalid constructions
and assert against an INDEPENDENT reference oracle: a slug is acceptable iff it
is 3..63 characters long AND matches ``^[a-z0-9]+(?:-[a-z0-9]+)*$``. Every
rejection must carry a non-empty human-readable reason; every acceptance must
carry no reason.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.organisations.slug_service import validate_slug_format

# ---------------------------------------------------------------------------
# Hypothesis settings (>=100 iterations) — pure in-memory validation.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

# Independent reference oracle for the acceptance rule (R2.2). Deliberately
# rewritten here rather than imported from the module under test so the test
# does not merely echo the implementation.
_REFERENCE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MIN_LEN = 3
_MAX_LEN = 63


def _reference_accepts(slug: str) -> bool:
    """A slug is acceptable iff 3..63 chars AND matches the slug regex."""
    return (_MIN_LEN <= len(slug) <= _MAX_LEN) and bool(_REFERENCE_RE.match(slug))


# ---------------------------------------------------------------------------
# Generators spanning the input space: valid slugs, near-misses, and arbitrary
# text. Mixing targeted constructions with free text gives both broad coverage
# and a healthy share of genuinely-valid examples.
# ---------------------------------------------------------------------------

# A label is a run of lowercase alphanumerics (the only thing allowed between
# hyphens). Joining 1+ labels with single hyphens yields a well-formed slug
# body; length still has to land in 3..63 to be accepted.
_label = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12)

_well_formed_body = st.lists(_label, min_size=1, max_size=6).map("-".join)

# Strings likely to be valid slugs (still length-checked by the oracle).
_valid_like = _well_formed_body

# Near-miss constructions that should mostly be rejected: leading/trailing/
# doubled hyphens, uppercase, underscores, spaces, and other punctuation.
_near_miss = st.one_of(
    st.builds(lambda b: f"-{b}", _well_formed_body),          # leading hyphen
    st.builds(lambda b: f"{b}-", _well_formed_body),          # trailing hyphen
    st.builds(lambda a, b: f"{a}--{b}", _label, _label),      # doubled hyphen
    st.builds(lambda b: b.upper(), _well_formed_body),        # uppercase
    st.builds(lambda b: f"{b}_x", _well_formed_body),         # underscore
    st.builds(lambda b: f"{b} x", _well_formed_body),         # space
)

# Free-form text over a charset that includes plenty of disallowed characters
# plus whitespace, so length and charset rules both get exercised.
_arbitrary = st.text(
    alphabet=st.characters(min_codepoint=0, max_codepoint=0x017F),
    min_size=0,
    max_size=70,
)

# Length edge cases around the 3 and 63 boundaries, built from valid chars so
# the only deciding factor is length.
_length_edges = st.integers(min_value=0, max_value=66).map(lambda n: "a" * n)

_candidate = st.one_of(_valid_like, _near_miss, _arbitrary, _length_edges)


# ---------------------------------------------------------------------------
# Property 4: Slug format acceptance
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(slug=_candidate)
def test_slug_format_matches_reference_oracle(slug: str) -> None:
    """Accept iff 3..63 chars AND matches the slug regex; else reject.

    Property 4 — for any candidate string, ``validate_slug_format`` returns
    ``ok=True`` exactly when an independent reference (length 3..63 AND regex
    ``^[a-z0-9]+(?:-[a-z0-9]+)*$``) accepts it.

    **Validates: Requirements 2.2, 2.3**
    """
    ok, message = validate_slug_format(slug)
    assert ok is _reference_accepts(slug)


@PBT_SETTINGS
@given(slug=_candidate)
def test_rejection_carries_human_readable_reason(slug: str) -> None:
    """Every rejection carries a non-empty reason; acceptance carries none.

    Property 4 / R2.3 — a rejected slug must come back with a human-readable
    message describing the violated rule, and an accepted slug carries no
    message. ``validate_slug_format`` is pure, so a rejected value is inherently
    never stored.

    **Validates: Requirements 2.2, 2.3**
    """
    ok, message = validate_slug_format(slug)
    if ok:
        assert message is None
    else:
        assert isinstance(message, str)
        assert message.strip() != ""


@PBT_SETTINGS
@given(slug=_valid_like)
def test_well_formed_in_range_is_accepted(slug: str) -> None:
    """A well-formed body whose length lands in 3..63 is accepted.

    **Validates: Requirements 2.2**
    """
    if _MIN_LEN <= len(slug) <= _MAX_LEN:
        ok, message = validate_slug_format(slug)
        assert ok is True
        assert message is None
