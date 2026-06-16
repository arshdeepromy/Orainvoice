"""Property-based test: restore-as-new preserves referential integrity.

# Feature: cloud-backup-restore, Property 11: Restore-as-new preserves referential integrity with zero dangling references

**Validates: Requirements 14.6**

Under :class:`ConflictPolicy.RESTORE_AS_NEW` the per-organisation apply engine
(``app/modules/backup_restore/restore/per_org_restore.py``) mints a fresh
identifier for every restored Org_Scoped_Row (``_build_id_remap``) and rewrites
every *intra-org* foreign key to the newly-minted target id (``_rewrite_values``)
so referential integrity holds with **zero dangling references**. References to
Shared_Global_Rows are deliberately left untouched: they resolve to the
ensured-existing target row rather than minting a new shared row (Req 14.6).

This property drives the pure apply logic against a small synthetic schema and
fully-mocked seams:

* a synthetic :class:`SchemaModel` built from an ad-hoc SQLAlchemy
  ``MetaData`` with real ``ForeignKey`` edges — a parent/child pair of
  org-scoped tables (``child.parent_id -> parent.id``) plus a shared-global
  reference table (``child.plan_id -> subscription_plans.id``);
* an in-memory :class:`RestoreTarget` fake that records inserts/updates and
  answers ensure-exists queries from a configurable pre-existing shared set;
* a deterministic, collision-free ``id_factory``.

For every generated dataset of org-scoped parent/child rows (one org) plus
shared-global plan rows, applying with RESTORE_AS_NEW must satisfy:

1. **New identifiers** — every inserted Org_Scoped_Row carries a minted pk that
   differs from its original pk (the pk was remapped).
2. **Intra-org FK integrity** — every intra-org foreign key in an inserted row
   points to a pk that was *also inserted* (FK target set ⊆ inserted pk set);
   no dangling reference.
3. **Shared-global resolution** — every shared-global foreign key is unchanged
   (still the original plan id) and resolves to a shared row that exists in the
   target (either pre-existing/ensured or freshly inserted); pre-existing shared
   rows are never re-inserted.
4. **Zero dangling references** across the entire inserted set.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any, Mapping

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
# Hypothesis settings (min 100 iterations) — pure in-memory apply, no DB/IO.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

PARENT_TABLE = "parent_entities"
CHILD_TABLE = "child_entities"
SHARED_TABLE = "subscription_plans"  # enumerated Shared_Global allowlist table


# ---------------------------------------------------------------------------
# Synthetic schema with real FK edges (so SchemaModel.foreign_keys works)
# ---------------------------------------------------------------------------


def build_schema_metadata() -> MetaData:
    """Build an ad-hoc schema: org-scoped parent/child + a shared-global table.

    * ``parent_entities`` / ``child_entities`` carry a NON-NULL ``org_id`` →
      classified ORG_SCOPED.
    * ``child.parent_id`` is an intra-org FK to ``parent.id``.
    * ``subscription_plans`` has no ``org_id`` and is on the Shared_Global
      allowlist → classified SHARED_GLOBAL; ``child.plan_id`` references it.
    """
    md = MetaData()
    Table(
        SHARED_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("label", String),
    )
    Table(
        PARENT_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("name", String),
    )
    Table(
        CHILD_TABLE,
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("parent_id", String, ForeignKey(f"{PARENT_TABLE}.id")),
        Column("plan_id", String, ForeignKey(f"{SHARED_TABLE}.id")),
    )
    return md


# ---------------------------------------------------------------------------
# In-memory RestoreTarget fake — records writes, answers ensure-exists queries.
# ---------------------------------------------------------------------------


class _AtomicCtx:
    async def __aenter__(self) -> "_AtomicCtx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeRestoreTarget(RestoreTarget):
    """Records inserts/updates; resolves shared ensure-exists from a seeded set."""

    def __init__(self, preexisting_shared: set[tuple[Any, ...]]) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.updates: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.org_context: str | None = None
        self._preexisting_shared = preexisting_shared

    async def set_org_context(self, org_id: str) -> None:
        self.org_context = org_id

    def atomic(self) -> _AtomicCtx:
        return _AtomicCtx()

    async def org_row_exists(
        self, table: str, pk_columns: tuple[str, ...], pk: tuple[Any, ...]
    ) -> bool:
        # restore-as-new never consults this; target starts empty of org rows.
        return False

    async def shared_global_equivalent(
        self, table: str, row: ExtractedRow, pk_columns: tuple[str, ...]
    ) -> tuple[Any, ...] | None:
        pk = tuple(row.values.get(c) for c in pk_columns)
        return pk if pk in self._preexisting_shared else None

    async def insert(self, table: str, values: Mapping[str, Any]) -> None:
        self.inserts.append((table, dict(values)))

    async def update(
        self,
        table: str,
        pk_columns: tuple[str, ...],
        pk: tuple[Any, ...],
        values: Mapping[str, Any],
    ) -> None:
        self.updates.append((table, pk, dict(values)))


def make_id_factory():
    """A deterministic, collision-free id factory (``new-1``, ``new-2``, ...)."""
    counter = itertools.count(1)

    def factory(table: str) -> str:
        return f"new-{next(counter)}"

    return factory


# ---------------------------------------------------------------------------
# Dataset generator: one org's parent/child rows + shared-global plan rows.
# ---------------------------------------------------------------------------


@st.composite
def restore_as_new_dataset(draw):
    org_id = str(draw(st.uuids()))

    n_plans = draw(st.integers(min_value=1, max_value=4))
    plan_ids = [f"plan-{i}" for i in range(n_plans)]

    n_parents = draw(st.integers(min_value=1, max_value=5))
    parent_ids = [f"parent-{i}" for i in range(n_parents)]

    n_children = draw(st.integers(min_value=0, max_value=8))
    children = []
    for i in range(n_children):
        children.append(
            {
                "id": f"child-{i}",
                "parent_id": draw(st.sampled_from(parent_ids)),
                "plan_id": draw(st.sampled_from(plan_ids)),
            }
        )

    # A subset of the plans already exist in the target (ensure-exists path);
    # the rest must be inserted. Either way, all referenced plans end up present.
    preexisting = draw(
        st.lists(st.sampled_from(plan_ids), unique=True, max_size=n_plans)
    )

    return {
        "org_id": org_id,
        "plan_ids": plan_ids,
        "parent_ids": parent_ids,
        "children": children,
        "preexisting_plans": preexisting,
    }


def build_dataset(spec) -> ExtractedDataset:
    org_id = spec["org_id"]
    dataset = ExtractedDataset(org_id=org_id)
    for pid in spec["plan_ids"]:
        dataset.add_row(
            ExtractedRow(
                table=SHARED_TABLE,
                values={"id": pid, "label": f"label-{pid}"},
                pk=(pid,),
                org_id=None,
            ),
            ("id",),
        )
    for parent in spec["parent_ids"]:
        dataset.add_row(
            ExtractedRow(
                table=PARENT_TABLE,
                values={"id": parent, "org_id": org_id, "name": f"name-{parent}"},
                pk=(parent,),
                org_id=org_id,
            ),
            ("id",),
        )
    for child in spec["children"]:
        values = {
            "id": child["id"],
            "org_id": org_id,
            "parent_id": child["parent_id"],
            "plan_id": child["plan_id"],
        }
        dataset.add_row(
            ExtractedRow(
                table=CHILD_TABLE,
                values=values,
                pk=(child["id"],),
                org_id=org_id,
            ),
            ("id",),
        )
    return dataset


# ---------------------------------------------------------------------------
# Property 11: Restore-as-new preserves referential integrity (zero dangling).
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(spec=restore_as_new_dataset())
def test_restore_as_new_preserves_referential_integrity(spec):
    """Restore-as-new mints new pks, rewrites intra-org FKs, and leaves zero
    dangling references; shared-global references resolve to ensured rows.

    **Validates: Requirements 14.6**
    """
    schema = SchemaModel(metadata=build_schema_metadata())
    preexisting_shared = {(pid,) for pid in spec["preexisting_plans"]}
    target = FakeRestoreTarget(preexisting_shared)
    engine = PerOrgApplyEngine(schema, target, id_factory=make_id_factory())
    dataset = build_dataset(spec)

    stats = asyncio.run(
        engine.apply(dataset, spec["org_id"], ConflictPolicy.RESTORE_AS_NEW)
    )

    # Partition the recorded inserts by table.
    inserted_parent_pks: set[str] = set()
    inserted_child_rows: list[dict[str, Any]] = []
    inserted_plan_pks: set[str] = set()
    for table, values in target.inserts:
        if table == PARENT_TABLE:
            inserted_parent_pks.add(values["id"])
        elif table == CHILD_TABLE:
            inserted_child_rows.append(values)
        elif table == SHARED_TABLE:
            inserted_plan_pks.add(values["id"])

    original_org_pks = set(spec["parent_ids"]) | {c["id"] for c in spec["children"]}
    minted_ids = set(engine.id_remap.values())

    # Every org-scoped row in the dataset was inserted (restore-as-new inserts all).
    assert len(inserted_parent_pks) == len(spec["parent_ids"])
    assert len(inserted_child_rows) == len(spec["children"])

    # (1) New identifiers: every inserted org pk is minted and differs from the
    # original pk — nothing reuses an original identifier.
    inserted_org_pks = inserted_parent_pks | {v["id"] for v in inserted_child_rows}
    for pk in inserted_org_pks:
        assert pk in minted_ids, f"inserted pk {pk!r} was not a minted id"
        assert pk not in original_org_pks, f"inserted pk {pk!r} reused an original id"

    # (2) Intra-org FK integrity: every child's rewritten parent_id points to a
    # parent pk that was also inserted — FK target set ⊆ inserted parent pks.
    child_parent_targets = {v["parent_id"] for v in inserted_child_rows}
    assert child_parent_targets <= inserted_parent_pks
    for v in inserted_child_rows:
        assert v["parent_id"] in inserted_parent_pks, (
            f"dangling intra-org FK: child {v['id']!r} -> parent "
            f"{v['parent_id']!r} not in inserted parents"
        )

    # (3) Shared-global resolution: plan_id is UNCHANGED (an original plan id,
    # never minted) and resolves to a shared row present in the target (either
    # pre-existing/ensured or freshly inserted). Pre-existing shared rows are
    # never re-inserted.
    original_plan_ids = set(spec["plan_ids"])
    preexisting_plan_ids = set(spec["preexisting_plans"])
    shared_in_target = preexisting_plan_ids | inserted_plan_pks
    assert inserted_plan_pks.isdisjoint(preexisting_plan_ids), (
        "ensure-exists violated: a pre-existing shared row was re-inserted"
    )
    for v in inserted_child_rows:
        assert v["plan_id"] in original_plan_ids, (
            f"shared-global FK {v['plan_id']!r} was remapped (must stay unchanged)"
        )
        assert v["plan_id"] not in minted_ids
        assert v["plan_id"] in shared_in_target, (
            f"dangling shared-global FK: child {v['id']!r} -> plan "
            f"{v['plan_id']!r} not present in target"
        )

    # (4) Zero dangling references across the whole inserted set: every FK target
    # (intra-org or shared-global) resolves to a row present in the target.
    resolvable = inserted_org_pks | shared_in_target
    for v in inserted_child_rows:
        assert v["parent_id"] in resolvable
        assert v["plan_id"] in resolvable

    # Sanity on the engine's own accounting: one remap per inserted org row.
    assert stats.remapped_ids == len(inserted_org_pks)
    assert target.org_context == spec["org_id"]


# ---------------------------------------------------------------------------
# Focused unit example — a concrete parent/child/plan apply (mirrors Req 14.6).
# ---------------------------------------------------------------------------


def test_restore_as_new_concrete_example():
    """A small concrete dataset: new pks, rewritten parent FK, untouched plan FK."""
    schema = SchemaModel(metadata=build_schema_metadata())
    org_id = "11111111-1111-1111-1111-111111111111"
    # plan-0 already exists in the target (ensure-exists), plan-1 must be inserted.
    target = FakeRestoreTarget(preexisting_shared={("plan-0",)})
    engine = PerOrgApplyEngine(schema, target, id_factory=make_id_factory())

    dataset = ExtractedDataset(org_id=org_id)
    dataset.add_row(
        ExtractedRow(SHARED_TABLE, {"id": "plan-0", "label": "A"}, ("plan-0",), None),
        ("id",),
    )
    dataset.add_row(
        ExtractedRow(SHARED_TABLE, {"id": "plan-1", "label": "B"}, ("plan-1",), None),
        ("id",),
    )
    dataset.add_row(
        ExtractedRow(
            PARENT_TABLE, {"id": "p1", "org_id": org_id, "name": "P"}, ("p1",), org_id
        ),
        ("id",),
    )
    dataset.add_row(
        ExtractedRow(
            CHILD_TABLE,
            {"id": "c1", "org_id": org_id, "parent_id": "p1", "plan_id": "plan-0"},
            ("c1",),
            org_id,
        ),
        ("id",),
    )
    dataset.add_row(
        ExtractedRow(
            CHILD_TABLE,
            {"id": "c2", "org_id": org_id, "parent_id": "p1", "plan_id": "plan-1"},
            ("c2",),
            org_id,
        ),
        ("id",),
    )

    asyncio.run(engine.apply(dataset, org_id, ConflictPolicy.RESTORE_AS_NEW))

    inserts = {t: [] for t in (PARENT_TABLE, CHILD_TABLE, SHARED_TABLE)}
    for table, values in target.inserts:
        inserts[table].append(values)

    # plan-0 pre-existed → ensured, not inserted; plan-1 inserted unchanged.
    assert [v["id"] for v in inserts[SHARED_TABLE]] == ["plan-1"]

    parent_pk = inserts[PARENT_TABLE][0]["id"]
    assert parent_pk != "p1" and parent_pk.startswith("new-")

    for child in inserts[CHILD_TABLE]:
        assert child["id"].startswith("new-")  # minted child pk
        assert child["parent_id"] == parent_pk  # intra-org FK rewritten to new pk
        assert child["plan_id"] in {"plan-0", "plan-1"}  # shared FK unchanged
