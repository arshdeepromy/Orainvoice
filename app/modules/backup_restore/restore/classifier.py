"""Row classifier — Org_Scoped_Row vs Shared_Global_Row (cloud-backup-restore Req 14.7).

Per-organisation restore (Requirement 14) must reconcile two requirements that
pull in opposite directions:

* **Req 14.3** forbids a single-organisation restore from inserting, updating,
  or deleting any row that belongs to a *different* organisation.
* **Req 14.7** requires the restore to transitively pull in rows the restored
  organisation's rows reference — including shared/global platform reference
  data (subscription plans, the global vehicle/CarJam database, feature flags,
  …) that is owned by no single organisation.

The resolution (design.md "Design Decision — Org-scoped vs shared/global
reference data", Open Question 4) is to **classify every row** as one of two
classes and apply different rules to each:

* **Org_Scoped_Row** — tenant data owned by exactly one organisation, identified
  by carrying an ``org_id``. The cross-org prohibition binds these rows: a
  per-org restore touches only rows whose ``org_id`` equals the selected org.
* **Shared_Global_Row** — platform/reference data shared by every organisation.
  Handled by **read-and-ensure-exists**: inserted only if no equivalent row
  already exists in the target, and *never* modified or deleted.

The classifier is deliberately a small, pure, side-effect-free decision function
so it can be exhaustively property-tested (Property 10 — *Row classification is
total and deterministic*): for any table/row in the schema it returns exactly
one class, and the result is stable across runs.

Classification rules — **three ordered rules**, first match wins (design.md
"Enumerated Shared_Global_Row tables"):

1. **Nullable-``org_id`` per-row hybrid.** A table whose ``org_id`` column is
   *nullable* (e.g. ``bounced_addresses``) is classified **per row**: a row with
   a non-NULL ``org_id`` is an Org_Scoped_Row, a row with ``org_id IS NULL`` is a
   Shared_Global_Row (the platform-wide blocklist). Evaluated first so hybrid
   tables are not mis-swept by rule 2 or 3.
2. **Non-nullable ``org_id`` column → Org_Scoped.** A table with a ``NOT NULL``
   ``org_id`` column is org-scoped tenant data; every row is an Org_Scoped_Row.
3. **Enumerated Shared_Global allowlist / default → Shared_Global.** A curated
   allowlist of platform/reference tables, plus the default for any table that
   has **no** ``org_id`` column at all, are Shared_Global_Rows.

**Excluded tables.** Node-local / non-replicated platform tables —
``ha_config``, ``ha_event_log`` (each node keeps its own row; never replicated),
``error_log``, and ``audit_log`` (append-only, nullable ``org_id``) — are
*excluded from per-org restore entirely*: a per-org restore never inserts,
updates, or deletes them. The exclusion is checked **before** the three rules so
that ``audit_log`` (which has a nullable ``org_id`` and would otherwise match the
hybrid rule) is not mistaken for restorable hybrid data.

Column nullability is read from SQLAlchemy model metadata (``Base.metadata``),
so the classifier tracks the live schema across all ~132 tables. The allowlist
is unit-tested against that live metadata (task 10.3) so a newly-added global
table with no ``org_id`` is caught by the default and a deliberately-shared table
stays pinned.
"""

from __future__ import annotations

import enum
import importlib
import logging
import pkgutil
from typing import Optional

from sqlalchemy import Column, MetaData

from app.core.database import Base

logger = logging.getLogger(__name__)

# Name of the tenant-identifying column. A row/table carries tenant identity
# exactly when it has a column with this name (design.md glossary
# "Org_Scoped_Row").
ORG_ID_COLUMN = "org_id"


class RowClass(enum.Enum):
    """The class of a single row for per-organisation restore (Req 14.7).

    Every restorable row is exactly one of these two classes — the classifier
    is total over the two-element codomain (Property 10).
    """

    ORG_SCOPED = "org_scoped"
    """Tenant data owned by one organisation; confined by the Req 14.3
    cross-org prohibition to the selected org."""

    SHARED_GLOBAL = "shared_global"
    """Shared/global platform reference data; handled by read-and-ensure-exists
    (insert-if-absent, never modify or delete) per Req 14.7."""


