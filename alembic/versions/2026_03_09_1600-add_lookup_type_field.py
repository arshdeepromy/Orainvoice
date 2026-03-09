"""add lookup_type field

Revision ID: 202603091600
Revises: 202603091536
Create Date: 2026-03-09 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '202603091600'
down_revision = '202603091536'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add lookup_type column to track which API was used (basic or abcd)
    op.add_column('global_vehicles', sa.Column('lookup_type', sa.String(length=10), nullable=True, server_default='basic'))
    
    # Update existing records to 'basic' (they were all from basic API)
    op.execute("UPDATE global_vehicles SET lookup_type = 'basic' WHERE lookup_type IS NULL")


def downgrade() -> None:
    # Drop the lookup_type column
    op.drop_column('global_vehicles', 'lookup_type')
