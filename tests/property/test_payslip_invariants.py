"""Property tests for payroll math invariants (Phase 4 task E2).

Hypothesis-driven invariants for ``app.modules.payslips.calc``:

1. **gross >= sum(taxable allowances)** — for any combination of
   hours / rates / allowances, ``gross`` is at least the sum of
   the taxable allowances attached to the draft.

2. **net >= 0** — net pay is never negative for any input
   combination when no deductions or reimbursements are attached
   to the draft (the calc-only surface). The downstream service
   layer attaches deductions in a second pass; clamping behaviour
   for over-deducted drafts is covered by the service-level
   tests, not the calc invariant.

3. **kiwisaver_employer NOT subtracted from gross** — toggling
   the employer rate (or enrolment) changes ``net`` but never
   changes ``gross`` for the same wage inputs.

4. **G2** — ``public_holiday_hours × public_holiday_rate``
   contributes correctly to gross. Fuzz
   ``(public_holiday_hours, ordinary_rate, override_rate)`` and
   assert
   ``gross == ordinary + overtime + ph_hours × ph_rate +
   taxable_allowances + casual_8pct``.

5. **G18** — for ``unit='shift'``, derived amount equals
   ``shift_count × default_amount``. Fuzz
   ``(shift_count, default_amount)`` and assert via
   :func:`_resolve_allowance_quantity`.

6. **N17** — casual employee with zero approved hours and no
   taxable allowances → no ``casual_8pct_holiday`` line attached
   at all (``calc.casual_8pct == 0``). Fuzz across employment
   types.

7. **Casual 8% never recurses** — running ``compute_payslip``
   twice with the prior casual-8% line attached yields the SAME
   ``casual_8pct`` value (idempotency). The first pass computes
   ``8% × wages_only``; the second pass subtracts the prior
   line's amount before re-computing, so the result must match.

Test pattern mirrors the ``_FakeSession`` mock from
``tests/unit/test_payslip_calc.py`` — no real DB. We constrain
the input search space so individual examples don't explode the
test runtime; ``@settings(max_examples=50, deadline=2000)``
keeps the suite under the CI 30-second budget.

**Validates: Requirements R3, R4, R4a, R5, R6 — Staff Management
Phase 4 task E2.**
"""

from __future__ import annotations

# Resolve mappers eagerly so SQLAlchemy can resolve the Organisation↔User
# relationship before any mapper is configured by calc.py imports.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings, strategies as st

from app.modules.payslips.calc import (
    CASUAL_HOLIDAY_PAY_RATE,
    PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER,
    _resolve_allowance_quantity,
    compute_payslip,
)


# ---------------------------------------------------------------------------
# Hypothesis settings — keep CI under 30s
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Test doubles (mirror tests/unit/test_payslip_calc.py)
# ---------------------------------------------------------------------------


@dataclass
class _AggregatedHours:
    ordinary_minutes: int
    overtime_minutes: int
    public_holiday_minutes: int


class _Result:
    """Stand-in for the ``AsyncSession.execute()`` result."""

    def __init__(
        self,
        *,
        all_rows: list | None = None,
        scalar: Any = None,
        one_or_none_row: Any = None,
        scalars_list: list | None = None,
    ):
        self._all = list(all_rows or [])
        self._scalar = scalar
        self._one_or_none = one_or_none_row
        self._scalars_list = scalars_list

    def all(self):
        return list(self._all)

    def one_or_none(self):
        return self._one_or_none

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = list(self._scalars_list or [])
        return proxy


