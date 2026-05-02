"""Change portal_token column from UUID to VARCHAR(64).

Supports secrets.token_urlsafe(32) tokens (43 chars) alongside
existing UUID tokens (36 chars).  Existing UUID tokens continue to
work until they expire — only newly generated tokens use the new
format.

Revision ID: 0175
Revises: 0174
Create Date: 2026-05-04
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Cast existing UUID values to text, then change column type to VARCHAR(64).
    # The UNIQUE constraint is preserved automatically by ALTER TYPE.
    op.execute(
        "ALTER TABLE customers "
        "ALTER COLUMN portal_token TYPE VARCHAR(64) "
        "USING portal_token::text"
    )


def downgrade() -> None:
    # Downgrade: cast back to UUID.  Any non-UUID tokens will fail this cast,
    # so only run downgrade after clearing non-UUID tokens.
    op.execute(
        "ALTER TABLE customers "
        "ALTER COLUMN portal_token TYPE UUID "
        "USING portal_token::uuid"
    )
