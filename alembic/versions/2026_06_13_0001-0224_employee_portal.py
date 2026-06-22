"""Organisation Employee Portal — slug column, portal tables, staff dedup + uniqueness.

Adds the schema prerequisites for the optional, org-branded Employee Portal
(a deliberate near-clone of the B2B Fleet Portal):

  1. ``organisations.slug`` — a nullable ``varchar(63)`` column (no backfill,
     R17.1) plus a global, case-insensitive unique functional index
     ``uq_organisations_slug_lower`` on ``lower(slug)`` (R2.5, R2.8).
  2. Three new org-scoped tables mirroring the fleet portal's security model:
     ``employee_portal_users`` (credential + lockout + invite/reset tokens),
     ``employee_portal_sessions`` (HttpOnly-cookie sessions), and
     ``employee_portal_audit_log`` (auth/security event log, nullable
     ``portal_user_id`` so unknown-email login attempts are recorded without
     revealing existence — R16.6). Each carries RLS ``ENABLE`` (not FORCE) with
     the standard ``tenant_isolation`` policy, identical to the fleet/roster
     tables.
  3. A one-time, **non-destructive** de-duplication of existing **active** staff
     (R1.7): for each org, every group of active staff sharing a normalised
     email (``lower(btrim(email))``) or a non-empty ``employee_id`` is resolved
     by keeping the survivor (earliest ``created_at``; tie → smallest ``id``)
     and flipping the remaining group members to ``is_active = false``. It
     **only flips the flag** — it never deletes and never touches
     already-inactive rows. One ``audit_log`` row is written per resolved group
     capturing the survivor id and each de-duplicated id (R1.8).
  4. A **pre-constraint guard** (R17.7): after the dedup, the migration re-scans
     for any remaining active duplicate group and ``raise``s to halt **before**
     creating the staff unique indexes, leaving data unchanged so the
     constraint is never enforced over dirty data.
  5. The staff partial unique indexes ``uq_staff_active_email_per_org`` and
     ``uq_staff_active_employee_id_per_org`` (R1.2, R1.3, R1.6), built
     CONCURRENTLY only after the guard passes.

Per the **database-migration-checklist** steering, the migration is split into
two phases:

  - A **transactional phase** — the catalogue-only column add, the
    ``CREATE TABLE`` + RLS statements, the dedup data step, and the guard. The
    dedup commits (and so is auditable) when the trailing autocommit block opens
    its boundary.
  - A trailing **autocommit phase** (runs LAST) — **every** ``CONCURRENTLY``
    index, wrapped in ``op.get_context().autocommit_block()`` because Postgres
    rejects ``CREATE/DROP INDEX CONCURRENTLY`` inside a transaction. Putting all
    index DDL after the guard means a guard ``raise`` halts the migration before
    any unique index is ever attempted over dirty data.

Every statement keeps ``IF NOT EXISTS`` / ``IF EXISTS`` / ``information_schema``
guards so the migration is re-runnable: a re-run (or a retry after a failed
CONCURRENTLY build that left an INVALID index behind) is a safe no-op (R17.6).
The dedup step is naturally idempotent — a second run finds no active duplicate
groups and changes nothing.

Never uses ``op.create_index`` / plain ``CREATE INDEX`` on the existing
``organisations`` / ``staff_members`` tables (they would take an
``ACCESS EXCLUSIVE`` lock). Mirrors the canonical autocommit template
``alembic/versions/2026_05_30_2300-0202_add_perf_indexes.py``.

Refs: requirements R1.1, R1.2, R1.3, R1.6, R1.7, R1.8, R2.5, R2.8, R5.2, R16.3,
       R17.1, R17.5, R17.6, R17.7.

Revision ID: 0224
Revises: 0223
Create Date: 2026-06-13
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from alembic import op
from sqlalchemy import text

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0224"
down_revision: str = "0223"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Autocommit-phase index DDL (runs LAST, outside any transaction).
#
# ALL CONCURRENTLY index builds for this revision live here so that the
# transactional-phase guard (Step 4) can `raise` and halt BEFORE any unique
# index is created over dirty data. Each statement is independent; ordering
# only affects log readability. Every statement is idempotent via
# IF NOT EXISTS so an interrupted (INVALID) build is safely retryable.
# ---------------------------------------------------------------------------
_UPGRADE_INDEXES: list[tuple[str, str]] = [
    # Step 1 — global, case-insensitive org-slug uniqueness (R2.5, R2.8).
    (
        "R2.5/R2.8: uq_organisations_slug_lower — global case-insensitive slug uniqueness",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_organisations_slug_lower "
        "ON organisations (lower(slug)) WHERE slug IS NOT NULL",
    ),
    # Step 2 — employee_portal_users indexes.
    (
        "R5.2: uq_emp_portal_users_org_email_active — per-org case-insensitive active email uniqueness",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_emp_portal_users_org_email_active "
        "ON employee_portal_users (org_id, lower(email)) WHERE is_active",
    ),
    (
        "idx_emp_portal_users_staff — staff link lookup",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emp_portal_users_staff "
        "ON employee_portal_users (staff_id)",
    ),
    (
        "uq_emp_portal_users_invite_hash — single-use invite token lookup",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_emp_portal_users_invite_hash "
        "ON employee_portal_users (invite_token_hash) WHERE invite_token_hash IS NOT NULL",
    ),
    (
        "uq_emp_portal_users_reset_hash — single-use reset token lookup",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_emp_portal_users_reset_hash "
        "ON employee_portal_users (reset_token_hash) WHERE reset_token_hash IS NOT NULL",
    ),
    # Step 2 — employee_portal_sessions session-token uniqueness.
    (
        "uq_emp_portal_sessions_token_hash — session token (sha256) uniqueness",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_emp_portal_sessions_token_hash "
        "ON employee_portal_sessions (session_token_hash)",
    ),
    # Step 5 — staff partial unique indexes (only reached if the guard passes).
    (
        "R1.2/R1.6: uq_staff_active_email_per_org — per-org case-insensitive active email uniqueness",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_staff_active_email_per_org "
        "ON staff_members (org_id, lower(btrim(email))) "
        "WHERE is_active AND email IS NOT NULL AND btrim(email) <> ''",
    ),
    (
        "R1.3/R1.6: uq_staff_active_employee_id_per_org — per-org active employee-id uniqueness",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_staff_active_employee_id_per_org "
        "ON staff_members (org_id, employee_id) "
        "WHERE is_active AND employee_id IS NOT NULL AND btrim(employee_id) <> ''",
    ),
]


# Drop in reverse order. Each statement is independent so order does not matter
# for correctness — reversed only for log readability.
_DOWNGRADE_INDEXES: list[tuple[str, str]] = [
    ("Drop uq_staff_active_employee_id_per_org",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_staff_active_employee_id_per_org"),
    ("Drop uq_staff_active_email_per_org",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_staff_active_email_per_org"),
    ("Drop uq_emp_portal_sessions_token_hash",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_emp_portal_sessions_token_hash"),
    ("Drop uq_emp_portal_users_reset_hash",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_emp_portal_users_reset_hash"),
    ("Drop uq_emp_portal_users_invite_hash",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_emp_portal_users_invite_hash"),
    ("Drop idx_emp_portal_users_staff",
     "DROP INDEX CONCURRENTLY IF EXISTS idx_emp_portal_users_staff"),
    ("Drop uq_emp_portal_users_org_email_active",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_emp_portal_users_org_email_active"),
    ("Drop uq_organisations_slug_lower",
     "DROP INDEX CONCURRENTLY IF EXISTS uq_organisations_slug_lower"),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    """Execute each statement inside an Alembic ``autocommit_block``.

    ``CREATE/DROP INDEX CONCURRENTLY`` cannot run inside a transaction.
    Alembic's ``autocommit_block`` context manager commits the active
    migration transaction, runs the body in autocommit mode, and then starts a
    fresh transaction for whatever follows. That's exactly the semantic Postgres
    requires for CONCURRENTLY DDL.

    Each statement is executed independently — a failure on one does not roll
    back the others (the only behaviour Postgres offers for CONCURRENTLY anyway:
    the index is left around in an INVALID state for that one, recoverable via
    REINDEX or by deleting + re-running this migration).
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0224] %s", description)
            op.execute(sql)


