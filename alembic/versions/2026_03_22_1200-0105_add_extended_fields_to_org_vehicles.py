"""Add extended vehicle fields to org_vehicles table.

Adds the same extended fields that exist on global_vehicles so that
manually-entered org vehicles can store full vehicle details (VIN,
chassis, transmission, WOF expiry, etc.) and bulk import can populate them.

Revision ID: 0105
Revises: 0104
"""

from alembic import op
import sqlalchemy as sa

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("org_vehicles", sa.Column("wof_expiry", sa.Date(), nullable=True))
    op.add_column("org_vehicles", sa.Column("registration_expiry", sa.Date(), nullable=True))
    op.add_column("org_vehicles", sa.Column("odometer_last_recorded", sa.Integer(), nullable=True))
    op.add_column("org_vehicles", sa.Column("service_due_date", sa.Date(), nullable=True))
    op.add_column("org_vehicles", sa.Column("vin", sa.String(17), nullable=True))
    op.add_column("org_vehicles", sa.Column("chassis", sa.String(50), nullable=True))
    op.add_column("org_vehicles", sa.Column("engine_no", sa.String(50), nullable=True))
    op.add_column("org_vehicles", sa.Column("transmission", sa.String(100), nullable=True))
    op.add_column("org_vehicles", sa.Column("country_of_origin", sa.String(50), nullable=True))
    op.add_column("org_vehicles", sa.Column("number_of_owners", sa.Integer(), nullable=True))
    op.add_column("org_vehicles", sa.Column("vehicle_type", sa.String(50), nullable=True))
    op.add_column("org_vehicles", sa.Column("power_kw", sa.Integer(), nullable=True))
    op.add_column("org_vehicles", sa.Column("tare_weight", sa.Integer(), nullable=True))
    op.add_column("org_vehicles", sa.Column("gross_vehicle_mass", sa.Integer(), nullable=True))
    op.add_column("org_vehicles", sa.Column("date_first_registered_nz", sa.Date(), nullable=True))
    op.add_column("org_vehicles", sa.Column("plate_type", sa.String(20), nullable=True))
    op.add_column("org_vehicles", sa.Column("submodel", sa.String(150), nullable=True))
    op.add_column("org_vehicles", sa.Column("second_colour", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("org_vehicles", "second_colour")
    op.drop_column("org_vehicles", "submodel")
    op.drop_column("org_vehicles", "plate_type")
    op.drop_column("org_vehicles", "date_first_registered_nz")
    op.drop_column("org_vehicles", "gross_vehicle_mass")
    op.drop_column("org_vehicles", "tare_weight")
    op.drop_column("org_vehicles", "power_kw")
    op.drop_column("org_vehicles", "vehicle_type")
    op.drop_column("org_vehicles", "number_of_owners")
    op.drop_column("org_vehicles", "country_of_origin")
    op.drop_column("org_vehicles", "transmission")
    op.drop_column("org_vehicles", "engine_no")
    op.drop_column("org_vehicles", "chassis")
    op.drop_column("org_vehicles", "vin")
    op.drop_column("org_vehicles", "service_due_date")
    op.drop_column("org_vehicles", "odometer_last_recorded")
    op.drop_column("org_vehicles", "registration_expiry")
    op.drop_column("org_vehicles", "wof_expiry")
