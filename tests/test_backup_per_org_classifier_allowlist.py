"""Unit test — Shared_Global allowlist against live model metadata (task 10.3).

Spec: cloud-backup-restore, Requirement 14.7 (per-organisation restore must
treat shared/global reference data as Shared_Global_Rows — read-and-ensure-exists
rather than org-scoped tenant data).

These are example-based UNIT tests (the totality/determinism property is covered
separately by task 10.2). They pin the classifier against the *live*
``Base.metadata`` so that:

  * every enumerated ``SHARED_GLOBAL_TABLES`` entry that exists in the live
    schema classifies as ``TableClass.SHARED_GLOBAL`` and carries no ``org_id``
    column (the reason it is shared) — "pinned shared tables stay shared";
  * a newly-added global table with no ``org_id`` defaults to
    ``TableClass.SHARED_GLOBAL`` (simulated with an ad-hoc SQLAlchemy table in a
    throwaway ``MetaData``);
  * a non-nullable ``org_id`` table classifies ``ORG_SCOPED`` and a nullable
    ``org_id`` table classifies ``HYBRID``;
  * the node-local ``EXCLUDED_TABLES`` classify ``EXCLUDED``.

Validates: Requirements 14.7
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from app.core.database import Base
from app.modules.backup_restore.restore.classifier import (
    EXCLUDED_TABLES,
    ORG_ID_COLUMN,
    SHARED_GLOBAL_TABLES,
    TableClass,
    classify_table,
    ensure_all_models_imported,
    org_id_is_nullable,
)


@pytest.fixture(scope="module")
def live_metadata() -> MetaData:
    """The full live ``Base.metadata`` with every model module imported."""
    ensure_all_models_imported()
    return Base.metadata


# ---------------------------------------------------------------------------
# (1) Pinned allowlist tables stay Shared_Global against the live metadata
# ---------------------------------------------------------------------------


class TestPinnedAllowlistAgainstLiveMetadata:
    """Every enumerated shared table present in the live schema stays shared."""

    def test_at_least_one_allowlist_table_is_present(self, live_metadata):
        # Guards against the whole suite silently passing if model discovery
        # failed to register any tables.
        present = [t for t in SHARED_GLOBAL_TABLES if t in live_metadata.tables]
        assert present, (
            "No SHARED_GLOBAL_TABLES entries found in live Base.metadata — "
            "model discovery likely failed."
        )

    def test_pinned_shared_tables_classify_shared_global(self, live_metadata):
        for table_name in sorted(SHARED_GLOBAL_TABLES):
            if table_name not in live_metadata.tables:
                # Allowlist entry not (yet) in the live schema — skip gracefully.
                pytest.skip(f"allowlist table {table_name!r} not in live metadata")
            assert classify_table(table_name) is TableClass.SHARED_GLOBAL, (
                f"pinned shared table {table_name!r} should classify SHARED_GLOBAL"
            )

    def test_pinned_shared_tables_carry_no_org_id(self, live_metadata):
        """Shared tables are shared *because* they have no ``org_id`` column.

        If one ever grows an ``org_id`` the allowlist pin would mask the change,
        so assert the absence explicitly (``org_id_is_nullable`` returns ``None``
        when there is no ``org_id`` column).
        """
        for table_name in sorted(SHARED_GLOBAL_TABLES):
            table = live_metadata.tables.get(table_name)
            if table is None:
                pytest.skip(f"allowlist table {table_name!r} not in live metadata")
            assert ORG_ID_COLUMN not in table.columns, (
                f"shared table {table_name!r} unexpectedly has an {ORG_ID_COLUMN!r} "
                "column — it would classify ORG_SCOPED/HYBRID, not SHARED_GLOBAL"
            )
            assert org_id_is_nullable(table_name) is None


# ---------------------------------------------------------------------------
# (2) A newly-added global table with NO org_id defaults to Shared_Global
# ---------------------------------------------------------------------------


class TestNewGlobalTableDefaultsShared:
    """A brand-new table with no ``org_id`` falls through to the default rule."""

    def test_new_table_without_org_id_defaults_shared_global(self):
        md = MetaData()
        Table(
            "brand_new_reference_table",
            md,
            Column("id", Integer, primary_key=True),
            Column("label", String(50)),
        )
        assert (
            classify_table("brand_new_reference_table", metadata=md)
            is TableClass.SHARED_GLOBAL
        )

    def test_unknown_table_defaults_shared_global(self):
        # A name not in the metadata at all has "no org_id column" and so also
        # falls through to the SHARED_GLOBAL default.
        md = MetaData()
        assert (
            classify_table("never_heard_of_this_table", metadata=md)
            is TableClass.SHARED_GLOBAL
        )


# ---------------------------------------------------------------------------
# (3) org_id column drives ORG_SCOPED (non-nullable) vs HYBRID (nullable)
# ---------------------------------------------------------------------------


class TestOrgIdColumnClassification:
    """The presence and nullability of ``org_id`` decides the table class."""

    def test_non_nullable_org_id_classifies_org_scoped(self):
        md = MetaData()
        Table(
            "synthetic_org_scoped",
            md,
            Column("id", Integer, primary_key=True),
            Column(ORG_ID_COLUMN, Integer, nullable=False),
        )
        assert (
            classify_table("synthetic_org_scoped", metadata=md)
            is TableClass.ORG_SCOPED
        )
        assert org_id_is_nullable("synthetic_org_scoped", metadata=md) is False

    def test_nullable_org_id_classifies_hybrid(self):
        md = MetaData()
        Table(
            "synthetic_hybrid",
            md,
            Column("id", Integer, primary_key=True),
            Column(ORG_ID_COLUMN, Integer, nullable=True),
        )
        assert classify_table("synthetic_hybrid", metadata=md) is TableClass.HYBRID
        assert org_id_is_nullable("synthetic_hybrid", metadata=md) is True


# ---------------------------------------------------------------------------
# (4) Node-local excluded tables classify EXCLUDED
# ---------------------------------------------------------------------------


class TestExcludedTables:
    """Node-local / non-replicated tables are excluded ahead of every rule."""

    @pytest.mark.parametrize(
        "table_name",
        sorted({"ha_config", "ha_event_log", "error_log", "audit_log"}),
    )
    def test_excluded_tables_classify_excluded(self, table_name):
        assert table_name in EXCLUDED_TABLES
        # Excluded check precedes the rules, so it holds against the live
        # metadata (default) regardless of any org_id column the table carries.
        assert classify_table(table_name) is TableClass.EXCLUDED

    def test_exclusion_beats_nullable_org_id(self):
        """``audit_log`` has a nullable ``org_id`` but exclusion wins over HYBRID."""
        md = MetaData()
        Table(
            "audit_log",  # name matches an EXCLUDED entry
            md,
            Column("id", Integer, primary_key=True),
            Column(ORG_ID_COLUMN, Integer, nullable=True),
        )
        assert classify_table("audit_log", metadata=md) is TableClass.EXCLUDED
