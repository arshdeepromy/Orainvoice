"""Backfill the FULL default statutory leave-type catalogue into every org.

Migration 0205 seeded 7 leave types per org *existing at that time*; 0228 added
3 more (public_holiday, jury_service, parental). But organisations created
between 0205 and the runtime-seeding hook (e.g. via self-service signup) never
received the original 7 — so some orgs have 0 or only a partial set.

This migration inserts the complete canonical default set (10 types) for EVERY
organisation, keyed on the ``uq_leave_types_org_code`` unique constraint
(``ON CONFLICT DO NOTHING``) so it is fully idempotent and never disturbs an
org's existing or customised rows. After this, every org has all 10 defaults
and can edit/deactivate them.

Mirrors :data:`app.modules.leave.provisioning.DEFAULT_LEAVE_TYPES` — keep in
sync when adding statutory types.

Revision ID: 0229
Revises: 0228
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision: str = "0229"
down_revision: str = "0228"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# (code, name, is_paid, accrual_method, accrual_amount, accrual_unit,
#  carry_over_max, is_statutory, requires_doctor_note, confidential_visibility,
#  display_order)
_DEFAULTS = (
    ("annual", "Annual leave", "true", "anniversary", "NULL", "hours", "NULL", "true", "false", "false", 1),
    ("sick", "Sick leave", "true", "per_period", "80.0", "hours", "160.0", "true", "true", "false", 2),
    ("bereavement", "Bereavement leave", "true", "event_based", "NULL", "days", "NULL", "true", "false", "false", 3),
    ("family_violence", "Family violence leave", "true", "per_period", "80.0", "hours", "80.0", "true", "false", "true", 4),
    ("public_holiday_alt", "Alternative holiday", "true", "event_based", "NULL", "days", "NULL", "true", "false", "false", 5),
    ("unpaid", "Unpaid leave", "false", "unaccrued", "NULL", "hours", "NULL", "true", "false", "false", 6),
    ("toil", "Time off in lieu", "true", "event_based", "NULL", "hours", "NULL", "false", "false", "false", 7),
    ("public_holiday", "Public holiday", "true", "event_based", "NULL", "days", "NULL", "true", "false", "false", 8),
    ("jury_service", "Jury service", "false", "unaccrued", "NULL", "hours", "NULL", "true", "false", "false", 9),
    ("parental", "Parental leave", "false", "unaccrued", "NULL", "hours", "NULL", "true", "false", "false", 10),
)


def upgrade() -> None:
    values = ",\n            ".join(
        f"('{code}', '{name}', {is_paid}, '{method}', {amount}, '{unit}', "
        f"{carry}, {statutory}, {doctor}, {confidential}, {order})"
        for (
            code, name, is_paid, method, amount, unit, carry, statutory,
            doctor, confidential, order,
        ) in _DEFAULTS
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
    # No-op: we cannot tell which rows pre-existed vs were inserted here, and
    # removing seeded leave types could orphan balances/requests. Intentionally
    # irreversible.
    pass
