"""Versioned, effective-dated leave rule-set registry + resolver.

The eligibility rules are **law, not tenant data** — identical for every org,
changing only when Parliament changes the Act. They are therefore captured as
**code-defined, version-controlled configuration**: frozen dataclasses in the
``RULE_SETS`` registry, each named and ``effective_from``-dated. The engine logic
reads only ``rule_set.*`` — no thresholds are hard-coded in the evaluator
(R17.3). A future ``EMPLOYMENT_LEAVE_BILL`` (≈2028) plugs in additively as a
second tuple entry with its own ``effective_from``; registering it does not touch
``HOLIDAYS_ACT_2003`` (R17.1, R17.2, R17.4).

``resolve_rule_set`` strictly selects the latest version whose ``effective_from``
is on or before the evaluation date (R6.3, R6.4); it raises ``NoApplicableRuleSet``
when the evaluation date precedes every registered version.

**Validates: Requirements 6.1–6.5, 17.1–17.4**
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

__all__ = [
    "Milestone",
    "HoursTestBounds",
    "LeaveRule",
    "RuleSet",
    "RULE_SETS",
    "HOLIDAYS_ACT_2003",
    "NoApplicableRuleSet",
    "resolve_rule_set",
]


class NoApplicableRuleSet(Exception):
    """Raised when no rule-set's ``effective_from`` is on/before the eval date."""

    def __init__(self, evaluation_date: date) -> None:
        super().__init__(
            f"No leave rule-set is effective on or before {evaluation_date.isoformat()}"
        )
        self.evaluation_date = evaluation_date


@dataclass(frozen=True)
class Milestone:
    key: str  # "day_1" | "six_months" | "twelve_months"
    months: int  # 0 | 6 | 12


@dataclass(frozen=True)
class HoursTestBounds:
    min_avg_hours_per_week: Decimal  # 10
    min_hours_every_week: Decimal  # 1
    min_hours_every_month: Decimal  # 40


@dataclass(frozen=True)
class LeaveRule:
    leave_type_code: str  # "annual" | "sick" | "bereavement" | "family_violence"
    milestone_key: str  # gating Service_Milestone
    requires_hours_test: bool
    accrues: bool  # False => day-one / event entitlement only (display vest)
    entitlement_weeks: Decimal | None  # annual = 4; None for non-accruing


@dataclass(frozen=True)
class RuleSet:
    version: str  # "holidays_act_2003"
    effective_from: date
    milestones: tuple[Milestone, ...]
    hours_test: HoursTestBounds
    rules: tuple[LeaveRule, ...]
    day_one_entitlements: tuple[str, ...]

    def milestone(self, key: str) -> Milestone | None:
        for m in self.milestones:
            if m.key == key:
                return m
        return None


# ---------------------------------------------------------------------------
# Holidays Act 2003 — the current NZ statutory rule-set.
# ---------------------------------------------------------------------------

HOLIDAYS_ACT_2003 = RuleSet(
    version="holidays_act_2003",
    # The Act has been in force since 2004-01-01; we use that as the effective
    # boundary so any realistic evaluation date resolves to it.
    effective_from=date(2004, 1, 1),
    milestones=(
        Milestone(key="day_1", months=0),
        Milestone(key="six_months", months=6),
        Milestone(key="twelve_months", months=12),
    ),
    hours_test=HoursTestBounds(
        min_avg_hours_per_week=Decimal("10"),
        min_hours_every_week=Decimal("1"),
        min_hours_every_month=Decimal("40"),
    ),
    rules=(
        # Annual holidays vest at 12 months; 4 weeks; no hours test; accruing.
        LeaveRule(
            leave_type_code="annual",
            milestone_key="twelve_months",
            requires_hours_test=False,
            accrues=True,
            entitlement_weeks=Decimal("4"),
        ),
        # Sick / bereavement / family-violence: 6-month milestone + hours test;
        # non-accruing gate (accrual amounts handled by the existing per-method
        # accrual handlers — this engine only vests/starts the entitlement).
        LeaveRule(
            leave_type_code="sick",
            milestone_key="six_months",
            requires_hours_test=True,
            accrues=False,
            entitlement_weeks=None,
        ),
        LeaveRule(
            leave_type_code="bereavement",
            milestone_key="six_months",
            requires_hours_test=True,
            accrues=False,
            entitlement_weeks=None,
        ),
        LeaveRule(
            leave_type_code="family_violence",
            milestone_key="six_months",
            requires_hours_test=True,
            accrues=False,
            entitlement_weeks=None,
        ),
    ),
    day_one_entitlements=(
        "public_holiday",
        "alternative_holiday",
        "jury_service",
    ),
)


# Future: append EMPLOYMENT_LEAVE_BILL with its own effective_from. The resolver
# automatically selects it for evaluation dates on/after that date; earlier dates
# keep resolving to HOLIDAYS_ACT_2003 (R17.2/R17.4).
RULE_SETS: tuple[RuleSet, ...] = (HOLIDAYS_ACT_2003,)


def resolve_rule_set(
    evaluation_date: date,
    rule_sets: tuple[RuleSet, ...] = RULE_SETS,
) -> RuleSet:
    """Strictly select the latest rule-set whose ``effective_from`` <= the date.

    Raises ``NoApplicableRuleSet`` when none apply (the date precedes them all).
    On ties of applicability, the version with the maximum ``effective_from``
    wins (R6.3, R6.4).
    """
    eligible = [rs for rs in rule_sets if rs.effective_from <= evaluation_date]
    if not eligible:
        raise NoApplicableRuleSet(evaluation_date)
    return max(eligible, key=lambda rs: rs.effective_from)
