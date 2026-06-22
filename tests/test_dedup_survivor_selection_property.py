"""Property-based test: de-duplication survivor selection.

# Feature: organisation-employee-portal, Property 2: De-duplication survivor selection

**Validates: Requirements 1.7**

R1.7 says that when active duplicate staff sharing a normalised email or a
non-empty employee identifier are resolved within an organisation, exactly one
survivor is retained — the record with the earliest ``created_at`` (ties broken
by the smallest ``id``) — and every other member of the group is marked
inactive, with nothing outside the active duplicate group deleted or altered.

The functions under test, ``select_dedup_survivor(group, now) -> survivor`` and
``partition_dedup_group(group, now) -> (survivor, losers)`` in
``app/modules/staff/dedup.py``, are pure, DB-free helpers, so they are
exercised directly with no database. We generate arbitrary groups of staff-like
records (a small frozen dataclass carrying ``created_at`` and ``id``) and assert
against an INDEPENDENT reference oracle: the survivor is the member minimising
``(created_at, id)``, the partition returns that survivor plus every other
member as losers, and the input group is never mutated.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.dedup import partition_dedup_group, select_dedup_survivor

# ---------------------------------------------------------------------------
# Hypothesis settings (>=100 iterations) — pure in-memory selection.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)


# ---------------------------------------------------------------------------
# Test record: a lightweight, staff-like value exposing the two attributes the
# helpers read — ``created_at`` and ``id`` — and nothing else. Frozen so a
# mutation of the input would be structurally impossible to hide.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaffRecord:
    id: int
    created_at: datetime


_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


# Draw timestamps from a small pool of offsets so ties on ``created_at`` are
# common (forcing the secondary ``id`` tie-break to be exercised), and ids from
# a range wide enough to be distinct within a group.
_created_at = st.integers(min_value=0, max_value=20).map(
    lambda days: _EPOCH + timedelta(days=days)
)


@st.composite
def _group(draw: st.DrawFn) -> list[StaffRecord]:
    """A non-empty group of staff-like records with unique ids.

    Ids are unique within a group (they identify distinct staff rows), while
    ``created_at`` values are drawn from a narrow pool so ties are frequent.
    """
    size = draw(st.integers(min_value=1, max_value=8))
    ids = draw(
        st.lists(
            st.integers(min_value=1, max_value=10_000),
            min_size=size,
            max_size=size,
            unique=True,
        )
    )
    return [StaffRecord(id=i, created_at=draw(_created_at)) for i in ids]


def _reference_survivor(group: list[StaffRecord]) -> StaffRecord:
    """Independent oracle: earliest ``created_at``, ties → smallest ``id``."""
    return min(group, key=lambda r: (r.created_at, r.id))


# ---------------------------------------------------------------------------
# Property 2: De-duplication survivor selection
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(group=_group())
def test_exactly_one_survivor_earliest_created_smallest_id(
    group: list[StaffRecord],
) -> None:
    """The survivor is the earliest ``created_at``, smallest ``id`` on a tie.

    Property 2 — for any non-empty group, ``select_dedup_survivor`` returns
    exactly one member, and that member is the one an independent reference
    (minimum of ``(created_at, id)``) picks.

    **Validates: Requirements 1.7**
    """
    now = _EPOCH + timedelta(days=100)
    survivor = select_dedup_survivor(group, now)

    expected = _reference_survivor(group)
    assert survivor.id == expected.id
    assert survivor.created_at == expected.created_at
    # Exactly one member of the group is the survivor (identity), and it is a
    # member of the input group.
    assert sum(1 for m in group if m is survivor) == 1


@PBT_SETTINGS
@given(group=_group())
def test_partition_survivor_plus_all_other_members_are_losers(
    group: list[StaffRecord],
) -> None:
    """Partition = (survivor, every other member as a loser); no overlap.

    Property 2 — ``partition_dedup_group`` returns the same survivor as
    ``select_dedup_survivor`` and every remaining member of the group as a
    loser. Survivor + losers exactly reconstitute the group with no duplicates
    and no omissions; the survivor never appears among the losers.

    **Validates: Requirements 1.7**
    """
    now = _EPOCH + timedelta(days=100)
    survivor, losers = partition_dedup_group(group, now)

    assert survivor is select_dedup_survivor(group, now)
    # The survivor is excluded from the losers (by identity).
    assert all(loser is not survivor for loser in losers)
    # Every other member is a loser: counts and identities reconcile exactly.
    assert len(losers) == len(group) - 1
    recombined_ids = sorted([survivor.id] + [loser.id for loser in losers])
    assert recombined_ids == sorted(m.id for m in group)


@PBT_SETTINGS
@given(group=_group())
def test_input_group_is_not_mutated(group: list[StaffRecord]) -> None:
    """Neither helper mutates the input group (nothing outside scope altered).

    Property 2 / R1.7 — selection and partitioning are read-only over the
    group: the list contents, order, and each record's fields are identical
    before and after. The helpers only flag losers downstream; they never
    delete or alter the records themselves.

    **Validates: Requirements 1.7**
    """
    now = _EPOCH + timedelta(days=100)
    snapshot = copy.deepcopy(group)

    select_dedup_survivor(group, now)
    partition_dedup_group(group, now)

    assert group == snapshot
    assert [m.id for m in group] == [m.id for m in snapshot]


@PBT_SETTINGS
@given(group=_group())
def test_survivor_is_minimal_against_every_other_member(
    group: list[StaffRecord],
) -> None:
    """The survivor compares <= every other member under (created_at, id).

    Property 2 — a stronger restatement of the ordering rule: no member of the
    group precedes the survivor under ``(created_at ASC, id ASC)``.

    **Validates: Requirements 1.7**
    """
    survivor = select_dedup_survivor(group)
    survivor_key = (survivor.created_at, survivor.id)
    for member in group:
        assert survivor_key <= (member.created_at, member.id)


def test_single_member_group_survives_with_no_losers() -> None:
    """A group of one resolves to itself with an empty loser set.

    **Validates: Requirements 1.7**
    """
    only = StaffRecord(id=7, created_at=_EPOCH)
    survivor, losers = partition_dedup_group([only])
    assert survivor is only
    assert losers == []