# Each tuple defines one staff-uniqueness key to de-duplicate:
#   (key_label, group_key_sql, active_filter_sql)
# group_key_sql is the normalised key expression used both to PARTITION groups
# and to GROUP duplicates; active_filter_sql restricts to the rows the matching
# partial unique index covers.
_DEDUP_KEYS: list[tuple[str, str, str]] = [
    (
        "email",
        "lower(btrim(email))",
        "is_active = true AND email IS NOT NULL AND btrim(email) <> ''",
    ),
    (
        "employee_id",
        "employee_id",
        "is_active = true AND employee_id IS NOT NULL AND btrim(employee_id) <> ''",
    ),
]


def _deduplicate_active_staff(conn) -> None:
    """Resolve every active-staff duplicate group, non-destructively (R1.7/R1.8).

    For each uniqueness key (normalised email, then employee_id), repeatedly:
      * find every org-scoped group of active staff sharing the key,
      * pick the survivor (earliest ``created_at``; tie → smallest ``id``),
      * write one ``audit_log`` row per group (survivor id + de-duplicated ids),
      * flip the non-survivors to ``is_active = false``.

    Deactivations are monotonic (a row is never re-activated), so resolving the
    email key first and the employee_id key second converges: each pass only
    shrinks the active set, and a final guard (Step 4) verifies convergence. The
    loop also makes the step naturally idempotent — a re-run finds no groups and
    writes nothing.
    """
    now = datetime.now(timezone.utc)

    for key_label, group_key_sql, active_filter_sql in _DEDUP_KEYS:
        # Loop until this key has no remaining active duplicate group. In
        # practice one pass suffices, but looping is robust against an
        # interrupted prior run and against cross-key deactivation effects.
        while True:
            groups = conn.execute(
                text(
                    f"""
                    SELECT org_id,
                           {group_key_sql} AS group_key,
                           array_agg(id ORDER BY created_at ASC, id ASC) AS member_ids
                    FROM staff_members
                    WHERE {active_filter_sql}
                    GROUP BY org_id, {group_key_sql}
                    HAVING count(*) > 1
                    """
                )
            ).fetchall()

            if not groups:
                break

            for org_id, group_key, member_ids in groups:
                survivor_id = member_ids[0]
                deduped_ids = member_ids[1:]

                # R1.8 — one auditable record per resolved group. audit_log has
                # NO RLS (append-only) so this INSERT is safe inside the
                # migration's transaction without an org GUC.
                conn.execute(
                    text(
                        """
                        INSERT INTO audit_log (
                            id, org_id, user_id, action, entity_type, entity_id,
                            before_value, after_value, ip_address, device_info, created_at
                        ) VALUES (
                            :id, :org_id, NULL, :action, :entity_type, :entity_id,
                            NULL, CAST(:after_value AS jsonb), NULL, :device_info, :created_at
                        )
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "org_id": str(org_id),
                        "action": "staff.deduplicated",
                        "entity_type": "staff_member",
                        "entity_id": str(survivor_id),
                        "after_value": json.dumps(
                            {
                                "key_type": key_label,
                                "key_value": str(group_key),
                                "survivor_id": str(survivor_id),
                                "deduplicated_ids": [str(x) for x in deduped_ids],
                                "reason": "organisation-employee-portal migration 0224 "
                                "pre-constraint staff dedup",
                            }
                        ),
                        "device_info": "alembic:0224",
                        "created_at": now,
                    },
                )

                # Flip ONLY the non-survivors to inactive — never delete, never
                # touch already-inactive rows (R1.7).
                conn.execute(
                    text(
                        """
                        UPDATE staff_members
                        SET is_active = false
                        WHERE id = ANY(:ids) AND is_active = true
                        """
                    ),
                    {"ids": [str(x) for x in deduped_ids]},
                )

            logger.info(
                "[0224] dedup: resolved %d active duplicate group(s) on key '%s'",
                len(groups),
                key_label,
            )


def _assert_no_active_duplicates(conn) -> None:
    """Pre-constraint guard (R17.7) — halt before index creation if dirty.

    Re-scans for any remaining active duplicate group on either key. If any
    remain (e.g. an interrupted dedup), ``raise`` to abort the migration BEFORE
    the autocommit index phase, leaving data unchanged so the unique indexes are
    never enforced over dirty data.
    """
    remaining = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(dup_groups), 0) FROM (
                SELECT count(*) AS dup_groups FROM (
                    SELECT 1
                    FROM staff_members
                    WHERE is_active = true AND email IS NOT NULL AND btrim(email) <> ''
                    GROUP BY org_id, lower(btrim(email))
                    HAVING count(*) > 1
                ) e
                UNION ALL
                SELECT count(*) AS dup_groups FROM (
                    SELECT 1
                    FROM staff_members
                    WHERE is_active = true AND employee_id IS NOT NULL AND btrim(employee_id) <> ''
                    GROUP BY org_id, employee_id
                    HAVING count(*) > 1
                ) i
            ) g
            """
        )
    ).scalar()

    if remaining and int(remaining) > 0:
        raise RuntimeError(
            f"[0224] Pre-constraint guard failed: {int(remaining)} active staff "
            "duplicate group(s) remain after de-duplication. Halting before the "
            "staff unique indexes are created so the constraint is never enforced "
            "over dirty data. Re-run the migration (the dedup step is idempotent) "
            "or resolve the duplicates manually, then re-run."
        )


