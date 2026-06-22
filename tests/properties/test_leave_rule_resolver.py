"""Property tests for the leave rule-set resolver.

Covers design Properties 15 and 16.

**Validates: Requirements 6.3, 6.4, 6.5, 17.1, 17.2, 17.4**
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.leave.rules.registry import (
    HOLIDAYS_ACT_2003,
    RULE_SETS,
    HoursTestBounds,
    NoApplicableRuleSet,
    RuleSet,
    resolve_rule_set,
)

_PBT = settings(max_examples=100, deadline=None)


def _mk_rule_set(version: str, eff: date) -> RuleSet:
    return RuleSet(
        version=version,
        effective_from=eff,
        milestones=HOLIDAYS_ACT_2003.milestones,
        hours_test=HoursTestBounds(Decimal("10"), Decimal("1"), Decimal("40")),
        rules=HOLIDAYS_ACT_2003.rules,
        day_one_entitlements=HOLIDAYS_ACT_2003.day_one_entitlements,
    )


_dates = st.dates(min_value=date(1990, 1, 1), max_value=date(2050, 12, 31))


# Feature: leave-balances-eligibility, Property 15: Rule-set resolver selects the latest applicable version
@_PBT
@given(
    eval_date=_dates,
    effs=st.lists(_dates, min_size=1, max_size=6, unique=True),
)
def test_resolver_selects_latest_applicable(eval_date: date, effs: list[date]) -> None:
    rule_sets = tuple(_mk_rule_set(f"v{i}", e) for i, e in enumerate(sorted(effs)))
    applicable = [rs for rs in rule_sets if rs.effective_from <= eval_date]
    if not applicable:
        try:
            resolve_rule_set(eval_date, rule_sets)
            assert False, "expected NoApplicableRuleSet"
        except NoApplicableRuleSet:
            return
    chosen = resolve_rule_set(eval_date, rule_sets)
    expected_eff = max(rs.effective_from for rs in applicable)
    assert chosen.effective_from == expected_eff
    assert chosen.effective_from <= eval_date


# Feature: leave-balances-eligibility, Property 15: Rule-set resolver selects the latest applicable version
@_PBT
@given(eval_date=st.dates(min_value=date(2004, 1, 1), max_value=date(2050, 12, 31)))
def test_real_registry_resolves_holidays_act(eval_date: date) -> None:
    # With only HOLIDAYS_ACT_2003 registered, every date on/after its effective
    # date resolves to it.
    assert resolve_rule_set(eval_date, RULE_SETS).version == "holidays_act_2003"


# Feature: leave-balances-eligibility, Property 16: Future versions register additively
@_PBT
@given(
    base_eff=_dates,
    later_gap_days=st.integers(min_value=1, max_value=10000),
    eval_offset=st.integers(min_value=1, max_value=10000),
)
def test_future_version_registers_additively(
    base_eff: date, later_gap_days: int, eval_offset: int
) -> None:
    later_eff = base_eff + timedelta(days=later_gap_days)
    base = _mk_rule_set("base", base_eff)
    later = _mk_rule_set("later", later_eff)
    # An evaluation date strictly before the later version's effective date.
    eval_date = later_eff - timedelta(days=eval_offset)
    if eval_date < base_eff:
        # Before both — resolution must raise either way; nothing to compare.
        return
    without = resolve_rule_set(eval_date, (base,))
    with_later = resolve_rule_set(eval_date, (base, later))
    assert without.version == with_later.version == "base"
