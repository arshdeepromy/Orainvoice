"""Register branch_management module in module_registry.

Multi-branch support: branch selector, branch-scoped data, inter-branch
transfers, per-branch scheduling, and branch_admin role.

Auto-enables the module for existing organisations that already have more
than one branch so their workflows are not disrupted.

Revision ID: 0137
Revises: 0136
Create Date: 2026-04-05
"""
from __future__ import annotations

from alembic import op


revision: str = "0137"
down_revision: str = "0136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Register branch_management in module_registry
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category,
            is_core, dependencies, incompatibilities, status, created_at
        ) VALUES (
            gen_random_uuid(),
            'branch_management',
            'Branch Management',
            'Multi-branch support: branch selector, branch-scoped data, inter-branch transfers, per-branch scheduling, and branch_admin role.',
            'operations',
            false,
            '[]',
            '[]',
            'available',
            now()
        )
        ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
        """
    )

    # 2. Auto-enable for existing orgs that have more than one branch
    op.execute(
        """
        INSERT INTO org_modules (id, org_id, module_slug, is_enabled, enabled_at)
        SELECT gen_random_uuid(), b.org_id, 'branch_management', true, now()
        FROM branches b
        GROUP BY b.org_id
        HAVING COUNT(*) > 1
        ON CONFLICT ON CONSTRAINT uq_org_modules_org_slug DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM org_modules WHERE module_slug = 'branch_management'")
    op.execute("DELETE FROM module_registry WHERE slug = 'branch_management'")
