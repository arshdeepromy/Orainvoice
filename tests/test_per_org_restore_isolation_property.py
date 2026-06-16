"""Property-based test: a per-org restore touches no other organisation's rows.

# Feature: cloud-backup-restore, Property 8: Per-org restore touches no other organisation's rows

**Validates: Requirements 14.3, 22.2**

For any multi-org backup and any selected ``org_id``, every insert/update/delete
performed by :class:`PerOrgApplyEngine.apply` targets only Org_Scoped_Rows whose
``org_id`` equals the selection. No Org_Scoped_Row of a different organisation is
ever created, modified, or deleted (Req 14.3 cross-org prohibition / Req 22.2).

This property exercises the *pure* apply logic with every external dependency
mocked (project PBT rule — no DB / storage / filesystem):

* A small **synthetic SQLAlchemy ``MetaData``** with a couple of org-scoped
  tables (``syn_customers``, ``syn_invoices`` — non-nullable ``org_id``), a
  shared-global table (``syn_plans`` — no ``org_id`` column), and a hybrid table
  (``syn_bounced`` — nullable ``org_id``). Building :class:`SchemaModel` over this
  fixed metadata makes the org-scoped / shared-global / hybrid classification
  fully deterministic and independent of the live ~132-table schema.
* A **recording :class:`RestoreTarget` fake** that captures every insert/update
  it is asked to perform plus the org context it is set to — no real database.

Two complementary behaviours are asserted across generated datasets that mix the
selected org's rows with *other* organisations' rows:

1. **Confined writes.** When the working set is confined to the selected org
   (plus shared-global rows), the apply succeeds and *every* recorded write
   carries ``org_id`` either ``None`` (a shared-global row) or exactly the
   selected org — never a foreign org. ``set_org_context`` is set to the
   selected org.
2. **Cross-org abort.** When the working set contains *any* foreign-org
   Org_Scoped_Row, the apply raises :class:`RestoreApplyError` and records
   **zero** writes (and never sets the org context), so the target is untouched.

In both cases the invariant holds: the restore never touches a row owned by an
organisation other than the selection.
"""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Column, ForeignKey, MetaData, String, Table

from app.modules.backup_restore.restore.classifier import TableClass
from app.modules.backup_restore.restore.per_org_restore import (
    ConflictPolicy,
    ExtractedDataset,
    ExtractedRow,
    PerOrgApplyEngine,
    RestoreApplyError,
    RestoreTarget,
    SchemaModel,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

ORGS = ("org-A", "org-B", "org-C")


# ---------------------------------------------------------------------------
# Synthetic schema — deterministic classification (no live metadata)
# ---------------------------------------------------------------------------


def _build_synthetic_metadata() -> MetaData:
    """A tiny schema covering org-scoped, shared-global, and hybrid tables.

    * ``syn_customers`` / ``syn_invoices`` — non-nullable ``org_id`` → ORG_SCOPED.
    * ``syn_plans`` — no ``org_id`` column → SHARED_GLOBAL (rule-3 default).
    * ``syn_bounced`` — nullable ``org_id`` → HYBRID (per-row by ``org_id``).
    """
    md = MetaData()
    Table(
        "syn_customers",
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("name", String),
    )
    Table(
        "syn_invoices",
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=False),
        Column("customer_id", String, ForeignKey("syn_customers.id")),
    )
    Table(
        "syn_plans",
        md,
        Column("id", String, primary_key=True),
        Column("name", String),
    )
    Table(
        "syn_bounced",
        md,
        Column("id", String, primary_key=True),
        Column("org_id", String, nullable=True),
        Column("email", String),
    )
    return md


_METADATA = _build_synthetic_metadata()
_SCHEMA = SchemaModel(metadata=_METADATA)


# ---------------------------------------------------------------------------
# Recording RestoreTarget fake (in-memory; no DB)
# ---------------------------------------------------------------------------


class RecordingRestoreTarget(RestoreTarget):
    """Records every insert/update and the org context set on it."""

    def __init__(
        self,
        *,
        existing_org_pks: set[tuple[str, tuple]] | None = None,
        existing_shared: dict[tuple[str, tuple], tuple] | None = None,
    ) -> None:
        # ("insert"|"update", table, values) for every write requested.
        self.writes: list[tuple[str, str, dict]] = []
        self.org_context: list[str] = []
        self._existing_org = existing_org_pks or set()
        self._existing_shared = existing_shared or {}

    async def set_org_context(self, org_id: str) -> None:
        self.org_context.append(org_id)

    def atomic(self):
        target = self

        class _Ctx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False  # propagate any error (no rollback bookkeeping needed)

        return _Ctx()

    async def org_row_exists(self, table, pk_columns, pk) -> bool:
        return (table, tuple(pk)) in self._existing_org

    async def shared_global_equivalent(self, table, row, pk_columns):
        pk = tuple(row.values.get(c) for c in pk_columns)
        return self._existing_shared.get((table, pk))

    async def insert(self, table, values) -> None:
        self.writes.append(("insert", table, dict(values)))

    async def update(self, table, pk_columns, pk, values) -> None:
        self.writes.append(("update", table, dict(values)))


# ---------------------------------------------------------------------------
# Dataset strategy — mixes the selected org's rows with other orgs' rows
# ---------------------------------------------------------------------------


