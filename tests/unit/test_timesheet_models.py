"""Unit tests for app.modules.timesheets.models — Timesheet + TimesheetSettings.

Validates: Requirements 1.1, 4.2
"""

from __future__ import annotations

import uuid

from app.modules.timesheets.models import Timesheet, TimesheetSettings


class TestTimesheetModel:
    """Verify Timesheet ORM model structure and defaults."""

    def test_tablename(self):
        assert Timesheet.__tablename__ == "timesheets"

    def test_expected_columns(self):
        col_names = [c.name for c in Timesheet.__table__.columns]
        expected = [
            "id", "org_id", "staff_id", "pay_period_id", "branch_id",
            "rostered_minutes", "actual_minutes", "adjusted_minutes",
            "ordinary_minutes", "overtime_minutes", "public_holiday_minutes",
            "exception_flags", "status", "approved_by", "approved_at",
            "locked_at", "locked_by", "payslip_id", "notes",
            "created_at", "updated_at",
        ]
        assert col_names == expected

    def test_primary_key(self):
        pk_cols = [c.name for c in Timesheet.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    def test_unique_constraint_staff_period(self):
        constraints = {
            c.name for c in Timesheet.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "uq_timesheets_staff_period" in constraints

    def test_status_check_constraint(self):
        constraints = {
            c.name for c in Timesheet.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "ck_timesheets_status" in constraints

    def test_id_column_has_default(self):
        """The id column has a client-side uuid4 default callable."""
        col = Timesheet.__table__.c.id
        assert col.default is not None
        assert col.default.is_callable

    def test_nullable_fields(self):
        col_map = {c.name: c for c in Timesheet.__table__.columns}
        assert col_map["branch_id"].nullable is True
        assert col_map["adjusted_minutes"].nullable is True
        assert col_map["approved_by"].nullable is True
        assert col_map["approved_at"].nullable is True
        assert col_map["locked_at"].nullable is True
        assert col_map["locked_by"].nullable is True
        assert col_map["payslip_id"].nullable is True
        assert col_map["notes"].nullable is True
        # Non-nullable
        assert col_map["org_id"].nullable is False
        assert col_map["staff_id"].nullable is False
        assert col_map["pay_period_id"].nullable is False
        assert col_map["rostered_minutes"].nullable is False
        assert col_map["actual_minutes"].nullable is False
        assert col_map["status"].nullable is False

    def test_foreign_keys(self):
        fk_targets = set()
        for c in Timesheet.__table__.columns:
            for fk in c.foreign_keys:
                fk_targets.add(fk.target_fullname)
        assert "staff_members.id" in fk_targets
        assert "pay_periods.id" in fk_targets
        assert "branches.id" in fk_targets
        assert "users.id" in fk_targets
        assert "payslips.id" in fk_targets


class TestTimesheetSettingsModel:
    """Verify TimesheetSettings ORM model structure and defaults."""

    def test_tablename(self):
        assert TimesheetSettings.__tablename__ == "timesheet_settings"

    def test_expected_columns(self):
        col_names = [c.name for c in TimesheetSettings.__table__.columns]
        expected = [
            "id", "org_id", "branch_id",
            "clock_rounding_minutes", "clock_rounding_direction",
            "early_grace_minutes", "late_grace_minutes",
            "match_policy", "auto_approve_threshold_minutes",
            "require_approval_before_lock",
            "created_at", "updated_at",
        ]
        assert col_names == expected

    def test_primary_key(self):
        pk_cols = [c.name for c in TimesheetSettings.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    def test_unique_constraint_org_branch(self):
        constraints = {
            c.name for c in TimesheetSettings.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "uq_timesheet_settings_org_branch" in constraints

    def test_check_constraints(self):
        constraints = {
            c.name for c in TimesheetSettings.__table__.constraints
            if hasattr(c, "name") and c.name
        }
        assert "ck_timesheet_settings_rounding_minutes" in constraints
        assert "ck_timesheet_settings_rounding_direction" in constraints
        assert "ck_timesheet_settings_match_policy" in constraints

    def test_id_column_has_default(self):
        col = TimesheetSettings.__table__.c.id
        assert col.default is not None
        assert col.default.is_callable

    def test_nullable_fields(self):
        col_map = {c.name: c for c in TimesheetSettings.__table__.columns}
        assert col_map["branch_id"].nullable is True
        # Non-nullable
        assert col_map["org_id"].nullable is False
        assert col_map["clock_rounding_minutes"].nullable is False
        assert col_map["clock_rounding_direction"].nullable is False
        assert col_map["match_policy"].nullable is False
        assert col_map["require_approval_before_lock"].nullable is False

    def test_foreign_keys(self):
        fk_targets = set()
        for c in TimesheetSettings.__table__.columns:
            for fk in c.foreign_keys:
                fk_targets.add(fk.target_fullname)
        assert "branches.id" in fk_targets