class TableClass(enum.Enum):
    """The classification of a whole table for per-organisation restore.

    A table is one of: org-scoped (every row Org_Scoped), shared-global (every
    row Shared_Global), hybrid (classified per row by its ``org_id``), or
    excluded (node-local / non-replicated — never touched by a per-org restore).
    """

    ORG_SCOPED = "org_scoped"
    """Non-nullable ``org_id`` column — every row is an Org_Scoped_Row (rule 2)."""

    SHARED_GLOBAL = "shared_global"
    """Allowlisted reference table, or a table with no ``org_id`` — every row is
    a Shared_Global_Row (rule 3 / default)."""

    HYBRID = "hybrid"
    """Nullable ``org_id`` column — each row is classified individually by
    whether its ``org_id`` is set (rule 1)."""

    EXCLUDED = "excluded"
    """Node-local / non-replicated table — never inserted, updated, or deleted
    by a per-org restore."""


# ---------------------------------------------------------------------------
# Constant table sets (the authoritative classifier constants — task 10.1)
# ---------------------------------------------------------------------------

# Node-local / non-replicated platform tables excluded from per-org restore
# entirely (design.md "Node-local / non-replicated platform tables"). Checked
# before the three ordered rules so the nullable-``org_id`` ``audit_log`` is not
# treated as restorable hybrid data.
EXCLUDED_TABLES: frozenset[str] = frozenset(
    {
        "ha_config",       # per-node HA configuration — never replicated
        "ha_event_log",    # per-node HA event history — never replicated
        "error_log",       # platform error log — node-local operational data
        "audit_log",       # append-only audit trail (nullable org_id) — excluded
    }
)

# Enumerated Shared_Global allowlist (design.md "Enumerated Shared_Global_Row
# tables"): platform/reference tables shared by every organisation. These have
# no ``org_id`` column and are treated as Shared_Global_Rows (rule 3).
#
# NOTE: ``bounced_addresses`` is intentionally NOT listed here. Although the
# design table mentions it, it has a *nullable* ``org_id`` and is therefore
# handled per-row by the hybrid rule (rule 1, evaluated first) — its NULL rows
# are the platform-wide blocklist (Shared_Global) and its non-NULL rows are
# org-scoped tenant data.
SHARED_GLOBAL_TABLES: frozenset[str] = frozenset(
    {
        "subscription_plans",   # platform plan catalogue
        "global_vehicles",      # shared CarJam/vehicle DB across all orgs
        "module_registry",      # global catalogue of available modules
        "feature_flags",        # platform feature flags + targeting
        "platform_branding",    # platform branding (BYTEA travels in the dump)
        "platform_settings",    # global platform settings
        "trade_families",       # trade-family reference data
        "public_holidays",      # NZ/AU public-holiday reference calendar
        "exchange_rates",       # currency reference rates (org-independent)
        "integration_configs",  # global integration credentials (encrypted)
        "email_providers",      # platform email-provider config
    }
)


# ---------------------------------------------------------------------------
# Metadata access
# ---------------------------------------------------------------------------

# Guard so the (relatively expensive) model-discovery import walk runs at most
# once per process.
_MODELS_LOADED = False


def ensure_all_models_imported() -> None:
    """Import every ``app.modules.*`` module so ``Base.metadata`` is complete.

    SQLAlchemy only registers a table on ``Base.metadata`` once the module
    defining its model class has been imported. In the running app most models
    are imported transitively at startup, but not all — some model classes live
    in modules whose names are neither ``models`` nor ``*_models`` (e.g.
    ``timesheets.pay_cycles``), so they never register unless explicitly
    imported. A missing table breaks the restore in two ways: the classifier
    cannot see it, and resolving any foreign key that *targets* it raises
    ``NoReferencedTableError`` mid-apply.

    To guarantee completeness this walks the entire ``app.modules`` package tree
    and imports every module (recursing into sub-packages), guarding each import
    individually so one missing/broken module never prevents the rest from
    registering. Idempotent and safe to call repeatedly; within the running app
    the imports are already cached so it is effectively free.
    """
    global _MODELS_LOADED
    if _MODELS_LOADED:
        return

    import app.modules as modules_pkg

    def _import_all(package) -> None:
        for info in pkgutil.iter_modules(package.__path__):
            full_name = f"{package.__name__}.{info.name}"
            try:
                module = importlib.import_module(full_name)
            except Exception:  # pragma: no cover - defensive: skip unimportable
                logger.debug(
                    "classifier: could not import %s", full_name, exc_info=True
                )
                continue
            if info.ispkg:
                _import_all(module)

    _import_all(modules_pkg)
    _MODELS_LOADED = True


def _resolve_metadata(metadata: Optional[MetaData]) -> MetaData:
    """Return the metadata to classify against, defaulting to ``Base.metadata``.

    When defaulting, ensures all model modules are imported so the metadata
    reflects the full ~132-table schema rather than whatever happened to be
    imported by the caller.
    """
    if metadata is not None:
        return metadata
    ensure_all_models_imported()
    return Base.metadata


