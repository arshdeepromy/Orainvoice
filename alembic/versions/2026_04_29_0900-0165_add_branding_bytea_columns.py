"""Add BYTEA and metadata columns to platform_branding.

Stores branding file data (logos, favicon) directly in PostgreSQL so they
replicate automatically via the existing logical replication pipeline.

Adds 9 columns:
  - logo_data, dark_logo_data, favicon_data          (BYTEA, nullable)
  - logo_content_type, dark_logo_content_type,
    favicon_content_type                              (VARCHAR(100), nullable)
  - logo_filename, dark_logo_filename,
    favicon_filename                                  (VARCHAR(255), nullable)

Revision ID: 0165
Revises: 0164
Create Date: 2026-04-29

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
"""

from alembic import op

revision = "0165"
down_revision = "0164"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: IF NOT EXISTS guard so re-running is safe.

    # Binary file data (BYTEA)
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS logo_data BYTEA"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS dark_logo_data BYTEA"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS favicon_data BYTEA"
    )

    # MIME content types
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS logo_content_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS dark_logo_content_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS favicon_content_type VARCHAR(100)"
    )

    # Original filenames
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS logo_filename VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS dark_logo_filename VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE platform_branding "
        "ADD COLUMN IF NOT EXISTS favicon_filename VARCHAR(255)"
    )


def downgrade() -> None:
    op.drop_column("platform_branding", "favicon_filename")
    op.drop_column("platform_branding", "dark_logo_filename")
    op.drop_column("platform_branding", "logo_filename")
    op.drop_column("platform_branding", "favicon_content_type")
    op.drop_column("platform_branding", "dark_logo_content_type")
    op.drop_column("platform_branding", "logo_content_type")
    op.drop_column("platform_branding", "favicon_data")
    op.drop_column("platform_branding", "dark_logo_data")
    op.drop_column("platform_branding", "logo_data")
