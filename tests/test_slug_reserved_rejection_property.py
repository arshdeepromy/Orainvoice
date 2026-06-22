"""Property-based test for reserved-slug superset and rejection (Task 3.4).

Feature: organisation-employee-portal, Property 7: Reserved-slug superset and rejection

Exercises the pure, DB-free slug helpers in
``app.modules.organisations.slug_service`` — ``RESERVED_SLUGS`` (frozenset),
``is_reserved`` and ``classify_availability`` — with no database or network I/O,
so the property is testable in isolation.

The property has two halves:

(a) **Superset of every known top-level route segment (R8.4, R8.5).**
    ``RESERVED_SLUGS`` MUST contain every top-level path segment used by the
    existing public, marketing, customer-portal, and fleet-portal routes so that
    no organisation slug can ever shadow a real platform route. The segment list
    below was inventoried from ``frontend-v2/src/App.tsx`` (and the fleet portal,
    a separate front-end app served under ``/fleet`` per design.md §D1).

(b) **Reserved candidates are rejected, never available (R2.4, R3.3).**
    For any reserved candidate (in any case / with surrounding whitespace, since
    normalisation folds those), ``is_reserved`` returns ``True`` (this is the
    pure check the save path uses to reject with ``422 slug_reserved``), and
    ``classify_availability`` never returns ``"available"`` — it returns
    ``"unavailable"`` for a well-formed reserved candidate (regardless of who, if
    anyone, currently holds it — the reserved check takes precedence over the
    "held by the requesting org itself" branch), and ``"invalid"`` only when the
    reserved value also fails the slug format rule (e.g. the single-character
    reserved segment ``e``).

Validates: Requirements 2.4, 8.4, 8.5
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.organisations.slug_service import (
    RESERVED_SLUGS,
    classify_availability,
    is_reserved,
    normalise_slug,
    validate_slug_format,
)

# ---------------------------------------------------------------------------
# (a) Known top-level route segments inventoried from frontend-v2/src/App.tsx.
# Every one of these MUST be a member of RESERVED_SLUGS (R8.4, R8.5).
# ---------------------------------------------------------------------------
# Marketing / managed pages (App.tsx /privacy, /trades, /workshop, /mechanics,
# /garage).
_MARKETING_SEGMENTS = ["privacy", "trades", "workshop", "mechanics", "garage"]

# Guest + authenticated auth routes (App.tsx AuthLayout: /login, /signup,
# /mfa-verify, /forgot-password, /reset-password, /verify-email, /passkey-setup).
_AUTH_SEGMENTS = [
    "login",
    "signup",
    "mfa-verify",
    "forgot-password",
    "reset-password",
    "verify-email",
    "passkey-setup",
]

# Customer-portal routes (App.tsx /portal/signed-out, /portal/recover,
# /portal/:token, /portal/:token/payment-success) — top-level segment "portal".
_CUSTOMER_PORTAL_SEGMENTS = ["portal"]

# Public token / booking / payment pages (App.tsx /book/:orgSlug, /pay/:token,
# /public/staff-roster/:token, /onboard/:token, /payments/qr-*).
_PUBLIC_TOKEN_SEGMENTS = ["book", "pay", "public", "onboard", "payments"]

# Kiosk (App.tsx /kiosk, /kiosk/clock).
_KIOSK_SEGMENTS = ["kiosk"]

# Fleet portal — a separate front-end app served under /fleet (design.md §D1).
_FLEET_PORTAL_SEGMENTS = ["fleet"]

# The employee portal's own reserved single-segment prefix (design.md §D1).
_EMPLOYEE_PORTAL_SEGMENTS = ["e"]

# The full superset of known top-level segments that must be reserved.
KNOWN_TOP_LEVEL_ROUTE_SEGMENTS: list[str] = (
    _MARKETING_SEGMENTS
    + _AUTH_SEGMENTS
    + _CUSTOMER_PORTAL_SEGMENTS
    + _PUBLIC_TOKEN_SEGMENTS
    + _KIOSK_SEGMENTS
    + _FLEET_PORTAL_SEGMENTS
    + _EMPLOYEE_PORTAL_SEGMENTS
)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

# A base reserved slug drawn from the actual reserved set, so the test stays in
# parity with the implementation as the set grows.
_reserved_base = st.sampled_from(sorted(RESERVED_SLUGS))

# Optional surrounding whitespace — normalisation must strip it before the
# reserved comparison (R2.7, R2.8).
_pad = st.sampled_from(["", " ", "  ", "\t", " \t ", "\n"])


@st.composite
def _reserved_candidates(draw: st.DrawFn) -> str:
    """Draw a reserved slug perturbed by case and surrounding whitespace.

    Because ``normalise_slug`` trims and lowercases, every value produced here
    normalises back to a member of ``RESERVED_SLUGS`` and so must remain
    reserved — exercising the case-/whitespace-insensitivity of the check.
    """
    base = draw(_reserved_base)

    # Randomly re-case each character so the candidate covers mixed case.
    cased = "".join(
        ch.upper() if draw(st.booleans()) else ch.lower() for ch in base
    )

    return draw(_pad) + cased + draw(_pad)


# Holder / requester ids — arbitrary "org ids" (plus None) so we prove the
# reserved verdict is independent of who holds the slug, even the requester.
_org_ids = st.one_of(st.none(), st.integers(min_value=1, max_value=10))


# ---------------------------------------------------------------------------
# (a) RESERVED_SLUGS is a superset of every known top-level route segment.
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(segment=st.sampled_from(KNOWN_TOP_LEVEL_ROUTE_SEGMENTS))
def test_reserved_slugs_superset_of_known_route_segments(segment: str) -> None:
    """Every known top-level route segment is reserved (R8.4, R8.5).

    **Validates: Requirements 8.4, 8.5**
    """
    # The segment is a literal member of the reserved frozenset...
    assert segment in RESERVED_SLUGS, (
        f"Top-level route segment {segment!r} must be in RESERVED_SLUGS so it "
        f"can never be claimed as an organisation slug (R8.5)."
    )
    # ...and the pure reserved check agrees (case-insensitive, R2.8).
    assert is_reserved(segment) is True
    assert is_reserved(segment.upper()) is True


def test_reserved_slugs_superset_is_complete() -> None:
    """The whole enumerated route-segment set is a subset of RESERVED_SLUGS.

    A single set-level assertion (in addition to the per-example check above)
    so a missing segment is reported all at once.

    **Validates: Requirements 8.4, 8.5**
    """
    missing = set(KNOWN_TOP_LEVEL_ROUTE_SEGMENTS) - set(RESERVED_SLUGS)
    assert not missing, f"RESERVED_SLUGS is missing route segments: {sorted(missing)}"


# ---------------------------------------------------------------------------
# (b) Reserved candidates are rejected and never reported available.
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    candidate=_reserved_candidates(),
    requesting_org_id=_org_ids,
    holder_org_id=_org_ids,
)
def test_reserved_candidate_is_rejected_and_never_available(
    candidate: str,
    requesting_org_id: object | None,
    holder_org_id: object | None,
) -> None:
    """A reserved candidate is reserved and is never classified available.

    For any case/whitespace variant of a reserved slug, and for any holder /
    requester combination (including the requester being the current holder),
    ``is_reserved`` is True and ``classify_availability`` never returns
    ``"available"`` — it returns ``"unavailable"`` for a well-formed reserved
    value and ``"invalid"`` only when the reserved value also breaks the format
    rule (R2.4, R3.3, R8.4, R8.5).

    **Validates: Requirements 2.4, 8.4, 8.5**
    """
    normalised = normalise_slug(candidate)

    # The pure reserved check the save path uses to reject (422 slug_reserved).
    assert is_reserved(candidate) is True
    assert normalised in RESERVED_SLUGS

    result, reason = classify_availability(
        candidate,
        requesting_org_id=requesting_org_id,
        holder_org_id=holder_org_id,
    )

    # Never available — the core safety invariant.
    assert result != "available"
    # The classifier is total: it returns one of the rejection verdicts.
    assert result in {"unavailable", "invalid"}
    # Every rejection carries a human-readable reason.
    assert reason

    # A well-formed reserved value is specifically reported "unavailable"; a
    # reserved value that also fails the format rule (e.g. the 1-char "e") is
    # "invalid". Either way it is rejected and never available.
    format_ok, _ = validate_slug_format(normalised)
    if format_ok:
        assert result == "unavailable"
    else:
        assert result == "invalid"
