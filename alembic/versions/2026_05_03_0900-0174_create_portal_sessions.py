"""Create portal_sessions table for session-based portal access.

Portal sessions allow HttpOnly cookie-based access after initial token
validation, with a 4-hour inactivity timeout.  The session_token is a
cryptographically strong random string (secrets.token_urlsafe(32)).

Revision ID: 0174
Revises: 0173
Create Date: 2026-05-03

Requirements: 40.1, 40.2, 40.3, 40.4
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0174"
down_revision: str = "0173"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS portal_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            session_token VARCHAR(255) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            last_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_portal_sessions_session_token
        ON portal_sessions (session_token)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_portal_sessions_customer_id
        ON portal_sessions (customer_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portal_sessions")
