"""add_failed_login_tracking

Revision ID: 2221e0371bbc
Revises: 0071
Create Date: 2026-03-09 13:03:27.287269+13:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2221e0371bbc'
down_revision: Union[str, None] = '0071'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add failed_login_count column
    op.add_column('users', sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'))
    
    # Add locked_until column
    op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove columns
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_count')
