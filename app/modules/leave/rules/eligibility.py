"""Pure eligibility evaluator.

``evaluate_eligibility`` is keyed on exactly two facts — Continuous_Service and
the Hours_Test — and never branches on employment type. The only employment-type
effect is that a casual annual-holiday pay method (``casual_payg``) reports the
annual rule as ``eligible=False`` with reason ``casual_payg`` so the applier never
vests an accruing annual balance (R7.6, R9.5, R11.2). All thresholds are read from
``rule_set.*`` (version-scoped configuration, R17.3) — no milestone-month or
hours-test literal appears here.

**Validates: Requirements 2.4, 7.4, 7.5, 7.6, 8.2, 8.3, 8.4, 9.1, 9.3, 9.5, 10.1, 10.4, 11.2**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.leave.rules.hours_test import HoursTestResult, evaluate_hours_test
from app.modules.leave.rules.registry import RuleSet
from app.modules.leave.rules.service_period import (
    StaffSnapshot,
    compute_continuous_service,
)

__all__ = ["EligibilityResult", "evaluate_eligibility"]

_DAY_ONE_MILESTONE = "day_1"
_ANNUAL_CODE = "annual"
_CASUAL_PAYG = "casual_payg"


@dataclass(frozen=True)
class EligibilityResult:
    leave_type_code: str
    eligible: bool
    milestone_key: str
    hours_test: HoursTestResult | None
    reason: str | None  # why not eligible, or the triggering condition when eligible
    rule_set_version: str


def evaluate_eligibility(
    snapshot: StaffSnapshot,
    evaluation_date: date,
    rule_set: RuleSet,
) -> list[EligibilityResult]:
    """Pure. One result per day-one entitlement and per accrual/hours-test rule."""
    service = compute_continuous_service(
        snapshot.employment_start_date, evaluation_date
    )
    is_casual_payg = snapshot.holiday_pay_method == _CASUAL_PAYG
    results: list[EligibilityResult] = []

    # --- Day-one entitlements (public holiday / alt holiday / jury service) ---
    day_one = rule_set.milestone(_DAY_ONE_MILESTONE)
    for code in rule_set.day_one_entitlements:
        if service is None:
            results.append(
                EligibilityResult(
                    leave_type_code=code,
                    eligible=False,
                    milestone_key=_DAY_ONE_MILESTONE,
                    hours_test=None,
                    reason="start_date_required",
                    rule_set_version=rule_set.version,
                )
            )
            continue
        eligible = day_one is not None and service.is_milestone_reached(day_one.months)
        results.append(
            EligibilityResult(
                leave_type_code=code,
                eligible=eligible,
                milestone_key=_DAY_ONE_MILESTONE,
                hours_test=None,
                reason="day_one_entitlement" if eligible else "not_yet_started",
                rule_set_version=rule_set.version,
            )
        )

    # --- Accrual / hours-test gated rules ------------------------------------
    for rule in rule_set.rules:
        if service is None:
            # No partial calculation — skip all milestone processing (R7.4).
            results.append(
                EligibilityResult(
                    leave_type_code=rule.leave_type_code,
                    eligible=False,
                    milestone_key=rule.milestone_key,
                    hours_test=None,
                    reason="start_date_required",
                    rule_set_version=rule_set.version,
                )
            )
            continue

        # Casual selects Casual_PAYG instead of accruing annual holidays.
        if rule.leave_type_code == _ANNUAL_CODE and is_casual_payg:
            results.append(
                EligibilityResult(
                    leave_type_code=rule.leave_type_code,
                    eligible=False,
                    milestone_key=rule.milestone_key,
                    hours_test=None,
                    reason=_CASUAL_PAYG,
                    rule_set_version=rule_set.version,
                )
            )
            continue

        milestone = rule_set.milestone(rule.milestone_key)
        milestone_reached = milestone is not None and service.is_milestone_reached(
            milestone.months
        )

        hours_result: HoursTestResult | None = None
        if rule.requires_hours_test:
            hours_result = evaluate_hours_test(
                snapshot.hours_test_input, rule_set.hours_test
            )

        if not milestone_reached:
            eligible = False
            reason: str | None = f"{rule.milestone_key}_not_reached"
        elif rule.requires_hours_test and not (hours_result and hours_result.met):
            eligible = False
            reason = (hours_result.reason if hours_result else None) or "hours_test_not_met"
        else:
            eligible = True
            reason = (
                f"{rule.milestone_key}_reached"
                if not rule.requires_hours_test
                else f"{rule.milestone_key}_reached_and_hours_test_met"
            )

        results.append(
            EligibilityResult(
                leave_type_code=rule.leave_type_code,
                eligible=eligible,
                milestone_key=rule.milestone_key,
                hours_test=hours_result,
                reason=reason,
                rule_set_version=rule_set.version,
            )
        )

    return results
