"""Canonical NZTA pre-trip checklist item set.

Source: New Zealand Transport Agency pre-trip safety inspection items
enumerated in B2B Fleet Portal Requirement 8.2 and design.md "NZTA
Default Template Items". The list below mirrors the spec verbatim.

This module is the single source of truth for the seed content used by
``checklist_service.seed_nzta_default_for_fleet`` (task 8.1). The
seeder must produce **exactly** the items below in the order they are
declared, with the third tuple element controlling whether photo
evidence is mandatory when the item is failed during a submission
(Property 23).

The seed is idempotent (Property 18): for any fleet account, any number
of seed calls results in exactly one ``is_system_seeded = true`` template
whose item set equals the result of ``nzta_items()``.

Implements: B2B Fleet Portal task 2.4 — Requirements 8.1, 8.2.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NZTATemplateItem:
    """A single canonical NZTA template item.

    ``display_order`` is 1-indexed and dense; the seeder writes this to
    ``fleet_checklist_template_items.display_order`` so the items render
    in the same order they appear here.
    """

    category: str
    label: str
    requires_photo_on_fail: bool
    display_order: int


# (category, label, requires_photo_on_fail) tuples — kept as a flat
# sequence so the source diff is easy to review against the spec.
# ``nzta_items()`` adds the 1-indexed ``display_order`` automatically.
NZTA_ITEMS: list[tuple[str, str, bool]] = [
    # Tyres
    ("tyres", "Tread depth ≥ 1.5 mm on all tyres", True),
    ("tyres", "No visible damage, cuts, or bulges", True),
    ("tyres", "Tyre pressure correct", False),
    # Lights
    ("lights", "Headlights — low beam working", True),
    ("lights", "Headlights — high beam working", True),
    ("lights", "Brake lights working", True),
    ("lights", "Front indicators working", True),
    ("lights", "Rear indicators working", True),
    ("lights", "Hazard lights working", True),
    ("lights", "Reversing light working", False),
    ("lights", "Number plate light working", False),
    # Brakes
    ("brakes", "Foot brake responsive", True),
    ("brakes", "Parking brake holds vehicle", True),
    ("brakes", "No brake warning lights on dash", True),
    # Mirrors
    ("mirrors", "Side mirrors clean and adjusted", False),
    ("mirrors", "Rear-view mirror clean and adjusted", False),
    # Windows / Wipers
    ("windows_wipers", "Windscreen free of cracks obstructing view", True),
    ("windows_wipers", "Wipers and washers functional", False),
    # Fluids
    ("fluids", "Engine oil level OK", False),
    ("fluids", "Coolant level OK", False),
    ("fluids", "Washer fluid level OK", False),
    # Body / Load
    ("body_load", "Load secured", True),
    ("body_load", "Doors close and latch", False),
    ("body_load", "No fluid leaks visible underneath", True),
    # Signage / Indicators
    ("signage", "Registration label current", False),
    ("signage", "WOF / COF label visible (if applicable)", False),
    ("signage", "Reflective tape and hazard signage where required", False),
    # Horn
    ("horn", "Horn audible", False),
    # Seatbelts
    ("seatbelts", "All seatbelts present and functional", True),
]


def nzta_items() -> list[NZTATemplateItem]:
    """Return the canonical NZTA item list with ``display_order`` populated.

    Each item is given a 1-indexed display order that matches its
    position in :data:`NZTA_ITEMS`. The seeder
    (``checklist_service.seed_nzta_default_for_fleet``) writes the
    entire list as ``fleet_checklist_template_items`` rows for the
    seeded template. The result is idempotent: calling this function
    repeatedly always returns the same list of items in the same order.
    """
    return [
        NZTATemplateItem(
            category=category,
            label=label,
            requires_photo_on_fail=requires_photo_on_fail,
            display_order=display_order,
        )
        for display_order, (category, label, requires_photo_on_fail) in enumerate(
            NZTA_ITEMS, start=1
        )
    ]


__all__ = ["NZTA_ITEMS", "NZTATemplateItem", "nzta_items"]
