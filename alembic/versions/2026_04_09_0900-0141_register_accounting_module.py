"""Register accounting module in module_registry.

OraFlows Accounting & Tax — double-entry ledger, financial reports,
GST filing, bank feeds, tax wallets, and IRD Gateway integration.
Gated behind the 'accounting' module slug (is_core = false).

Revision ID: 0141
Revises: 0140
Create Date: 2026-04-09
"""
from __future__ import annotations

from alembic import op


revision: str = "0141"
down_revision: str = "0140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category,
            is_core, dependencies, incompatibilities, status, created_at
        ) VALUES (
            gen_random_uuid(),
            'accounting',
            'Accounting & Tax',
            'Double-entry ledger, financial reports, GST filing, Akahu bank feeds, tax savings wallets, and IRD Gateway integration for NZ-compliant accounting.',
            'finance',
            false,
            '[]',
            '[]',
            'available',
            now()
        )
        ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM org_modules WHERE module_slug = 'accounting'")
    op.execute("DELETE FROM module_registry WHERE slug = 'accounting'")
