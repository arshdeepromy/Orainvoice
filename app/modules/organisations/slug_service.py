"""Pure, side-effect-free, DB-free slug helpers for the Organisation Employee Portal.

These functions carry **no** database, network, or other side effects so they can be
property-tested in isolation (design.md §Slug service; Properties 4, 5, 7, 8) and so the
mobile/web client mirrors can stay in parity.

Responsibilities:
- ``RESERVED_SLUGS`` — the set of disallowed slugs. Per R8.4/R8.5 it is a **superset** of
  every existing top-level route segment used by public, marketing, customer-portal, and
  fleet-portal routes in ``frontend-v2/src/App.tsx``, plus platform/operational/brand terms.
- ``normalise_slug`` — the single normalisation (trim + lowercase) used everywhere (R2.7, R2.8).
- ``validate_slug_format`` — length 3..63 and ``[a-z0-9]`` with single internal hyphens (R2.2, R2.3).
- ``is_reserved`` — membership test against ``RESERVED_SLUGS`` on the normalised form (R2.4).
- ``classify_availability`` — the pure availability classifier (R3.2–R3.6) given the format
  result, the reserved check, and the resolved holder org id (the DB lookup happens in the
  caller; this function never touches a database).

Validates: Requirements 2.2, 2.3, 2.4, 2.7, 2.8, 3.2, 3.3, 3.4, 3.5, 3.6, 8.4, 8.5.
"""

from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# Reserved slugs (R2.4, R8.4, R8.5)
# ---------------------------------------------------------------------------
# This set is a SUPERSET of every existing top-level route segment so that no
# organisation slug can ever shadow a real platform route. The segments below
# were inventoried from ``frontend-v2/src/App.tsx`` (public, marketing,
# customer-portal, and fleet-portal routes) plus platform/operational/brand terms.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        # Platform & operational
        "api", "admin", "app", "www", "health", "static", "assets", "login", "logout",
        "signup", "dashboard", "settings", "auth", "mfa", "password",
        # Existing top-level public/marketing/customer-portal/fleet route segments (R8.4, R8.5)
        "e", "portal", "fleet", "public", "book", "pay", "onboard", "payments",
        "staff-portal", "new", "edit",
        # Guest auth routes (App.tsx AuthLayout)
        "mfa-verify", "forgot-password", "reset-password", "verify-email", "passkey-setup",
        # Marketing pages (App.tsx managed/marketing routes)
        "privacy", "trades", "workshop", "mechanics", "garage", "kiosk",
        # Brand / abuse-prone
        "support", "help", "status", "billing", "stripe", "webhook", "webhooks",
    }
)

# Availability result type (exactly one of three values — R3.2).
AvailabilityResult = Literal["available", "unavailable", "invalid"]

# Slug regex: lowercase alphanumerics with single internal hyphens; no leading,
# trailing, or doubled hyphens (R2.2).
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_MIN_LEN = 3
_MAX_LEN = 63


def normalise_slug(raw: str) -> str:
    """Trim surrounding whitespace and fold to lowercase.

    This is the single normalisation used everywhere a slug is stored or compared,
    so reservation, format, and uniqueness checks are all case-insensitive (R2.7, R2.8).
    Idempotent: ``normalise_slug(normalise_slug(x)) == normalise_slug(x)``.
    """
    return raw.strip().lower()


def validate_slug_format(slug: str) -> tuple[bool, str | None]:
    """Return ``(ok, human_message)`` for a candidate slug.

    Accepts iff the value is 3..63 characters long and consists of lowercase letters,
    digits, and single internal hyphens (no leading/trailing/doubled hyphen). On rejection,
    ``ok`` is ``False`` and the second element is a human-readable reason naming the violated
    rule (R2.2, R2.3). On acceptance returns ``(True, None)``.
    """
    if not (_MIN_LEN <= len(slug) <= _MAX_LEN):
        return False, "Slug must be between 3 and 63 characters."
    if not _SLUG_RE.match(slug):
        return (
            False,
            "Use only lowercase letters, numbers, and single hyphens "
            "(no leading, trailing, or repeated hyphens).",
        )
    return True, None


def is_reserved(slug: str) -> bool:
    """Return ``True`` if the slug, in normalised form, is reserved (R2.4)."""
    return normalise_slug(slug) in RESERVED_SLUGS


def classify_availability(
    candidate: str,
    *,
    requesting_org_id: object | None,
    holder_org_id: object | None,
) -> tuple[AvailabilityResult, str | None]:
    """Classify slug availability — pure given the resolved holder org id (R3.2–R3.6).

    The caller is responsible for the (DB) lookup that resolves which organisation, if any,
    currently holds the normalised candidate slug, and passes the result as ``holder_org_id``
    (``None`` when the slug is free). This function performs **no** I/O.

    Returns ``(result, reason)`` where ``result`` is exactly one of
    ``{"available", "unavailable", "invalid"}`` (R3.2) and ``reason`` is a human-readable
    message for the non-available cases (``None`` when available):

    - ``invalid`` — the candidate fails format validation; never returned as available (R3.6).
    - ``unavailable`` — the candidate is reserved (R3.3) or held by another organisation (R3.4).
    - ``available`` — the candidate is free, or is already held by the requesting org itself (R3.5).

    Args:
        candidate: The raw candidate slug (normalised internally).
        requesting_org_id: The id of the organisation asking, or ``None`` (e.g. a new org).
        holder_org_id: The id of the organisation that currently holds the normalised slug,
            or ``None`` if no organisation holds it.
    """
    n = normalise_slug(candidate)

    ok, message = validate_slug_format(n)
    if not ok:
        # Bad format is invalid and must never be reported as available (R3.6).
        return "invalid", message

    if n in RESERVED_SLUGS:
        return "unavailable", "This slug is reserved and cannot be used."

    if holder_org_id is None:
        # Free — nobody holds it (R3.2/R3.5 "free" branch).
        return "available", None

    if requesting_org_id is not None and holder_org_id == requesting_org_id:
        # The requesting organisation already holds this slug (R3.5).
        return "available", None

    # Held by a different organisation (R3.4).
    return "unavailable", "This slug is already taken."
