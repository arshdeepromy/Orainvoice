"""Add 'kiosk' to odometer_readings source constraint.

Revision ID: 0177
Revises: 0176
Create Date: 2026-05-06 09:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0177"
down_revision = "0176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old constraint and add new one with 'kiosk' included
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
