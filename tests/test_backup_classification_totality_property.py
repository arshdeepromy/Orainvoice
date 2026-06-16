"""Property-based test: row classification is total and deterministic.

# Feature: cloud-backup-restore, Property 10: Row classification is total and deterministic

**Validates: Requirements 14.7**

The per-organisation restore (Req 14.7) leans on the row classifier
(``app/modules/backup_restore/restore/classifier.py``) to decide, for every
table/row in the live schema, whether it is org-scoped tenant data or
shared/global reference data. For that decision to be safe it must be:

* **Total** — for *every* classifiable table (every table on the live
  ``Base.metadata`` except the excluded node-local tables) and *any* row
  ``org_id`` value (``None`` or a UUID), ``classify_row`` returns exactly one of
  the two ``RowClass`` members and never raises. Likewise ``classify_table``
  returns exactly one ``TableClass`` for every table.
* **Deterministic** — repeated calls with the same inputs return the same
  result, with no dependence on external/mutable state.

Excluded node-local tables (``ha_config``, ``ha_event_log``, ``error_log``,
``audit_log``) have no per-row class: ``classify_row`` must raise ``ValueError``
for them, consistently across repeated calls.

This is a pure metadata classification — no database or storage is involved.
Table names are drawn from the live ``classifiable_tables()`` and ``org_id``
values from ``None | uuid``.
"""

from __future__ import annotations

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.restore.classifier import (
    EXCLUDED_TABLES,
    RowClass,
    TableClass,
    classifiable_tables,
    classify_row,
    classify_table,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory classification.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# The classifiable tables over the live Base.metadata (computed once — the
# metadata is static for the process). Sampling from this exercises the real
# ~132-table schema rather than synthetic names.
_CLASSIFIABLE_TABLES = classifiable_tables()

# org_id values a row may carry: NULL (shared/global hybrid entry) or a UUID
# (an org-scoped tenant row).
org_ids = st.one_of(st.none(), st.uuids())


# ---------------------------------------------------------------------------
# Property 10: Row classification is total and deterministic
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(table_name=st.sampled_from(_CLASSIFIABLE_TABLES), org_id=org_ids)
def test_classify_row_is_total_and_deterministic(table_name: str, org_id):
    """classify_row returns exactly one RowClass and is stable across calls.

    **Validates: Requirements 14.7**
    """
    # Total: never raises for a classifiable (non-excluded) table, and the
    # result is always a member of the two-element RowClass codomain.
    result = classify_row(table_name, org_id)
    assert isinstance(result, RowClass)
    assert result in (RowClass.ORG_SCOPED, RowClass.SHARED_GLOBAL)

    # Deterministic: a second call with identical inputs yields the same class.
    again = classify_row(table_name, org_id)
    assert again == result


@PBT_SETTINGS
@given(table_name=st.sampled_from(_CLASSIFIABLE_TABLES), org_id=org_ids)
def test_classify_table_is_total_and_deterministic(table_name: str, org_id):
    """classify_table returns exactly one TableClass and is stable across calls.

    **Validates: Requirements 14.7**
    """
    result = classify_table(table_name)
    assert isinstance(result, TableClass)
    # A classifiable table is never EXCLUDED (exclusions are filtered out).
    assert result in (
        TableClass.ORG_SCOPED,
        TableClass.SHARED_GLOBAL,
        TableClass.HYBRID,
    )

    again = classify_table(table_name)
    assert again == result


@PBT_SETTINGS
@given(table_name=st.sampled_from(sorted(EXCLUDED_TABLES)), org_id=org_ids)
def test_classify_row_raises_consistently_for_excluded_tables(table_name: str, org_id):
    """Excluded node-local tables have no per-row class — classify_row raises.

    The ValueError is raised consistently regardless of the row's org_id and
    across repeated calls (determinism of the failure mode).

    **Validates: Requirements 14.7**
    """
    for _ in range(2):
        raised = False
        try:
            classify_row(table_name, org_id)
        except ValueError:
            raised = True
        assert raised, f"expected ValueError for excluded table {table_name!r}"

    # And the table itself classifies as EXCLUDED, deterministically.
    assert classify_table(table_name) is TableClass.EXCLUDED
    assert classify_table(table_name) is TableClass.EXCLUDED
