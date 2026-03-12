"""Rename service_catalogue to items_catalogue and remove hardcoded category
CHECK constraint. Update FK on bookings table to point to renamed table.

Revision ID: 0082_universal_items_catalogue
Revises: 0081_booking_modal_enhancements
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0082_universal_items_catalogue"
down_revision: str = "0081_booking_modal_enhancements"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Remove the hardcoded category CHECK constraint
    op.drop_constraint(
        "ck_service_catalogue_category", "service_catalogue", type_="check"
    )

    # Rename table
    op.rename_table("service_catalogue", "items_catalogue")

    # Update the FK on bookings table that references service_catalogue
    op.drop_constraint(
        "bookings_service_catalogue_id_fkey", "bookings", type_="foreignkey"
    )
    op.create_foreign_key(
        "bookings_service_catalogue_id_fkey",
        "bookings",
        "items_catalogue",
        ["service_catalogue_id"],
        ["id"],
    )


def downgrade() -> None:
    # Reverse FK to point back to service_catalogue
    op.drop_constraint(
        "bookings_service_catalogue_id_fkey", "bookings", type_="foreignkey"
    )
    op.create_foreign_key(
        "bookings_service_catalogue_id_fkey",
        "bookings",
        "service_catalogue",
        ["service_catalogue_id"],
        ["id"],
    )

    # Rename table back
    op.rename_table("items_catalogue", "service_catalogue")

    # Restore the hardcoded category CHECK constraint
    op.create_check_constraint(
        "ck_service_catalogue_category",
        "service_catalogue",
        "category IN ('warrant','service','repair','diagnostic')",
    )
