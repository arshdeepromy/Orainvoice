"""Break enforcement rules for timesheet validation.

Configurable mandatory break rules that raise exception flags when
break records don't satisfy the configured rules.

Phase C implementation per design § Phase C Architecture Notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class BreakRule:
    """A single break enforcement rule.

    Example: "After 4 hours of continuous work, a 30-minute break is required."
    """
    after_work_minutes: int  # e.g. 240 (4 hours)
    min_break_minutes: int   # e.g. 30
    break_type: str = "any"  # 'rest_paid', 'meal_unpaid', or 'any'
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "BreakRule":
        return cls(
            after_work_minutes=d.get("after_work_minutes", 240),
            min_break_minutes=d.get("min_break_minutes", 30),
            break_type=d.get("break_type", "any"),
            description=d.get("description", ""),
        )


@dataclass
class BreakRecord:
    """Minimal break record data for enforcement checking."""
    start_minutes_from_shift_start: int  # how many minutes into the shift
    duration_minutes: int
    break_type: str  # 'rest_paid' or 'meal_unpaid'


@dataclass
class ShiftBreakData:
    """Data for a single shift used in break enforcement."""
    clock_entry_id: str
    shift_date: date
    worked_minutes: int
    breaks: list[BreakRecord] = field(default_factory=list)


@dataclass
class BreakEnforcementResult:
    """Result of break enforcement check."""
    compliant: bool = True
    violations: list[dict] = field(default_factory=list)


def check_break_compliance(
    *,
    shifts: list[ShiftBreakData],
    rules: list[BreakRule],
) -> BreakEnforcementResult:
    """Check if break records satisfy the configured break rules.

    For each shift, validates that the required breaks were taken
    based on the duration of continuous work.

    Returns a BreakEnforcementResult with any violations found.
    """
    result = BreakEnforcementResult()

    if not rules:
        return result  # No rules configured = always compliant

    for shift in shifts:
        for rule in rules:
            if shift.worked_minutes < rule.after_work_minutes:
                continue  # Shift not long enough to trigger this rule

            # Check if adequate breaks were taken
            qualifying_breaks = [
                b for b in shift.breaks
                if (rule.break_type == "any" or b.break_type == rule.break_type)
                and b.duration_minutes >= rule.min_break_minutes
            ]

            if not qualifying_breaks:
                result.compliant = False
                result.violations.append({
                    "type": "break_violation",
                    "clock_entry_id": shift.clock_entry_id,
                    "shift_date": str(shift.shift_date),
                    "detail": (
                        f"Shift of {shift.worked_minutes} minutes requires a "
                        f"{rule.min_break_minutes}-minute break after "
                        f"{rule.after_work_minutes} minutes of work"
                    ),
                    "rule": {
                        "after_work_minutes": rule.after_work_minutes,
                        "min_break_minutes": rule.min_break_minutes,
                        "break_type": rule.break_type,
                    },
                })

    return result


# Default NZ Employment Relations Act break rules
NZ_DEFAULT_BREAK_RULES = [
    BreakRule(
        after_work_minutes=120,
        min_break_minutes=10,
        break_type="rest_paid",
        description="10-minute paid rest break after 2 hours",
    ),
    BreakRule(
        after_work_minutes=240,
        min_break_minutes=30,
        break_type="meal_unpaid",
        description="30-minute unpaid meal break after 4 hours",
    ),
    BreakRule(
        after_work_minutes=360,
        min_break_minutes=10,
        break_type="rest_paid",
        description="10-minute paid rest break after 6 hours",
    ),
]
