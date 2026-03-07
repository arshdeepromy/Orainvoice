"""Create floor_plans, restaurant_tables, and table_reservations tables.

Revision ID: 0043
Revises: 0042
Create Date: 2025-01-15

Requirements: Table Module — Task 31.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0043"
down_revision: str = "0042"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # --- floor_plans ---
    op.create_table(
        "floor_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(100), server_default=sa.text("'Main Floor'"), nullable=False),
        sa.Column("width", sa.Numeric(8, 2), server_default=sa.text("800"), nullable=False),
        sa.Column("height", sa.Numeric(8, 2), server_default=sa.text("600"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_floor_plans_org_id"),
    )
    op.create_index("idx_floor_plans_org", "floor_plans", ["org_id"])

    # --- restaurant_tables ---
    op.create_table(
        "restaurant_tables",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("table_number", sa.String(20), nullable=False),
        sa.Column("seat_count", sa.Integer(), server_default=sa.text("4"), nullable=False),
        sa.Column("position_x", sa.Numeric(8, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("position_y", sa.Numeric(8, 2), server_default=sa.text("0"), nullable=False),
        sa.Column("width", sa.Numeric(8, 2), server_default=sa.text("100"), nullable=False),
        sa.Column("height", sa.Numeric(8, 2), server_default=sa.text("100"), nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'available'"), nullable=False),
        sa.Column("merged_with_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("floor_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_restaurant_tables_org_id"),
        sa.ForeignKeyConstraint(["merged_with_id"], ["restaurant_tables.id"], name="fk_restaurant_tables_merged"),
        sa.ForeignKeyConstraint(["floor_plan_id"], ["floor_plans.id"], name="fk_restaurant_tables_floor_plan"),
    )
    op.create_index("idx_restaurant_tables_org", "restaurant_tables", ["org_id"])
    op.create_index("idx_restaurant_tables_floor_plan", "restaurant_tables", ["floor_plan_id"])

    # --- table_reservations ---
    op.create_table(
        "table_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("reservation_date", sa.Date(), nullable=False),
        sa.Column("reservation_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default=sa.text("90"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'confirmed'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["organisations.id"], name="fk_table_reservations_org_id"),
        sa.ForeignKeyConstraint(["table_id"], ["restaurant_tables.id"], name="fk_table_reservations_table_id"),
    )
    op.create_index("idx_table_reservations_org_date", "table_reservations", ["org_id", "reservation_date"])
    op.create_index("idx_table_reservations_table", "table_reservations", ["table_id"])


def downgrade() -> None:
    op.drop_index("idx_table_reservations_table", table_name="table_reservations")
    op.drop_index("idx_table_reservations_org_date", table_name="table_reservations")
    op.drop_table("table_reservations")
    op.drop_index("idx_restaurant_tables_floor_plan", table_name="restaurant_tables")
    op.drop_index("idx_restaurant_tables_org", table_name="restaurant_tables")
    op.drop_table("restaurant_tables")
    op.drop_index("idx_floor_plans_org", table_name="floor_plans")
    op.drop_table("floor_plans")
