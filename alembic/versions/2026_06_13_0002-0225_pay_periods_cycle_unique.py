"""Per-Staff Pay Cycle: relax the ``pay_periods`` uniqueness key to be cycle-scoped.

Changes the ``pay_periods`` uniqueness guarantee from
``UNIQUE(org_id, start_date)`` (constraint ``uq_pay_periods_org_start``,
created by revision 0209) to ``UNIQUE(org_id, pay_cycle_id, start_date)``
(unique index ``uq_pay_periods_org_cycle_start``).

Why (design Decision 5): with per-staff pay cycles an organisation can run
several active cycles at once, and two cycles frequently share a ``start_date``
(e.g. a weekly and a fortnightly cycle both anchored to Mondays). REQ 8.3
explicitly contemplates "two Pay_Period records from different Active_Cycle
records share the same date range" — the old org+start_date key makes that
impossible. Widening the key to include ``pay_cycle_id`` lets each active cycle
own its own period for a given start_date while still forbidding a single cycle
from materialising the same start_date twice.

Backward compatibility: a single-cycle org has one consistent ``pay_cycle_id``
per start_date, so the new key behaves identically to the old one — no duplicate
periods can appear (REQ 9.2).

Idempotent (project rule): the upgrade uses ``DROP CONSTRAINT IF EXISTS`` and
``CREATE UNIQUE INDEX IF NOT EXISTS``; the downgrade uses ``DROP INDEX IF
EXISTS`` and recreates the original constraint defensively.

Revision ID: 0225
Revises: 0224
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op

revision: str = "0225"
down_revision: str = "0224"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Drop the old org+start_date uniqueness (constraint from revision 0209).
    op.execute(
        "ALTER TABLE pay_periods DROP CONSTRAINT IF EXISTS uq_pay_periods_org_start"
    )
    # Add the cycle-scoped uniqueness key. A unique index (rather than a table
    # constraint) keeps the migration idempotent via IF NOT EXISTS.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pay_periods_org_cycle_start "
        "ON pay_periods (org_id, pay_cycle_id, start_date)"
    )


def downgrade() -> None:
    # Drop the cycle-scoped unique index.
    op.execute("DROP INDEX IF EXISTS uq_pay_periods_org_cycle_start")
    # Restore the original org+start_date uniqueness constraint. Guard with a
    # prior DROP so a re-run after a partial upgrade does not fail.
    op.execute(
        "ALTER TABLE pay_periods DROP CONSTRAINT IF EXISTS uq_pay_periods_org_start"
    )
    op.execute(
        "ALTER TABLE pay_periods "
        "ADD CONSTRAINT uq_pay_periods_org_start UNIQUE (org_id, start_date)"
    )
