"""Create customer_claims and claim_actions tables.

Adds the customer_claims table for tracking customer complaints,
warranty issues, and returns. Adds the claim_actions table for
timeline tracking of all claim lifecycle events.

Includes CHECK constraints for claim_type, status, resolution_type,
source_reference, and action_type. Adds indexes for common query
patterns (org, customer, status, branch, created_at, claim actions).

Revision ID: 0132
Revises: 0131
Create Date: 2026-04-03

Requirements: 1.1, 1.2, 2.1, 3.1, 5.5
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "0132"
down_revision: str = "0131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create customer_claims table ───────────────────────────────────
    op.create_table(
        "customer_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        # Source references (at least one required via CHECK)
        sa.Column("invoice_id", UUID(as_uuid=True), nullable=True),
        sa.Column("job_card_id", UUID(as_uuid=True), nullable=True),
        sa.Column("line_item_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # Claim details
        sa.Column("claim_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'open'")),
        sa.Column("description", sa.Text(), nullable=False),
        # Resolution details
        sa.Column("resolution_type", sa.String(20), nullable=True),
        sa.Column("resolution_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", UUID(as_uuid=True), nullable=True),
        # Downstream entity references
        sa.Column("refund_id", UUID(as_uuid=True), nullable=True),
        sa.Column("credit_note_id", UUID(as_uuid=True), nullable=True),
        sa.Column("return_movement_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warranty_job_id", UUID(as_uuid=True), nullable=True),
        # Cost tracking
        sa.Column("cost_to_business", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cost_breakdown",
            JSONB,
            nullable=False,
            server_default=sa.text("'{\"labour_cost\": 0, \"parts_cost\": 0, \"write_off_cost\": 0}'::jsonb"),
        ),
        # Audit
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_customer_claims_org_id"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"], name="fk_customer_claims_branch_id"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_customer_claims_customer_id"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name="fk_customer_claims_invoice_id"),
        sa.ForeignKeyConstraint(["job_card_id"], ["job_cards.id"], name="fk_customer_claims_job_card_id"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], name="fk_customer_claims_resolved_by"),
        sa.ForeignKeyConstraint(["refund_id"], ["payments.id"], name="fk_customer_claims_refund_id"),
        sa.ForeignKeyConstraint(["credit_note_id"], ["credit_notes.id"], name="fk_customer_claims_credit_note_id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_customer_claims_created_by"),
        # CHECK constraints
        sa.CheckConstraint(
            "claim_type IN ('warranty', 'defect', 'service_redo', 'exchange', 'refund_request')",
            name="ck_claim_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'approved', 'rejected', 'resolved')",
            name="ck_claim_status",
        ),
        sa.CheckConstraint(
            "resolution_type IS NULL OR resolution_type IN ('full_refund', 'partial_refund', 'credit_note', 'exchange', 'redo_service', 'no_action')",
            name="ck_resolution_type",
        ),
        sa.CheckConstraint(
            "invoice_id IS NOT NULL OR job_card_id IS NOT NULL",
            name="ck_source_reference",
        ),
    )

    # ── 2. Indexes for customer_claims ────────────────────────────────────
    op.create_index("idx_claims_org", "customer_claims", ["org_id"])
    op.create_index("idx_claims_customer", "customer_claims", ["customer_id"])
    op.create_index("idx_claims_status", "customer_claims", ["org_id", "status"])
    op.create_index(
        "idx_claims_branch",
        "customer_claims",
        ["branch_id"],
        postgresql_where=sa.text("branch_id IS NOT NULL"),
    )
    op.create_index("idx_claims_created", "customer_claims", ["org_id", sa.text("created_at DESC")])

    # ── 3. Create claim_actions table ─────────────────────────────────────
    op.create_table(
        "claim_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=True),
        sa.Column("to_status", sa.String(20), nullable=True),
        sa.Column("action_data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("performed_by", UUID(as_uuid=True), nullable=False),
        sa.Column("performed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Foreign keys
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_claim_actions_org_id"),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["customer_claims.id"],
            name="fk_claim_actions_claim_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], name="fk_claim_actions_performed_by"),
        # CHECK constraint
        sa.CheckConstraint(
            "action_type IN ('status_change', 'note_added', 'resolution_applied', 'cost_updated')",
            name="ck_action_type",
        ),
    )

    # ── 4. Indexes for claim_actions ──────────────────────────────────────
    op.create_index("idx_claim_actions_claim", "claim_actions", ["claim_id"])
    op.create_index("idx_claim_actions_performed", "claim_actions", ["claim_id", "performed_at"])


def downgrade() -> None:
    # ── Drop claim_actions ────────────────────────────────────────────────
    op.drop_index("idx_claim_actions_performed", table_name="claim_actions")
    op.drop_index("idx_claim_actions_claim", table_name="claim_actions")
    op.drop_table("claim_actions")

    # ── Drop customer_claims ──────────────────────────────────────────────
    op.drop_index("idx_claims_created", table_name="customer_claims")
    op.drop_index("idx_claims_branch", table_name="customer_claims")
    op.drop_index("idx_claims_status", table_name="customer_claims")
    op.drop_index("idx_claims_customer", table_name="customer_claims")
    op.drop_index("idx_claims_org", table_name="customer_claims")
    op.drop_table("customer_claims")
