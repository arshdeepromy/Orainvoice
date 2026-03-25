"""Enhance parts_catalogue with extended fields and add part_categories table.

Revision ID: 0106
Revises: 0105
Create Date: 2026-03-25 09:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create part_categories table
    op.create_table(
        "part_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_part_categories_org_name"),
    )
    op.execute("ALTER TABLE part_categories ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY part_categories_tenant ON part_categories "
        "USING (org_id::text = current_setting('app.current_org_id', true))"
    )

    # Add new columns to parts_catalogue
    op.add_column("parts_catalogue", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("parts_catalogue", sa.Column("part_type", sa.String(20), server_default="part", nullable=False))
    op.add_column("parts_catalogue", sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("part_categories.id"), nullable=True))
    op.add_column("parts_catalogue", sa.Column("brand", sa.String(100), nullable=True))
    op.add_column("parts_catalogue", sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("suppliers.id"), nullable=True))
    # Tyre-specific fields
    op.add_column("parts_catalogue", sa.Column("tyre_width", sa.String(10), nullable=True))
    op.add_column("parts_catalogue", sa.Column("tyre_profile", sa.String(10), nullable=True))
    op.add_column("parts_catalogue", sa.Column("tyre_rim_dia", sa.String(10), nullable=True))
    op.add_column("parts_catalogue", sa.Column("tyre_load_index", sa.String(10), nullable=True))
    op.add_column("parts_catalogue", sa.Column("tyre_speed_index", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("parts_catalogue", "tyre_speed_index")
    op.drop_column("parts_catalogue", "tyre_load_index")
    op.drop_column("parts_catalogue", "tyre_rim_dia")
    op.drop_column("parts_catalogue", "tyre_profile")
    op.drop_column("parts_catalogue", "tyre_width")
    op.drop_column("parts_catalogue", "supplier_id")
    op.drop_column("parts_catalogue", "brand")
    op.drop_column("parts_catalogue", "category_id")
    op.drop_column("parts_catalogue", "part_type")
    op.drop_column("parts_catalogue", "description")
    op.execute("DROP POLICY IF EXISTS part_categories_tenant ON part_categories")
    op.drop_table("part_categories")
