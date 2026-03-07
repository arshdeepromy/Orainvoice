"""Migrate existing V1 org_vehicles data to the assets table.

Copies org_vehicles records into the assets table with asset_type='vehicle',
mapping rego → identifier, and linking customer associations from
customer_vehicles.

Revision ID: 0058
Revises: 0057
Create Date: 2025-01-15

Requirements: Extended Asset Tracking — Task 45.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0058"
down_revision: str = "0057"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Copy org_vehicles → assets
    op.execute(
        """
        INSERT INTO assets (id, org_id, asset_type, identifier, make, model, year, is_active, created_at, updated_at)
        SELECT
            id,
            org_id,
            'vehicle',
            rego,
            make,
            model,
            year,
            true,
            created_at,
            updated_at
        FROM org_vehicles
        ON CONFLICT DO NOTHING
        """
    )

    # Link customer associations from customer_vehicles
    op.execute(
        """
        UPDATE assets a
        SET customer_id = cv.customer_id
        FROM customer_vehicles cv
        WHERE cv.org_vehicle_id = a.id
          AND a.customer_id IS NULL
        """
    )


def downgrade() -> None:
    # Remove migrated vehicle assets (those with asset_type='vehicle'
    # whose id matches an org_vehicles record)
    op.execute(
        """
        DELETE FROM assets
        WHERE asset_type = 'vehicle'
          AND id IN (SELECT id FROM org_vehicles)
        """
    )
