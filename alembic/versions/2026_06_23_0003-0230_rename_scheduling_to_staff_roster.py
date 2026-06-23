"""Rename the 'scheduling' module to 'Staff Roster' in the module registry.

The scheduling module's page is used to roster staff (build weekly shift
rosters), so the user-facing label "Scheduling" / "visual calendar" was
confusing. This updates the ``module_registry`` display name, description, and
the setup-guide question/description that org users see during onboarding and
in Settings → Modules. The module **slug stays ``scheduling``** (it's
referenced throughout the code + data) — only the human-facing copy changes.

Idempotent data-only UPDATE.

Revision ID: 0230
Revises: 0229
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision: str = "0230"
down_revision: str = "0229"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE module_registry
        SET display_name = 'Staff Roster',
            description = 'Build weekly staff rosters, assign shifts, and manage leave, shift swaps, and open shifts.',
            setup_question = 'Do you need to roster staff and manage shifts?',
            setup_question_description = 'Build weekly staff rosters, assign shifts, and manage staff leave.'
        WHERE slug = 'scheduling'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE module_registry
        SET display_name = 'Scheduling',
            description = 'Visual calendar, drag-and-drop scheduling, and resource allocation.',
            setup_question = 'Do you need a visual calendar for scheduling work?',
            setup_question_description = 'Drag-and-drop scheduling and resource allocation.'
        WHERE slug = 'scheduling'
        """
    )
