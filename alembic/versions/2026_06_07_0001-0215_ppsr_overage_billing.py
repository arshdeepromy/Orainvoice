"""Add PPSR overage columns to billing_receipts.

PPSR lookups now bill usage-based overage exactly like CarJam lookups
(the lookup is never hard-blocked when the module is enabled; usage beyond
the plan's ``ppsr_lookups_included`` quota is charged at the configured
``ppsr_per_check_cost_nzd``). This records the PPSR overage on the receipt
alongside the existing SMS / CarJam / storage breakdown.

Columns added to ``billing_receipts``:

- ``ppsr_overage_cents INTEGER NOT NULL DEFAULT 0`` — PPSR overage charge
  (excl. GST) for the billing period, in cents.
- ``ppsr_overage_count INTEGER NOT NULL DEFAULT 0`` — number of PPSR lookups
  beyond the plan's included quota that were billed.

Both carry a ``server_default`` so the ``NOT NULL`` add is safe on existing
rows (PostgreSQL stores the constant default in catalog for additive
columns — no table rewrite, no backfill).

No index is added (these are written at billing time and read per-row by the
billing-receipt serializer), so no ``CREATE INDEX CONCURRENTLY`` /
``autocommit_block`` is required.

HA replication
--------------
``billing_receipts`` is already a member of ``orainvoice_ha_pub`` and is not
on the publication-exclusion list, so these additive defaulted columns
replicate automatically — no ``ALTER PUBLICATION`` snippet required.

Revision ID: 0215
Revises: 0214
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0215"
down_revision: str = "0214"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_receipts",
        sa.Column(
            "ppsr_overage_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "billing_receipts",
        sa.Column(
            "ppsr_overage_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_receipts", "ppsr_overage_count")
    op.drop_column("billing_receipts", "ppsr_overage_cents")
