"""Register vehicles module in module_registry.

Vehicle database, CarJam lookups, vehicle search, odometer tracking,
and vehicle info on invoices.

Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.

Revision ID: 0076_register_vehicles_module
Revises: 0075_add_odometer_readings_table
Create Date: 2026-03-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0076_register_vehicles_module"
down_revision: str = "0075_add_odometer_readings_table"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category,
            is_core, dependencies, status, created_at
        ) VALUES (
            gen_random_uuid(),
            'vehicles',
            'Vehicles',
            'Vehicle database, CarJam lookups, vehicle search, odometer tracking, and vehicle info on invoices.',
            'automotive',
            false,
            '[]'::jsonb,
            'available',
            now()
        )
        ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM module_registry WHERE slug = 'vehicles'")
