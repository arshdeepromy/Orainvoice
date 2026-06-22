"""Staff Onboarding Link — onboarding token table + compliance staff link.

Adds the self-service staff-onboarding subsystem schema:

  - Creates ``staff_onboarding_tokens`` — single-use, token-gated onboarding
    links. Mirrors ``staff_roster_view_tokens`` (migration ``0203``): org-scoped,
    RLS with ``tenant_isolation`` policy, and ``ON DELETE CASCADE`` on both the
    ``org_id`` and ``staff_id`` FKs so hard-deleting a staff or org sweeps the
    tokens automatically. Diverges from the roster token in that it stores a
    SHA-256 ``token_hash`` (never the raw token), carries an explicit ``status``
    lifecycle column, and tracks ``consumed_at``. The two nullable draft columns
    (``draft_data_encrypted``, ``draft_updated_at`` — R12) are created inline:
    the whole partial form payload is stored envelope-encrypted as JSON, NULL
    until the first draft is saved and NULLed again on submit/revoke/expiry-purge.
  - Adds a nullable ``staff_id`` link column to the existing
    ``compliance_documents`` table (mirrors its existing nullable
    ``invoice_id`` / ``job_id`` link columns) so working-rights documents can
    be linked to a staff member (R7.6).

The migration is split into two phases (per design §Migration Plan):

  1. A **transactional phase** — ``CREATE TABLE``, RLS, and the additive
     ``compliance_documents.staff_id`` column. The ``ADD COLUMN ... IF NOT
     EXISTS`` with no default is a fast catalogue-only change, safe inside the
     transaction.
  2. A trailing **autocommit phase** (runs LAST) — both indexes built with
     ``CREATE INDEX CONCURRENTLY ... IF NOT EXISTS`` inside
     ``op.get_context().autocommit_block()``. CONCURRENTLY is mandatory for
     ``ix_compliance_documents_staff`` because ``compliance_documents`` is an
     existing, potentially large table (a plain ``CREATE INDEX`` would take an
     ``ACCESS EXCLUSIVE`` lock and block all reads/writes for the build);
     ``ix_staff_onboarding_tokens_staff`` uses CONCURRENTLY too for consistency
     with the checklist. The autocommit block comes last so the
     transaction-boundary change it introduces does not affect any earlier
     transactional op.

Every statement keeps ``IF NOT EXISTS`` / ``IF EXISTS`` guards so the migration
is re-runnable (an interrupted CONCURRENTLY build leaves an INVALID index
behind; the guards make it safely retryable). Follows the
**database-migration-checklist** steering.

Refs: requirements R2.2, R7.6, R11.2, R12.6.

Revision ID: 0223
Revises: 0222
Create Date: 2026-06-12
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0223"
down_revision: str = "0222"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Index DDL runs CONCURRENTLY, outside any transaction (checklist rule).
# Each tuple: (description, SQL). Indexes are independent; ordering only
# affects logging readability.
_UPGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "R12: ix_staff_onboarding_tokens_staff(staff_id, status) — token lookup by staff + status",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staff_onboarding_tokens_staff "
        "ON staff_onboarding_tokens (staff_id, status)",
    ),
    (
        "R7.6: ix_compliance_documents_staff(staff_id) — existing large table, CONCURRENTLY required",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_compliance_documents_staff "
        "ON compliance_documents (staff_id)",
    ),
]


# Drop in reverse order. Each statement is independent so order does not
# matter for correctness — reversed only for log readability.
_DOWNGRADE_INDEXES: list[tuple[str, str]] = [
    ("Drop ix_compliance_documents_staff",
     "DROP INDEX CONCURRENTLY IF EXISTS ix_compliance_documents_staff"),
    ("Drop ix_staff_onboarding_tokens_staff",
     "DROP INDEX CONCURRENTLY IF EXISTS ix_staff_onboarding_tokens_staff"),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    """Execute each statement inside an Alembic ``autocommit_block``.

    ``CREATE/DROP INDEX CONCURRENTLY`` cannot run inside a transaction.
    Alembic's ``autocommit_block`` context manager commits the active
    migration transaction, runs the body in autocommit mode, and then
    starts a fresh transaction for whatever follows. That's exactly the
    semantic Postgres requires for CONCURRENTLY DDL.

    Each statement is executed independently — a failure on one does not
    roll back the others (which is the only behaviour Postgres offers for
    CONCURRENTLY anyway: the index is left around in an INVALID state for
    that one, recoverable via REINDEX or by deleting + re-running this
    migration).
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0223] %s", description)
            op.execute(sql)


def upgrade() -> None:
    # --- Transactional phase (runs inside Alembic's default transaction) ---

    # 1. staff_onboarding_tokens — mirrors staff_roster_view_tokens (0203 §4).
    #    New, empty table → created normally (no CONCURRENTLY needed for the
    #    table). Stores a SHA-256 token_hash (never the raw token), an explicit
    #    status lifecycle, consumed_at, and the two nullable draft columns (R12)
    #    inline at create time. ON DELETE CASCADE on both FKs so hard-deleting a
    #    staff or org sweeps the tokens automatically.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_onboarding_tokens (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            staff_id    uuid NOT NULL REFERENCES staff_members(id) ON DELETE CASCADE,
            token_hash  varchar(64) NOT NULL,
            status      varchar(20) NOT NULL DEFAULT 'pending',
            created_at  timestamptz NOT NULL DEFAULT now(),
            expires_at  timestamptz NOT NULL,
            consumed_at timestamptz NULL,
            -- Draft (R12): whole partial form payload, envelope-encrypted JSON.
            -- NULL until the first draft is saved; NULLed again on
            -- submit/revoke/expiry-purge.
            draft_data_encrypted bytea NULL,
            draft_updated_at     timestamptz NULL,
            CONSTRAINT uq_staff_onboarding_tokens_hash UNIQUE (token_hash)
        )
        """
    )

    # 2. RLS — identical posture to staff_roster_view_tokens (ENABLE, not FORCE).
    op.execute("ALTER TABLE staff_onboarding_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON staff_onboarding_tokens")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON staff_onboarding_tokens
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # 3. Additive, non-locking column on the existing compliance_documents table
    #    (mirrors the existing nullable invoice_id / job_id link columns). The
    #    ADD COLUMN ... IF NOT EXISTS with no default/volatile default is a fast
    #    catalogue-only change, safe inside the transaction.
    op.execute(
        "ALTER TABLE compliance_documents "
        "ADD COLUMN IF NOT EXISTS staff_id uuid NULL"
    )

    # --- Autocommit phase (LAST) — CONCURRENTLY index builds, no surrounding tx ---
    _run_outside_tx(_UPGRADE_INDEXES)


def downgrade() -> None:
    # Drop the CONCURRENTLY indexes first (also CONCURRENTLY), then the schema.
    # Dropping the table removes the draft columns with it.
    _run_outside_tx(_DOWNGRADE_INDEXES)
    op.execute("DROP TABLE IF EXISTS staff_onboarding_tokens")
    op.execute("ALTER TABLE compliance_documents DROP COLUMN IF EXISTS staff_id")
