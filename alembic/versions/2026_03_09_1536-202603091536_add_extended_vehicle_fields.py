"""add extended vehicle fields

Revision ID: 202603091536
Revises: 2221e0371bbc
Create Date: 2026-03-09 15:36:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '202603091536'
down_revision = '2221e0371bbc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add extended vehicle fields to global_vehicles table
    op.add_column('global_vehicles', sa.Column('vin', sa.String(length=17), nullable=True))
    op.add_column('global_vehicles', sa.Column('chassis', sa.String(length=50), nullable=True))
    op.add_column('global_vehicles', sa.Column('engine_no', sa.String(length=50), nullable=True))
    op.add_column('global_vehicles', sa.Column('transmission', sa.String(length=100), nullable=True))
    op.add_column('global_vehicles', sa.Column('country_of_origin', sa.String(length=50), nullable=True))
    op.add_column('global_vehicles', sa.Column('number_of_owners', sa.Integer(), nullable=True))
    op.add_column('global_vehicles', sa.Column('vehicle_type', sa.String(length=50), nullable=True))
    op.add_column('global_vehicles', sa.Column('reported_stolen', sa.String(length=10), nullable=True))
    op.add_column('global_vehicles', sa.Column('power_kw', sa.Integer(), nullable=True))
    op.add_column('global_vehicles', sa.Column('tare_weight', sa.Integer(), nullable=True))
    op.add_column('global_vehicles', sa.Column('gross_vehicle_mass', sa.Integer(), nullable=True))
    op.add_column('global_vehicles', sa.Column('date_first_registered_nz', sa.Date(), nullable=True))
    op.add_column('global_vehicles', sa.Column('plate_type', sa.String(length=20), nullable=True))
    op.add_column('global_vehicles', sa.Column('submodel', sa.String(length=150), nullable=True))
    op.add_column('global_vehicles', sa.Column('second_colour', sa.String(length=50), nullable=True))
    
    # Create index on VIN for faster lookups
    op.create_index('idx_global_vehicles_vin', 'global_vehicles', ['vin'], unique=False)


def downgrade() -> None:
    # Drop index
    op.drop_index('idx_global_vehicles_vin', table_name='global_vehicles')
    
    # Drop columns
    op.drop_column('global_vehicles', 'second_colour')
    op.drop_column('global_vehicles', 'submodel')
    op.drop_column('global_vehicles', 'plate_type')
    op.drop_column('global_vehicles', 'date_first_registered_nz')
    op.drop_column('global_vehicles', 'gross_vehicle_mass')
    op.drop_column('global_vehicles', 'tare_weight')
    op.drop_column('global_vehicles', 'power_kw')
    op.drop_column('global_vehicles', 'reported_stolen')
    op.drop_column('global_vehicles', 'vehicle_type')
    op.drop_column('global_vehicles', 'number_of_owners')
    op.drop_column('global_vehicles', 'country_of_origin')
    op.drop_column('global_vehicles', 'transmission')
    op.drop_column('global_vehicles', 'engine_no')
    op.drop_column('global_vehicles', 'chassis')
    op.drop_column('global_vehicles', 'vin')
