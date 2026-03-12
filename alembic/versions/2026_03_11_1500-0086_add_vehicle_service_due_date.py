"""Add service_due_date column to global_vehicles table.

Revision ID: 0086_add_vehicle_service_due_date
Revises: 0085
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0086_add_vehicle_service_due_date"
down_revision: str = "0085"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "global_vehicles",
        sa.Column("service_due_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("global_vehicles", "service_due_date")
