"""Pure, side-effect-free de-duplication survivor selection for staff members.

This module isolates the *ordering rule* used to resolve a group of active
staff members that share a normalised email address or employee identifier
within a single organisation. It is deliberately DB-free so the rule can be
property-tested in isolation (see task 4.4 / Property 2) and so it stays in
lock-step with the migration that enforces the same rule over existing data.

The survivor of a duplicate group is the record with:

  1. the **earliest** ``created_at`` timestamp, and
  2. on a tie, the **smallest** ``id``.

This is exactly the ordering used by migration ``0224``'s Step 3
(``alembic/versions/2026_06_13_0001-0224_employee_portal.py``), which selects
the survivor as element ``[0]`` of
``array_agg(id ORDER BY created_at ASC, id ASC)``. Keeping the rule here in a
single pure function guarantees the application-side resolution and the
migration-side resolution can never drift apart.

These helpers **never mutate their input**: they read ``created_at``/``id`` from
each group member and return references to the existing objects.

Validates: Requirements 1.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeVar, runtime_checkable

__all__ = [
    "DedupCandidate",
    "select_dedup_survivor",
    "partition_dedup_group",
]


@runtime_checkable
class DedupCandidate(Protocol):
    """Structural type for anything resolvable as a dedup group member.

    Any object exposing a ``created_at`` (comparable, e.g. ``datetime``) and an
    ``id`` (comparable, e.g. ``uuid.UUID`` or ``int``) attribute satisfies this
    protocol — including SQLAlchemy ``StaffMember`` rows and lightweight test
    records.
    """

    @property
    def id(self) -> object: ...

    @property
    def created_at(self) -> datetime: ...


# Bound to the protocol so callers keep their concrete element type on the way
# out (e.g. a list[StaffMember] yields a StaffMember survivor).
T = TypeVar("T", bound=DedupCandidate)


def _survivor_sort_key(member: DedupCandidate) -> tuple[object, object]:
    """Sort key implementing ``ORDER BY created_at ASC, id ASC``.

    The survivor is the minimum under this key: earliest ``created_at`` wins,
    and ties are broken by the smallest ``id`` — byte/int ordering of ``id``
    matches PostgreSQL's ascending order for the ``uuid``/integer column used by
    the migration.
    """

    return (member.created_at, member.id)


def select_dedup_survivor(group: list[T], now: datetime | None = None) -> T:
    """Return the survivor of a duplicate ``group`` without mutating it.

    The survivor is the member with the earliest ``created_at``; ties are
    broken by the smallest ``id`` — identical to migration 0224 Step 3.

    Args:
        group: A non-empty collection of active, staff-like records that share
            a normalised email address or employee identifier within one
            organisation. Each element must expose ``created_at`` and ``id``.
        now: The point-in-time at which resolution is evaluated. The ordering
            rule does not depend on it (survivor selection is a function of the
            group alone), but it is accepted to mirror the migration's
            resolution signature and keep the call site explicit.

    Returns:
        The single survivor record (a reference to an element of ``group``).

    Raises:
        ValueError: If ``group`` is empty — an empty group has no survivor.
    """

    # ``now`` is intentionally unused by the ordering rule; accepted for
    # signature parity with the migration's point-in-time resolution.
    del now

    if not group:
        raise ValueError("cannot select a dedup survivor from an empty group")

    # ``min`` does not mutate the input and returns the first element that
    # compares smallest, exactly matching ``array_agg(... ORDER BY ...)[0]``.
    return min(group, key=_survivor_sort_key)


def partition_dedup_group(
    group: list[T], now: datetime | None = None
) -> tuple[T, list[T]]:
    """Split a duplicate ``group`` into ``(survivor, losers)`` without mutating it.

    The survivor is selected by :func:`select_dedup_survivor`. The losers are
    every other member of the group, returned in the group's original order so
    the caller can deactivate them deterministically. The input list is never
    modified; a fresh list of losers is returned.

    Args:
        group: A non-empty collection of staff-like records (see
            :func:`select_dedup_survivor`).
        now: Point-in-time of resolution; forwarded to
            :func:`select_dedup_survivor` (unused by the ordering rule).

    Returns:
        A ``(survivor, losers)`` tuple. ``losers`` is empty when ``group`` has a
        single member. The survivor never appears in ``losers``.

    Raises:
        ValueError: If ``group`` is empty.
    """

    survivor = select_dedup_survivor(group, now)

    # Identity comparison (``is``) ensures we exclude exactly the survivor
    # instance even if two distinct records compare equal on their fields.
    losers = [member for member in group if member is not survivor]

    return survivor, losers
