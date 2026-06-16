"""Property-based test: Shared_Global rows are ensured-exists, never mutated.

# Feature: cloud-backup-restore, Property 9: Shared-global rows are ensured-exists, never mutated

**Validates: Requirements 14.6, 14.7**

A per-organisation restore (Requirement 14) handles Shared_Global_Rows — the
platform/reference data that belongs to no single organisation — by
**read-and-ensure-exists** (Req 14.6 / 14.7):

* a referenced Shared_Global_Row is inserted into the target **only if no
  equivalent row already exists** there, and
* an existing Shared_Global_Row is **NEVER modified or deleted**.

This is independent of the conflict policy chosen for the org's own data — the
policy (restore-as-new / skip / overwrite) governs Org_Scoped_Rows only, so the
ensure-exists behaviour must hold under every policy.

The code under test is
``app/modules/backup_restore/restore/per_org_restore.py``
(``PerOrgApplyEngine._ensure_shared_global``). The engine is pure orchestration
over an injected :class:`RestoreTarget`, so this test drives it with an
in-memory fake target and a tiny synthetic two-table schema (a shared-global
table with no ``org_id`` plus an org-scoped table that references it). The fake
records every insert / update / delete and pre-seeds a chosen subset of
shared-global rows as already present.

The property asserts, for any generated dataset of shared-global rows (some
pre-existing in the target, some absent) and org-scoped rows, under any conflict
policy, that after the apply:

* every **absent** shared-global row is inserted **exactly once**;
* every **already-present** shared-global row is **never inserted, updated, or
  deleted** (zero mutation of shared data);
* **no** update or delete ever targets a shared-global table.

Everything is mocked / in-memory — no database, storage, or filesystem.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Column, ForeignKey, MetaData, String, Table

from app.modules.backup_restore.restore.per_org_restore import (
    ConflictPolicy,
    ExtractedDataset,
    ExtractedRow,
    PerOrgApplyEngine,
    RestoreTarget,
    SchemaModel,
)

# ---------------------------------------------------------------------------
# Synthetic schema — one shared-global table + one org-scoped table.
# ---------------------------------------------------------------------------
#
# ``ref_plans`` has NO ``org_id`` column → classifier rule 3/default makes it
# SHARED_GLOBAL. ``widgets`` has a NOT NULL ``org_id`` → ORG_SCOPED, and carries
# a foreign key to ``ref_plans`` so a restored org row can reference a shared
# row (the ensure-exists target).
SHARED_TABLE = "ref_plans"
ORG_TABLE = "widgets"
SELECTED_ORG = "11111111-1111-1111-1111-111111111111"


def _build_metadata() -> MetaData:
    md = MetaData()
    Table(
        SHARED_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("name", String),
    )
    Table(
        ORG_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("plan_id", String, ForeignKey(f"{SHARED_TABLE}.id")),
        Column("label", String),
    )
    return md


_METADATA = _build_metadata()


# ---------------------------------------------------------------------------
# In-memory RestoreTarget fake — records every write; pre-seeds shared rows.
# ---------------------------------------------------------------------------


class FakeRestoreTarget(RestoreTarget):
    """Records inserts/updates/deletes and answers existence queries in memory.

    ``present_shared`` is the set of Shared_Global_Row PKs the target already
    holds; it grows as shared rows are inserted so a repeated ensure-exists for
    the same shared key resolves to the existing row (faithful to a real session
    seeing its own inserts). ``existing_org`` is the set of Org_Scoped_Row PKs
    that already exist (drives skip/overwrite).
    """

    def __init__(
        self,
        *,
        present_shared: dict[str, set[tuple[Any, ...]]],
        existing_org: dict[str, set[tuple[Any, ...]]],
        pk_columns_by_table: dict[str, tuple[str, ...]],
        shared_tables: set[str],
    ) -> None:
        self.present_shared = {t: set(pks) for t, pks in present_shared.items()}
        self.existing_org = {t: set(pks) for t, pks in existing_org.items()}
        self.pk_columns_by_table = pk_columns_by_table
        self.shared_tables = set(shared_tables)
        # Pre-existing shared PKs at the start of the apply (never to be mutated).
        self.preexisting_shared = {t: set(pks) for t, pks in present_shared.items()}
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[tuple[str, tuple[Any, ...]]] = []
        self.deletes: list[tuple[str, tuple[Any, ...]]] = []
        self.org_context: str | None = None

    async def set_org_context(self, org_id: str) -> None:
        self.org_context = org_id

    def atomic(self):
        target = self

        class _Atomic:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *exc_info):
                return False  # propagate exceptions (rollback semantics)

        return _Atomic()

    async def org_row_exists(self, table, pk_columns, pk):
        return pk in self.existing_org.get(table, set())

    async def shared_global_equivalent(self, table, row, pk_columns):
        pk = tuple(row.values.get(c) for c in pk_columns)
        if pk in self.present_shared.get(table, set()):
            return pk
        return None

    async def insert(self, table, values):
        self.inserts.append((table, dict(values)))
        if table in self.shared_tables:
            pk_cols = self.pk_columns_by_table.get(table, ("id",))
            pk = tuple(values.get(c) for c in pk_cols)
            self.present_shared.setdefault(table, set()).add(pk)

    async def update(self, table, pk_columns, pk, values):
        self.updates.append((table, pk))

    # Not part of the RestoreTarget ABC (the apply engine never deletes), kept
    # so the fake records any hypothetical delete for the zero-mutation assert.
    async def delete(self, table, pk_columns, pk):  # pragma: no cover - defensive
        self.deletes.append((table, pk))


# ---------------------------------------------------------------------------
# Generators — shared rows (some pre-existing), org rows, conflict policy.
# ---------------------------------------------------------------------------

_plan_ids = st.integers(min_value=0, max_value=999).map(lambda i: f"plan-{i}")
_widget_ids = st.integers(min_value=0, max_value=999).map(lambda i: f"widget-{i}")


@st.composite
def _scenarios(draw):
    # Distinct shared-global rows; a random subset pre-exists in the target.
    shared_ids = draw(st.lists(_plan_ids, min_size=0, max_size=8, unique=True))
    pre_existing_shared = {
        sid for sid in shared_ids if draw(st.booleans())
    }

    # Distinct org-scoped rows for the selected org, each optionally referencing
    # one of the shared rows; a random subset pre-exists (drives skip/overwrite).
    widget_ids = draw(st.lists(_widget_ids, min_size=0, max_size=8, unique=True))
    widgets: list[tuple[str, str | None]] = []
    pre_existing_widgets: set[tuple[Any, ...]] = set()
    for wid in widget_ids:
        if shared_ids:
            plan_ref = draw(st.one_of(st.none(), st.sampled_from(shared_ids)))
        else:
            plan_ref = None
        widgets.append((wid, plan_ref))
        if draw(st.booleans()):
            pre_existing_widgets.add((wid,))

    policy = draw(st.sampled_from(list(ConflictPolicy)))
    return shared_ids, pre_existing_shared, widgets, pre_existing_widgets, policy


def _build_dataset(shared_ids, widgets) -> ExtractedDataset:
    dataset = ExtractedDataset(org_id=SELECTED_ORG)
    for sid in shared_ids:
        dataset.add_row(
            ExtractedRow(
                table=SHARED_TABLE,
                values={"id": sid, "name": f"name-{sid}"},
                pk=(sid,),
                org_id=None,
            ),
            ("id",),
        )
    for wid, plan_ref in widgets:
        dataset.add_row(
            ExtractedRow(
                table=ORG_TABLE,
                values={
                    "id": wid,
                    "org_id": SELECTED_ORG,
                    "plan_id": plan_ref,
                    "label": f"label-{wid}",
                },
                pk=(wid,),
                org_id=SELECTED_ORG,
            ),
            ("id",),
        )
    return dataset


# ---------------------------------------------------------------------------
# Property 9: Shared-global rows are ensured-exists, never mutated.
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(scenario=_scenarios())
def test_shared_global_rows_are_ensured_exists_never_mutated(scenario):
    """Absent shared rows inserted once; present shared rows never mutated.

    Holds under every conflict policy (the policy governs org-scoped rows only).

    **Validates: Requirements 14.6, 14.7**
    """
    shared_ids, pre_existing_shared, widgets, pre_existing_widgets, policy = scenario

    target = FakeRestoreTarget(
        present_shared={SHARED_TABLE: {(sid,) for sid in pre_existing_shared}},
        existing_org={ORG_TABLE: set(pre_existing_widgets)},
        pk_columns_by_table={SHARED_TABLE: ("id",), ORG_TABLE: ("id",)},
        shared_tables={SHARED_TABLE},
    )
    schema = SchemaModel(metadata=_METADATA)
    engine = PerOrgApplyEngine(schema, target)
    dataset = _build_dataset(shared_ids, widgets)

    stats = asyncio.run(engine.apply(dataset, SELECTED_ORG, policy))

    # (1) No update or delete EVER targets a shared-global table (zero mutation).
    assert all(t != SHARED_TABLE for t, _pk in target.updates)
    assert all(t != SHARED_TABLE for t, _pk in target.deletes)

    # (2) Inserts into the shared table, grouped by primary key.
    shared_insert_counts = Counter(
        vals["id"] for t, vals in target.inserts if t == SHARED_TABLE
    )
    for sid in shared_ids:
        if sid in pre_existing_shared:
            # Already-present shared row: never inserted (ensure-exists no-op).
            assert shared_insert_counts[sid] == 0, (
                f"pre-existing shared row {sid!r} must not be re-inserted"
            )
        else:
            # Absent shared row: inserted exactly once.
            assert shared_insert_counts[sid] == 1, (
                f"absent shared row {sid!r} must be inserted exactly once"
            )

    # (3) No insert ever targets a pre-existing shared PK.
    inserted_shared_pks = {
        vals["id"] for t, vals in target.inserts if t == SHARED_TABLE
    }
    assert inserted_shared_pks.isdisjoint(pre_existing_shared)

    # (4) Stats agree with the ensure-exists accounting.
    absent = [s for s in shared_ids if s not in pre_existing_shared]
    present = [s for s in shared_ids if s in pre_existing_shared]
    assert stats.shared_rows_inserted == len(absent)
    assert stats.shared_rows_existing == len(present)
