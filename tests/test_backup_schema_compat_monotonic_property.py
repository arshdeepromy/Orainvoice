"""Property-based test: schema-compatibility decision is monotonic in version order.

# Feature: cloud-backup-restore, Property 15: Schema-compatibility decision is monotonic in version order

**Validates: Requirements 10.2, 10.3, 10.4, 10.5**

The schema-compatibility gate (``app/modules/backup_restore/restore/dry_run.py``
:func:`compare_schema_versions`) classifies a backup's recorded Alembic revision
against the target deployment's current revision. Alembic revision ids in this
repository are **zero-padded, monotonically increasing numeric strings** (e.g.
``"0194"``), so the relationship is defined by the integer value of each id
(:func:`parse_revision_order`):

* backup numeric ``==`` target numeric  → ``equal``  → ``proceed``            (Req 10.4)
* backup numeric ``>``  target numeric  → ``newer``  → ``refused``            (Req 10.3)
* backup numeric ``<``  target numeric  → ``older``  → ``confirm_required``   (Req 10.5)
* backup version missing/empty          → ``missing`` → ``refused``           (Req 10.2)

This property asserts the decision is **monotonic in version order**: holding the
target fixed and walking the backup version from low → high marches the outcome
through ``older`` → ``equal`` → ``newer`` (decision ``confirm_required`` →
``proceed`` → ``refused``) and never regresses. It also asserts the
``older_schema`` flag is set *exactly* when the backup is strictly older than the
target.

The function under test is pure, so no mocks are required — revisions are
generated directly as zero-padded numeric strings.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.restore.dry_run import (
    COMPARE_EQUAL,
    COMPARE_MISSING,
    COMPARE_NEWER,
    COMPARE_OLDER,
    DECISION_CONFIRM_REQUIRED,
    DECISION_PROCEED,
    DECISION_REFUSED,
    compare_schema_versions,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# Alembic revision ids in this repo are zero-padded 4-digit numeric strings.
_REVISION_RANGE = (0, 9999)


def _rev(n: int) -> str:
    """Render an integer as a zero-padded numeric Alembic revision id."""
    return f"{n:04d}"


revision_numbers = st.integers(min_value=_REVISION_RANGE[0], max_value=_REVISION_RANGE[1])


def _rank(outcome: str) -> int:
    """Map an outcome onto its position in the monotone version order.

    Walking the backup version low → high relative to a fixed target marches the
    outcome older → equal → newer, so the rank increases monotonically.
    """
    return {COMPARE_OLDER: 0, COMPARE_EQUAL: 1, COMPARE_NEWER: 2}[outcome]


# ---------------------------------------------------------------------------
# Property 15: Schema-compatibility decision is monotonic in version order
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(backup_n=revision_numbers, target_n=revision_numbers)
def test_outcome_matches_numeric_ordering(backup_n: int, target_n: int) -> None:
    """The classified outcome/decision matches the numeric ordering of B vs T.

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
    """
    res = compare_schema_versions(_rev(backup_n), _rev(target_n))

    if backup_n < target_n:
        # Req 10.5 — older backup: warn + require confirmation.
        assert res.outcome == COMPARE_OLDER
        assert res.decision == DECISION_CONFIRM_REQUIRED
        assert res.older_schema is True
        assert res.is_blocking_incompatibility is False
    elif backup_n == target_n:
        # Req 10.4 — equal: proceed.
        assert res.outcome == COMPARE_EQUAL
        assert res.decision == DECISION_PROCEED
        assert res.older_schema is False
        assert res.is_blocking_incompatibility is False
    else:
        # Req 10.3 — newer backup: refuse.
        assert res.outcome == COMPARE_NEWER
        assert res.decision == DECISION_REFUSED
        assert res.older_schema is False
        assert res.is_blocking_incompatibility is True


@PBT_SETTINGS
@given(target_n=revision_numbers, backups=st.lists(revision_numbers, min_size=2, max_size=12))
def test_decision_is_monotonic_holding_target_fixed(target_n: int, backups: list[int]) -> None:
    """Holding T fixed and increasing B never regresses the outcome rank.

    Sorting the generated backup versions ascending must yield a non-decreasing
    sequence of outcome ranks (older → equal → newer), proving the decision is
    monotonic in version order with no regressions.

    **Validates: Requirements 10.3, 10.4, 10.5**
    """
    target = _rev(target_n)
    ascending = sorted(backups)

    previous_rank = -1
    for b in ascending:
        res = compare_schema_versions(_rev(b), target)
        rank = _rank(res.outcome)
        assert rank >= previous_rank, (
            f"outcome regressed: backup={b} target={target_n} "
            f"outcome={res.outcome} rank={rank} < previous={previous_rank}"
        )
        previous_rank = rank


@PBT_SETTINGS
@given(backup_n=revision_numbers, target_n=revision_numbers)
def test_older_schema_flag_set_exactly_when_backup_older(backup_n: int, target_n: int) -> None:
    """``older_schema`` is True iff the backup is strictly older than the target.

    **Validates: Requirements 10.5**
    """
    res = compare_schema_versions(_rev(backup_n), _rev(target_n))
    assert res.older_schema is (backup_n < target_n)


@PBT_SETTINGS
@given(target_n=revision_numbers, delta=st.integers(min_value=1, max_value=5000))
def test_strict_order_boundaries(target_n: int, delta: int) -> None:
    """Crossing the target boundary flips the decision deterministically.

    A backup just below the target is ``older``/confirm; exactly at the target is
    ``equal``/proceed; just above is ``newer``/refused.

    **Validates: Requirements 10.3, 10.4, 10.5**
    """
    target = _rev(target_n)

    older_n = max(_REVISION_RANGE[0], target_n - delta)
    newer_n = min(_REVISION_RANGE[1], target_n + delta)

    equal_res = compare_schema_versions(target, target)
    assert equal_res.outcome == COMPARE_EQUAL
    assert equal_res.decision == DECISION_PROCEED

    if older_n < target_n:
        older_res = compare_schema_versions(_rev(older_n), target)
        assert older_res.outcome == COMPARE_OLDER
        assert older_res.decision == DECISION_CONFIRM_REQUIRED

    if newer_n > target_n:
        newer_res = compare_schema_versions(_rev(newer_n), target)
        assert newer_res.outcome == COMPARE_NEWER
        assert newer_res.decision == DECISION_REFUSED


@PBT_SETTINGS
@given(target_n=revision_numbers)
def test_missing_backup_version_always_refused(target_n: int) -> None:
    """A missing/empty backup version is refused regardless of target (Req 10.2).

    **Validates: Requirements 10.2**
    """
    for missing in (None, "", "   "):
        res = compare_schema_versions(missing, _rev(target_n))
        assert res.outcome == COMPARE_MISSING
        assert res.decision == DECISION_REFUSED
        assert res.older_schema is False
        assert res.is_blocking_incompatibility is True
