"""Add catalogue_item_id to job_card_items.

Nullable UUID FK referencing items_catalogue.id — links job card line
items back to their catalogue source for traceability through the
Booking → Job Card → Invoice chain.

Revision ID: 0085
Revises: 0084
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0085"
down_revision: str = "0084"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "job_card_items",
        sa.Column(
            "catalogue_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("items_catalogue.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_card_items", "catalogue_item_id")
