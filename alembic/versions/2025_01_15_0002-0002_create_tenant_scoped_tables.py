"""Create tenant-scoped tables: users, sessions, branches, fleet_accounts,
customers — with RLS enabled and indexes.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-15

Requirements: 5.1, 11.5, 11.6, 66.1
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str = "0001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # -- users ---------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "mfa_methods",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("backup_codes_hash", postgresql.JSONB(), nullable=True),
        sa.Column(
            "passkey_credentials",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("google_oauth_id", sa.String(255), nullable=True),
        sa.Column(
            "branch_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
            ["org_id"], ["organisations.id"], name="fk_users_org_id"
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "role IN ('global_admin','org_admin','salesperson')",
            name="ck_users_role",
        ),
    )
    op.create_index("idx_users_org", "users", ["org_id"])
    op.create_index("idx_users_email", "users", ["email"])
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")

    # -- sessions ------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("refresh_token_hash", sa.String(255), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_type", sa.String(100), nullable=True),
        sa.Column("browser", sa.String(100), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "is_revoked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.id"], name="fk_sessions_org_id"
        ),
    )
    op.execute("ALTER TABLE sessions ENABLE ROW LEVEL SECURITY")

    # -- branches ------------------------------------------------------------
    op.create_table(
        "branches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organisations.id"], name="fk_branches_org_id"
        ),
    )
    op.execute("ALTER TABLE branches ENABLE ROW LEVEL SECURITY")

    # -- fleet_accounts ------------------------------------------------------
    op.create_table(
        "fleet_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("primary_contact_name", sa.String(255), nullable=True),
        sa.Column("primary_contact_email", sa.String(255), nullable=True),
        sa.Column("primary_contact_phone", sa.String(50), nullable=True),
        sa.Column("billing_address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            ["org_id"], ["organisations.id"], name="fk_fleet_accounts_org_id"
        ),
    )
    op.execute("ALTER TABLE fleet_accounts ENABLE ROW LEVEL SECURITY")

    # -- customers -----------------------------------------------------------
    op.create_table(
        "customers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("fleet_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "is_anonymised",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "email_bounced",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("portal_token", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["org_id"], ["organisations.id"], name="fk_customers_org_id"
        ),
        sa.ForeignKeyConstraint(
            ["fleet_account_id"],
            ["fleet_accounts.id"],
            name="fk_customers_fleet_account_id",
        ),
        sa.UniqueConstraint("portal_token", name="uq_customers_portal_token"),
    )
    op.create_index("idx_customers_org", "customers", ["org_id"])
    # Full-text search GIN index on customer name, email, phone
    op.execute(
        "CREATE INDEX idx_customers_search ON customers "
        "USING gin(to_tsvector('english', "
        "first_name || ' ' || last_name || ' ' || COALESCE(email,'') || ' ' || COALESCE(phone,'')))"
    )
    op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE customers DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_customers_search")
    op.drop_index("idx_customers_org", table_name="customers")
    op.drop_table("customers")

    op.execute("ALTER TABLE fleet_accounts DISABLE ROW LEVEL SECURITY")
    op.drop_table("fleet_accounts")

    op.execute("ALTER TABLE branches DISABLE ROW LEVEL SECURITY")
    op.drop_table("branches")

    op.execute("ALTER TABLE sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("sessions")

    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_index("idx_users_org", table_name="users")
    op.drop_table("users")
