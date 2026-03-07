"""Create ecommerce tables: woocommerce_connections, ecommerce_sync_log, sku_mappings, api_credentials.

Revision ID: 0051
Revises: 0050
Create Date: 2025-01-15

Requirements: Ecommerce Module — Task 39.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0051"
down_revision: str = "0050"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- woocommerce_connections ---
    op.create_table(
        "woocommerce_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("store_url", sa.String(500), nullable=False),
        sa.Column("consumer_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("consumer_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("sync_frequency_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("auto_create_invoices", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("invoice_status_on_import", sa.String(20), server_default="draft", nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id"),
    )

    # --- ecommerce_sync_log ---
    op.create_table(
        "ecommerce_sync_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ecommerce_sync_org", "ecommerce_sync_log", ["org_id", "created_at"])

    # --- sku_mappings ---
    op.create_table(
        "sku_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_sku", sa.String(100), nullable=False),
        sa.Column("internal_product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "external_sku", "platform", name="uq_sku_mapping_org_sku_platform"),
    )

    # --- api_credentials ---
    op.create_table(
        "api_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), server_default='["read"]', nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default="100", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_api_credentials_org", "api_credentials", ["org_id"])


def downgrade() -> None:
    op.drop_index("idx_api_credentials_org", table_name="api_credentials")
    op.drop_table("api_credentials")
    op.drop_table("sku_mappings")
    op.drop_index("idx_ecommerce_sync_org", table_name="ecommerce_sync_log")
    op.drop_table("ecommerce_sync_log")
    op.drop_table("woocommerce_connections")
