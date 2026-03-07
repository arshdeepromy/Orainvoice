"""Create catalogue and inventory tables: service_catalogue, parts_catalogue,
suppliers, part_suppliers, labour_rates — with RLS enabled.

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-15

Requirements: 27.1, 28.1, 28.3, 63.1, 63.2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str = "0003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- service_catalogue ---------------------------------------------------
    op.create_table(
        "service_catalogue",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_gst_exempt",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column(
            "is_active",
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
            ["org_id"],
            ["organisations.id"],
            name="fk_service_catalogue_org_id",
        ),
        sa.CheckConstraint(
            "category IN ('warrant','service','repair','diagnostic')",
            name="ck_service_catalogue_category",
        ),
    )
    op.execute("ALTER TABLE service_catalogue ENABLE ROW LEVEL SECURITY")

    # -- parts_catalogue -----------------------------------------------------
    op.create_table(
        "parts_catalogue",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=True),
        sa.Column("default_price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "current_stock",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "min_stock_threshold",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reorder_quantity",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
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
            ["org_id"],
            ["organisations.id"],
            name="fk_parts_catalogue_org_id",
        ),
    )
    op.execute("ALTER TABLE parts_catalogue ENABLE ROW LEVEL SECURITY")

    # -- suppliers -----------------------------------------------------------
    op.create_table(
        "suppliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("account_number", sa.String(100), nullable=True),
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
            ["org_id"],
            ["organisations.id"],
            name="fk_suppliers_org_id",
        ),
    )
    op.execute("ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY")

    # -- part_suppliers ------------------------------------------------------
    op.create_table(
        "part_suppliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("part_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_part_number", sa.String(100), nullable=True),
        sa.Column("supplier_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "is_preferred",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["part_id"],
            ["parts_catalogue.id"],
            name="fk_part_suppliers_part_id",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="fk_part_suppliers_supplier_id",
        ),
        sa.UniqueConstraint("part_id", "supplier_id", name="uq_part_suppliers_part_supplier"),
    )
    # NOTE: part_suppliers has no org_id column — access is controlled
    # through the RLS-protected parts_catalogue and suppliers tables.
    # RLS is intentionally NOT enabled here.

    # -- labour_rates --------------------------------------------------------
    op.create_table(
        "labour_rates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "is_active",
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
            ["org_id"],
            ["organisations.id"],
            name="fk_labour_rates_org_id",
        ),
    )
    op.execute("ALTER TABLE labour_rates ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE labour_rates DISABLE ROW LEVEL SECURITY")
    op.drop_table("labour_rates")

    op.drop_table("part_suppliers")

    op.execute("ALTER TABLE suppliers DISABLE ROW LEVEL SECURITY")
    op.drop_table("suppliers")

    op.execute("ALTER TABLE parts_catalogue DISABLE ROW LEVEL SECURITY")
    op.drop_table("parts_catalogue")

    op.execute("ALTER TABLE service_catalogue DISABLE ROW LEVEL SECURITY")
    op.drop_table("service_catalogue")
