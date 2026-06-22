"""Backfill missing statutory leave types into every organisation.

The original ``0205_leave_schema`` backfill seeded seven leave types per org
(annual, sick, bereavement, family_violence, public_holiday_alt, unpaid, toil).
The Holidays Act 2003 reference set also includes **public holiday**, **jury
service**, and **parental leave**, which were missing from the Settings → Leave
Types configuration page.

This migration inserts those three rows for every existing organisation,
keyed on the ``uq_leave_types_org_code`` unique constraint so re-runs and orgs
that already have a given code are no-ops (``ON CONFLICT DO NOTHING``). It never
mutates an existing row, so org customisations are preserved. New display_order
values (8/9/10) sit after the existing seven so prior ordering is untouched.

Mirrors :data:`app.modules.leave.provisioning.DEFAULT_LEAVE_TYPES` — keep the
two in sync when adding statutory types.

Revision ID: 0228
Revises: 0227
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision: str = "0228"
down_revision: str = "0227"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# (code, name, is_paid, accrual_method, accrual_amount, accrual_unit,
#  carry_over_max, is_statutory, requires_doctor_note, confidential_visibility,
#  display_order)
_NEW_TYPES = (
    ("public_holiday", "Public holiday", "true", "event_based", "NULL", "days",
     "NULL", "true", "false", "false", 8),
    ("jury_service", "Jury service", "false", "unaccrued", "NULL", "hours",
     "NULL", "true", "false", "false", 9),
    ("parental", "Parental leave", "false", "unaccrued", "NULL", "hours",
     "NULL", "true", "false", "false", 10),
)


def upgrade() -> None:
    values = ",\n            ".join(
        f"('{code}', '{name}', {is_paid}, '{method}', {amount}, '{unit}', "
        f"{carry}, {statutory}, {doctor}, {confidential}, {order})"
        for (
            code, name, is_paid, method, amount, unit, carry, statutory,
            doctor, confidential, order,
        ) in _NEW_TYPES
    )
    op.execute(
        f"""
        INSERT INTO leave_types (
            id, org_id, code, name, is_paid, accrual_method, accrual_amount,
            accrual_unit, carry_over_max, is_statutory, requires_doctor_note,
            confidential_visibility, active, display_order
        )
        SELECT
            gen_random_uuid(), o.id, t.code, t.name, t.is_paid, t.accrual_method,
            t.accrual_amount::numeric(8,2), t.accrual_unit,
            t.carry_over_max::numeric(8,2), t.is_statutory,
            t.requires_doctor_note, t.confidential_visibility, true, t.display_order
        FROM organisations o
        CROSS JOIN (
            VALUES
            {values}
        ) AS t (
            code, name, is_paid, accrual_method, accrual_amount, accrual_unit,
            carry_over_max, is_statutory, requires_doctor_note,
            confidential_visibility, display_order
        )
        ON CONFLICT (org_id, code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM leave_types
        WHERE code IN ('public_holiday', 'jury_service', 'parental')
        """
    )
