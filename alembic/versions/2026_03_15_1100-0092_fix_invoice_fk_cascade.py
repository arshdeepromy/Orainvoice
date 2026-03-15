"""Fix invoice FK cascade/set-null for bulk delete.

- payments.invoice_id: ON DELETE CASCADE
- credit_notes.invoice_id: ON DELETE CASCADE
- odometer_readings.invoice_id: ON DELETE SET NULL
- tips.invoice_id: ON DELETE SET NULL
- pos_transactions.invoice_id: ON DELETE SET NULL

Revision ID: 0092
Revises: 0091
Create Date: 2026-03-15
"""

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- payments: ON DELETE CASCADE --
    op.drop_constraint("fk_payments_invoice_id", "payments", type_="foreignkey")
    op.create_foreign_key(
        "fk_payments_invoice_id",
        "payments",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # -- credit_notes: ON DELETE CASCADE --
    op.drop_constraint("fk_credit_notes_invoice_id", "credit_notes", type_="foreignkey")
    op.create_foreign_key(
        "fk_credit_notes_invoice_id",
        "credit_notes",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # -- odometer_readings: ON DELETE SET NULL --
    # Auto-generated name from inline sa.ForeignKey()
    op.drop_constraint(
        "odometer_readings_invoice_id_fkey", "odometer_readings", type_="foreignkey"
    )
    op.create_foreign_key(
        "odometer_readings_invoice_id_fkey",
        "odometer_readings",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- tips: ON DELETE SET NULL --
    op.drop_constraint("fk_tips_invoice_id", "tips", type_="foreignkey")
    op.create_foreign_key(
        "fk_tips_invoice_id",
        "tips",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- pos_transactions: ON DELETE SET NULL --
    op.drop_constraint(
        "fk_pos_transactions_invoice_id", "pos_transactions", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_pos_transactions_invoice_id",
        "pos_transactions",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Revert all to bare FKs (no ON DELETE action)
    for constraint, table, ref_cols in [
        ("fk_payments_invoice_id", "payments", ["invoice_id"]),
        ("fk_credit_notes_invoice_id", "credit_notes", ["invoice_id"]),
        ("odometer_readings_invoice_id_fkey", "odometer_readings", ["invoice_id"]),
        ("fk_tips_invoice_id", "tips", ["invoice_id"]),
        ("fk_pos_transactions_invoice_id", "pos_transactions", ["invoice_id"]),
    ]:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, "invoices", ref_cols, ["id"]
        )
