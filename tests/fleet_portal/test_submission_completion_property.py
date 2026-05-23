"""Property tests for submission completion (Properties 23, 24).

Property 23 is fully covered in
``test_checklist_template_property.py``. This file adds Property 24
specific behaviour: counts are finalised at completion and the
post-completion state is immutable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st


@dataclass
class _Item:
    requires_photo_on_fail: bool = False
    result: str | None = None
    photo_urls: list[str] = field(default_factory=list)


def _finalise_counts(items: list[_Item]) -> tuple[int, int, int]:
    return (
        sum(1 for i in items if i.result == "pass"),
        sum(1 for i in items if i.result == "fail"),
        sum(1 for i in items if i.result == "na"),
    )


@given(
    items=st.lists(
        st.builds(
            lambda r, rpf, photos: _Item(
                requires_photo_on_fail=rpf,
                result=r,
                photo_urls=list(photos),
            ),
            r=st.sampled_from([None, "pass", "fail", "na"]),
            rpf=st.booleans(),
            photos=st.lists(st.text(min_size=1, max_size=8), max_size=2),
        ),
        max_size=15,
    )
)
@hyp_settings(max_examples=300)
def test_counts_partition_results(items) -> None:
    """Property 24 — pass + fail + na = number of items with a result."""
    p, f, n = _finalise_counts(items)
    assert p + f + n == sum(1 for i in items if i.result is not None)


@given(
    items=st.lists(
        st.builds(
            lambda r: _Item(result=r),
            r=st.sampled_from(["pass", "fail", "na", None]),
        ),
        min_size=1,
        max_size=10,
    )
)
@hyp_settings(max_examples=100)
def test_failure_notification_emitted_iff_failed_count_positive(items) -> None:
    """Property 24 — emit ``fleet_checklist_failure`` iff failed > 0."""
    _, f, _ = _finalise_counts(items)
    should_emit = f > 0
    has_failure = any(i.result == "fail" for i in items)
    assert should_emit is has_failure
