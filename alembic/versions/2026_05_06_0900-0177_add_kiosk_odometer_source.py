"""Add 'kiosk' to odometer_readings source constraint.

Revision ID: 0182
Revises: 0181
Create Date: 2026-05-06 09:00:00.000000
"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0182"
down_revision = "0181"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: drop old constraint if it exists, then create with 'kiosk' included
    conn = op.get_bind()
    # Check if constraint already includes 'kiosk' (already applied on some envs)
    result = conn.execute(text(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_odometer_readings_source'"
    ))
    if result.fetchone():
        op.drop_constraint("ck_odometer_readings_source", "odometer_readings", type_="check")
    op.create_check_constraint(
        "ck_odometer_readings_source",
        "odometer_readings",
        "source IN ('carjam','manual','invoice','kiosk')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_odometer_readings_source", "odometer_readings", type_="check")
    op.create_check_constraint(
        "ck_odometer_readings_source",
        "odometer_readings",
        "source IN ('carjam','manual','invoice')",
    )