class _FakeSession:
    """In-memory ``AsyncSession`` stand-in that routes
    ``execute(stmt)`` based on substring matching against the SQL.

    Returns:
      - aggregated hour row from ``timesheet_approvals``,
      - shift-count scalar from ``schedule_entries`` JOIN,
      - empty rows for the YTD ``payslips × pay_periods`` join,
      - pre-attached allowance / deduction / reimbursement lists
        (so we can exercise the casual-8% recursion property),
      - ``org_row`` from ``get(Organisation, ...)``.
    """

    def __init__(
        self,
        *,
        aggregated_hours: _AggregatedHours | None = None,
        shift_count: int = 0,
        org_row: Any = None,
        payslip_allowances: list | None = None,
        payslip_deductions: list | None = None,
        payslip_reimbursements: list | None = None,
    ):
        self.aggregated_hours = aggregated_hours or _AggregatedHours(0, 0, 0)
        self.shift_count = shift_count
        self.org_row = org_row
        self.payslip_allowances = list(payslip_allowances or [])
        self.payslip_deductions = list(payslip_deductions or [])
        self.payslip_reimbursements = list(payslip_reimbursements or [])

    async def get(self, model, key):
        if model.__name__ == "Organisation":
            return self.org_row
        return None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        sql_lc = sql.lower()

        # 1. Hour aggregation (text statement).
        if "from timesheet_approvals" in sql_lc:
            row = SimpleNamespace(
                ordinary_minutes=self.aggregated_hours.ordinary_minutes,
                overtime_minutes=self.aggregated_hours.overtime_minutes,
                public_holiday_minutes=self.aggregated_hours.public_holiday_minutes,
            )
            return _Result(one_or_none_row=row)

        # 2. Shift count (text statement).
        if "from schedule_entries" in sql_lc and "timesheet_approvals" in sql_lc:
            return _Result(scalar=self.shift_count)

        # 3. YTD payslips × pay_periods join.
        if "payslips" in sql_lc and "pay_periods" in sql_lc and "gross_pay" in sql_lc:
            return _Result(all_rows=[])

        # 4. Pre-attached allowance / deduction / reimbursement lines.
        if "payslip_allowances" in sql_lc:
            return _Result(scalars_list=self.payslip_allowances)
        if "payslip_deductions" in sql_lc:
            return _Result(scalars_list=self.payslip_deductions)
        if "payslip_reimbursements" in sql_lc:
            return _Result(scalars_list=self.payslip_reimbursements)

        return _Result(all_rows=[])

    @asynccontextmanager
    async def begin(self):
        yield self


# ---------------------------------------------------------------------------
# Test-data builders
# ---------------------------------------------------------------------------


def _make_staff(
    *,
    org_id: uuid.UUID | None = None,
    hourly_rate: Decimal = Decimal("25.00"),
    overtime_rate: Decimal | None = None,
    employment_type: str = "permanent",
    kiwisaver_enrolled: bool = False,
    kiwisaver_employee_rate: Decimal = Decimal("3.00"),
    kiwisaver_employer_rate: Decimal = Decimal("3.00"),
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id or uuid.uuid4(),
        name="Jane Doe",
        first_name="Jane",
        hourly_rate=hourly_rate,
        overtime_rate=overtime_rate,
        employment_type=employment_type,
        kiwisaver_enrolled=kiwisaver_enrolled,
        kiwisaver_employee_rate=kiwisaver_employee_rate,
        kiwisaver_employer_rate=kiwisaver_employer_rate,
        standard_hours_per_week=Decimal("40.00"),
    )


def _make_period(
    *,
    start: date = date(2026, 6, 1),
    end: date = date(2026, 6, 14),
    pay: date = date(2026, 6, 17),
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        start_date=start,
        end_date=end,
        pay_date=pay,
    )


def _make_org():
    return SimpleNamespace(
        id=uuid.uuid4(),
        income_tax_year_end=date(2026, 3, 31),
    )


def _make_payslip(
    *,
    public_holiday_rate: Decimal | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        public_holiday_rate=public_holiday_rate,
    )


