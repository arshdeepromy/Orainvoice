"""Add ownership-check columns to ppsr_searches.

The PPSR search can now optionally run a CarJam ``owner_check`` (the
``owner_check`` API product), verifying a supplied identity against the
current registered owner in the NZ Motor Vehicle Register. The result is
denormalised onto the search row so the history list + detail view can
surface it without decrypting the payload.

Columns added to ``ppsr_searches``:

- ``owner_check_type TEXT NULL`` — one of ``person_names`` / ``person_dl`` /
  ``company``; NULL when no ownership check was run for the search.
- ``owner_check_match BOOLEAN NULL`` — ``true`` when the supplied details
  matched the registered owner, ``false`` when not, NULL when no check ran.
- ``owner_check_ref TEXT NULL`` — CarJam reference id for the check
  (e.g. ``OC1A2B3C4D``).

All three are nullable with no server default, so the add is metadata-only
on PostgreSQL — no table rewrite, no backfill.

HA replication
--------------
``ppsr_searches`` is already a member of ``orainvoice_ha_pub`` and is not on
the publication-exclusion list, so these additive nullable columns replicate
automatically — no ``ALTER PUBLICATION`` snippet required.

Revision ID: 0216
Revises: 0215
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0216"
down_revision: str = "0215"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "ppsr_searches",
        sa.Column("owner_check_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "ppsr_searches",
        sa.Column("owner_check_match", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "ppsr_searches",
        sa.Column("owner_check_ref", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ppsr_searches", "owner_check_ref")
    op.drop_column("ppsr_searches", "owner_check_match")
    op.drop_column("ppsr_searches", "owner_check_type")