def upgrade() -> None:
    conn = op.get_bind()

    # --- Transactional phase (runs inside Alembic's default transaction) ---

    # Step 1 (column) — additive, catalogue-only nullable column, no backfill
    # (R17.1). ADD COLUMN ... IF NOT EXISTS with no default is a fast metadata
    # change, safe inside the transaction. The unique index is built LAST in the
    # autocommit phase.
    op.execute(
        "ALTER TABLE organisations ADD COLUMN IF NOT EXISTS slug varchar(63) NULL"
    )

    # Step 2 — new, empty portal tables. CREATE TABLE IF NOT EXISTS is idempotent
    # and needs no CONCURRENTLY (empty tables). Their indexes are built LAST in
    # the autocommit phase. RLS posture mirrors the fleet/roster tables exactly:
    # ENABLE (not FORCE) + a tenant_isolation policy keyed on app.current_org_id.

    # 2a. employee_portal_users — dedicated identity store linked to staff (D4).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_portal_users (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id              uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            email                 varchar(255) NOT NULL,
            password_hash         varchar(255) NULL,
            is_active             boolean NOT NULL DEFAULT true,
            failed_login_attempts integer NOT NULL DEFAULT 0,
            locked_until          timestamptz NULL,
            invite_token_hash     varchar(64) NULL,
            invite_sent_at        timestamptz NULL,
            invite_accepted_at    timestamptz NULL,
            reset_token_hash      varchar(64) NULL,
            reset_token_expires_at timestamptz NULL,
            last_login_at         timestamptz NULL,
            last_login_ip         varchar(45) NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE employee_portal_users ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON employee_portal_users")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON employee_portal_users
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # 2b. employee_portal_sessions — dedicated session table (structural
    # cross-portal cookie rejection). session_token_hash uniqueness is enforced
    # by a CONCURRENTLY index in the autocommit phase (per task), not inline.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_portal_sessions (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id             uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_user_id     uuid NOT NULL REFERENCES employee_portal_users(id) ON DELETE CASCADE,
            session_token_hash varchar(64) NOT NULL,
            csrf_token         varchar(64) NOT NULL,
            created_at         timestamptz NOT NULL DEFAULT now(),
            last_seen_at       timestamptz NOT NULL DEFAULT now(),
            expires_at         timestamptz NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE employee_portal_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON employee_portal_sessions")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON employee_portal_sessions
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # 2c. employee_portal_audit_log — auth/security event log. portal_user_id and
    # actor_user_id are nullable with ON DELETE SET NULL so unknown-email login
    # attempts (R16.6) and post-deletion records survive without revealing
    # existence.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_portal_audit_log (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id         uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_user_id uuid NULL REFERENCES employee_portal_users(id) ON DELETE SET NULL,
            actor_user_id  uuid NULL REFERENCES users(id) ON DELETE SET NULL,
            action         varchar(80) NOT NULL,
            outcome        varchar(10) NOT NULL,
            ip_address     varchar(45) NULL,
            details        jsonb NULL,
            created_at     timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE employee_portal_audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON employee_portal_audit_log")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON employee_portal_audit_log
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # Step 3 — de-duplicate existing active staff (non-destructive, auditable).
    _deduplicate_active_staff(conn)

    # Step 4 — pre-constraint guard: halt BEFORE the autocommit index phase if
    # any active duplicate group remains, leaving data unchanged.
    _assert_no_active_duplicates(conn)

    # Step 5 (+ Steps 1/2 index builds) — autocommit phase, runs LAST. Reached
    # only when the guard passes. CONCURRENTLY cannot run in a transaction.
    _run_outside_tx(_UPGRADE_INDEXES)


def downgrade() -> None:
    # Drop the CONCURRENTLY indexes first (also CONCURRENTLY, in an autocommit
    # block), then the portal tables, then the additive slug column. Dropping a
    # table removes its remaining (non-CONCURRENTLY) objects with it.
    _run_outside_tx(_DOWNGRADE_INDEXES)
    op.execute("DROP TABLE IF EXISTS employee_portal_audit_log")
    op.execute("DROP TABLE IF EXISTS employee_portal_sessions")
    op.execute("DROP TABLE IF EXISTS employee_portal_users")
    op.execute("ALTER TABLE organisations DROP COLUMN IF EXISTS slug")