def _org_id_column(table_name: str, metadata: Optional[MetaData]) -> Column | None:
    """Return the ``org_id`` :class:`~sqlalchemy.Column` for *table_name*, or None.

    Returns ``None`` both when the table is unknown to the metadata and when it
    has no ``org_id`` column — callers treat both as "no tenant column".
    """
    md = _resolve_metadata(metadata)
    table = md.tables.get(table_name)
    if table is None:
        return None
    return table.columns.get(ORG_ID_COLUMN)


def org_id_is_nullable(table_name: str, metadata: Optional[MetaData] = None) -> bool | None:
    """Whether *table_name*'s ``org_id`` column is nullable.

    Returns ``True``/``False`` for the column's nullability, or ``None`` when the
    table has no ``org_id`` column (or is unknown to the metadata).
    """
    col = _org_id_column(table_name, metadata)
    if col is None:
        return None
    return bool(col.nullable)


def is_excluded(table_name: str) -> bool:
    """Whether *table_name* is a node-local / non-replicated excluded table."""
    return table_name in EXCLUDED_TABLES


# ---------------------------------------------------------------------------
# Classification (the three ordered rules)
# ---------------------------------------------------------------------------


def classify_table(table_name: str, metadata: Optional[MetaData] = None) -> TableClass:
    """Classify a whole table by the three ordered rules (first match wins).

    Precedence (design.md "Enumerated Shared_Global_Row tables"):

    0. **Excluded** — node-local / non-replicated tables are excluded *before*
       the rules so the nullable-``org_id`` ``audit_log`` is not mistaken for a
       restorable hybrid table.
    1. **Nullable ``org_id`` → HYBRID** — classified per row at apply time.
    2. **Non-nullable ``org_id`` → ORG_SCOPED.**
    3. **Allowlist / no ``org_id`` → SHARED_GLOBAL.**

    Total and deterministic: every table maps to exactly one
    :class:`TableClass`, with no dependence on external state.
    """
    # Rule 0 — exclusions take precedence over every rule below.
    if table_name in EXCLUDED_TABLES:
        return TableClass.EXCLUDED

    col = _org_id_column(table_name, metadata)

    # Rule 1 — nullable org_id hybrid (evaluated first).
    if col is not None and col.nullable:
        return TableClass.HYBRID

    # Rule 2 — non-nullable org_id column → org-scoped tenant data.
    if col is not None:  # col present and NOT nullable
        return TableClass.ORG_SCOPED

    # Rule 3 — enumerated allowlist, and the default for any table with no
    # org_id column, are shared/global reference data.
    return TableClass.SHARED_GLOBAL


def classify_row(
    table_name: str,
    org_id: object | None,
    metadata: Optional[MetaData] = None,
) -> RowClass:
    """Classify a single row given its table and the row's ``org_id`` value.

    Returns exactly one of :attr:`RowClass.ORG_SCOPED` /
    :attr:`RowClass.SHARED_GLOBAL` (Property 10 — total over the two-element
    codomain). The decision follows the table's class:

    * **ORG_SCOPED table** → the row is an Org_Scoped_Row.
    * **SHARED_GLOBAL table** → the row is a Shared_Global_Row.
    * **HYBRID table** → decided per row: a non-NULL ``org_id`` is Org_Scoped, a
      NULL ``org_id`` is Shared_Global (the platform-wide entry).

    Raises:
        ValueError: if *table_name* is an excluded node-local table — a per-org
            restore must never apply such rows, so asking for a row class is a
            programming error rather than a data class.
    """
    table_class = classify_table(table_name, metadata)

    if table_class is TableClass.EXCLUDED:
        raise ValueError(
            f"Table {table_name!r} is node-local / non-replicated and is excluded "
            "from per-org restore; it has no per-row class."
        )

    if table_class is TableClass.ORG_SCOPED:
        return RowClass.ORG_SCOPED

    if table_class is TableClass.SHARED_GLOBAL:
        return RowClass.SHARED_GLOBAL

    # HYBRID — decide by this row's org_id (rule 1, row level).
    if org_id is None:
        return RowClass.SHARED_GLOBAL
    return RowClass.ORG_SCOPED


def classifiable_tables(metadata: Optional[MetaData] = None) -> list[str]:
    """Return the sorted names of all tables a per-org restore may classify.

    Every table known to the metadata except the excluded node-local tables.
    Sorted for deterministic iteration (useful for restore ordering and tests).
    """
    md = _resolve_metadata(metadata)
    return sorted(name for name in md.tables.keys() if name not in EXCLUDED_TABLES)
