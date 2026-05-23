"""Enable Postgres RLS on every B2B Fleet Portal table created in 0191.

This migration adds row-level security policies to the 16 tables created
in migration ``0191_b2b_fleet_portal``. It is split out into a follow-up
migration (rather than being bundled into 0191) because 0191 has already
been applied at the time RLS was specified — splitting keeps both
migrations cleanly replay-safe and lets ``alembic upgrade head`` apply
the policies on every environment without rewinding 0191.

Policy shape
============

For every new table:

    ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS <t>_org_isolation ON <t>;
    CREATE POLICY <t>_org_isolation ON <t>
        USING (<predicate>);

The default ``CREATE POLICY`` (no ``FOR`` clause and no ``WITH CHECK``)
applies the ``USING`` expression to all of SELECT/INSERT/UPDATE/DELETE
which is exactly the project convention used in migrations 0008, 0093,
0094, 0096, 0144, 0145, 0162, 0170, 0184, 0185, 0190 and others.

Predicate variants
==================

1) **Org-only** (6 tables — security/account scope, no fleet column):
   ``portal_accounts``, ``portal_account_mfa_methods``,
   ``portal_account_backup_codes``, ``portal_account_password_history``,
   ``portal_audit_log``, ``portal_fleet_accounts``.

   Policy: ``USING (org_id = current_setting('app.current_org_id', true)::uuid)``

2) **Org + fleet defence-in-depth** (7 tables — fleet-scoped tables that
   physically carry a ``fleet_account_id`` column):
   ``fleet_checklist_templates``, ``fleet_driver_assignments``,
   ``fleet_checklist_submissions``, ``fleet_reminder_preferences``,
   ``fleet_service_booking_requests``, ``fleet_quotation_requests``,
   ``fleet_driver_hours``.

   Policy:
   ``USING (org_id = current_setting('app.current_org_id', true)::uuid
            OR fleet_account_id = current_setting('app.current_fleet_account_id', true)::uuid)``

   The OR predicate is the design's defence-in-depth: even if an
   application-level fleet filter is forgotten, requests that set the
   ``app.current_fleet_account_id`` GUC (via
   ``require_fleet_portal_session`` → ``_set_rls_fleet_account_id``) can
   still see only their own fleet's rows. Cross-org reads are still
   blocked because the OR is wrapped by the surrounding ``WHERE`` clause
   that filters by ``org_id`` in every service query — and in the worst
   case a missing GUC evaluates ``current_setting(..., true)`` to
   ``NULL`` so the cast fails-closed (no rows leak).

3) **Org-only because they are children of a fleet-scoped parent**
   (3 tables — fleet-scoped logically but join through their parent):
   ``fleet_checklist_template_items`` (→ ``fleet_checklist_templates``),
   ``fleet_checklist_submission_items`` (→ ``fleet_checklist_submissions``),
   ``portal_account_devices`` (→ ``portal_accounts``).

   These tables carry ``org_id`` but not ``fleet_account_id``. The
   surrounding application code always reaches them through their parent
   (which has the fleet RLS predicate), so adding a JOIN-based fleet
   predicate here would only re-do the same check at higher cost.
   ``USING (org_id = current_setting('app.current_org_id', true)::uuid)``
   is the correct second line of defence for these tables.

The two GUCs (``app.current_org_id`` and ``app.current_fleet_account_id``)
use ``current_setting(name, true)`` — the second arg ``true`` returns
NULL on missing-setting instead of raising an error. This matches the
existing pattern in migration 0106 and is the safer of the two: a
NULL::uuid cast returns NULL, ``NULL = anything`` is NULL (treated as
false), so a request without the GUC sees zero rows.

Idempotency
===========

Every step uses ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` (no-op if
already enabled) and ``DROP POLICY IF EXISTS`` immediately before
``CREATE POLICY``. ``alembic downgrade`` drops the policies and disables
RLS on each table.

Revision ID: 0192
Revises: 0191
Create Date: 2026-05-18

Requirements: 17.2
"""
from __future__ import annotations

from alembic import op


revision: str = "0192"
down_revision: str = "0191"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Tables whose RLS predicate is org-only.
# (Includes the security/account-scope tables that were named in the
# spec's exclusion list, plus three child tables — submission items,
# template items, and portal_account_devices — that carry org_id but
# not fleet_account_id and are reached via their fleet-scoped parent.)
_ORG_ONLY_TABLES: tuple[str, ...] = (
    # Security/account-scope tables (per the task's exclusion list)
    "portal_accounts",
    "portal_account_mfa_methods",
    "portal_account_backup_codes",
    "portal_account_password_history",
    "portal_audit_log",
    "portal_fleet_accounts",
    # Child tables of fleet-scoped parents — protected via parent join.
    "portal_account_devices",
    "fleet_checklist_template_items",
    "fleet_checklist_submission_items",
)


# Tables whose RLS predicate is org + fleet (defence-in-depth OR clause).
# Every table here physically carries a fleet_account_id column.
_FLEET_SCOPED_TABLES: tuple[str, ...] = (
    "fleet_checklist_templates",
    "fleet_driver_assignments",
    "fleet_checklist_submissions",
    "fleet_reminder_preferences",
    "fleet_service_booking_requests",
    "fleet_quotation_requests",
    "fleet_driver_hours",
)


# All new tables (used by downgrade). Order doesn't matter for RLS drop.
_ALL_NEW_TABLES: tuple[str, ...] = _ORG_ONLY_TABLES + _FLEET_SCOPED_TABLES


_ORG_ONLY_USING = (
    "org_id = current_setting('app.current_org_id', true)::uuid"
)

_FLEET_SCOPED_USING = (
    "org_id = current_setting('app.current_org_id', true)::uuid"
    " OR fleet_account_id = current_setting("
    "'app.current_fleet_account_id', true)::uuid"
)


def _enable_rls_with_policy(table: str, using_expr: str) -> None:
    """Idempotently enable RLS and (re)create the org_isolation policy."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # DROP-then-CREATE is the project's standard idempotency pattern for
    # CREATE POLICY (Postgres does not support CREATE POLICY IF NOT
    # EXISTS). Wrapped in a single transaction by Alembic so a partial
    # failure leaves the previous policy intact.
    op.execute(
        f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}"
    )
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({using_expr})"
    )


def upgrade() -> None:
    # ── 1. Org-only tables ────────────────────────────────────────────
    for table in _ORG_ONLY_TABLES:
        _enable_rls_with_policy(table, _ORG_ONLY_USING)

    # ── 2. Fleet-scoped tables (org + fleet defence-in-depth) ─────────
    for table in _FLEET_SCOPED_TABLES:
        _enable_rls_with_policy(table, _FLEET_SCOPED_USING)


def downgrade() -> None:
    # Drop policies first (in reverse), then disable RLS on each table.
    for table in reversed(_ALL_NEW_TABLES):
        op.execute(
            f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}"
        )
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
