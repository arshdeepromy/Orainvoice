"""Expiry-status badge function for WOF / COF / service-due.

Implements Property 16: a pure function ``badge(expiry, today)`` that
returns ``'red' | 'amber' | 'green'`` per the rules in design.md and
Requirements 6.3, 6.4, 7.8:

    expiry < today                                  → red    (Expired)
    today <= expiry <= today + 28 days              → amber  (Expiring soon)
    expiry > today + 28 days                        → green  (OK)

The function is total over (date, date) — every input pair maps to
exactly one of the three buckets. ``None`` for ``expiry`` returns
``None`` so callers can render a "no expiry recorded" badge.

The 28-day amber window is the one knob a future spec might want to
make per-org configurable; for now it is hard-coded per the spec.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

BadgeColour = Literal["red", "amber", "green"]

# Hard-coded 28-day amber window per design.md (Property 16).
AMBER_WINDOW_DAYS = 28


def badge(expiry: date | None, today: date) -> BadgeColour | None:
    """Return the badge colour for an expiry date, or None when missing."""
    if expiry is None:
        return None
    if expiry < today:
        return "red"
    if expiry <= today + timedelta(days=AMBER_WINDOW_DAYS):
        return "amber"
    return "green"


__all__ = ["BadgeColour", "AMBER_WINDOW_DAYS", "badge"]
