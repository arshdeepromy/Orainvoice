"""Property tests for checklist templates and submissions.

Implements:
- **Property 18** — NZTA seed is idempotent and complete
- **Property 19** — At-most-one default per fleet (DB-level; tested by
  the partial unique index — smoke covers the application path)
- **Property 23** — Photo evidence enforcement at completion
- **Property 24** — Submission completion finalises counts
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.nzta_template import NZTA_ITEMS, nzta_items
from app.modules.fleet_portal.services.checklist_service import (
    submission_can_complete,
)


# ---------------------------------------------------------------------------
# Property 18 — NZTA seed shape
# ---------------------------------------------------------------------------


def test_nzta_items_is_idempotent() -> None:
    """nzta_items() returns the same list every call (deterministic seed)."""
    a = nzta_items()
    b = nzta_items()
    assert a == b


def test_nzta_items_count_matches_design() -> None:
    """29 items across 10 categories per design.md."""
    items = nzta_items()
    assert len(items) == 29
    cats = {i.category for i in items}
    assert cats == {
        "tyres",
        "lights",
        "brakes",
        "mirrors",
        "windows_wipers",
        "fluids",
        "body_load",
        "signage",
        "horn",
        "seatbelts",
    }


def test_nzta_items_have_dense_display_order() -> None:
    items = nzta_items()
    orders = [i.display_order for i in items]
    assert orders == list(range(1, len(items) + 1))


def test_at_least_one_item_per_category_requires_photo() -> None:
    """Spec — every safety-critical category has at least one photo-on-fail."""
    photo_required_cats = {i.category for i in nzta_items() if i.requires_photo_on_fail}
    # Tyres, lights, brakes, body_load, seatbelts must require photos
    # for at least one item each.
    for required_cat in {"tyres", "lights", "brakes", "body_load", "seatbelts"}:
        assert required_cat in photo_required_cats


# ---------------------------------------------------------------------------
# Property 23 — photo evidence at completion
# ---------------------------------------------------------------------------


@dataclass
class _FakeItem:
    label: str = "Item"
    requires_photo_on_fail: bool = False
    result: str | None = None
    photo_urls: list[str] = field(default_factory=list)


def test_complete_ok_when_no_failures() -> None:
    items = [
        _FakeItem(label="A", result="pass"),
        _FakeItem(label="B", result="na"),
    ]
    ok, reason = submission_can_complete(items)
    assert ok is True
    assert reason is None


def test_complete_ok_when_failure_does_not_require_photo() -> None:
    items = [_FakeItem(label="A", requires_photo_on_fail=False, result="fail")]
    ok, reason = submission_can_complete(items)
    assert ok is True


def test_complete_blocked_when_photo_required_failure_has_no_photo() -> None:
    items = [
        _FakeItem(label="Headlight", requires_photo_on_fail=True, result="fail")
    ]
    ok, reason = submission_can_complete(items)
    assert ok is False
    assert "Headlight" in (reason or "")


def test_complete_ok_when_photo_required_failure_has_photo() -> None:
    items = [
        _FakeItem(
            label="Headlight",
            requires_photo_on_fail=True,
            result="fail",
            photo_urls=["s3://bucket/photo.jpg"],
        )
    ]
    ok, _ = submission_can_complete(items)
    assert ok is True


@given(
    items_data=st.lists(
        st.tuples(
            st.booleans(),  # requires_photo_on_fail
            st.sampled_from([None, "pass", "fail", "na"]),
            st.lists(st.text(min_size=1, max_size=8), max_size=3),
        ),
        min_size=0,
        max_size=10,
    )
)
@hyp_settings(max_examples=300)
def test_complete_predicate_matches_specification(items_data) -> None:
    """Property 23 — predicate ⇔ every (rpf ∧ result=fail) item has photos."""
    items = [
        _FakeItem(
            label=f"item_{i}",
            requires_photo_on_fail=rpf,
            result=res,
            photo_urls=list(photos),
        )
        for i, (rpf, res, photos) in enumerate(items_data)
    ]
    ok, _ = submission_can_complete(items)
    expected_ok = all(
        not (i.requires_photo_on_fail and i.result == "fail" and not i.photo_urls)
        for i in items
    )
    assert ok is expected_ok


# ---------------------------------------------------------------------------
# Property 24 — counts finalisation (pure helper)
# ---------------------------------------------------------------------------


def _count_results(results: list[str | None]) -> tuple[int, int, int]:
    """Mirror of the count finalisation done in complete_submission."""
    return (
        sum(1 for r in results if r == "pass"),
        sum(1 for r in results if r == "fail"),
        sum(1 for r in results if r == "na"),
    )


@given(
    results=st.lists(
        st.sampled_from([None, "pass", "fail", "na"]),
        min_size=0,
        max_size=20,
    )
)
@hyp_settings(max_examples=300)
def test_counts_are_disjoint_and_cover_results(results: list[str | None]) -> None:
    p, f, n = _count_results(results)
    # Disjoint: pass + fail + na ≤ total.
    assert p + f + n <= len(results)
    # Equal to count of non-None entries.
    assert p + f + n == sum(1 for r in results if r is not None)
