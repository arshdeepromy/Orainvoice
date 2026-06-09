"""Unit tests for break enforcement rules."""
import pytest
from datetime import date

from app.modules.timesheets.breaks import (
    BreakRecord,
    BreakRule,
    ShiftBreakData,
    check_break_compliance,
    NZ_DEFAULT_BREAK_RULES,
)


class TestBreakEnforcement:
    """Tests for check_break_compliance()."""

    def test_compliant_with_no_rules(self):
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=600,
                breaks=[],
            )],
            rules=[],
        )
        assert result.compliant is True
        assert result.violations == []

    def test_violation_no_break_taken(self):
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=300,
                breaks=[],
            )],
            rules=[BreakRule(after_work_minutes=240, min_break_minutes=30)],
        )
        assert result.compliant is False
        assert len(result.violations) == 1
        assert result.violations[0]["type"] == "break_violation"

    def test_compliant_break_taken(self):
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=300,
                breaks=[BreakRecord(
                    start_minutes_from_shift_start=120,
                    duration_minutes=30,
                    break_type="meal_unpaid",
                )],
            )],
            rules=[BreakRule(after_work_minutes=240, min_break_minutes=30)],
        )
        assert result.compliant is True

    def test_short_shift_no_rule_trigger(self):
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=180,  # Less than 240
                breaks=[],
            )],
            rules=[BreakRule(after_work_minutes=240, min_break_minutes=30)],
        )
        assert result.compliant is True

    def test_break_type_specific_rule(self):
        """Rule requires meal_unpaid but only rest_paid taken."""
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=300,
                breaks=[BreakRecord(
                    start_minutes_from_shift_start=120,
                    duration_minutes=30,
                    break_type="rest_paid",
                )],
            )],
            rules=[BreakRule(
                after_work_minutes=240,
                min_break_minutes=30,
                break_type="meal_unpaid",
            )],
        )
        assert result.compliant is False

    def test_break_type_any_accepts_either(self):
        """Rule with break_type='any' accepts both paid and unpaid."""
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=300,
                breaks=[BreakRecord(
                    start_minutes_from_shift_start=120,
                    duration_minutes=30,
                    break_type="rest_paid",
                )],
            )],
            rules=[BreakRule(
                after_work_minutes=240,
                min_break_minutes=30,
                break_type="any",
            )],
        )
        assert result.compliant is True

    def test_break_too_short(self):
        """Break taken but shorter than required."""
        result = check_break_compliance(
            shifts=[ShiftBreakData(
                clock_entry_id="entry-1",
                shift_date=date(2026, 6, 9),
                worked_minutes=300,
                breaks=[BreakRecord(
                    start_minutes_from_shift_start=120,
                    duration_minutes=15,  # Only 15 min, need 30
                    break_type="meal_unpaid",
                )],
            )],
            rules=[BreakRule(after_work_minutes=240, min_break_minutes=30)],
        )
        assert result.compliant is False

    def test_nz_defaults_exist(self):
        """Verify NZ default break rules are defined."""
        assert len(NZ_DEFAULT_BREAK_RULES) == 3
        assert NZ_DEFAULT_BREAK_RULES[0].after_work_minutes == 120
        assert NZ_DEFAULT_BREAK_RULES[1].after_work_minutes == 240
        assert NZ_DEFAULT_BREAK_RULES[2].after_work_minutes == 360

    def test_multiple_shifts_partial_compliance(self):
        """Two shifts: one compliant, one not."""
        result = check_break_compliance(
            shifts=[
                ShiftBreakData(
                    clock_entry_id="entry-1",
                    shift_date=date(2026, 6, 9),
                    worked_minutes=300,
                    breaks=[BreakRecord(
                        start_minutes_from_shift_start=120,
                        duration_minutes=30,
                        break_type="meal_unpaid",
                    )],
                ),
                ShiftBreakData(
                    clock_entry_id="entry-2",
                    shift_date=date(2026, 6, 10),
                    worked_minutes=300,
                    breaks=[],
                ),
            ],
            rules=[BreakRule(after_work_minutes=240, min_break_minutes=30)],
        )
        assert result.compliant is False
        assert len(result.violations) == 1
        assert result.violations[0]["clock_entry_id"] == "entry-2"
