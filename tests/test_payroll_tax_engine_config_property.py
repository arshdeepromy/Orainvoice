"""Property-based test for the config-driven PAYE engine (task 1.4).

# Feature: payroll-tax-settings, Property 13: The PAYE engine honours the resolved configuration

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**

``compute_paye`` in ``app/modules/timesheets/paye.py`` reads every statutory rate
from the :class:`ResolvedTaxConfig` it is handed (defaulting to ``SAFETY_NET``).
This is a **metamorphic, pure / in-memory** property: for a freshly generated
valid ``ResolvedTaxConfig`` and a pay input, perturbing a *single* configuration
field in a known direction must move the corresponding payslip output in the
direction the rate math predicts, with everything else held constant.

The relationships exercised (one per generated scenario), each tied to the
requirement that wires that field into the engine:

* **PAYE bracket rate up → PAYE up** (Req 6.1). Raising the marginal rate of the
  lowest finite band increases progressive income tax for a primary ``M`` code.
* **Secondary code rate up → PAYE up** (Req 6.2). For a secondary tax code the
  whole annualised gross is taxed at that flat rate.
* **ACC levy rate up → ACC levy up** (Req 6.3). The levy is ``liable * rate``.
* **ACC max-liable cap up → ACC levy up (or equal)** (Req 6.3). A higher cap can
  only raise (never lower) the capped liable earnings.
* **Student-loan rate up → student loan up** (Req 6.4). Repayment is
  ``liable * rate`` above the threshold.
* **Student-loan threshold up → student loan down (or equal)** (Req 6.4). A
  higher threshold shrinks the liable amount.
* **IETC amount up → PAYE down (or equal)** (Req 6.5). A bigger ``ME`` credit
  reduces income tax (clamped at zero).
* **Default KiwiSaver employee rate up → employee KiwiSaver up** (Req 6.6/6.7).
  When the caller passes ``None`` the engine uses the resolved default.

Each relationship is asserted **non-strictly** (``>=`` / ``<=``): the engine
quantises to whole cents, and cent-rounding is monotonic, so the predicted
direction always holds even when a small change rounds to no visible movement.
The generators build only *valid* configs (ascending finite bracket limits, a
single open-ended top band last, rates within range, non-decreasing IETC
bounds) and pick the tax code / flags so the perturbed field genuinely feeds
the checked output (secondary rate only for a secondary code, IETC only for
``ME``, KiwiSaver only when enrolled with an unset employee rate).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.timesheets.paye import (
    IETCParams,
    PAYEBracket,
    ResolvedTaxConfig,
    compute_paye,
)

# ---------------------------------------------------------------------------
# Hypothesis configuration — the engine is a fast pure function.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

SECONDARY_CODES = ("SB", "S", "SH", "ST", "SA")

# Rates carry headroom (<= 0.90) so a +0.05 perturbation stays within [0, 1].
rate_strat = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("0.90"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)

# KiwiSaver rates are percentages; keep headroom for a +5 perturbation.
percent_strat = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("90"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def brackets_strat(draw) -> tuple[PAYEBracket, ...]:
    """A valid progressive bracket set: ascending finite limits then one
    open-ended top band (``upper_limit=None``)."""
    n = draw(st.integers(min_value=1, max_value=5))
    limits = draw(
        st.lists(
            st.decimals(
                min_value=Decimal("1000"),
                max_value=Decimal("250000"),
                places=0,
                allow_nan=False,
                allow_infinity=False,
            ),
            min_size=n,
            max_size=n,
            unique=True,
        )
    )
    limits = sorted(limits)
    rates = [draw(rate_strat) for _ in range(n + 1)]
    brackets = [
        PAYEBracket(upper_limit=limit, rate=rates[i])
        for i, limit in enumerate(limits)
    ]
    brackets.append(PAYEBracket(upper_limit=None, rate=rates[n]))
    return tuple(brackets)


@st.composite
def ietc_strat(draw) -> IETCParams:
    """IETC params with non-decreasing ``lower <= abatement_start <= upper``."""
    bounds = sorted(
        draw(
            st.lists(
                st.decimals(
                    min_value=Decimal("0"),
                    max_value=Decimal("100000"),
                    places=0,
                    allow_nan=False,
                    allow_infinity=False,
                ),
                min_size=3,
                max_size=3,
            )
        )
    )
    lower, abatement_start, upper = bounds
    return IETCParams(
        amount=draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("2000"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        lower=lower,
        abatement_start=abatement_start,
        abatement_rate=draw(rate_strat),
        upper=upper,
    )


@st.composite
def config_strat(draw) -> ResolvedTaxConfig:
    """A fully-populated, valid ``ResolvedTaxConfig``."""
    return ResolvedTaxConfig(
        paye_brackets=draw(brackets_strat()),
        secondary_rates={code: draw(rate_strat) for code in SECONDARY_CODES},
        acc_levy_rate=draw(rate_strat),
        acc_max_liable_earnings=draw(
            st.decimals(
                min_value=Decimal("1000"),
                max_value=Decimal("200000"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        student_loan_rate=draw(rate_strat),
        student_loan_threshold=draw(
            st.decimals(
                min_value=Decimal("0"),
                max_value=Decimal("60000"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        ietc=draw(ietc_strat()),
        default_kiwisaver_employee_rate=draw(percent_strat),
        default_kiwisaver_employer_rate=draw(percent_strat),
        tax_year_label="TEST",
    )


gross_strat = st.decimals(
    min_value=Decimal("500"),
    max_value=Decimal("30000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

period_strat = st.sampled_from([7, 14, 30])

_RATE_STEP = Decimal("0.05")


def _bump_rate(value: Decimal) -> Decimal:
    return min(Decimal("1"), value + _RATE_STEP)


@st.composite
def scenario(draw) -> dict:
    """Build a base config + input, then perturb exactly one field and record
    which output is expected to move and in which direction."""
    config = draw(config_strat())
    kwargs: dict = {
        "gross_pay": draw(gross_strat),
        "period_days": draw(period_strat),
        "config": config,
    }
    field = draw(
        st.sampled_from(
            [
                "bracket_rate",
                "secondary_rate",
                "acc_rate",
                "acc_cap",
                "sl_rate",
                "sl_threshold",
                "ietc_amount",
                "kiwisaver_emp",
            ]
        )
    )

    if field == "bracket_rate":
        head = config.paye_brackets[0]
        new_brackets = (
            PAYEBracket(upper_limit=head.upper_limit, rate=_bump_rate(head.rate)),
            *config.paye_brackets[1:],
        )
        perturbed = replace(config, paye_brackets=new_brackets)
        kwargs["tax_code"] = "M"
        attr, direction = "paye_tax", "up"

    elif field == "secondary_rate":
        code = draw(st.sampled_from(SECONDARY_CODES))
        new_secondary = dict(config.secondary_rates)
        new_secondary[code] = _bump_rate(new_secondary[code])
        perturbed = replace(config, secondary_rates=new_secondary)
        kwargs["tax_code"] = code
        attr, direction = "paye_tax", "up"

    elif field == "acc_rate":
        perturbed = replace(config, acc_levy_rate=_bump_rate(config.acc_levy_rate))
        kwargs["tax_code"] = "M"
        attr, direction = "acc_levy", "up"

    elif field == "acc_cap":
        perturbed = replace(
            config,
            acc_max_liable_earnings=config.acc_max_liable_earnings + Decimal("10000"),
        )
        kwargs["tax_code"] = "M"
        attr, direction = "acc_levy", "up"

    elif field == "sl_rate":
        perturbed = replace(
            config, student_loan_rate=_bump_rate(config.student_loan_rate)
        )
        kwargs["tax_code"] = "M"
        kwargs["student_loan"] = True
        attr, direction = "student_loan", "up"

    elif field == "sl_threshold":
        perturbed = replace(
            config,
            student_loan_threshold=config.student_loan_threshold + Decimal("5000"),
        )
        kwargs["tax_code"] = "M"
        kwargs["student_loan"] = True
        attr, direction = "student_loan", "down"

    elif field == "ietc_amount":
        perturbed = replace(
            config, ietc=replace(config.ietc, amount=config.ietc.amount + Decimal("100"))
        )
        kwargs["tax_code"] = "ME"
        attr, direction = "paye_tax", "down"

    else:  # kiwisaver_emp
        perturbed = replace(
            config,
            default_kiwisaver_employee_rate=min(
                Decimal("100"), config.default_kiwisaver_employee_rate + Decimal("5")
            ),
        )
        kwargs["tax_code"] = "M"
        kwargs["kiwisaver_enrolled"] = True
        kwargs["kiwisaver_employee_rate"] = None
        attr, direction = "kiwisaver_employee", "up"

    return {
        "kwargs": kwargs,
        "perturbed": perturbed,
        "attr": attr,
        "direction": direction,
        "field": field,
    }


@given(sc=scenario())
@PBT_SETTINGS
def test_engine_honours_resolved_config(sc):
    """Property 13: perturbing a single resolved-config field moves the matching
    payslip output in the direction the rate math predicts.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**
    """
    base_kwargs = sc["kwargs"]
    attr = sc["attr"]
    direction = sc["direction"]

    base = compute_paye(**base_kwargs)
    perturbed = compute_paye(**{**base_kwargs, "config": sc["perturbed"]})

    base_val = getattr(base, attr)
    perturbed_val = getattr(perturbed, attr)

    if direction == "up":
        assert perturbed_val >= base_val, (
            f"{sc['field']}: expected {attr} to rise or hold "
            f"({perturbed_val} < {base_val})"
        )
    else:
        assert perturbed_val <= base_val, (
            f"{sc['field']}: expected {attr} to fall or hold "
            f"({perturbed_val} > {base_val})"
        )
