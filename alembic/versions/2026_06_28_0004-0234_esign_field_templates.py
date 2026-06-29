"""E-Signature Field Placement — saved field templates table (R17).

Adds the ONE new table this spec (``esignature-field-placement``) introduces:
``esign_field_templates`` — org-scoped, named, reusable field templates that
store **roles, not people**. A template captures the geometry/type/required/
label of each field plus a ``Template_Recipient_Role`` slot per field, so it can
be re-applied to a fresh send and mapped onto that send's actual recipients
client-side. **No recipient name or email is ever stored** (R17.1).

The table mirrors the RLS posture of the four existing esign tables (migration
``0232``): row-level security enabled with a ``tenant_isolation`` policy keyed on
``current_setting('app.current_org_id', true)::uuid`` (``USING`` + ``WITH CHECK``).

Columns:
  - ``id``             uuid PK, ``gen_random_uuid()``
  - ``org_id``         uuid NOT NULL — owning org (RLS key, indexed)
  - ``name``           text NOT NULL — sender-chosen template name
  - ``agreement_type`` text NULL — optional association to one agreement type (R17.2)
  - ``fields``         jsonb NOT NULL — ``TemplateField[]``
                       (``{type,page,position_x,position_y,width,height,required,
                       label?,placeholder?,template_role}``)
  - ``roles``          jsonb NOT NULL — distinct ``Template_Recipient_Role`` slots (R17.1)
  - ``created_at`` / ``updated_at`` timestamptz NOT NULL DEFAULT now()
  - ``created_by``     uuid NULL

Indexing follows ``database-migration-checklist``: ``op.create_index`` is BANNED.
The two indexes (``ix_esign_field_templates_org`` on ``(org_id)`` and
``ix_esign_field_templates_org_agreement`` on ``(org_id, agreement_type)``) are
created with raw ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` inside
``op.get_context().autocommit_block()`` — because ``CREATE INDEX CONCURRENTLY``
cannot run inside a transaction. The ``CREATE TABLE`` + RLS-policy statements run
in the normal transactional body; the indexes run in the autocommit block of the
same migration. ``downgrade()`` drops the policy + table (transactional body) and
both indexes (``DROP INDEX CONCURRENTLY IF EXISTS`` in an autocommit block).

Idempotent throughout: ``CREATE TABLE IF NOT EXISTS``, ``DROP POLICY IF EXISTS``
then ``CREATE POLICY``, and ``IF NOT EXISTS`` / ``IF EXISTS`` guards on every
CONCURRENTLY index so a partial (INVALID) index left behind by an interrupted
build is safely re-runnable.

Follows the canonical templates ``0232_esign_schema`` (table + RLS) and
``0202_add_perf_indexes`` / ``0233_esign_perf_indexes`` (CONCURRENTLY autocommit
block).

Refs: requirements 17.1, 17.2, 17.3, 17.4; design §"Data Models" /
       §"Templates architecture (R17)".

Revision ID: 0234
Revises: 0233
Create Date: 2026-06-28
"""

from __future__ import annotations

import logging

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0234"
down_revision: str = "0233"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# CONCURRENTLY index DDL — runs in an autocommit block (cannot run in a tx).
# Each tuple: (description, SQL). The two indexes are independent; ordering
# only affects logging readability.
_UPGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "ix_esign_field_templates_org — org-scoped list (RLS key)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_esign_field_templates_org "
        "ON esign_field_templates (org_id)",
    ),
    (
        "ix_esign_field_templates_org_agreement — list filtered by agreement_type",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_esign_field_templates_org_agreement "
        "ON esign_field_templates (org_id, agreement_type)",
    ),
]

# Drop in reverse order. Each statement is independent so order does not matter
# for correctness — reversed only for log readability.
_DOWNGRADE_INDEXES: list[tuple[str, str]] = [
    (
        "Drop ix_esign_field_templates_org_agreement",
        "DROP INDEX CONCURRENTLY IF EXISTS ix_esign_field_templates_org_agreement",
    ),
    (
        "Drop ix_esign_field_templates_org",
        "DROP INDEX CONCURRENTLY IF EXISTS ix_esign_field_templates_org",
    ),
]


def _run_outside_tx(statements: list[tuple[str, str]]) -> None:
    """Execute each statement inside an Alembic ``autocommit_block``.

    ``CREATE/DROP INDEX CONCURRENTLY`` cannot run inside a transaction.
    Alembic's ``autocommit_block`` context manager commits the active
    migration transaction, runs the body in autocommit mode, and then
    starts a fresh transaction for whatever follows — exactly the semantic
    Postgres requires for CONCURRENTLY DDL. Each statement runs independently;
    the ``IF NOT EXISTS`` / ``IF EXISTS`` guards make an interrupted build
    safely re-runnable.
    """
    with op.get_context().autocommit_block():
        for description, sql in statements:
            logger.info("[0234] %s", description)
            op.execute(sql)


def upgrade() -> None:
    # ==================================================================
    # 1. esign_field_templates — org-scoped saved field templates (RLS).
    #    Stores roles, NOT people (R17.1). Created in the normal
    #    transactional body; CONCURRENTLY indexes follow in the autocommit
    #    block below.
    # ==================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS esign_field_templates (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id         uuid NOT NULL,
            name           text NOT NULL,
            agreement_type text NULL,
            fields         jsonb NOT NULL,
            roles          jsonb NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now(),
            created_by     uuid NULL
        )
        """
    )

    # RLS — standard tenant isolation keyed on app.current_org_id, identical
    # to esign_envelopes / esign_org_connections (migration 0232).
    op.execute("ALTER TABLE esign_field_templates ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_field_templates")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON esign_field_templates
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ==================================================================
    # 2. Performance indexes — CONCURRENTLY, in an autocommit block.
    #    op.create_index is BANNED per database-migration-checklist.
    # ==================================================================
    _run_outside_tx(_UPGRADE_INDEXES)


def downgrade() -> None:
    # Drop the CONCURRENTLY indexes first (autocommit block), then the policy
    # and table (transactional body). Dropping the table would also drop its
    # policy/indexes, but the explicit drops keep the downgrade self-documenting
    # and re-runnable.
    _run_outside_tx(_DOWNGRADE_INDEXES)

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_field_templates")
    op.execute("DROP TABLE IF EXISTS esign_field_templates")
