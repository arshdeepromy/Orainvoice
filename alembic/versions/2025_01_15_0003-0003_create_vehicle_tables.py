"""Create vehicle tables: org_vehicles, customer_vehicles — with RLS enabled
and vehicle_link_check constraint.

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-15

Requirements: 14.7, 15.1, 15.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str = "0002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- org_vehicles --------------------------------------------------------
    op.create_table(
        "org_vehicles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rego", sa.String(20), nullable=False),
        sa.Column("make", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("colour", sa.String(50), nullable=True),
        sa.Column("body_type", sa.String(50), nullable=True),
        sa.Column("fuel_type", sa.String(50), nullable=True),
        sa.Column("engine_size", sa.String(50), nullable=True),
        sa.Column("num_seats", sa.Integer(), nullable=True),
        sa.Column(
            "is_manual_entry",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.id"], name="fk_org_vehicles_org_id"
        ),
    )
    op.execute("ALTER TABLE org_vehicles ENABLE ROW LEVEL SECURITY")

    # -- customer_vehicles ---------------------------------------------------
    op.create_table(
        "customer_vehicles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("global_vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("org_vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("odometer_at_link", sa.Integer(), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.id"], name="fk_customer_vehicles_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name="fk_customer_vehicles_customer_id"
        ),
        sa.ForeignKeyConstraint(
            ["global_vehicle_id"],
            ["global_vehicles.id"],
            name="fk_customer_vehicles_global_vehicle_id",
        ),
        sa.ForeignKeyConstraint(
            ["org_vehicle_id"],
            ["org_vehicles.id"],
            name="fk_customer_vehicles_org_vehicle_id",
        ),
        sa.CheckConstraint(
            "(global_vehicle_id IS NOT NULL AND org_vehicle_id IS NULL) OR "
            "(global_vehicle_id IS NULL AND org_vehicle_id IS NOT NULL)",
            name="vehicle_link_check",
        ),
    )
    op.execute("ALTER TABLE customer_vehicles ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE customer_vehicles DISABLE ROW LEVEL SECURITY")
    op.drop_table("customer_vehicles")

    op.execute("ALTER TABLE org_vehicles DISABLE ROW LEVEL SECURITY")
    op.drop_table("org_vehicles")
