"""Property-based test: per-org restore apply is atomic (all-or-nothing).

# Feature: cloud-backup-restore, Property 12: Per-org restore is atomic

**Validates: Requirements 14.10**

The per-organisation apply (``PerOrgApplyEngine.apply`` in
``app/modules/backup_restore/restore/per_org_restore.py``) wraps the whole apply
in ``RestoreTarget.atomic()`` — a context manager that, in production, is a
single transaction/SAVEPOINT. Requirement 14.10 demands that any error *after
writes have begun* rolls everything back, so the target returns to its exact
pre-restore state. There is no partial application: either every row of the
working set is committed, or none of them are.

This property exercises that guarantee with everything mocked. We drive the
*real* apply engine against:

* a small synthetic ``SchemaModel`` whose tables carry a NOT-NULL ``org_id`` (so
  the classifier treats every row as an Org_Scoped_Row — rule 2), and
* an in-memory :class:`RestoreTarget` fake whose ``atomic()`` is a genuine
  snapshot/rollback context manager: it deep-copies the committed-rows dict on
  ``__aenter__`` and, on ``__aexit__`` with an exception, restores that snapshot
  (simulating ROLLBACK) before propagating. Its ``insert()`` is configured to
  raise on the ``k``-th call to model an error partway through the apply.

For any generated dataset and failure point ``k`` (drawn across the whole row
count *including* "no failure"):

* **Failure case** (``k`` lands on a real insert) — ``apply`` raises and the
  target's committed state equals its pre-apply state exactly (full rollback,
  zero net change).
* **Success case** (no failure) — ``apply`` returns and every dataset row is
  present in the target alongside the untouched pre-existing baseline (commit).

No database, storage, or filesystem is involved — the apply logic is pure
orchestration over the injected, fully-mocked target.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from typing import Any, Mapping

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Column, MetaData, String, Table

from app.modules.backup_restore.restore.per_org_restore import (
    ConflictPolicy,
    ExtractedDataset,
    ExtractedRow,
    PerOrgApplyEngine,
    RestoreTarget,
    SchemaModel,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory apply, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=150, deadline=None)

# A small synthetic schema: three tables, each with a NOT-NULL ``org_id`` so the
# classifier (rule 2) treats every row as an Org_Scoped_Row. No foreign keys, so
# the working set is exactly the dataset rows (no transitive closure surprises).
_TEST_METADATA = MetaData()
_ORG_TABLES = ("alpha", "beta", "gamma")
for _name in _ORG_TABLES:
    Table(
        _name,
        _TEST_METADATA,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("payload", String),
    )

_SCHEMA = SchemaModel(metadata=_TEST_METADATA)


# ---------------------------------------------------------------------------
# In-memory transactional RestoreTarget fake with real snapshot/rollback.
# ---------------------------------------------------------------------------


class _SnapshotTxn:
    """Async context manager modelling a transaction over the fake's rows dict.

    Snapshots the committed-rows dict on enter; on exit-with-exception it
    restores that snapshot (ROLLBACK) and lets the exception propagate; on a
    clean exit the mutations stand (COMMIT).
    """

    def __init__(self, target: "InMemoryRestoreTarget") -> None:
        self.target = target
        self._snapshot: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}

    async def __aenter__(self) -> "_SnapshotTxn":
        self._snapshot = copy.deepcopy(self.target.rows)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            # ROLLBACK: discard every write made inside the transaction.
            self.target.rows = self._snapshot
        # COMMIT otherwise (leave self.target.rows as-is). Never suppress.
        return False


class InMemoryRestoreTarget(RestoreTarget):
    """A fully in-memory :class:`RestoreTarget` for the atomicity property.

    ``rows`` is the committed state: ``(table, pk_tuple) -> values``. ``atomic``
    yields a real snapshot/rollback transaction. ``insert`` raises on the
    ``fail_on_insert`` -th call (1-based) to simulate an error partway through.
    """

    def __init__(
        self,
        pk_columns: Mapping[str, tuple[str, ...]],
        *,
        baseline: Mapping[tuple[str, tuple[Any, ...]], dict[str, Any]] | None = None,
        fail_on_insert: int | None = None,
    ) -> None:
        self._pk_columns = dict(pk_columns)
        self.rows: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = (
            copy.deepcopy(dict(baseline)) if baseline else {}
        )
        self._fail_on_insert = fail_on_insert
        self.insert_calls = 0
        self.org_context: str | None = None

    def _pk_of(self, table: str, values: Mapping[str, Any]) -> tuple[Any, ...]:
        cols = self._pk_columns.get(table, ("id",))
        return tuple(values.get(c) for c in cols)

    async def set_org_context(self, org_id: str) -> None:
        self.org_context = str(org_id)

    def atomic(self) -> _SnapshotTxn:
        return _SnapshotTxn(self)

    async def org_row_exists(
        self, table: str, pk_columns: tuple[str, ...], pk: tuple[Any, ...]
    ) -> bool:
        return (table, tuple(pk)) in self.rows

    async def shared_global_equivalent(
        self, table: str, row: ExtractedRow, pk_columns: tuple[str, ...]
    ) -> tuple[Any, ...] | None:
        pk = tuple(row.values.get(c) for c in pk_columns)
        return pk if (table, pk) in self.rows else None

    async def insert(self, table: str, values: Mapping[str, Any]) -> None:
        self.insert_calls += 1
        if self._fail_on_insert is not None and self.insert_calls == self._fail_on_insert:
            raise RuntimeError(
                f"simulated apply error on insert #{self.insert_calls} into {table!r}"
            )
        self.rows[(table, self._pk_of(table, values))] = dict(values)

    async def update(
        self,
        table: str,
        pk_columns: tuple[str, ...],
        pk: tuple[Any, ...],
        values: Mapping[str, Any],
    ) -> None:
        self.rows[(table, tuple(pk))] = dict(values)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

_uuid_str = st.builds(lambda: str(uuid.uuid4()))


@st.composite
def restore_scenarios(draw):
    """Generate (org_id, dataset, baseline, fail_on_insert).

    * ``dataset`` — Org_Scoped_Rows for the selected org across the synthetic
      tables, with globally-unique single-column PKs.
    * ``baseline`` — pre-existing committed rows in the target with PKs disjoint
      from the dataset (the pre-restore state we expect rollback to restore).
    * ``fail_on_insert`` — failure point across the row count *including* the
      no-failure case (``0``). Because every dataset PK is unique and absent from
      the baseline, the apply performs exactly ``len(dataset rows)`` inserts, so
      ``1..N`` are genuine partway failures and ``0`` (or ``> N``) means success.
    """
    org_id = draw(_uuid_str)

    n_rows = draw(st.integers(min_value=1, max_value=12))
    used_ids: set[str] = set()
    dataset = ExtractedDataset(org_id=org_id)
    for _ in range(n_rows):
        table = draw(st.sampled_from(_ORG_TABLES))
        row_id = draw(_uuid_str.filter(lambda v: v not in used_ids))
        used_ids.add(row_id)
        values = {
            "id": row_id,
            "org_id": org_id,
            "payload": draw(st.text(max_size=8)),
        }
        dataset.add_row(
            ExtractedRow(table=table, values=values, pk=(row_id,), org_id=org_id),
            ("id",),
        )

    # Pre-existing baseline rows with PKs disjoint from the dataset.
    baseline: dict[tuple[str, tuple[Any, ...]], dict[str, Any]] = {}
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        table = draw(st.sampled_from(_ORG_TABLES))
        row_id = draw(_uuid_str.filter(lambda v: v not in used_ids))
        used_ids.add(row_id)
        baseline[(table, (row_id,))] = {
            "id": row_id,
            "org_id": org_id,
            "payload": draw(st.text(max_size=8)),
        }

    # Failure point across the row count incl. no-failure (0) and beyond (N+1).
    fail_on_insert = draw(st.integers(min_value=0, max_value=n_rows + 1))

    return {
        "org_id": org_id,
        "dataset": dataset,
        "baseline": baseline,
        "n_rows": n_rows,
        "fail_on_insert": fail_on_insert,
    }


# ---------------------------------------------------------------------------
# Property 12: Per-org restore is atomic
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(scenario=restore_scenarios())
def test_per_org_apply_is_atomic(scenario):
    """An error partway through the apply leaves zero net changes (Req 14.10).

    Failure → full ROLLBACK to the pre-apply committed state; success → COMMIT
    of every dataset row alongside the untouched baseline.

    **Validates: Requirements 14.10**
    """
    org_id = scenario["org_id"]
    dataset = scenario["dataset"]
    baseline = scenario["baseline"]
    n_rows = scenario["n_rows"]
    fail_on_insert = scenario["fail_on_insert"]

    # Independent copies so the assertion baselines are never aliased to the
    # target's mutable state.
    pre_apply_state = copy.deepcopy(baseline)

    target = InMemoryRestoreTarget(
        {t: ("id",) for t in _ORG_TABLES},
        baseline=baseline,
        fail_on_insert=(fail_on_insert if fail_on_insert >= 1 else None),
    )
    engine = PerOrgApplyEngine(_SCHEMA, target)

    # A failure occurs only when the configured insert index lands within the
    # number of inserts the apply will actually perform (one per dataset row,
    # since every PK is unique and absent from the baseline).
    failure_expected = 1 <= fail_on_insert <= n_rows

    async def run() -> None:
        await engine.apply(dataset, org_id, ConflictPolicy.SKIP)

    if failure_expected:
        raised = False
        try:
            asyncio.run(run())
        except RuntimeError:
            raised = True
        assert raised, "expected the simulated insert error to propagate out of apply"

        # ROLLBACK: the committed state is *exactly* the pre-apply state — no
        # row inserted before the failure survives (all-or-nothing, Req 14.10).
        assert target.rows == pre_apply_state
    else:
        asyncio.run(run())

        # COMMIT: every dataset row is present in addition to the untouched
        # baseline, and nothing else was invented.
        expected = dict(pre_apply_state)
        for table, rows in dataset.rows_by_table.items():
            for row in rows:
                expected[(table, (row.values["id"],))] = dict(row.values)
        assert target.rows == expected
        # The pre-existing baseline rows are still present and unmodified.
        for key, value in pre_apply_state.items():
            assert target.rows[key] == value
