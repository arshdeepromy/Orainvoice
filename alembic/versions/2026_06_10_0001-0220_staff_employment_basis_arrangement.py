"""Staff employment basis + working arrangement.

Adds two columns to ``staff_members``:
  - ``employment_basis`` — full_time | part_time | casual | contractor.
    Granular employment classification surfaced in the Add/Edit Staff
    modal. Defaults to ``full_time`` for existing rows.
  - ``working_arrangement`` — fixed | rostered | casual_on_demand.
    Drives how timesheets are generated. ``fixed`` makes the staff's
    ``availability_schedule`` (work days + hours) the single source of
    truth for rostered hours, so timesheets materialise even without a
    roster entry or clock punch. Defaults to ``rostered``.

Idempotent: ADD COLUMN IF NOT EXISTS throughout. No DML, so no replication
double-insert risk.

Revision ID: 0220
Revises: 0219
Create Date: 2026-06-10
"""

from __future__ import annotations

from alembic import op

revision: str = "0220"
down_revision: str = "0219"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE staff_members
            ADD COLUMN IF NOT EXISTS employment_basis text NOT NULL DEFAULT 'full_time'
        """
    )
    op.execute(
        """
        ALTER TABLE staff_members
            ADD COLUMN IF NOT EXISTS working_arrangement text NOT NULL DEFAULT 'rostered'
        """
    )

    # CHECK constraints — drop-then-create so the migration is re-runnable.
    op.execute(
        "ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_basis"
    )
    op.execute(
        """
        ALTER TABLE staff_members
            ADD CONSTRAINT ck_staff_employment_basis
            CHECK (employment_basis IN ('full_time','part_time','casual','contractor'))
        """
    )
    op.execute(
        "ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_working_arrangement"
    )
    op.execute(
        """
        ALTER TABLE staff_members
            ADD CONSTRAINT ck_staff_working_arrangement
            CHECK (working_arrangement IN ('fixed','rostered','casual_on_demand'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_working_arrangement"
    )
    op.execute(
        "ALTER TABLE staff_members DROP CONSTRAINT IF EXISTS ck_staff_employment_basis"
    )
    op.execute("ALTER TABLE staff_members DROP COLUMN IF EXISTS working_arrangement")
    op.execute("ALTER TABLE staff_members DROP COLUMN IF EXISTS employment_basis")
