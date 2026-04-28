"""Add service_types, service_type_fields, job_card_service_type_values tables.

Creates the Service Type Catalogue tables for plumbing/gas trade organisations.
Service Types are non-priced categories of work with configurable additional
info fields that workers fill in on job cards.

- CREATE TABLE service_types with org_id index and partial unique index on (org_id, name)
- CREATE TABLE service_type_fields with service_type_id index
- CREATE TABLE job_card_service_type_values with job_card_id index and unique constraint
- ALTER TABLE job_cards ADD COLUMN service_type_id (nullable FK)
- Enable RLS on all three new tables with org isolation policies

Revision ID: 0161
Revises: 0160
Create Date: 2026-04-27

Requirements: 1.1, 1.3, 1.4, 1.5, 6.5, 7.1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0161"
down_revision: str = "0160"
branch_labels = None
depends_on = None


_NEW_TABLES = ["service_types", "service_type_fields", "job_card_service_type_values"]

_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication DROP TABLE IF EXISTS {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. Create service_types table ─────────────────────────────────────
    op.create_table(
        "service_types",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_service_types_org_id"),
    )

    op.create_index("ix_service_types_org_id", "service_types", ["org_id"])

    # Partial unique index: no two active service types with the same name per org
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_service_types_org_name "
        "ON service_types (org_id, name) WHERE is_active = true"
    )

    # ── 2. Create service_type_fields table ───────────────────────────────
    op.create_table(
        "service_type_fields",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("service_type_id", UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("field_type", sa.String(20), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("options", JSONB(), nullable=True),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["service_type_id"],
            ["service_types.id"],
            name="fk_service_type_fields_service_type_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index("ix_service_type_fields_service_type_id", "service_type_fields", ["service_type_id"])

    # ── 3. Create job_card_service_type_values table ──────────────────────
    op.create_table(
        "job_card_service_type_values",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_card_id", UUID(as_uuid=True), nullable=False),
        sa.Column("field_id", UUID(as_uuid=True), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_array", JSONB(), nullable=True),
        # Foreign keys
        sa.ForeignKeyConstraint(
            ["job_card_id"],
            ["job_cards.id"],
            name="fk_jcstv_job_card_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["field_id"],
            ["service_type_fields.id"],
            name="fk_jcstv_field_id",
        ),
        # Unique constraint: one value per field per job card
        sa.UniqueConstraint("job_card_id", "field_id", name="uq_jcstv_job_card_field"),
    )

    op.create_index("ix_jcstv_job_card_id", "job_card_service_type_values", ["job_card_id"])

    # ── 4. Add service_type_id column to job_cards ────────────────────────
    op.add_column(
        "job_cards",
        sa.Column("service_type_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_job_cards_service_type_id",
        "job_cards",
        "service_types",
        ["service_type_id"],
        ["id"],
    )

    # ── 5. Enable RLS + create org isolation policies ─────────────────────
    # service_types has its own org_id
    op.execute("ALTER TABLE service_types ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY service_types_org_isolation ON service_types "
        "USING (org_id = current_setting('app.current_org_id')::uuid)"
    )

    # service_type_fields inherits org scope via service_type_id → service_types.org_id
    # Use a subquery-based policy for tables without direct org_id
    op.execute("ALTER TABLE service_type_fields ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY service_type_fields_org_isolation ON service_type_fields "
        "USING (service_type_id IN ("
        "  SELECT id FROM service_types WHERE org_id = current_setting('app.current_org_id')::uuid"
        "))"
    )

    # job_card_service_type_values inherits org scope via job_card_id → job_cards.org_id
    op.execute("ALTER TABLE job_card_service_type_values ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY jcstv_org_isolation ON job_card_service_type_values "
        "USING (job_card_id IN ("
        "  SELECT id FROM job_cards WHERE org_id = current_setting('app.current_org_id')::uuid"
        "))"
    )

    # ── 6. Add tables to HA replication publication if it exists ───────────
    for table in _NEW_TABLES:
        op.execute(sa.text(_HA_ADD_TPL.format(table=table)))


def downgrade() -> None:
    # Drop HA publication membership
    for table in reversed(_NEW_TABLES):
        op.execute(sa.text(_HA_DROP_TPL.format(table=table)))

    # Drop RLS policies
    op.execute("DROP POLICY IF EXISTS jcstv_org_isolation ON job_card_service_type_values")
    op.execute("DROP POLICY IF EXISTS service_type_fields_org_isolation ON service_type_fields")
    op.execute("DROP POLICY IF EXISTS service_types_org_isolation ON service_types")

    # Drop service_type_id FK and column from job_cards
    op.drop_constraint("fk_job_cards_service_type_id", "job_cards", type_="foreignkey")
    op.drop_column("job_cards", "service_type_id")

    # Drop job_card_service_type_values
    op.drop_index("ix_jcstv_job_card_id", table_name="job_card_service_type_values")
    op.drop_table("job_card_service_type_values")

    # Drop service_type_fields
    op.drop_index("ix_service_type_fields_service_type_id", table_name="service_type_fields")
    op.drop_table("service_type_fields")

    # Drop service_types
    op.execute("DROP INDEX IF EXISTS uq_service_types_org_name")
    op.drop_index("ix_service_types_org_id", table_name="service_types")
    op.drop_table("service_types")
