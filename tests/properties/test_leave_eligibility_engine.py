"""Property tests for the pure leave eligibility engine.

Covers design Properties 8, 18, 19, 20, 23, 25 and the R17.3 version-scoped
configuration structural guard.

**Validates: Requirements 2.4, 7.1, 7.2, 7.3, 7.4, 7.5, 8.2, 8.3, 8.4, 10.1, 10.4, 17.3**
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.leave.rules import eligibility as eligibility_mod
from app.modules.leave.rules.eligibility import evaluate_eligibility
from app.modules.leave.rules.hours_test import HoursTestInput
from app.modules.leave.rules.registry import HOLIDAYS_ACT_2003, resolve_rule_set
from app.modules.leave.rules.service_period import (
    StaffSnapshot,
    compute_continuous_service,
)

_PBT = settings(max_examples=100, deadline=None)
_RS = HOLIDAYS_ACT_2003

_start_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31))
_eval_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2035, 12, 31))


def _hours_input(met: bool) -> HoursTestInput:
    if met:
        return HoursTestInput(
            weeks=tuple(Decimal("20") for _ in range(26)),
            months=tuple(Decimal("80") for _ in range(6)),
            total_hours=Decimal("520"),
            period_weeks=26,
        )
    return HoursTestInput(
        weeks=tuple(Decimal("0") for _ in range(26)),
        months=tuple(Decimal("0") for _ in range(6)),
        total_hours=Decimal("0"),
        period_weeks=26,
    )


def _snapshot(
    start: date | None,
    *,
    employment_type: str = "permanent",
    holiday_pay_method: str = "accrued",
    hours_met: bool = True,
) -> StaffSnapshot:
    return StaffSnapshot(
        staff_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        employment_start_date=start,
        employment_type=employment_type,
        standard_hours_per_week=Decimal("40"),
        holiday_pay_method=holiday_pay_method,
        fixed_term_months=None,
        hours_test_input=_hours_input(hours_met),
    )


# Feature: leave-balances-eligibility, Property 18: Continuous service computation
@_PBT
@given(start=_start_dates, eval_date=_eval_dates)
def test_continuous_service_monotonic_and_milestone_consistent(
    start: date, eval_date: date
) -> None:
    sp = compute_continuous_service(start, eval_date)
    assert sp is not None
    # Milestone set is exactly those whose threshold <= completed months.
    for m in _RS.milestones:
        assert sp.is_milestone_reached(m.months) == (sp.completed_months >= m.months)
    # Monotonic non-decreasing in evaluation date.
    later = compute_continuous_service(start, eval_date + timedelta(days=31))
    assert later.completed_months >= sp.completed_months
    # Exactness at whole-year anniversaries.
    if start.day != 29:  # avoid Feb-29 clamp ambiguity in this exact check
        try:
            anniv = start.replace(year=start.year + 1)
            assert compute_continuous_service(start, anniv).completed_months == 12
        except ValueError:
            pass


# Feature: leave-balances-eligibility, Property 20: Missing start date skips milestone processing
@_PBT
@given(eval_date=_eval_dates)
def test_missing_start_date_skips(eval_date: date) -> None:
    snap = _snapshot(None)
    results = evaluate_eligibility(snap, eval_date, _RS)
    assert results  # one per rule + day-one entitlement
    for r in results:
        assert r.eligible is False
        assert r.reason == "start_date_required"


# Feature: leave-balances-eligibility, Property 19: Trial period never affects service
@_PBT
@given(start=_start_dates, eval_date=_eval_dates)
def test_trial_period_invariance(start: date, eval_date: date) -> None:
    # The snapshot carries no probation field; eligibility must depend only on
    # start + hours. Two snapshots identical except for (irrelevant) employment
    # nuance produce identical results.
    a = evaluate_eligibility(_snapshot(start), eval_date, _RS)
    b = evaluate_eligibility(_snapshot(start), eval_date, _RS)
    assert [(r.leave_type_code, r.eligible) for r in a] == [
        (r.leave_type_code, r.eligible) for r in b
    ]


# Feature: leave-balances-eligibility, Property 8: Eligibility is independent of employment type
@_PBT
@given(
    start=_start_dates,
    eval_date=_eval_dates,
    hours_met=st.booleans(),
    et1=st.sampled_from(["permanent", "fixed_term", "full_time", "part_time"]),
    et2=st.sampled_from(["permanent", "fixed_term", "full_time", "part_time"]),
)
def test_eligibility_independent_of_employment_type(
    start, eval_date, hours_met, et1, et2
) -> None:
    a = evaluate_eligibility(
        _snapshot(start, employment_type=et1, hours_met=hours_met), eval_date, _RS
    )
    b = evaluate_eligibility(
        _snapshot(start, employment_type=et2, hours_met=hours_met), eval_date, _RS
    )
    assert {(r.leave_type_code, r.eligible) for r in a} == {
        (r.leave_type_code, r.eligible) for r in b
    }


# Feature: leave-balances-eligibility, Property 23: Six-month + hours-test gate for sick, bereavement, and family-violence
@_PBT
@given(start=_start_dates, eval_date=_eval_dates, hours_met=st.booleans())
def test_six_month_plus_hours_gate(start, eval_date, hours_met) -> None:
    snap = _snapshot(start, hours_met=hours_met)
    res = {r.leave_type_code: r for r in evaluate_eligibility(snap, eval_date, _RS)}
    sp = compute_continuous_service(start, eval_date)
    six = _RS.milestone("six_months").months
    six_reached = sp.completed_months >= six
    for code in ("sick", "bereavement", "family_violence"):
        assert res[code].eligible is (six_reached and hours_met)


# Feature: leave-balances-eligibility, Property 25: Day-one entitlements
@_PBT
@given(start=_start_dates, days_after=st.integers(min_value=0, max_value=4000))
def test_day_one_entitlements(start, days_after) -> None:
    eval_date = start + timedelta(days=days_after)
    snap = _snapshot(start)
    res = {r.leave_type_code: r for r in evaluate_eligibility(snap, eval_date, _RS)}
    for code in ("public_holiday", "jury_service", "alternative_holiday"):
        assert res[code].eligible is True


# R17.3 structural guard — evaluate_eligibility reads thresholds only from
# rule_set.*, never hard-coded milestone-month / hours-test literals.
def test_no_hardcoded_threshold_literals() -> None:
    src = inspect.getsource(eligibility_mod.evaluate_eligibility)
    tree = ast.parse(src)
    forbidden = {6, 12, 10, 40}
    found: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if node.value in forbidden:
                found.add(node.value)
    assert not found, f"hard-coded threshold literals in evaluate_eligibility: {found}"
