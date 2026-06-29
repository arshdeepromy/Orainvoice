"""E-Signature Integration (Migration B) — performance indexes (CONCURRENTLY).

Separate revision from ``0232`` (Migration A, which creates the four esign
tables under RLS) because mixing ``CREATE INDEX CONCURRENTLY`` with the
transactional DDL of that migration in one ``upgrade()`` is a banned pattern —
``CONCURRENTLY`` changes the transaction semantics for the rest of the migration
and Postgres rejects ``CREATE/DROP INDEX CONCURRENTLY`` inside a transaction. All
DDL here runs inside ``op.get_context().autocommit_block()`` — the canonical
``0202_add_perf_indexes`` / ``0227_leave_perf_indexes`` autocommit template.

Indexes (both on ``esign_envelopes``, the system-of-record table):

  - ``idx_esign_envelopes_org_updated`` on ``esign_envelopes (org_id,
    updated_at DESC)`` — backs the Agreements dashboard list, which is org-scoped
    and ordered by ``updated_at DESC`` (R11.4). Without the compound the planner
    falls back to an org filter + in-memory sort that degrades as the per-org
    envelope count grows.

  - ``idx_esign_envelopes_documenso_doc`` on ``esign_envelopes
    (documenso_document_id) WHERE documenso_document_id IS NOT NULL`` — partial
    index backing the webhook lookup that resolves an inbound Documenso event to
    its envelope by ``documenso_document_id`` (R8.5). Partial because rows with a
    NULL ``documenso_document_id`` (pre-send / error envelopes) are never the
    target of that lookup, keeping the index small.

Every statement carries ``IF NOT EXISTS`` / ``IF EXISTS`` guards so a partial
(INVALID) index left behind by an interrupted CONCURRENTLY build is safely
re-runnable — re-running re-asserts the index without erroring on the stub.

Refs: requirements 11.4, 8.5, 13.1; design §"Data Models" / §"Performance".

Revision ID: 0233
Revises: 0232
Create Date: 2026-06-28
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0233"
down_revision: str = "0232"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Each tuple: (description, SQL). The two indexes are independent; ordering
# only affects logging readability.
_UPGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "idx_esign_envelopes_org_updated — Agreements dashboard ordering "
        "(org_id, updated_at DESC)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_esign_envelopes_org_updated "
        "ON esign_envelopes (org_id, updated_at DESC)",
    ),
    (
        "idx_esign_envelopes_documenso_doc — partial, webhook lookup by "
        "documenso_document_id",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_esign_envelopes_documenso_doc "
        "ON esign_envelopes (documenso_document_id) "
        "WHERE documenso_document_id IS NOT NULL",
    ),
]

# Drop in reverse order. Each statement is independent so order does not matter
# for correctness — reversed only for log readability.
_DOWNGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "Drop idx_esign_envelopes_documenso_doc",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_esign_envelopes_documenso_doc",
    ),
    (
        "Drop idx_esign_envelopes_org_updated",
        "DROP INDEX CONCURRENTLY IF EXISTS idx_esign_envelopes_org_updated",
    ),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    """Execute each statement inside an Alembic ``autocommit_block``.

    ``CREATE/DROP INDEX CONCURRENTLY`` cannot run inside a transaction.
    Alembic's ``autocommit_block`` context manager commits the active
    migration transaction, runs the body in autocommit mode, and then
    starts a fresh transaction for whatever follows. That's exactly the
    semantic Postgres requires for CONCURRENTLY DDL.

    Each statement is executed independently — a failure on one does not
    roll back the others (the only behaviour Postgres offers for
    CONCURRENTLY anyway: an interrupted build leaves an INVALID index that
    the ``IF NOT EXISTS`` / ``IF EXISTS`` guards make safely re-runnable via
    REINDEX or by deleting + re-running this migration).
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0233] %s", description)
            op.execute(sql)


def upgrade() -> None:
    _run_outside_tx(_UPGRADE_INDEXES)


def downgrade() -> None:
    _run_outside_tx(_DOWNGRADE_INDEXES)
