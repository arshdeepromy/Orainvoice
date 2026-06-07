"""Add CarJam ownership (owner_check) usage-based billing columns.

The CarJam ``owner_check`` product is now billed usage-based exactly like
PPSR / CarJam lookups: the check is never hard-blocked, and usage beyond the
plan's included ``owner_check_lookups_included`` quota is charged at the
configured ``owner_check_per_check_cost_nzd``.

Columns added:

- ``organisations.owner_check_lookups_this_month INTEGER NOT NULL DEFAULT 0``
  — per-org monthly counter, incremented at lookup time, reset at the billing
  cycle boundary (shares the carjam reset boundary).
- ``subscription_plans.owner_check_lookups_included INTEGER NOT NULL DEFAULT 0``
  — per-plan included monthly quota.
- ``billing_receipts.owner_check_overage_cents INTEGER NOT NULL DEFAULT 0``
  — owner_check overage charge (excl. GST) for the period, in cents.
- ``billing_receipts.owner_check_overage_count INTEGER NOT NULL DEFAULT 0``
  — number of owner_check lookups beyond the included quota that were billed.

All carry a ``server_default`` so the ``NOT NULL`` add is safe on existing
rows (PostgreSQL stores the constant default in catalog for additive columns
— no table rewrite, no backfill).

HA replication
--------------
``organisations``, ``subscription_plans`` and ``billing_receipts`` are all
members of ``orainvoice_ha_pub`` and not on the publication-exclusion list,
so these additive defaulted columns replicate automatically — no
``ALTER PUBLICATION`` snippet required.

Revision ID: 0217
Revises: 0216
Create Date: 2026-06-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0217"
down_revision: str = "0216"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "organisations",
        sa.Column(
            "owner_check_lookups_this_month",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "subscription_plans",
        sa.Column(
            "owner_check_lookups_included",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "billing_receipts",
        sa.Column(
            "owner_check_overage_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "billing_receipts",
        sa.Column(
            "owner_check_overage_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("billing_receipts", "owner_check_overage_count")
    op.drop_column("billing_receipts", "owner_check_overage_cents")
    op.drop_column("subscription_plans", "owner_check_lookups_included")
    op.drop_column("organisations", "owner_check_lookups_this_month")
