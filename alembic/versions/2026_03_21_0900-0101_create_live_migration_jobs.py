"""Create live_migration_jobs table for the live database migration feature.

This table tracks zero-downtime database migration jobs initiated by
global_admin users.  Named ``live_migration_jobs`` to avoid conflict
with any existing ``migration_jobs`` table used by the V1 org data
migration tool.

Revision ID: 0101
Revises: 0100
Create Date: 2026-03-21 09:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_migration_jobs",
        # Primary key
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # Status
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        # Source connection info
        sa.Column("source_host", sa.String(255), nullable=False),
        sa.Column("source_port", sa.Integer, nullable=False),
        sa.Column("source_db_name", sa.String(255), nullable=False),
        # Target connection info
        sa.Column("target_host", sa.String(255), nullable=False),
        sa.Column("target_port", sa.Integer, nullable=False),
        sa.Column("target_db_name", sa.String(255), nullable=False),
        # SSL
        sa.Column("ssl_mode", sa.String(10), nullable=False, server_default="prefer"),
        # Encrypted connection string (cleared after completion/cancellation)
        sa.Column("target_conn_encrypted", sa.LargeBinary, nullable=True),
        # Progress tracking
        sa.Column("batch_size", sa.Integer, nullable=False, server_default="1000"),
        sa.Column("current_table", sa.String(255), nullable=True),
        sa.Column("rows_processed", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_total", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("progress_pct", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("table_progress", JSONB, nullable=False, server_default="[]"),
        sa.Column("dual_write_queue_depth", sa.Integer, nullable=False, server_default="0"),
        # Integrity check results
        sa.Column("integrity_check", JSONB, nullable=True),
        # Error tracking
        sa.Column("error_message", sa.Text, nullable=True),
        # Timestamps
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cutover_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rollback_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # Who initiated
        sa.Column("initiated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        # Check constraint on status
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'validating', 'schema_migrating', 'copying_data', "
            "'draining_queue', 'integrity_check', 'ready_for_cutover', "
            "'cutting_over', 'completed', 'failed', 'cancelled', 'rolled_back'"
            ")",
            name="ck_live_migration_job_status",
        ),
    )

    # Indexes
    op.create_index("idx_live_migration_jobs_status", "live_migration_jobs", ["status"])
    op.create_index("idx_live_migration_jobs_created", "live_migration_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_live_migration_jobs_created", table_name="live_migration_jobs")
    op.drop_index("idx_live_migration_jobs_status", table_name="live_migration_jobs")
    op.drop_table("live_migration_jobs")