def _allowance_row(*, label: str, amount: Decimal, taxable: bool = True):
    """Build a fake ``PayslipAllowance`` row for the calc to load."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        allowance_type_id=None,
        label=label,
        quantity=Decimal("1"),
        unit="period",
        amount=amount,
        taxable=taxable,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Bound the search space so individual examples don't explode runtime.
# Hours up to ~80h per band; rates between $15 and $100 per hour.
hours_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("80"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
rate_strategy = st.decimals(
    min_value=Decimal("15.00"),
    max_value=Decimal("100.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
override_rate_strategy = st.decimals(
    min_value=Decimal("20.00"),
    max_value=Decimal("200.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
allowance_amount_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("500.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
shift_count_strategy = st.integers(min_value=0, max_value=30)


def _hours_to_minutes(hours: Decimal) -> int:
    """Convert decimal hours to integer minutes for the
    ``timesheet_approvals`` aggregate row.
    """
    return int((Decimal(hours) * Decimal(60)).quantize(Decimal("1")))


# ===========================================================================
# 1. gross >= sum(taxable allowances)
# ===========================================================================


@PBT_SETTINGS
@given(
    ordinary_h=hours_strategy,
    overtime_h=hours_strategy,
    ph_h=hours_strategy,
    ord_rate=rate_strategy,
    taxable_a=allowance_amount_strategy,
    non_taxable_a=allowance_amount_strategy,
)
def test_gross_geq_sum_taxable_allowances(
    ordinary_h: Decimal,
    overtime_h: Decimal,
    ph_h: Decimal,
    ord_rate: Decimal,
    taxable_a: Decimal,
    non_taxable_a: Decimal,
) -> None:
    """**Validates: Requirements R3, R4** — gross is at least the
    sum of the taxable allowances attached to the draft.

    ``gross = ordinary + overtime + public_holiday + taxable_allowances
    + casual_8pct``. All terms are non-negative, so
    ``gross >= taxable_allowances`` for any input.
    """

    async def _run() -> None:
        staff = _make_staff(hourly_rate=ord_rate, employment_type="permanent")
        period = _make_period()
        org = _make_org()
        payslip = _make_payslip()
        allowances = [
            _allowance_row(
                label="Tool allowance",
                amount=taxable_a,
                taxable=True,
            ),
            _allowance_row(
                label="Vehicle reimbursement",
                amount=non_taxable_a,
                taxable=False,
            ),
        ]
        db = _FakeSession(
            aggregated_hours=_AggregatedHours(
                ordinary_minutes=_hours_to_minutes(ordinary_h),
                overtime_minutes=_hours_to_minutes(overtime_h),
                public_holiday_minutes=_hours_to_minutes(ph_h),
            ),
            org_row=org,
            payslip_allowances=allowances,
        )

        calc = await compute_payslip(db, staff, period, payslip=payslip)

        assert calc.gross >= calc.allowances_taxable, (
            f"gross={calc.gross} < allowances_taxable={calc.allowances_taxable}"
        )
        # Sanity — non-taxable allowances are NOT included in gross.
        assert calc.gross >= Decimal("0")

    asyncio.run(_run())


# ===========================================================================
# 2. net >= 0 (no deductions / reimbursements path)
# ===========================================================================


@PBT_SETTINGS
@given(
    ordinary_h=hours_strategy,
    overtime_h=hours_strategy,
    ph_h=hours_strategy,
    ord_rate=rate_strategy,
    taxable_a=allowance_amount_strategy,
    employment_type=st.sampled_from(["permanent", "casual"]),
    kiwisaver_enrolled=st.booleans(),
    ks_employee_rate=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("10"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_net_non_negative_for_calc_only_inputs(
    ordinary_h: Decimal,
    overtime_h: Decimal,
    ph_h: Decimal,
    ord_rate: Decimal,
    taxable_a: Decimal,
    employment_type: str,
    kiwisaver_enrolled: bool,
    ks_employee_rate: Decimal,
) -> None:
    """**Validates: Requirements R3, R6** — for any combination of
    hours, rates, and a taxable allowance line, ``net >= 0`` when no
    deductions or reimbursements are attached.

    The calc-layer ``net = gross - deductions_total + reimbursements_total``;
    with no attached deduction rows, ``deductions_total == 0`` and
    ``net == gross >= 0``. The downstream service layer applies
    KiwiSaver / PAYE deductions in a second pass — clamping
    behaviour for over-deducted drafts is covered by service-level
    tests, not the calc invariant.
    """

    async def _run() -> None:
        staff = _make_staff(
            hourly_rate=ord_rate,
            employment_type=employment_type,
            kiwisaver_enrolled=kiwisaver_enrolled,
            kiwisaver_employee_rate=ks_employee_rate,
        )
        period = _make_period()
        org = _make_org()
        payslip = _make_payslip()
        allowances = [
            _allowance_row(
                label="Meal allowance",
                amount=taxable_a,
                taxable=True,
            ),
        ]
        db = _FakeSession(
            aggregated_hours=_AggregatedHours(
                ordinary_minutes=_hours_to_minutes(ordinary_h),
                overtime_minutes=_hours_to_minutes(overtime_h),
                public_holiday_minutes=_hours_to_minutes(ph_h),
            ),
            org_row=org,
            payslip_allowances=allowances,
        )

        calc = await compute_payslip(db, staff, period, payslip=payslip)

        assert calc.net >= Decimal("0"), (
            f"net={calc.net} should be >= 0 with no deductions attached"
        )

    asyncio.run(_run())


# ===========================================================================
# 3. kiwisaver_employer NOT subtracted from gross
# ===========================================================================


@PBT_SETTINGS
@given(
    ordinary_h=hours_strategy,
    ord_rate=rate_strategy,
    ks_employer_rate_a=st.decimals(
        min_value=Decimal("3"),
        max_value=Decimal("10"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    ks_employer_rate_b=st.decimals(
        min_value=Decimal("3"),
        max_value=Decimal("10"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_kiwisaver_employer_does_not_affect_gross(
    ordinary_h: Decimal,
    ord_rate: Decimal,
    ks_employer_rate_a: Decimal,
    ks_employer_rate_b: Decimal,
) -> None:
    """**Validates: Requirement R6.2** — toggling the KiwiSaver
    employer rate changes ``calc.kiwisaver_employer`` but does NOT
    change ``calc.gross`` for the same wage inputs.
    """

    async def _run() -> None:
        period = _make_period()
        org = _make_org()
        payslip_a = _make_payslip()
        payslip_b = _make_payslip()
        hours = _hours_to_minutes(ordinary_h)

        staff_a = _make_staff(
            hourly_rate=ord_rate,
            kiwisaver_enrolled=True,
            kiwisaver_employer_rate=ks_employer_rate_a,
        )
        db_a = _FakeSession(
            aggregated_hours=_AggregatedHours(hours, 0, 0),
            org_row=org,
        )
        calc_a = await compute_payslip(db_a, staff_a, period, payslip=payslip_a)

        staff_b = _make_staff(
            hourly_rate=ord_rate,
            kiwisaver_enrolled=True,
            kiwisaver_employer_rate=ks_employer_rate_b,
        )
        db_b = _FakeSession(
            aggregated_hours=_AggregatedHours(hours, 0, 0),
            org_row=org,
        )
        calc_b = await compute_payslip(db_b, staff_b, period, payslip=payslip_b)

        # Gross is identical regardless of employer rate.
        # (The employer figure CAN quantize to the same cents value
        # for tiny gross amounts even when the rate differs slightly,
        # so we don't assert on the employer figure itself — only on
        # the named invariant: gross is not affected by employer rate.)
        assert calc_a.gross == calc_b.gross, (
            f"gross_a={calc_a.gross} != gross_b={calc_b.gross}"
        )

    asyncio.run(_run())


# ===========================================================================
# 4. G2 — public_holiday_hours × public_holiday_rate
# ===========================================================================


@PBT_SETTINGS
@given(
    ordinary_h=hours_strategy,
    overtime_h=hours_strategy,
    ph_h=hours_strategy,
    ord_rate=rate_strategy,
    use_override=st.booleans(),
    override_rate=override_rate_strategy,
)
def test_g2_public_holiday_band_contributes_to_gross(
    ordinary_h: Decimal,
    overtime_h: Decimal,
    ph_h: Decimal,
    ord_rate: Decimal,
    use_override: bool,
    override_rate: Decimal,
) -> None:
    """**Validates: Requirement R4a (G2)** — for any
    ``(public_holiday_hours, ordinary_rate, override_rate)`` triple:

    ``gross == ordinary + overtime + ph_hours × ph_rate +
    taxable_allowances + casual_8pct``

    where ``ph_rate`` is the override (when admin set one on the
    draft) or ``ordinary_rate × PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER``.
    Permanent staff with no allowances → ``casual_8pct == 0`` and
    ``allowances_taxable == 0``.
    """

    async def _run() -> None:
        staff = _make_staff(hourly_rate=ord_rate, employment_type="permanent")
        period = _make_period()
        org = _make_org()
        payslip = _make_payslip(
            public_holiday_rate=override_rate if use_override else None,
        )
        db = _FakeSession(
            aggregated_hours=_AggregatedHours(
                ordinary_minutes=_hours_to_minutes(ordinary_h),
                overtime_minutes=_hours_to_minutes(overtime_h),
                public_holiday_minutes=_hours_to_minutes(ph_h),
            ),
            org_row=org,
        )

        calc = await compute_payslip(db, staff, period, payslip=payslip)

        # Expected ph_rate.
        if use_override:
            expected_ph_rate = override_rate.quantize(Decimal("0.01"))
        else:
            expected_ph_rate = (
                ord_rate * PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER
            ).quantize(Decimal("0.01"))

        assert calc.public_holiday_rate == expected_ph_rate, (
            f"ph_rate={calc.public_holiday_rate} expected={expected_ph_rate}"
        )

        # ph band amount.
        expected_ph_amount = (
            calc.public_holiday_hours * expected_ph_rate
        ).quantize(Decimal("0.01"))
        assert calc.public_holiday == expected_ph_amount, (
            f"ph={calc.public_holiday} expected={expected_ph_amount}"
        )

        # Gross composition — permanent + no allowances → casual_8pct=0,
        # allowances_taxable=0.
        expected_gross = (
            calc.ordinary + calc.overtime + calc.public_holiday
        ).quantize(Decimal("0.01"))
        assert calc.gross == expected_gross, (
            f"gross={calc.gross} expected="
            f"ordinary({calc.ordinary})+overtime({calc.overtime})"
            f"+ph({calc.public_holiday})={expected_gross}"
        )

    asyncio.run(_run())


# ===========================================================================
# 5. G18 — for unit='shift', derived amount = shift_count × default_amount
# ===========================================================================


@PBT_SETTINGS
@given(
    shift_count=shift_count_strategy,
    default_amount=allowance_amount_strategy,
)
def test_g18_shift_unit_amount_equals_count_times_default(
    shift_count: int,
    default_amount: Decimal,
) -> None:
    """**Validates: Requirement R4.6 (G18)** — for ``unit='shift'``,
    the derived quantity equals the approved-shift count and the
    derived amount equals ``shift_count × default_amount``.
    """

    async def _run() -> None:
        atype = SimpleNamespace(
            id=uuid.uuid4(),
            unit="shift",
            default_amount=default_amount,
        )
        period = _make_period()
        db = _FakeSession(shift_count=shift_count)

        quantity, amount, source = await _resolve_allowance_quantity(
            db,
            allowance_type=atype,
            recurring_rule=None,
            staff_id=uuid.uuid4(),
            period=period,
        )

        assert quantity == Decimal(shift_count), (
            f"quantity={quantity} expected={shift_count}"
        )
        expected_amount = (
            Decimal(shift_count) * default_amount
        ).quantize(Decimal("0.01"))
        assert amount == expected_amount, (
            f"amount={amount} expected={expected_amount} "
            f"(shifts={shift_count} × default={default_amount})"
        )
        assert source == "shift_count"

    asyncio.run(_run())


# ===========================================================================
# 6. N17 — casual employee with zero approved hours → no casual_8pct line
# ===========================================================================


@PBT_SETTINGS
@given(
    employment_type=st.sampled_from(
        ["permanent", "casual", "fixed_term", "contractor"],
    ),
)
def test_n17_zero_hours_no_casual_8pct_line(
    employment_type: str,
) -> None:
    """**Validates: Requirement R5 (N17)** — when there are zero
    approved hours and no taxable allowances, the casual 8% line is
    OMITTED (``calc.casual_8pct == 0``) regardless of employment
    type. The service-layer ``_attach_casual_8pct_line`` only adds
    a row when ``calc.casual_8pct > 0`` per the omission rule.
    """

    async def _run() -> None:
        staff = _make_staff(
            hourly_rate=Decimal("25.00"),
            employment_type=employment_type,
        )
        period = _make_period()
        org = _make_org()
        payslip = _make_payslip()
        # Zero approved hours, no allowances loaded.
        db = _FakeSession(
            aggregated_hours=_AggregatedHours(0, 0, 0),
            org_row=org,
        )

        calc = await compute_payslip(db, staff, period, payslip=payslip)

        assert calc.casual_8pct == Decimal("0"), (
            f"casual_8pct={calc.casual_8pct} should be 0 for zero-wage "
            f"employment_type={employment_type}"
        )
        assert calc.gross == Decimal("0")

    asyncio.run(_run())


# ===========================================================================
# 7. Casual 8% never recurses
# ===========================================================================


@PBT_SETTINGS
@given(
    ordinary_h=st.decimals(
        min_value=Decimal("1"),  # > 0 so casual_8pct > 0
        max_value=Decimal("80"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    overtime_h=hours_strategy,
    ph_h=hours_strategy,
    ord_rate=rate_strategy,
)
def test_casual_8pct_idempotent_across_recompute(
    ordinary_h: Decimal,
    overtime_h: Decimal,
    ph_h: Decimal,
    ord_rate: Decimal,
) -> None:
    """**Validates: Requirement R5** — running ``compute_payslip``
    twice with the prior casual-8% line attached as an allowance
    yields the SAME ``casual_8pct`` value (idempotency).

    The calc subtracts any prior ``casual%`` allowance from the
    wages-only base before re-computing 8%, so re-running the math
    on a payslip that already has the line attached must not double
    the contribution.
    """

    async def _run() -> None:
        staff = _make_staff(
            hourly_rate=ord_rate,
            employment_type="casual",
        )
        period = _make_period()
        org = _make_org()
        payslip = _make_payslip()
        hours = _AggregatedHours(
            ordinary_minutes=_hours_to_minutes(ordinary_h),
            overtime_minutes=_hours_to_minutes(overtime_h),
            public_holiday_minutes=_hours_to_minutes(ph_h),
        )

        # Pass 1: no allowance lines attached.
        db_first = _FakeSession(
            aggregated_hours=hours,
            org_row=org,
        )
        first = await compute_payslip(
            db_first, staff, period, payslip=payslip,
        )

        # Simulate the service layer attaching the casual-8% line.
        prior_line = _allowance_row(
            label="Casual 8% holiday pay (s28)",
            amount=first.casual_8pct,
            taxable=True,
        )
        db_second = _FakeSession(
            aggregated_hours=hours,
            org_row=org,
            payslip_allowances=[prior_line],
        )
        second = await compute_payslip(
            db_second, staff, period, payslip=payslip,
        )

        # The recomputed casual_8pct must equal the prior pass's
        # value — the calc subtracts the prior line before computing
        # 8%, so the result is stable across runs.
        assert second.casual_8pct == first.casual_8pct, (
            f"recursion detected: first={first.casual_8pct} "
            f"second={second.casual_8pct}"
        )
        # Cross-check the formula directly: first.casual_8pct
        # = 8% × (ordinary + overtime + ph) and the second pass
        # subtracts that prior amount from wages_only before
        # re-applying 8% — yielding the same value.
        wages_only = (
            first.ordinary + first.overtime + first.public_holiday
        ).quantize(Decimal("0.01"))
        if wages_only > Decimal("0"):
            expected = (
                wages_only * CASUAL_HOLIDAY_PAY_RATE
            ).quantize(Decimal("0.01"))
            assert first.casual_8pct == expected, (
                f"first.casual_8pct={first.casual_8pct} "
                f"expected={expected} (wages_only={wages_only})"
            )

    asyncio.run(_run())
