"""Register customer_claims module in module_registry.

Customer Claims & Returns — tracking customer complaints, warranty issues,
and managing resolution processes (refunds, credit notes, exchanges, redo service).

Revision ID: 0135
Revises: 0134
Create Date: 2026-04-03
"""
from __future__ import annotations

from alembic import op


revision: str = "0135"
down_revision: str = "0134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category,
            is_core, dependencies, status, created_at
        ) VALUES (
            gen_random_uuid(),
            'customer_claims',
            'Customer Claims',
            'Track customer complaints, warranty issues, and manage resolution processes including refunds, credit notes, exchanges, and redo service.',
            'general',
            false,
            '[]',
            'available',
            now()
        )
        ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM module_registry WHERE slug = 'customer_claims'")