@st.composite
def datasets(draw):
    selected = draw(st.sampled_from(ORGS))
    policy = draw(st.sampled_from(list(ConflictPolicy)))
    # When True, seed the target so the selected org's rows already exist
    # (exercises OVERWRITE -> update and SKIP -> skip code paths).
    preexisting = draw(st.booleans())

    dataset = ExtractedDataset(org_id=selected)

    # Org-scoped customers (org_id may be any org, including foreign).
    cust_ids: list[str] = []
    for i in range(draw(st.integers(min_value=0, max_value=4))):
        org = draw(st.sampled_from(ORGS))
        cid = f"cust-{i}"
        cust_ids.append(cid)
        dataset.add_row(
            ExtractedRow("syn_customers", {"id": cid, "org_id": org, "name": f"c{i}"}, (cid,), org),
            ("id",),
        )

    # Org-scoped invoices (FK to a customer when one exists).
    for i in range(draw(st.integers(min_value=0, max_value=4))):
        org = draw(st.sampled_from(ORGS))
        iid = f"inv-{i}"
        customer_id = draw(st.sampled_from(cust_ids)) if cust_ids else None
        dataset.add_row(
            ExtractedRow(
                "syn_invoices",
                {"id": iid, "org_id": org, "customer_id": customer_id},
                (iid,),
                org,
            ),
            ("id",),
        )

    # Shared-global plans (no org_id at all).
    for i in range(draw(st.integers(min_value=0, max_value=3))):
        pid = f"plan-{i}"
        dataset.add_row(
            ExtractedRow("syn_plans", {"id": pid, "name": f"plan {i}"}, (pid,), None),
            ("id",),
        )

    # Hybrid bounced addresses (org_id None -> shared-global, else org-scoped).
    for i in range(draw(st.integers(min_value=0, max_value=3))):
        choice = draw(st.sampled_from((None,) + ORGS))
        bid = f"bounce-{i}"
        dataset.add_row(
            ExtractedRow(
                "syn_bounced",
                {"id": bid, "org_id": choice, "email": f"b{i}@example.com"},
                (bid,),
                choice,
            ),
            ("id",),
        )

    return selected, policy, preexisting, dataset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_org_scoped(row: ExtractedRow) -> bool:
    cls = _SCHEMA.classify(row.table)
    if cls is TableClass.ORG_SCOPED:
        return True
    if cls is TableClass.HYBRID:
        return row.org_id is not None
    return False


def _has_foreign_org_row(dataset: ExtractedDataset, selected: str) -> bool:
    return any(
        _row_org_scoped(row) and str(row.org_id) != selected
        for row in dataset.all_rows()
    )


def _write_org_id(values: dict):
    """The ``org_id`` recorded on a written row (None for shared-global rows)."""
    org = values.get("org_id")
    return None if org is None else str(org)


# ---------------------------------------------------------------------------
# Property 8: Per-org restore touches no other organisation's rows
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(case=datasets())
def test_per_org_restore_touches_no_other_org_rows(case):
    """Every write targets only the selected org (or a shared-global row).

    **Validates: Requirements 14.3, 22.2**
    """
    selected, policy, preexisting, dataset = case

    # Optionally pre-seed the target with the selected org's org-scoped rows so
    # OVERWRITE produces updates and SKIP produces skips (still selected-org).
    existing_org_pks: set[tuple[str, tuple]] = set()
    if preexisting:
        for row in dataset.all_rows():
            if _row_org_scoped(row) and str(row.org_id) == selected:
                existing_org_pks.add((row.table, row.pk))

    target = RecordingRestoreTarget(existing_org_pks=existing_org_pks)
    engine = PerOrgApplyEngine(_SCHEMA, target)

    has_foreign = _has_foreign_org_row(dataset, selected)

    if has_foreign:
        # Cross-org prohibition: abort with RestoreApplyError and zero writes,
        # without ever setting the org context (Req 14.3).
        raised = False
        try:
            asyncio.run(engine.apply(dataset, selected, policy))
        except RestoreApplyError:
            raised = True
        assert raised, "expected RestoreApplyError for a foreign-org row in the working set"
        assert target.writes == [], "no writes may occur when a cross-org row is present"
        assert target.org_context == [], "org context must not be set before the cross-org abort"
        return

    # Confined case: apply succeeds and every write is selected-org or shared.
    asyncio.run(engine.apply(dataset, selected, policy))

    # The target's RLS context was set to the selected org (Req 14.3 defence).
    assert target.org_context == [selected]

    for kind, table, values in target.writes:
        org = _write_org_id(values)
        # The core invariant: a write never carries a foreign org_id.
        assert org in (None, selected), (
            f"{kind} into {table!r} wrote org_id={org!r}; per-org restore is "
            f"confined to {selected!r} (Req 14.3/22.2)"
        )
        # Org-scoped tables must carry the selected org_id explicitly.
        if _SCHEMA.classify(table) is TableClass.ORG_SCOPED:
            assert org == selected
        # Plain shared-global tables never carry an org_id.
        if _SCHEMA.classify(table) is TableClass.SHARED_GLOBAL:
            assert org is None


if __name__ == "__main__":  # pragma: no cover
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
