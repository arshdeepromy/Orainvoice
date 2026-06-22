"""Property-based test: the slug availability classifier is total.

# Feature: organisation-employee-portal, Property 8: Availability classifier totality

**Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**

The real-time slug availability check (R3.2) leans on the pure helper
``app.modules.organisations.slug_service.classify_availability`` to decide, for
any candidate slug crossed with whichever organisation (if any) currently holds
it, exactly one availability outcome. For that decision to be safe it must be:

* **Total** — for *every* candidate (well-formed, malformed, or reserved) and
  *any* holder relationship (the slug is free, held by the requesting org
  itself, or held by another org), ``classify_availability`` returns exactly one
  of ``{"available", "unavailable", "invalid"}`` and never raises (R3.2).
* **Sound on rejection** — a candidate that fails the slug format rules is
  always classified ``invalid`` and is *never* reported ``available`` (R3.6).
* **Sound on availability** — ``available`` is returned *only* when the
  normalised candidate is well-formed, not reserved, and either free
  (no holder) or already held by the requesting organisation itself
  (R3.3 reserved → unavailable, R3.4 other-org → unavailable, R3.5 own/free →
  available).

This mirrors the pure helper exactly — no database, network, or other I/O is
involved; the holder lookup happens in the caller and is supplied here as the
``holder_org_id`` argument.
"""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.organisations.slug_service import (
    RESERVED_SLUGS,
    classify_availability,
    normalise_slug,
    validate_slug_format,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (>= 100 iterations) — pure in-memory classification.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

_RESULTS = {"available", "unavailable", "invalid"}

# ---------------------------------------------------------------------------
# Candidate strategies — a deliberate mix of well-formed, reserved, and
# malformed slugs so the classifier's whole input space is exercised.
# ---------------------------------------------------------------------------

_SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# Well-formed slugs: 1..6 hyphen-joined segments of lowercase alphanumerics,
# total length constrained to 3..63. Built so no empty segment can appear,
# hence never a leading/trailing/doubled hyphen.
_valid_format_candidates = (
    st.lists(
        st.text(alphabet=_SLUG_ALPHABET, min_size=1, max_size=10),
        min_size=1,
        max_size=6,
    )
    .map(lambda parts: "-".join(parts))
    .filter(lambda s: 3 <= len(s) <= 63)
)

# Reserved slugs, plus case/whitespace variants that still normalise to a
# reserved value (R3.3 — reserved must classify unavailable, never available).
_reserved_candidates = st.sampled_from(sorted(RESERVED_SLUGS)).flatmap(
    lambda s: st.sampled_from([s, s.upper(), s.title(), f"  {s}  ", f"\t{s}\n"])
)

# Malformed candidates whose normalised form fails the format rules: too short,
# too long, leading/trailing/doubled hyphens, disallowed characters, blanks.
_invalid_format_candidates = st.one_of(
    st.text(alphabet=_SLUG_ALPHABET, min_size=0, max_size=2),  # too short
    st.text(alphabet=_SLUG_ALPHABET, min_size=64, max_size=90),  # too long
    st.sampled_from(
        [
            "",
            "  ",
            "-abc",
            "abc-",
            "a--b",
            "--",
            "ab_cd",
            "a b c",
            "a@b",
            "a.b",
            "a/b",
            "café",
            "naïve-org",
            "UPPER ONLY!",
        ]
    ),
    st.text(alphabet="_!@#$%^&*(). /\\", min_size=3, max_size=12),
)

_candidates = st.one_of(
    _valid_format_candidates,
    _reserved_candidates,
    _invalid_format_candidates,
)


@st.composite
def _holder_relationships(draw):
    """Generate ``(requesting_org_id, holder_org_id)`` across holder = none|self|other.

    * ``none``  — the slug is free (``holder_org_id is None``).
    * ``self``  — the requesting org already holds the slug (R3.5).
    * ``other`` — a different org holds the slug (R3.4).
    """
    holder_kind = draw(st.sampled_from(["none", "self", "other"]))
    requesting = draw(st.one_of(st.none(), st.uuids()))

    if holder_kind == "none":
        return requesting, None
    if holder_kind == "self":
        # "self" is only meaningful when the requester has an identity.
        if requesting is None:
            requesting = draw(st.uuids())
        return requesting, requesting
    # other: a holder that is definitely not the requester.
    holder = draw(st.uuids().filter(lambda u: u != requesting))
    return requesting, holder


# ---------------------------------------------------------------------------
# Property 8: Availability classifier totality
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(candidate=_candidates, orgs=_holder_relationships())
def test_availability_classifier_totality(candidate, orgs):
    """classify_availability is total and never reports an unsafe ``available``.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6**
    """
    requesting_org_id, holder_org_id = orgs

    result, reason = classify_availability(
        candidate,
        requesting_org_id=requesting_org_id,
        holder_org_id=holder_org_id,
    )

    # 1. Totality (R3.2): exactly one of the three outcomes, and never raises.
    assert result in _RESULTS

    normalised = normalise_slug(candidate)
    ok, _ = validate_slug_format(normalised)

    # 2. Bad format <=> invalid (R3.6): a malformed candidate is always invalid
    #    and is never reported available; a well-formed one is never "invalid".
    if not ok:
        assert result == "invalid"
    else:
        assert result != "invalid"

    # 3. "available" is sound (R3.3/R3.4/R3.5): only when well-formed, not
    #    reserved, and either free or held by the requesting org itself.
    if result == "available":
        assert ok, "available must imply a well-formed slug"
        assert normalised not in RESERVED_SLUGS, "reserved slugs must never be available"
        assert (
            holder_org_id is None or holder_org_id == requesting_org_id
        ), "available must imply the slug is free or owned by the requesting org"
        assert reason is None
    else:
        # Non-available outcomes always carry a human-readable reason.
        assert reason is not None and reason.strip() != ""


# ---------------------------------------------------------------------------
# Worked unit examples — concrete anchors for each branch of the classifier.
# ---------------------------------------------------------------------------


def test_free_well_formed_slug_is_available():
    """A well-formed, unheld slug is available (R3.2 free branch / R3.5)."""
    result, reason = classify_availability(
        "acme-motors", requesting_org_id=uuid.uuid4(), holder_org_id=None
    )
    assert result == "available"
    assert reason is None


def test_own_slug_is_available():
    """A slug held by the requesting org itself is available (R3.5)."""
    org = uuid.uuid4()
    result, _ = classify_availability(
        "acme", requesting_org_id=org, holder_org_id=org
    )
    assert result == "available"


def test_other_org_slug_is_unavailable():
    """A slug held by a different org is unavailable (R3.4)."""
    result, reason = classify_availability(
        "acme", requesting_org_id=uuid.uuid4(), holder_org_id=uuid.uuid4()
    )
    assert result == "unavailable"
    assert reason


def test_reserved_slug_is_unavailable_even_when_free():
    """A reserved slug is unavailable even with no holder (R3.3)."""
    result, reason = classify_availability(
        "admin", requesting_org_id=uuid.uuid4(), holder_org_id=None
    )
    assert result == "unavailable"
    assert reason


def test_bad_format_is_invalid_with_reason():
    """A malformed candidate is invalid and never available (R3.6)."""
    result, reason = classify_availability(
        "ab", requesting_org_id=None, holder_org_id=None
    )
    assert result == "invalid"
    assert reason
