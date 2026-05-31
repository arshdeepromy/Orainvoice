"""Staff Management Phase 4 — Payslips, allowances, and termination payouts.

Module surface (per ``.kiro/specs/staff-management-p4/design.md`` §1):

  - :mod:`._preflight` — startup-time column-presence check (task B0).
  - :mod:`.models` — SQLAlchemy ORM mappings for the eight new tables
    introduced by migration ``0209_payslip_schema``.
  - :mod:`.schemas` — Pydantic v2 schemas for the payslip / allowance
    / pay-period / termination surface.

Service / router / PDF / termination modules live alongside as siblings
and are added in subsequent tasks (B3 onwards).
"""
